"""Точка входа единого веб-приложения (по умолчанию порт 8084).

Это «сайт»: то же приложение, что миниapp MAX, но его можно открыть
  как обычный сайт (вход по имени/паролю),
  как миниapp Telegram (кнопка в боте → TG_WEBAPP_URL),
  как миниapp MAX (адрес сайта в консоли MAX).
Все платформы сходятся в одной базе users_web (database_web.py).

Whisper здесь не грузится: распознавание делает общий asr_service.py
(в .env задан ASR_URL). Пайплайн — тот же, что у мини-приложения MAX.
"""
import asyncio
import logging
import os

from aiohttp import web
from apscheduler.triggers.cron import CronTrigger

from database_web import init_db_web
from config import WEB_PORT, MOSCOW_TZ
from app import scheduler, transcriber, asr_fast, ffmpeg, analyzer, renderer, downloader
from webapp import register_webapp
from services_web import reset_all_daily_limits_web, check_expired_subscriptions_web

# ============================================================
# Логирование (как в main.py / tg_main.py)
# ============================================================
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

for _name in ("aiohttp", "aiohttp.access", "aiohttp.server",
              "apscheduler", "apscheduler.scheduler",
              "httpx", "httpcore", "huggingface_hub", "faster_whisper",
              "urllib3", "sqlalchemy", "sqlalchemy.engine"):
    logging.getLogger(_name).setLevel(logging.ERROR)

_fh = logging.FileHandler("timing.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
for _name in ("timing", "link_downloader", "sources.downloader"):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.INFO)
    _lg.addHandler(_fh)
# ============================================================


async def warmup_asr():
    """Проверяем связь с ASR-сервисом (модели грузит и греет он сам)."""
    try:
        await asyncio.to_thread(transcriber.warmup)
        await asyncio.to_thread(asr_fast.warmup)
        print("✅ ASR-сервис отвечает", flush=True)
    except Exception as e:
        print(f"⚠️ ASR-сервис недоступен ({e}) — субтитры и поиск моментов не заработают",
              flush=True)


async def main():
    await init_db_web()
    os.makedirs("downloads", exist_ok=True)

    # 1. HTTP-сервер: сайт + API
    app = web.Application()
    register_webapp(app, ffmpeg=ffmpeg, analyzer=analyzer,
                    renderer=renderer, downloader=downloader)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    print(f"✅ Единый веб-миниapp запущен на порту {WEB_PORT}", flush=True)

    # 2. Проверка ASR в фоне
    asyncio.create_task(warmup_asr())

    # 3. Планировщик: сброс дневных лимитов и проверка подписок users_web
    scheduler.add_job(reset_all_daily_limits_web,
                      CronTrigger(hour=0, minute=30, timezone=MOSCOW_TZ),
                      id="daily_reset_web", replace_existing=True)
    scheduler.add_job(check_expired_subscriptions_web,
                      CronTrigger(hour=1, minute=0, timezone=MOSCOW_TZ),
                      id="check_expired_web", replace_existing=True)
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
