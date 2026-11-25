"""Логика Telegram-бота: команды, приём видео/ссылок, кнопки нарезки.

Переиспользуем пайплайн miniapp (JobStore / ScanService / RenderService) —
меняется только «фронт»: вместо веб-интерфейса — сообщения и inline-кнопки.
После сканирования ScanService зовет previews.run(job) — вместо превью шлём
в чат список моментов с кнопками (TgMomentsNotifier).

Биллинг — единая база users_web (web_billing.UnifiedBilling): TG-пользователь
резолвится через services_web.resolve_identity, и аккаунт в чате совпадает
с аккаунтом в миниapp-приложении (кнопка «Открыть приложение» в /start).
"""
import asyncio
import html
import os
import traceback
import uuid

from app import analyzer, renderer, ffmpeg
from config import (TG_TOKEN, MAX_HIGHLIGHTS, MAX_FULL_VIDEO_SEC, RENDER_SLOTS,
                    MAX_CLIPS_PER_REQUEST, TG_DOWNLOAD_LIMIT, TG_UPLOAD_LIMIT,
                    FREE_PERIOD, TG_ADMIN_IDS, TG_WEBAPP_URL)
from tg_bot_client import TgBot
from web_billing import UnifiedBilling
from sources import extract_url, detect_platform
from sources.file_source import FileSource
from sources.link_source import LinkSource
from miniapp.jobs import Job, JobStore, rm
from miniapp.scan_service import ScanService
from miniapp.render_service import RenderService
from miniapp.tasks import spawn
from miniapp.errors import ApiError
from services_web import resolve_identity, get_users_stats_web

VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ").webm")

bot = TgBot(TG_TOKEN)
billing = UnifiedBilling()
jobs = JobStore()


# ============================================================
# Список моментов в чате
# ============================================================

class TgMomentsNotifier:
    """«Превью» для TG: ScanService после сканирования зовёт run(job)."""

    def __init__(self, bot: TgBot):
        self._bot = bot

    async def run(self, job):
        try:
            mid = getattr(job, "tg_status_msg", None)
            if mid:
                await self._bot.edit_message_text(job.chat_id, mid, "✅ Готово — моменты ниже.")
            await send_moments(job)
        except Exception:
            traceback.print_exc()
        finally:
            job.previews_status = "done"
            job.progress = ""


scan = ScanService(analyzer, TgMomentsNotifier(bot), MAX_HIGHLIGHTS, ffmpeg)
render = RenderService(renderer, ffmpeg, billing, MAX_FULL_VIDEO_SEC, slots=RENDER_SLOTS)


def _ts(sec: float) -> str:
    sec = int(sec)
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _moments_text(job) -> str:
    title = f" в «{html.escape(job.title)}»" if job.title else ""
    lines = [f"🎬 <b>Нашёл моментов: {len(job.moments)}</b>{title}:"]
    for i, m in enumerate(job.moments, 1):
        row = f"{i}. {m['emoji']} {html.escape(m['label'])} — {_ts(m['start'])}–{_ts(m['end'])}"
        if m.get("snippet"):
            row += f"\n<i>«{html.escape(m['snippet'])}»</i>"
        lines.append(row)
    lines.append("")
    lines.append(f"Жми на номер — нарежу клип с субтитрами (до {MAX_CLIPS_PER_REQUEST} за раз).")
    return "\n".join(lines)


def _moments_kb(job) -> dict:
    def btn(i: int) -> dict:
        r = job.renders.get(i - 1)
        if r and r.get("status") == "ready":
            mark = "✅ "
        elif r and r.get("status") == "pending":
            mark = "⏳ "
        elif r and r.get("status") == "error":
            mark = "⚠️ "
        else:
            mark = ""
        return {"text": f"{mark}{i}", "callback_data": f"cut:{job.id}:{i - 1}"}
    return {"inline_keyboard": [[btn(i) for i in range(1, len(job.moments) + 1)]]}


def _cancel_kb(job_id: str) -> dict:
    return {"inline_keyboard": [[{"text": "⏹ Отмена", "callback_data": f"cancel:{job_id}"}]]}


async def send_moments(job):
    mid = await bot.send_message(job.chat_id, _moments_text(job), reply_markup=_moments_kb(job))
    if mid:
        job.tg_msg_id = mid


