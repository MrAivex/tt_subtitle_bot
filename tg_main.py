"""Точка входа Telegram-бота: отдельный процесс, отдельный порт (по умолчанию 8083).

Whisper здесь не грузится: распознавание делает общий asr_service.py
(в .env задан ASR_URL). Пайплайн — тот же, что у мини-приложения MAX.
"""
import asyncio
import logging
import os

from aiohttp import web
from apscheduler.triggers.cron import CronTrigger

from database_max import init_db_max
from config import (TG_WEBHOOK_URL, TG_WEBHOOK_PATH, TG_PORT, TG_WEBHOOK_SECRET,
                    MOSCOW_TZ)
from app import scheduler, transcriber, asr_fast
from tg_handlers import bot
from tg_webhook import handle_tg_webhook
from services_tg import reset_all_daily_limits_tg, check_expired_subscriptions_tg

# ============================================================
# Логирование (как в main.py)
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
    await init_db_max()
    os.makedirs("downloads", exist_ok=True)

    # 1. HTTP-сервер
    app = web.Application()
    app.router.add_post(TG_WEBHOOK_PATH, handle_tg_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", TG_PORT)
    await site.start()
    print(f"✅ TG-бот запущен на порту {TG_PORT}", flush=True)

    # 2. Вебхук
    if TG_WEBHOOK_URL and os.getenv("REGISTER_WEBHOOK", "1") != "0":
        ok = await bot.set_webhook(TG_WEBHOOK_URL, TG_WEBHOOK_SECRET)
        print(f"✅ TG webhook: {TG_WEBHOOK_URL}" if ok else "⚠️ TG webhook не зарегистрирован",
              flush=True)
    else:
        print("⚠️ TG_WEBHOOK_URL не задан или REGISTER_WEBHOOK=0 — вебхук не регистрирую",
              flush=True)

    # 3. Проверка ASR в фоне
    asyncio.create_task(warmup_asr())

    # 4. Планировщик: только users_tg (users_max обслуживает MAX-процесс)
    scheduler.add_job(reset_all_daily_limits_tg,
                      CronTrigger(hour=0, minute=30, timezone=MOSCOW_TZ),
                      id="daily_reset_tg", replace_existing=True)
    scheduler.add_job(check_expired_subscriptions_tg,
                      CronTrigger(hour=1, minute=0, timezone=MOSCOW_TZ),
                      id="check_expired_tg", replace_existing=True)
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
