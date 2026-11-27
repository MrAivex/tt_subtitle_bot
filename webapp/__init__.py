"""webapp/__init__.py — единое веб-приложение (сайт), которое работает сразу как:

  миниapp MAX      (initData MAX из https://st.max.ru/js/max-web-app.js),
  миниapp Telegram (initData TG  из https://telegram.org/js/telegram-web-app.js),
  отдельный сайт   (вход по имени/паролю — X-Site-Token).

Композиция повторяет miniapp/__init__.py: зависимости приходят из app.py,
пайплайн (JobStore/ScanService/RenderService/PreviewService) общий с миниapp MAX.
Биллинг — единая база users_web (web_billing.UnifiedBilling).
"""
import os
from pathlib import Path

from aiohttp import web

from config import (MAX_TOKEN, TG_TOKEN, MAX_HIGHLIGHTS, MAX_FULL_VIDEO_SEC,
                    RENDER_SLOTS, WEB_SESSION_SECRET, WEB_SESSION_TTL)
from miniapp.auth import auth_tokens
from miniapp.jobs import JobStore
from miniapp.preview_service import PreviewService
from miniapp.scan_service import ScanService
from miniapp.render_service import RenderService
from web_billing import UnifiedBilling
from .auth import MultiInitDataValidator, SessionTokens, MediaTokenSigner
from .chat_delivery import ChatDelivery
from .middleware import make_middleware
from .clips_handlers import WebClipsHandlers
from .profile_handlers import WebProfileHandlers
from .site_handlers import SiteHandlers

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"
STATIC_DIR = BASE_DIR / "static"


def register_webapp(app: web.Application, *, ffmpeg, analyzer, renderer, downloader):
    """Зависимости приходят снаружи (из app.py), глобальных синглтонов здесь нет."""

    os.makedirs("downloads", exist_ok=True)
    debug = os.getenv("AUTH_DEBUG") == "1"

    validator = MultiInitDataValidator(auth_tokens(MAX_TOKEN), TG_TOKEN, debug=debug)
    # секрет сессий/медиа должен быть стабильным между перезапусками
    _secret = (WEB_SESSION_SECRET or TG_TOKEN or MAX_TOKEN or "").encode()
    if not _secret:
        _secret = os.urandom(32)
    sessions = SessionTokens(_secret, WEB_SESSION_TTL)
    signer = MediaTokenSigner(_secret)

    jobs = JobStore()
    billing = UnifiedBilling()

    previews = PreviewService(ffmpeg)
    scan = ScanService(analyzer, previews, MAX_HIGHLIGHTS, ffmpeg)

    # готовые клипы дополнительно уходят документом в чат мессенджера (TG/MAX)
    delivery = ChatDelivery()

    async def _deliver(job, idx):
        r = job.renders.get(idx) or {}
        if r.get("status") == "ready" and r.get("path"):
            await delivery.deliver(job, idx, r["path"], r.get("name", ""))

    render = RenderService(renderer, ffmpeg, billing, MAX_FULL_VIDEO_SEC,
                            slots=RENDER_SLOTS, on_ready=_deliver)

    clips = WebClipsHandlers(jobs, billing, scan, render, signer, ffmpeg, downloader)
    profile = WebProfileHandlers(billing)
    site = SiteHandlers(sessions)

    api = web.Application(middlewares=[make_middleware(validator, sessions, signer, jobs, debug)],
                          client_max_size=3 * 1024 ** 3)
    api.add_routes(clips.routes() + profile.routes() + site.routes())
    app.add_subapp("/api", api)

    async def index(request):
        return web.FileResponse(INDEX_PATH, headers={"Cache-Control": "no-cache"})

    app.router.add_get("/", index)
    app.router.add_get("/app", index)      # старый путь миниapp — можно вести и сюда
    app.router.add_get("/app/", index)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR)
    print(f"[WEBAPP] index.html: {INDEX_PATH} exists={INDEX_PATH.exists()}", flush=True)
