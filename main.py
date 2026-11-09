"""Точка входа в приложение. Только запуск сервера и планировщика."""

import asyncio
import sys
from aiohttp import web
import logging
from apscheduler.triggers.cron import CronTrigger

from database_max import init_db_max
from services_max import reset_all_daily_limits, check_expired_subscriptions
from config import MAX_WEBHOOK_URL, WEBHOOK_PATH, PORT, MOSCOW_TZ
from app import bot, scheduler
from app import engine
from webhook import handle_max_webhook
from yookassa_webhook import handle_yookassa_webhook


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Устанавливаем глобальный уровень WARNING для всех логгеров
logging.basicConfig(
    level=logging.WARNING,  # По умолчанию только WARNING и выше
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Включаем INFO только для нашего основного логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Явно выключаем спам от всех библиотек
SPAM_LOGGERS = [
    "aiohttp", "aiohttp.access", "aiohttp.server",
    "apscheduler", "apscheduler.scheduler",
    "httpx", "httpx2", "httpcore",
    "huggingface_hub", "faster_whisper",
    "urllib3", "urllib3.connectionpool",
    "PIL", "PIL.PngImagePlugin",
    "sqlalchemy", "sqlalchemy.engine",
]

_fh = logging.FileHandler("timing.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
for _name in ("timing", "link_downloader"):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.INFO)
    _lg.addHandler(_fh)

for logger_name in SPAM_LOGGERS:
    logging.getLogger(logger_name).setLevel(logging.WARNING)
# ============================================================


async def update_ytdlp():
    """Обновляет yt-dlp в фоне, не блокируя запуск бота."""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            print("⚠️ Обновление yt-dlp: таймаут 120 сек")
            return

        if proc.returncode == 0:
            print("✅ yt-dlp обновлён")
        else:
            print(f"⚠️ Не удалось обновить yt-dlp: {stderr.decode(errors='ignore')[:200]}")
    except Exception as e:
        print(f"⚠️ Не удалось обновить yt-dlp: {e}")


async def register_webhook():
    url = "https://platform-api.max.ru/subscriptions"
    headers = {"Authorization": bot.token, "Content-Type": "application/json"}
    payload = {"url": MAX_WEBHOOK_URL, "event_types": ["message_created", "bot_started", "message_callback"]}
    try:
        import aiohttp
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status in (200, 201):
                    print(f"✅ MAX webhook зарегистрирован: {MAX_WEBHOOK_URL}")
                else:
                    print(f"⚠️ MAX webhook: {resp.status} {await resp.text()}")
    except Exception as e:
        print(f"❌ MAX webhook error: {e}")


async def main():
    ytdlp_task = asyncio.create_task(update_ytdlp())  # в фоне, не ждём

        
    await init_db_max()
    warmup_task = asyncio.create_task(asyncio.to_thread(engine.warmup))
    await register_webhook()

    # Планировщик
    scheduler.add_job(
        reset_all_daily_limits,
        CronTrigger(hour=0, minute=30, timezone=MOSCOW_TZ),
        id="daily_reset",
        replace_existing=True,
    )
    scheduler.add_job(
        check_expired_subscriptions,
        CronTrigger(hour=1, minute=0, timezone=MOSCOW_TZ),
        id="check_expired",
        replace_existing=True,
    )
    scheduler.start()

    # Веб-сервер
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_max_webhook)
    app.router.add_post("/yookassa-webhook", handle_yookassa_webhook)
    app.router.add_post("/yookassa-webhook-max", handle_yookassa_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print(f"✅ MAX-бот запущен на порту {PORT}")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())