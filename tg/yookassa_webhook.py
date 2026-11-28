"""tg/yookassa_webhook.py — вебхук ЮKassa для платежей, созданных из Telegram (metadata.platform == "tg")."""
import asyncio
import logging

from aiohttp import web
from yookassa import Payment

from .app import bot
from .db import async_session_tg
from .services import activate_subscription, get_or_create_user

log = logging.getLogger("tg")


async def handle_yookassa_webhook_tg(request: web.Request):
    try:
        data = await request.json()
        if data.get("event") != "payment.succeeded":
            return web.Response(text="OK")
        payment = await asyncio.to_thread(Payment.find_one, data["object"]["id"])
        if payment.status != "succeeded":
            return web.Response(text="OK")
        meta = payment.metadata or {}
        if meta.get("platform") != "tg":
            return web.Response(text="OK")
        user_id = int(meta["user_id"])

        async with async_session_tg() as session:
            result = await activate_subscription(session, user_id, meta["sub_id"])
            user = await get_or_create_user(session, user_id) if result else None
        if result and user and user.chat_id:
            await bot.send_message(
                user.chat_id,
                "🎉 <b>Подписка активирована!</b>\n\n"
                f"📦 Тариф: {result['sub_name']}\n"
                f"📆 До: {result['expiry']}\n"
                f"🔢 Лимит: {result['video_limit']}/день",
            )
        return web.Response(text="OK")
    except Exception as e:
        log.error(f"[YooKassa webhook TG] {type(e).__name__}: {e}")
        return web.Response(text="OK")
