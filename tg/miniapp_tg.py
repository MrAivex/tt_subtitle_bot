"""tg/miniapp_tg.py — composition root мини-приложения для Telegram.

Повторяет miniapp.register_miniapp, но с TG-токеном, TG-биллингом/профилем/middleware
и с index.html, пропатченным под Telegram WebApp. Остальные сервисы — те же классы, что в MAX.
"""
import os
from pathlib import Path

from aiohttp import web

import miniapp as _mx
from config import MAX_FULL_VIDEO_SEC, MAX_HIGHLIGHTS
from miniapp.auth import InitDataValidator, MediaTokenSigner
from miniapp.clips_handlers import ClipsHandlers
from miniapp.jobs import JobStore
from miniapp.preview_service import PreviewService
from miniapp.render_service import RenderService
from miniapp.scan_service import ScanService
from .billing import TgBilling
from .index_patch import patch_for_telegram
from .middleware import make_middleware
from .profile import TgProfileHandlers
from .settings import TG_TOKEN

BASE_DIR = Path(_mx.__file__).resolve().parent      # берём index.html и static прямо из miniapp/
INDEX_PATH = BASE_DIR / "index.html"
STATIC_DIR = BASE_DIR / "static"


def register_tg_miniapp(app: web.Application, *, ffmpeg, analyzer, renderer, downloader):
    os.makedirs("downloads", exist_ok=True)
    debug = os.getenv("AUTH_DEBUG") == "1"

    # initData Telegram подписан HMAC("WebAppData", bot_token) — тот же алгоритм, что в MAX,
    # поэтому InitDataValidator подходит без изменений.
    validator = InitDataValidator([TG_TOKEN] if TG_TOKEN else [], debug=debug)
    signer = MediaTokenSigner(b"media:" + TG_TOKEN.encode() if TG_TOKEN else os.urandom(32))
    jobs = JobStore()
    billing = TgBilling()

    previews = PreviewService(ffmpeg)
    scan = ScanService(analyzer, previews, MAX_HIGHLIGHTS)
    render = RenderService(renderer, ffmpeg, billing, MAX_FULL_VIDEO_SEC)

    clips = ClipsHandlers(jobs, billing, scan, render, signer, ffmpeg, downloader)
    profile = TgProfileHandlers(billing)

    api = web.Application(middlewares=[make_middleware(validator, signer, jobs, debug)],
                          client_max_size=3 * 1024 ** 3)
    api.add_routes(clips.routes() + profile.routes())
    app.add_subapp("/api", api)

    async def index(request):
        html = patch_for_telegram(INDEX_PATH.read_text(encoding="utf-8"))
        return web.Response(text=html, content_type="text/html",
                            headers={"Cache-Control": "no-cache"})

    app.router.add_get("/app", index)
    app.router.add_get("/app/", index)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR)
    print(f"[TG MINIAPP] index.html: {INDEX_PATH} exists={INDEX_PATH.exists()}", flush=True)