async def refresh_moments(job):
    """Обновляем список (галочки на уже отрендеренных клипах)."""
    mid = getattr(job, "tg_msg_id", None)
    if mid:
        await bot.edit_message_text(job.chat_id, mid, _moments_text(job),
                                    reply_markup=_moments_kb(job))


async def _status(job, text: str):
    """Меняем статусное сообщение (или шлём новое, если старого нет)."""
    mid = getattr(job, "tg_status_msg", None)
    if mid:
        await bot.edit_message_text(job.chat_id, mid, text)
    else:
        await bot.send_message(job.chat_id, text)


# ============================================================
# Запуск сканирования
# ============================================================

async def _start_job(chat_id: int, uid: int, source) -> None:
    try:
        await billing.ensure_can_start(uid)
        with jobs.slot(uid):
            job = jobs.add(Job(uid, chat_id, source))
    except PermissionError as e:
        await bot.send_message(chat_id, f"⛔ {e}")
        return
    except ApiError as e:
        await bot.send_message(chat_id, e.msg)
        return

    mid = await bot.send_message(chat_id, "🔍 Ищу лучшие моменты — обычно это несколько минут…",
                                 reply_markup=_cancel_kb(job.id))
    if mid:
        job.tg_status_msg = mid
    job.task = spawn(_scan_and_report(job))


async def _scan_and_report(job):
    """Обёртка сканирования: в чат уходят ошибки и «пустые» видео.

    Успех с моментами не здесь — список шлёт TgMomentsNotifier (его зовёт
    ScanService). Отмена чистит файлы внутри ScanService, здесь только текст.
    """
    try:
        await scan.run(job)
    except asyncio.CancelledError:
        await _status(job, "⏹ Поиск остановлен.")
        return
    if job.status == "error":
        await _status(job, f"❌ Не получилось: {html.escape(job.error[:200])}")
    elif job.status == "ready" and not job.moments:
        await _status(job, "🤔 Не нашёл заметных моментов — попробуй другое видео.")


def _pick_video(msg: dict):
    """video / document-видео из сообщения → объект файла Telegram."""
    if msg.get("video"):
        return msg["video"]
    doc = msg.get("document")
    if doc:
        name = (doc.get("file_name") or "").lower()
        mime = (doc.get("mime_type") or "").lower()
        if name.endswith(VIDEO_EXT) or mime.startswith("video/"):
            return doc
    return None


async def _start_file_job(chat_id: int, uid: int, v: dict) -> None:
    size = v.get("file_size") or 0
    name = v.get("file_name") or "video.mp4"
    stem, ext = os.path.splitext(name)
    if ext.lower() not in VIDEO_EXT:
        await bot.send_message(chat_id, "Нужен видеофайл: mp4, mov, avi, mkv или webm.")
        return
    if size and size > TG_DOWNLOAD_LIMIT:
        await bot.send_message(
            chat_id,
            f"📦 Файл {size / 1e6:.0f} МБ — Telegram отдаёт ботам файлы максимум 20 МБ.\n"
            "Пришли ссылку на видео (YouTube, Twitch, TikTok, Google Drive, Яндекс.Диск) — "
            "по ссылке ограничений нет.")
        return
    try:
        await billing.ensure_can_start(uid)
    except PermissionError as e:
        await bot.send_message(chat_id, f"⛔ {e}")
        return

    mid = await bot.send_message(chat_id, "⏬ Скачиваю видео…")
    path = f"downloads/tg_{uid}_{uuid.uuid4().hex[:10]}{ext.lower()}"
    try:
        # слот держим на всё время скачивания: две параллельные загрузки не пройдут
        with jobs.slot(uid):
            got = await bot.download_file(v["file_id"], path)
            if not got:
                raise RuntimeError("download failed")
            job = jobs.add(Job(uid, chat_id, FileSource(path, stem or "video", ffmpeg)))
    except ApiError as e:
        rm(path)
        await bot.send_message(chat_id, e.msg)
        return
    except RuntimeError:
        rm(path)
        await bot.send_message(chat_id, "❌ Не удалось скачать файл. Попробуй ещё раз или пришли ссылку.")
        return

    if mid:
        job.tg_status_msg = mid
        await bot.edit_message_text(chat_id, mid,
                                    "🔍 Ищу лучшие моменты — обычно это несколько минут…",
                                    reply_markup=_cancel_kb(job.id))
    job.task = spawn(_scan_and_report(job))


