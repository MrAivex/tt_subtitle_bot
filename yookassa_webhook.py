"""Обработчик вебхука ЮKassa.

Два источника платежей:
  platform="max" — старый MAX-бот (user_id — id в MAX): активируем в users_max
                   и синхронизируем единую базу, если человек уже заходил на сайт;
  platform="web" — сайт (user_id — единый users_web.id): активируем в users_web
                   и уведомляем через бота той платформы, где есть chat_id.
"""

import asyncio

from aiohttp import web

from database_max import async_session_max
from database_web import async_session_web
from services_max import activate_subscription, get_or_create_user
from services_web import (activate_subscription_web, activate_subscription_web_by_max,
                           list_identities)
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
        platform = meta.get("platform")
        user_id = int(meta["user_id"])
        sub_id = meta["sub_id"]

        if platform == "web":
            # оплата на сайте: user_id — уже единый id
            async with async_session_web() as session:
                result = await activate_subscription_web(session, user_id, sub_id)
            if result:
                await _notify_web_user(user_id, result)
            return web.Response(text="OK")

        if platform != "max":
            return web.Response(text="OK")

        # старый MAX-бот: как раньше
        async with async_session_max() as session:
            result = await activate_subscription(session, user_id, sub_id)
            if result:
                # человек мог уже заходить на сайт — применяем подписку и к единой базе
                await activate_subscription_web_by_max(user_id, sub_id)
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
        print(f"[YooKassa webhook] {e}")
        return web.Response(text="OK")


async def _notify_web_user(uid: int, result: dict):
    """Сообщаем об активации в чат бота той платформы, где известен chat_id."""
    try:
        idents = await list_identities(uid)
        for i in idents:
            try:
                if i.platform == "max":
                    async with async_session_max() as s2:
                        user = await get_or_create_user(s2, int(i.ext_id))
                        if user.chat_id:
                            await bot.send_message(
                                user.chat_id,
                                f"🎉 *Подписка активирована!*\n\n"
                                f"📦 Тариф: {result['sub_name']}\n"
                                f"📆 До: {result['expiry']}\n"
                                f"🔢 Лимит: {result['video_limit']}/день")
                            return
                elif i.platform == "tg":
                    from database_web import UserWeb
                    from sqlalchemy import select
                    async with async_session_web() as s:
                        u = (await s.execute(
                            select(UserWeb).where(UserWeb.id == uid))).scalar_one_or_none()
                        if u and u.chat_id:
                            from tg_handlers import bot as tg_bot   # лениво: без цикла импортов
                            await tg_bot.send_message(
                                u.chat_id,
                                f"🎉 <b>Подписка активирована!</b>\n\n"
                                f"📦 Тариф: {result['sub_name']}\n"
                                f"📆 До: {result['expiry']}\n"
                                f"🔢 Лимит: {result['video_limit']}/день")
                            return
            except Exception:
                pass
    except Exception:
        pass
