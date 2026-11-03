"""Обработка видео и хайлайтов — самая мясная часть."""

import asyncio
import os
import subprocess
import traceback
import uuid

from database_max import async_session_max
from services_max import (
    get_or_create_user,
    can_process_video,
    increment_video_counter,
)
from app import bot, engine, session_manager
from config import ADMIN_IDS, MAX_FILE_SIZE_BYTES, MAX_FULL_VIDEO_SEC, MAX_HIGHLIGHTS, MAX_CLIPS_PER_REQUEST
from utils import extract_video_attachment, download_video, format_moment_time


# ------------------------------------------------------------
# Обычное видео (полное субтитрирование)
# ------------------------------------------------------------
async def handle_video(chat_id: int, user_id: int, att: dict):
    """Скачивает и обрабатывает видео с субтитрами."""
    is_admin = user_id in ADMIN_IDS

    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)
        if not is_admin and not can_process_video(user):
            await bot.send_message(
                chat_id,
                "😔 Закончились бесплатные видео на сегодня (3/день).\n"
                "Возвращайся завтра или оформи подписку через /pay.",
            )
            return
        is_premium = user.active_sub != "default"

    status_id = await bot.send_message(chat_id, "📥 Готовлю видео к скачиванию...")

    # Защита по размеру
    size = att.get("size") or 0
    if size and size > MAX_FILE_SIZE_BYTES:
        await bot.edit_message(chat_id, status_id, "❌ Файл больше 2.5 ГБ — подрежь видео и отправь ещё раз.")
        return

    # Получение URL
    video_url = att.get("url")
    if not video_url and att.get("token"):
        video_url = await bot.get_video_url(att["token"])
    if not video_url:
        await bot.edit_message(chat_id, status_id, "❌ Не удалось получить ссылку на видео.")
        return

    await bot.edit_message(chat_id, status_id, "📥 Скачиваю видео...")

    os.makedirs("downloads", exist_ok=True)
    input_path = f"downloads/max_{user_id}_{uuid.uuid4().hex[:8]}.mp4"

    try:
        await download_video(video_url, input_path)
    except Exception as e:
        print(f"[VIDEO ERROR] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка скачивания: {type(e).__name__}: {e}")
        return

    # Проверка длины
    try:
        dur = await asyncio.to_thread(engine.get_video_duration, input_path)
        if dur > MAX_FULL_VIDEO_SEC and not is_admin:
            await bot.edit_message(
                chat_id, status_id,
                "⏱ Видео длиннее 30 минут — полное субтитрирование займёт часы.\n"
                "Нажми «🎬 Найти хайлайты» и отправь это видео ещё раз: "
                "я найду лучшие моменты и нарежу клипы с субтитрами.",
            )
            if os.path.exists(input_path):
                os.remove(input_path)
            return
    except Exception:
        pass

    # Обработка
    await bot.edit_message(chat_id, status_id, "🎬 Обрабатываю видео...")
    try:
        result = await asyncio.to_thread(engine.process_video, input_path, str(user_id), is_premium)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "")[:500]
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка ffmpeg:\n{err}")
        return
    except Exception as e:
        print(f"[PROCESS VIDEO ERROR] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка: {type(e).__name__}: {e}")
        return

    # Отправка
    await bot.edit_message(chat_id, status_id, "📤 Отправляю видео...")
    await bot.send_video(chat_id, result["video_path"], caption="✅ Твоё видео с субтитрами!")

    if result.get("srt_path"):
        srt_path = result["srt_path"]
        txt_path = srt_path.rsplit(".", 1)[0] + ".txt"
        try:
            os.rename(srt_path, txt_path)
        except Exception:
            txt_path = srt_path
        await bot.send_document(chat_id, txt_path, caption="📄 Файл субтитров")

    if not is_admin:
        await increment_video_counter(user, session)

    await bot.edit_message(chat_id, status_id, "✅ Готово!")


# ------------------------------------------------------------
# Хайлайты: запуск поиска
# ------------------------------------------------------------
async def handle_find_highlights_start(chat_id: int, user_id: int):
    session_manager.set_awaiting_video(user_id, chat_id)
    await bot.send_message(
        chat_id,
        "🎬 *Поиск хайлайтов*\n\n"
        "Отправь мне видео (до 2 часов, до 2.5 ГБ) — я найду самые крутые моменты!\n\n"
        "💡 Лучше отправляй как ФАЙЛ (скрепка → файл) — тогда без сжатия.\n"
        "⏱️ Сканирование займёт 2-4 минуты.",
    )


