"""webapp/profile_handlers.py — профиль, email, оплата, статистика + привязки платформ."""
from aiohttp import web

from config import FREE_PERIOD, WEB_PUBLIC_URL
from payments import create_payment
from database_web import async_session_web
from services_web import get_or_create_user_web, set_user_email_web, list_identities
from subscriptions import SUBSCRIPTIONS
from miniapp.errors import ApiError

PLATFORM_NAMES = {"max": "MAX", "tg": "Telegram", "site": "Сайт"}


class WebProfileHandlers:
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
        idents = await list_identities(uid)
        return web.json_response({
            "platform": request["platform"],
            "name": request.get("display_name") or (u.username or ""),
            "is_admin": request.get("admin", False),
            "sub": u.active_sub, "limit": u.video_limit,
            "used": u.videos_used_today, "email": u.email or "",
            "expiry": u.subscription_expiry.strftime("%d.%m.%Y") if u.subscription_expiry else "",
            "subs": [{"id": k, "name": v["name"], "price": v["price"], "description": v["description"]}
                     for k, v in SUBSCRIPTIONS.items() if v["price"] > 0],
            "free_period": FREE_PERIOD,
            "identities": [{"platform": i.platform,
                            "name": i.display_name or i.ext_id}
                           for i in idents],
        })

    async def email(self, request):
        email = ((await request.json()).get("email") or "").strip()
        if "@" not in email or "." not in email:
            raise ApiError("Похоже, email неверный")
        async with async_session_web() as s:
            await get_or_create_user_web(s, request["uid"])
            await set_user_email_web(s, request["uid"], email)
        return web.json_response({"ok": True})

    async def pay(self, request):
        sub_id = (await request.json()).get("sub_id")
        if sub_id not in SUBSCRIPTIONS or SUBSCRIPTIONS[sub_id]["price"] == 0:
            raise ApiError("Неизвестный тариф")
        user = await self._billing.user(request["uid"])
        if not user.email:
            raise ApiError("Сначала сохрани email — он нужен для чека")
        # платёж привязан к единому пользователю: вернётся из ЮKassa в users_web
        _, url = await create_payment(request["uid"], sub_id, user.email,
                                      platform="web",
                                      return_url=WEB_PUBLIC_URL or None)
        return web.json_response({"url": url})

    async def stats(self, request):
        if not request.get("admin", False):
            raise ApiError("Недостаточно прав", 403)
        from services_web import get_users_stats_web
        total, paid, with_email, n_max, n_tg, n_site = await get_users_stats_web()
        return web.json_response({
            "total": total, "paid": paid, "with_email": with_email,
            "max": n_max, "tg": n_tg, "site": n_site,
        })
