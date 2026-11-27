"""tg/handlers.py — вебхук Telegram: команды, inline-кнопки, перенаправление в мини-приложение."""
import hmac
import html
import logging
import traceback

from aiohttp import web

from config import FREE_PERIOD
from miniapp.tasks import spawn
from payments import create_payment
from sources import detect_platform, extract_url
from subscriptions import SUBSCRIPTIONS
from .app import bot
from .db import async_session_tg
from .services import get_or_create_user, get_users_stats
from .settings import TG_ADMIN_IDS, TG_MINIAPP_URL, TG_WEBHOOK_SECRET

log = logging.getLogger("tg")

_REDIRECT = ("🎬 Вся обработка в мини-приложении: превью клипов, плеер и скачивание.\n"
             "Открой его и загрузи видео или ссылку там 👇")


# ---------------- клавиатуры ----------------

def main_menu_kb() -> dict:
    return {"inline_keyboard": [[{"text": "🎬 Открыть приложение", "web_app": {"url": TG_MINIAPP_URL}}]]}


def subscriptions_kb() -> dict:
    rows = [[{"text": f"{i['name']} – {i['price']}₽", "callback_data": f"pay:{sid}"}]
            for sid, i in SUBSCRIPTIONS.items() if i["price"] > 0]
    rows.append([{"text": "🔙 Назад", "callback_data": "back_to_menu"}])
    return {"inline_keyboard": rows}


# ---------------- команды ----------------

async def handle_start(chat_id: int, user_id: int):
    async with async_session_tg() as s:
        await get_or_create_user(s, user_id, chat_id)
    promo = ("🎁 <b>Сейчас ты можешь пользоваться ботом абсолютно бесплатно, "
             "пока он находится в стадии тестирования!</b>\n\n") if FREE_PERIOD else ""
    await bot.send_message(
        chat_id,
        "👋 Привет! Я бот, который накладывает анимированные субтитры на видео "
        "и находит лучшие моменты в стримах.\n\n"
        f"{promo}"
        "Открой мини-приложение, пришли ссылку на видео или загрузи файл — "
        "и я верну клипы с крутыми караоке-субтитрами! 🎬",
        reply_markup=main_menu_kb(),
    )


async def handle_help(chat_id: int):
    await bot.send_message(
        chat_id,
        "🤖 <b>Справка</b>\n\n"
        "/pay — подписки\n"
        "/start — начать\n"
        "/help — это сообщение\n\n"
        "Открой мини-приложение, пришли ссылку на видео, я найду интересные моменты и наложу субтитры",
        reply_markup=main_menu_kb(),
    )


async def handle_show_subscriptions(chat_id: int):
    if FREE_PERIOD:
        await bot.send_message(chat_id, "🎁 Сейчас всё бесплатно, пока бот в тестировании — подписка не нужна!")
        return
    lines = ["📦 <b>Доступные подписки:</b>"]
    for info in SUBSCRIPTIONS.values():
        if info["price"] > 0:
            lines.append(f"• {html.escape(info['name'])} – {info['price']}₽\n  {html.escape(info['description'])}")
    await bot.send_message(chat_id, "\n".join(lines), reply_markup=subscriptions_kb())


async def handle_pay(chat_id: int, user_id: int, sub_id: str):
    async with async_session_tg() as s:
        user = await get_or_create_user(s, user_id, chat_id)
    if not user.email:
        await bot.send_message(chat_id, "✉️ Сначала сохрани email в профиле мини-приложения — он нужен для чека.",
                               reply_markup=main_menu_kb())
        return
    await bot.send_message(chat_id, "⏳ Создаю платёж, подожди...")
    try:
        _, url = await create_payment(user_id, sub_id, user.email, platform="tg")
        await bot.send_message(chat_id, "💳 Оплати подписку:",
                               reply_markup={"inline_keyboard": [[{"text": "💳 Перейти к оплате", "url": url}]]})
    except Exception as e:
        await bot.send_message(chat_id, f"❌ Ошибка: {html.escape(str(e))[:300]}")


async def handle_stats(chat_id: int, user_id: int):
    if user_id not in TG_ADMIN_IDS:
        await bot.send_message(chat_id, "Недостаточно прав.")
        return
    total, paid, with_email = await get_users_stats()
    await bot.send_message(
        chat_id,
        "📊 <b>Статистика TG-бота:</b>\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"💎 С активной подпиской: {paid}\n"
        f"📧 С указанным email: {with_email}",
    )


# ---------------- разбор апдейтов ----------------

async def _on_callback(cb: dict):
    await bot.answer_callback(cb["id"])
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id") or cb["from"]["id"]
    user_id = cb["from"]["id"]
    data = cb.get("data") or ""
    if data == "back_to_menu":
        await bot.send_message(chat_id, "📋 Главное меню:", reply_markup=main_menu_kb())
    elif data.startswith("pay:"):
        await handle_pay(chat_id, user_id, data.split(":", 1)[1])


async def _on_message(msg: dict):
    if (msg.get("chat") or {}).get("type") != "private" or not msg.get("from"):
        return                                  # группы и каналы не обслуживаем
    chat_id, user_id = msg["chat"]["id"], msg["from"]["id"]
    text = (msg.get("text") or msg.get("caption") or "").strip()

    if text.startswith("/"):
        cmd = text.split()[0].split("@")[0].lower()
        if cmd == "/start":
            return await handle_start(chat_id, user_id)
        if cmd == "/help":
            return await handle_help(chat_id)
        if cmd == "/stats":
            return await handle_stats(chat_id, user_id)
        if cmd == "/pay":
            return await handle_show_subscriptions(chat_id)

    url = extract_url(text)
    has_media = any(k in msg for k in ("video", "document", "video_note", "animation"))
    if (url and detect_platform(url)) or has_media:
        await bot.send_message(chat_id, _REDIRECT, reply_markup=main_menu_kb())


async def handle_update(update: dict):
    try:
        if update.get("callback_query"):
            await _on_callback(update["callback_query"])
        elif update.get("message"):
            await _on_message(update["message"])
    except Exception:
        log.error("[TG update] " + traceback.format_exc())


async def handle_tg_webhook(request: web.Request):
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(got, TG_WEBHOOK_SECRET):
        return web.Response(status=403)
    try:
        update = await request.json()
    except Exception:
        return web.Response(text="OK")
    spawn(handle_update(update))                # отвечаем Telegram сразу, работаем в фоне
    return web.Response(text="OK")
