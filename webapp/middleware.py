"""webapp/middleware.py — из кого бы ни пришёл запрос, получаем uid единого пользователя.

Порядок:
  1) /api/site/register и /api/site/login — публичные (свои проверки в обработчиках);
  2) медиа-ссылки /api/jobs/{id}/preview|download — токен ?t= (заголовков <video> не шлёт);
  3) X-Site-Token — сессия сайта (вход по имени/паролю);
  4) X-Init-Data — initData MAX или Telegram (подсказка платформы в X-Platform).
После успеха: request['uid'] = users_web.id, request['platform'], request['admin'].
"""
import logging
import traceback

from aiohttp import web

from config import ADMIN_IDS, TG_ADMIN_IDS
from miniapp.errors import ApiError
from services_web import resolve_identity

log = logging.getLogger("timing")

PUBLIC_PATHS = ("/api/site/register", "/api/site/login")


def _is_admin(platform: str, ext_id: str) -> bool:
    try:
        i = int(ext_id)
    except (TypeError, ValueError):
        return False
    return (platform == "max" and i in ADMIN_IDS) or (platform == "tg" and i in TG_ADMIN_IDS)


def make_middleware(validator, sessions, signer, jobs, debug: bool = False):
    @web.middleware
    async def _mw(request, handler):
        path = request.path
        try:
            if path in PUBLIC_PATHS:
                return await handler(request)

            # Медиа: <video src> и <a download> не шлют заголовков — авторизуем токеном ?t=
            if path.startswith("/api/jobs/") and ("/preview/" in path or "/download/" in path):
                jid = path.split("/")[3]
                job = jobs.get_by_id(jid)
                if job and signer.verify(jid, request.query.get("t", "")):
                    request["uid"] = job.user_id
                    return await handler(request)
                raise ApiError("Открой приложение", 401)

            # Сайт: сессия по имени/паролю
            token = request.headers.get("X-Site-Token", "")
            if token:
                uid = sessions.verify(token)
                if uid:
                    if debug:
                        log.warning(f"[REQ] {request.method} {path} site uid={uid}")
                    request["uid"] = uid
                    request["platform"] = "site"
                    request["ext_id"] = ""
                    request["display_name"] = ""
                    request["admin"] = False
                    return await handler(request)

            # MAX / Telegram: initData мессенджера
            raw = request.headers.get("X-Init-Data", "")
            if raw:
                hint = request.headers.get("X-Platform", "").lower()
                res = validator.validate(raw, hint)
                if res:
                    platform, ext_id, name = res
                    user = await resolve_identity(platform, ext_id, display_name=name)
                    if debug:
                        log.warning(f"[REQ] {request.method} {path} {platform} "
                                    f"ext={ext_id} → uid={user.id}")
                    request["uid"] = user.id
                    request["platform"] = platform
                    request["ext_id"] = ext_id
                    request["display_name"] = name
                    request["admin"] = _is_admin(platform, ext_id)
                    return await handler(request)
                if debug:
                    log.warning(f"[REQ] {request.method} {path} initData не прошла "
                                f"(len={len(raw)}, hint={hint})")

            raise ApiError("Войди на сайте или открой приложение из MAX / Telegram", 401)
        except ApiError as e:
            if debug:
                log.warning(f"[REQ] {path} → {e.code}: {e.msg}")
            return web.json_response({"error": e.msg}, status=e.code)
        except web.HTTPException:
            raise
        except Exception as e:
            traceback.print_exc()
            return web.json_response({"error": f"{type(e).__name__}: {str(e)[:150]}"}, status=500)

    return _mw
