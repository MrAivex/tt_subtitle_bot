"""tg/middleware.py — авторизация и единый формат ошибок (копия miniapp.middleware с текстом про Telegram)."""
import logging
import traceback

from aiohttp import web

from miniapp.errors import ApiError

log = logging.getLogger("timing")

_OPEN_MSG = "Открой приложение из Telegram"


def make_middleware(validator, signer, jobs, debug: bool = False):
    @web.middleware
    async def _mw(request, handler):
        path = request.path
        try:
            # Медиа: <video src> и ссылки скачивания не шлют заголовков — авторизуем токеном ?t=
            if path.startswith("/api/jobs/") and ("/preview/" in path or "/download/" in path):
                jid = path.split("/")[3]
                job = jobs.get_by_id(jid)
                if job and signer.verify(jid, request.query.get("t", "")):
                    request["uid"] = job.user_id
                    return await handler(request)
                raise ApiError(_OPEN_MSG, 401)

            raw = request.headers.get("X-Init-Data", "")
            uid = validator.validate(raw)
            if debug:
                log.warning(f"[REQ] {request.method} {path} initData_len={len(raw)} uid={uid}")
            if not uid:
                raise ApiError(_OPEN_MSG, 401)
            request["uid"] = uid
            return await handler(request)
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
