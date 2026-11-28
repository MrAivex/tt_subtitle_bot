"""webapp/site_handlers.py — вход/регистрация на сайте и привязка аккаунтов.

register и login публичные (см. middleware), поэтому здесь простая защита от
подбора пароля: не больше 20 попыток с одного IP за 10 минут.
"""
import time

from aiohttp import web

from miniapp.errors import ApiError
from services_web import register_site_user, login_site_user, issue_link_code, apply_link_code

_ATTEMPTS: dict = {}          # ip → список меток времени
_ATTEMPT_WINDOW = 600
_ATTEMPT_MAX = 20


def _too_many_attempts(ip: str) -> bool:
    now = time.time()
    marks = [t for t in _ATTEMPTS.get(ip, []) if now - t < _ATTEMPT_WINDOW]
    marks.append(now)
    _ATTEMPTS[ip] = marks
    return len(marks) > _ATTEMPT_MAX


class SiteHandlers:
    def __init__(self, sessions):
        self._sessions = sessions

    def routes(self):
        return [
            web.post("/site/register", self.register),
            web.post("/site/login", self.login),
            web.post("/link/start", self.link_start),
            web.post("/link/apply", self.link_apply),
        ]

    async def register(self, request):
        if _too_many_attempts(request.remote):
            raise ApiError("Слишком много попыток — подожди немного", 429)
        body = await request.json()
        try:
            user = await register_site_user(body.get("username") or "",
                                            body.get("password") or "")
        except ValueError as e:
            raise ApiError(str(e))
        return web.json_response({"token": self._sessions.issue(user.id),
                                   "name": user.username or ""})

    async def login(self, request):
        if _too_many_attempts(request.remote):
            raise ApiError("Слишком много попыток — подожди немного", 429)
        body = await request.json()
        try:
            user = await login_site_user(body.get("username") or "",
                                          body.get("password") or "")
        except ValueError:
            raise ApiError("Неверное имя или пароль")
        return web.json_response({"token": self._sessions.issue(user.id),
                                   "name": user.username or ""})

    async def link_start(self, request):
        """Код, который можно ввести на другой платформе, чтобы слить аккаунты."""
        code, ttl = await issue_link_code(request["uid"])
        return web.json_response({"code": code, "ttl": ttl})

    async def link_apply(self, request):
        code = ((await request.json()).get("code") or "").strip()
        try:
            await apply_link_code(code, request["uid"])
        except ValueError as e:
            raise ApiError(str(e))
        return web.json_response({"ok": True})
