"""Точка входа Telegram-бота: отдельный процесс, отдельный порт (по умолчанию 8083).

Whisper здесь не грузится: распознавание делает общий asr_service.py
(в .env задан ASR_URL). Пайплайн — тот же, что у мини-приложения MAX.
Биллинг — единая база users_web (таблицы создаёт web-процесс или этот).
"""
import asyncio
import logging
import os

from aiohttp import web

from database_web import init_db_web
from config import (TG_WEBHOOK_URL, TG_WEBHOOK_PATH, TG_PORT, TG_WEBHOOK_SECRET)
from app import transcriber, asr_fast
from tg_handlers import bot
from tg_webhook import handle_tg_webhook

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
    # таблицы единой базы: users_web, identities_web, link_codes_web
    # (сброс лимитов и проверку подписок делает web-процесс, здесь только доступ)
    await init_db_web()
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

    # Планировщик не нужен: единая база обслуживается web-процессом
    # (reset_all_daily_limits_web / check_expired_subscriptions_web — в web_main.py).

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