# ============================================================
# Рендер и отправка клипов
# ============================================================

async def _render_and_send(job, idx: int):
    try:
        await render.run(job, idx, subs=True, vertical=False)
    except Exception:
        traceback.print_exc()
        job.renders[idx] = {"status": "error", "error": "внутренняя ошибка"}

    r = job.renders.get(idx) or {}
    if r.get("status") != "ready":
        err = html.escape(str(r.get("error", "ошибка"))[:150])
        await bot.send_message(job.chat_id, f"❌ Клип {idx + 1}: {err}")
        await refresh_moments(job)
        return

    path = r.get("path", "")
    size = os.path.getsize(path) if os.path.exists(path) else 0
    if size > TG_UPLOAD_LIMIT:
        await bot.send_message(
            job.chat_id,
            f"❌ Клип {idx + 1} получился {size / 1e6:.0f} МБ — Telegram позволяет ботам "
            "отправлять до 50 МБ.")
        await refresh_moments(job)
        return

    m = job.moments[idx]
    caption = (f"{m['emoji']} <b>Клип {idx + 1}</b> · {html.escape(m['label'])}\n"
               f"{_ts(m['start'])}–{_ts(m['end'])}")
    if m.get("snippet"):
        caption += f"\n«{html.escape(m['snippet'])}»"
    if not await bot.send_video(job.chat_id, path, caption=caption):
        await bot.send_message(job.chat_id, f"❌ Клип {idx + 1}: не удалось отправить видео в Telegram.")
    await refresh_moments(job)


# ============================================================
# Команды
# ============================================================

def _app_kb() -> dict | None:
    """Кнопка «Открыть приложение» — запускает сайт как миниapp Telegram.
    Telegram требует https, поэтому без TG_WEBAPP_URL кнопки нет."""
    if not TG_WEBAPP_URL or not TG_WEBAPP_URL.startswith("https://"):
        return None
    return {"keyboard": [[{"text": "🎬 Открыть приложение",
                          "web_app": {"url": TG_WEBAPP_URL}}]],
            "resize_keyboard": True}


async def cmd_start(chat_id: int, user_id: int):
    # единый пользователь: tg id → users_web (создаётся при первом /start)
    await resolve_identity("tg", user_id, chat_id=chat_id)
    promo = "\n\n🎁 Пока бот в тестировании — всё бесплатно!" if FREE_PERIOD else ""
    kb = _app_kb()
    text = ("👋 Привет! Я нахожу лучшие моменты в видео и нарезаю клипы с анимированными "
            "субтитрами.\n\n"
            "• Жми кнопку ниже — откроется приложение (как в MAX, только в Telegram)\n"
            "• Или пришли <b>ссылку</b> — YouTube, Twitch, TikTok, Google Drive, Яндекс.Диск "
            "(подходит для длинных стримов)\n"
            "• Или <b>видеофайл</b> до 20 МБ — тогда всё прямо в чате" + promo)
    await bot.send_message(chat_id, text, reply_markup=kb)


async def cmd_help(chat_id: int):
    await bot.send_message(
        chat_id,
        "🤖 <b>Справка</b>\n\n"
        "/start — начать\n"
        "/help — это сообщение\n\n"
        "Есть приложение с превью и галереей — кнопка под этим сообщением (или в /start). "
        "Можно и по-старинке: пришли ссылку на видео или файл до 20 МБ — всё в чате.\n\n"
        "Аккаунт один и тот же и в чате, и в приложении; связать его с MAX или сайтом "
        "можно в профиле приложения — «Код привязки».")


async def cmd_stats(chat_id: int, user_id: int):
    if user_id not in TG_ADMIN_IDS:
        await bot.send_message(chat_id, "Недостаточно прав.")
        return
    total, paid, _email, n_max, n_tg, n_site = await get_users_stats_web()
    await bot.send_message(
        chat_id,
        "📊 <b>Статистика (единая база)</b>\n\n"
        f"👥 Пользователей: {total}\n"
        f"💎 С активной подпиской: {paid}\n\n"
        f"Привязки: MAX — {n_max}, Telegram — {n_tg}, сайт — {n_site}")


