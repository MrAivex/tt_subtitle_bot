"""miniapp/__init__.py — composition root: единственное место, где всё собирается вместе."""
import os
from pathlib import Path

from aiohttp import web

from config import MAX_TOKEN, MAX_HIGHLIGHTS, MAX_FULL_VIDEO_SEC, RENDER_SLOTS
from .auth import InitDataValidator, MediaTokenSigner, auth_tokens
from .billing import Billing
from .clips_handlers import ClipsHandlers
from .jobs import JobStore
from .middleware import make_middleware
from .preview_service import PreviewService
from .profile_handlers import ProfileHandlers
from .render_service import RenderService
from .scan_service import ScanService

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"
STATIC_DIR = BASE_DIR / "static"


def register_miniapp(app: web.Application, *, ffmpeg, analyzer, renderer, downloader):
    """Зависимости приходят снаружи (из app.py), глобальных синглтонов здесь нет.

    ffmpeg     — core.ffmpeg_tools.FFmpeg
    analyzer   — highlights.analyzer.HighlightAnalyzer (метод analyze(wav, n) -> dict)
    renderer   — subtitles.renderer.SubtitleRenderer (render(src, premium=, vertical=))
    downloader — объект с audio_only / section / by_link / get_title (см. LinkSource)
    """
    os.makedirs("downloads", exist_ok=True)
    debug = os.getenv("AUTH_DEBUG") == "1"

    validator = InitDataValidator(auth_tokens(MAX_TOKEN), debug=debug)
    signer = MediaTokenSigner(MAX_TOKEN.encode() if MAX_TOKEN else os.urandom(32))
    jobs = JobStore()
    billing = Billing()

    previews = PreviewService(ffmpeg)
    scan = ScanService(analyzer, previews, MAX_HIGHLIGHTS, ffmpeg)
    render = RenderService(renderer, ffmpeg, billing, MAX_FULL_VIDEO_SEC, slots=RENDER_SLOTS)

    clips = ClipsHandlers(jobs, billing, scan, render, signer, ffmpeg, downloader)
    profile = ProfileHandlers(billing)

    api = web.Application(middlewares=[make_middleware(validator, signer, jobs, debug)],
                          client_max_size=3 * 1024 ** 3)
    api.add_routes(clips.routes() + profile.routes())
    app.add_subapp("/api", api)

    async def index(request):
        return web.FileResponse(INDEX_PATH, headers={"Cache-Control": "no-cache"})

    app.router.add_get("/app", index)
    app.router.add_get("/app/", index)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR)

    # Статику без Cache-Control браузеры и вебвью TG/MAX кэшируют без перепроверки:
    # после деплоя пользователи продолжали видеть старый интерфейс. Теперь файлы
    # хранятся в кэше, но при каждом открытии переспрашиваются (не изменились —
    # дешёвый 304), обновления доезжают со следующей же загрузкой страницы.
    @web.middleware
    async def _revalidate_static(request, handler):
        resp = await handler(request)
        if request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
        return resp

    app.middlewares.append(_revalidate_static)

    print(f"[MINIAPP] index.html: {INDEX_PATH} exists={INDEX_PATH.exists()}", flush=True)
