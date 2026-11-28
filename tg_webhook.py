"""Обработчик вебхука Telegram (зеркало webhook.py для MAX)."""
import asyncio

from aiohttp import web

from config import TG_WEBHOOK_SECRET
from tg_handlers import handle_message, handle_callback_query


async def handle_tg_webhook(request: web.Request):
    # Запросы шлёт только Telegram — с нашим secret_token из .env
    if TG_WEBHOOK_SECRET and \
            request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TG_WEBHOOK_SECRET:
        return web.Response(status=403)
    try:
        update = await request.json()
    except Exception:
        return web.Response(status=400)

    if "message" in update:
        asyncio.create_task(handle_message(update["message"]))
    elif "callback_query" in update:
        asyncio.create_task(handle_callback_query(update["callback_query"]))
    return web.Response(text="OK")