# ============================================================
# Точки входа (их зовёт tg_webhook)
# ============================================================

async def handle_message(msg: dict):
    try:
        chat_id = int(msg["chat"]["id"])
        user_id = int((msg.get("from") or {}).get("id") or 0)
        if not chat_id or not user_id:
            return
        text = (msg.get("text") or msg.get("caption") or "").strip()

        if text.startswith("/start"):
            await cmd_start(chat_id, user_id)
            return
        if text.startswith("/help"):
            await cmd_help(chat_id)
            return
        if text.startswith("/stats"):
            await cmd_stats(chat_id, user_id)
            return

        # Всё остальное — от имени единого пользователя (tg id → users_web)
        user = await resolve_identity("tg", user_id, chat_id=chat_id)
        uid = user.id

        # Ссылка (в тексте или в подписи к видео)
        url = extract_url(text)
        if url and detect_platform(url):
            await _start_job(chat_id, uid, LinkSource(url))
            return

        v = _pick_video(msg)
        if v:
            await _start_file_job(chat_id, uid, v)
            return

        if msg.get("video_note"):
            await bot.send_message(chat_id, "🎥 Кружки не поддерживаются — пришли обычное видео или ссылку.")
            return

        await bot.send_message(
            chat_id,
            "Пришли ссылку (YouTube, Twitch, TikTok, Google Drive, Яндекс.Диск) или "
            "видеофайл до 20 МБ. Подробнее — /help")
    except Exception:
        traceback.print_exc()


async def handle_callback_query(cb: dict):
    try:
        data = cb.get("data") or ""
        chat_id = int(((cb.get("message") or {}).get("chat") or {}).get("id") or 0)
        user_id = int((cb.get("from") or {}).get("id") or 0)
        cb_id = cb.get("id") or ""
        if not chat_id:
            await bot.answer_callback_query(cb_id)
            return

        # задачи привязаны к единому пользователю, поэтому сначала резолвим tg id
        user = await resolve_identity("tg", user_id)
        uid = user.id

        if data.startswith("cancel:"):
            await _on_cancel(cb_id, uid, data.split(":", 1)[1])
        elif data.startswith("cut:"):
            _, job_id, idx_s = data.split(":", 2)
            await _on_cut(cb_id, uid, job_id, int(idx_s))
        else:
            await bot.answer_callback_query(cb_id)
    except Exception:
        traceback.print_exc()


async def _on_cancel(cb_id: str, uid: int, job_id: str):
    job = jobs.get_by_id(job_id)
    if not job or job.user_id != uid:
        await bot.answer_callback_query(cb_id, "Задача не найдена")
        return
    if job.status != "scanning" or not job.task or job.task.done():
        await bot.answer_callback_query(cb_id, "Уже нечего отменять")
        return
    job.cancelled = True
    job.task.cancel()
    jobs.drop(job)          # как в miniapp: отменённая задача сразу освобождает место
    await bot.answer_callback_query(cb_id, "Останавливаю…")


async def _on_cut(cb_id: str, uid: int, job_id: str, idx: int):
    job = jobs.get_by_id(job_id)
    if not job or job.user_id != uid:
        await bot.answer_callback_query(cb_id, "Задача устарела — пришли видео заново")
        return
    if job.status != "ready":
        await bot.answer_callback_query(cb_id, "Подожди окончания поиска")
        return
    if not 0 <= idx < len(job.moments):
        await bot.answer_callback_query(cb_id, "Неверный момент")
        return
    cur = job.renders.get(idx)
    if cur and cur.get("status") == "pending":
        await bot.answer_callback_query(cb_id, "Этот клип уже рендерится")
        return
    if cur and cur.get("status") == "ready":
        await bot.answer_callback_query(cb_id, "Этот клип уже отправлен — ищи видео выше")
        return
    active = [k for k, v in job.renders.items() if v.get("status") in ("pending", "ready")]
    if len(active) >= MAX_CLIPS_PER_REQUEST:
        await bot.answer_callback_query(cb_id, f"Не больше {MAX_CLIPS_PER_REQUEST} клипов за раз")
        return

    job.renders[idx] = {"status": "pending"}
    await refresh_moments(job)
    await bot.answer_callback_query(cb_id, f"Рендерю клип {idx + 1}…")
    spawn(_render_and_send(job, idx))
