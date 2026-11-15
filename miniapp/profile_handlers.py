"""miniapp/profile_handlers.py — профиль, email, оплата, статистика."""
from aiohttp import web

from config import ADMIN_IDS
from payments import create_payment
from database_max import async_session_max
from services_max import get_or_create_user, get_users_stats, set_user_email
from subscriptions import SUBSCRIPTIONS
from .errors import ApiError


class ProfileHandlers:
    def __init__(self, billing):
        self._billing = billing

    def routes(self):
        return [
            web.get("/me", self.me),
            web.post("/email", self.email),
            web.post("/pay", self.pay),
            web.get("/stats", self.stats),
        ]

    async def me(self, request):
        uid = request["uid"]
        u = await self._billing.user(uid)
        return web.json_response({
            "is_admin": uid in ADMIN_IDS, "sub": u.active_sub, "limit": u.video_limit,
            "used": u.videos_used_today, "email": u.email or "",
            "expiry": u.subscription_expiry.strftime("%d.%m.%Y") if u.subscription_expiry else "",
            "subs": [{"id": k, "name": v["name"], "price": v["price"], "description": v["description"]}
                     for k, v in SUBSCRIPTIONS.items() if v["price"] > 0],
        })

    async def email(self, request):
        email = ((await request.json()).get("email") or "").strip()
        if "@" not in email or "." not in email:
            raise ApiError("Похоже, email неверный")
        async with async_session_max() as s:
            await get_or_create_user(s, request["uid"])
            await set_user_email(s, request["uid"], email)
        return web.json_response({"ok": True})

    async def pay(self, request):
        sub_id = (await request.json()).get("sub_id")
        if sub_id not in SUBSCRIPTIONS or SUBSCRIPTIONS[sub_id]["price"] == 0:
            raise ApiError("Неизвестный тариф")
        user = await self._billing.user(request["uid"])
        if not user.email:
            raise ApiError("Сначала сохрани email — он нужен для чека")
        _, url = await create_payment(request["uid"], sub_id, user.email, platform="max")
        return web.json_response({"url": url})

    async def stats(self, request):
        if request["uid"] not in ADMIN_IDS:
            raise ApiError("Недостаточно прав", 403)
        total, paid, with_email = await get_users_stats()
        return web.json_response({"total": total, "paid": paid, "with_email": with_email})