# ------------------------------------------------------------
# Хайлайты: сканирование
# ------------------------------------------------------------
async def handle_scan_video(chat_id: int, user_id: int, att: dict):
    """Этап 1: скачивает видео и ищет крутые моменты."""
    is_admin = user_id in ADMIN_IDS

    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)
        if not is_admin and not can_process_video(user):
            await bot.send_message(
                chat_id,
                "😔 Закончились бесплатные видео на сегодня (3/день).\n"
                "Возвращайся завтра или оформи подписку через /pay.",
            )
            return

    status_id = await bot.send_message(chat_id, "📥 Скачиваю видео для сканирования...")

    size = att.get("size") or 0
    if size and size > MAX_FILE_SIZE_BYTES:
        await bot.edit_message(chat_id, status_id, "❌ Файл больше 2.5 ГБ — подрежь видео и отправь ещё раз.")
        return

    video_url = att.get("url")
    if not video_url and att.get("token"):
        video_url = await bot.get_video_url(att["token"])
    if not video_url:
        await bot.edit_message(chat_id, status_id, "❌ Не удалось получить ссылку на видео.")
        return

    os.makedirs("downloads", exist_ok=True)
    input_path = f"downloads/max_hl_{user_id}_{uuid.uuid4().hex[:8]}.mp4"

    try:
        await download_video(video_url, input_path)
    except Exception as e:
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка скачивания: {e}")
        return

    await bot.edit_message(chat_id, status_id, "🔍 Сканирую на крутые моменты (2-4 минуты)...")

    try:
        result = await asyncio.to_thread(engine.scan_highlights, input_path, MAX_HIGHLIGHTS)
    except Exception as e:
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка сканирования: {e}")
        return

    moments = result.get("moments", [])
    if not moments:
        await bot.edit_message(chat_id, status_id, "😕 Не нашёл ярких моментов в этом видео.")
        if os.path.exists(input_path):
            os.remove(input_path)
        return

    session_manager.set_awaiting_selection(user_id, chat_id, input_path, moments)

    lines = ["🎬 *Нашёл крутые моменты!*\n"]
    for i, m in enumerate(moments, 1):
        s, e = m["start"], m["end"]
        lines.append(
            f"*{i}.* {format_moment_time(s)} – {format_moment_time(e)} "
            f"({int(e - s)} сек, громкость x{m['energy']})"
        )
    lines.append("\nКакие моменты нарезать с субтитрами?")
    lines.append("Напиши номера через запятую (например: 1, 3)")
    lines.append("/cancel — отмена.")

    await bot.edit_message(chat_id, status_id, "\n".join(lines))


# ------------------------------------------------------------
# Хайлайты: выбор моментов
# ------------------------------------------------------------
async def handle_select_moments(chat_id: int, user_id: int, text: str):
    """Обрабатывает выбор моментов пользователем."""
    state = session_manager.get_state(user_id)
    if not state:
        await bot.send_message(chat_id, "❌ Сначала нажми '🎬 Найти хайлайты' и отправь видео.")
        return

    if text.strip().lower() == "/cancel":
        session_manager.clear_state(user_id)
        if os.path.exists(state.video_path):
            os.remove(state.video_path)
        from keyboards import main_menu_kb
        await bot.send_message(chat_id, "❌ Отменено.", reply_markup=main_menu_kb())
        return

    try:
        selected_indices = [int(x.strip()) - 1 for x in text.split(",")]
    except ValueError:
        await bot.send_message(chat_id, "❌ Введи номера через запятую (например: 1, 3, 5)")
        return

    valid_indices = [i for i in selected_indices if 0 <= i < len(state.moments)]
    if not valid_indices:
        await bot.send_message(chat_id, f"❌ Нет таких моментов. Доступно от 1 до {len(state.moments)}.")
        return

    if len(valid_indices) > MAX_CLIPS_PER_REQUEST:
        await bot.send_message(chat_id, f"❌ Можно выбрать максимум {MAX_CLIPS_PER_REQUEST} момента.")
        return

    status_id = await bot.send_message(chat_id, f"🎬 Нарезаю {len(valid_indices)} клип(ов) с субтитрами...")

    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)
        is_premium = user.active_sub != "default"
        if user_id not in ADMIN_IDS:
            await increment_video_counter(user, session)

    clips = []
    try:
        for idx in valid_indices:
            moment = state.moments[idx]
            clip_path = state.video_path.replace(".mp4", f"_clip_{idx}.mp4")
            await asyncio.to_thread(engine.cut_clip, state.video_path, moment["start"], moment["end"], clip_path)
            result = await asyncio.to_thread(engine.process_video, clip_path, str(user_id), is_premium)
            clips.append(result["video_path"])
            if os.path.exists(clip_path):
                os.remove(clip_path)
    except Exception as e:
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка нарезки: {e}")
        session_manager.clear_state(user_id)
        if os.path.exists(state.video_path):
            os.remove(state.video_path)
        return

    await bot.edit_message(chat_id, status_id, "📤 Отправляю клипы...")
    for i, clip in enumerate(clips, 1):
        await bot.send_video(chat_id, clip, caption=f"✅ Клип #{i}")
        if os.path.exists(clip):
            os.remove(clip)

    session_manager.clear_state(user_id)
    if os.path.exists(state.video_path):
        os.remove(state.video_path)

    await bot.edit_message(chat_id, status_id, "✅ Готово!")