"""Обработчик вебхука ЮKassa."""

import asyncio

from aiohttp import web

from database_max import async_session_max
from services_max import activate_subscription, get_or_create_user
from app import bot
from yookassa import Payment


async def handle_yookassa_webhook(request: web.Request):
    try:
        data = await request.json()
        if data.get("event") != "payment.succeeded":
            return web.Response(text="OK")
        payment = await asyncio.to_thread(Payment.find_one, data["object"]["id"])
        if payment.status != "succeeded":
            return web.Response(text="OK")
        meta = payment.metadata or {}
        if meta.get("platform") != "max":
            return web.Response(text="OK")
        user_id = int(meta["user_id"])
        sub_id = meta["sub_id"]

        async with async_session_max() as session:
            result = await activate_subscription(session, user_id, sub_id)
            if result:
                async with async_session_max() as s2:
                    user = await get_or_create_user(s2, user_id)
                    if user.chat_id:
                        await bot.send_message(
                            user.chat_id,
                            f"🎉 *Подписка активирована!*\n\n"
                            f"📦 Тариф: {result['sub_name']}\n"
                            f"📆 До: {result['expiry']}\n"
                            f"🔢 Лимит: {result['video_limit']}/день",
                        )
        return web.Response(text="OK")
    except Exception as e:
        print(f"[YooKassa webhook MAX] {e}")
        return web.Response(text="OK")