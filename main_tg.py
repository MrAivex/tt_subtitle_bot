"""Точка входа Telegram-версии. Запуск: python main_tg.py  (отдельный процесс рядом с main.py)."""

import tg.settings as S   # noqa: F401  — первым: подменяет PAYMENT_RETURN_URL до импорта config/payments

import asyncio
import logging
import os

from aiohttp import web
from apscheduler.triggers.cron import CronTrigger

from config import MOSCOW_TZ
from tg.app import analyzer, bot, ffmpeg, renderer, scheduler, transcriber
from sources import downloader
from tg.db import init_db_tg
from tg.handlers import handle_tg_webhook
from tg.miniapp_tg import register_tg_miniapp
from tg.services import check_expired_subscriptions, reset_all_daily_limits
from tg.yookassa_webhook import handle_yookassa_webhook_tg

# ---------- логирование ----------
logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
_fh = logging.FileHandler("timing_tg.log", encoding="utf-8")    # отдельный файл, чтобы не мешать MAX-процессу
_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
for _name in ("timing", "link_downloader", "tg"):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.INFO)
    _lg.addHandler(_fh)
for _name in ("aiohttp", "aiohttp.access", "aiohttp.server", "apscheduler", "httpx", "httpcore",
              "huggingface_hub", "faster_whisper", "urllib3", "PIL", "sqlalchemy", "sqlalchemy.engine"):
    logging.getLogger(_name).setLevel(logging.WARNING)


async def setup_telegram():
    """Вебхук, кнопка меню и команды — только когда HTTP-сервер уже слушает порт."""
    if not S.TG_WEBHOOK_URL:
        print("⚠️ TG_WEBHOOK_URL не задан — вебхук не регистрирую", flush=True)
    elif await bot.set_webhook(S.TG_WEBHOOK_URL, S.TG_WEBHOOK_SECRET):
        print(f"✅ TG webhook зарегистрирован: {S.TG_WEBHOOK_URL}", flush=True)
    else:
        print("❌ TG webhook не зарегистрирован (см. timing_tg.log)", flush=True)

    if S.TG_MINIAPP_URL:
        await bot.set_menu_button(S.TG_MINIAPP_URL)
    else:
        print("⚠️ TG_MINIAPP_URL не задан — кнопки «Открыть приложение» работать не будут", flush=True)
    await bot.set_commands()


async def main():
    if not S.TG_TOKEN:
        raise SystemExit("Не задан TG_BOT_TOKEN")
    await init_db_tg()

    app = web.Application()
    register_tg_miniapp(app, ffmpeg=ffmpeg, analyzer=analyzer, renderer=renderer, downloader=downloader)
    app.router.add_post(S.TG_WEBHOOK_PATH, handle_tg_webhook)
    app.router.add_post("/yookassa-webhook-tg", handle_yookassa_webhook_tg)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", S.TG_PORT).start()
    print(f"✅ TG-бот запущен на порту {S.TG_PORT}", flush=True)

    if os.getenv("REGISTER_WEBHOOK", "1") != "0":
        await setup_telegram()

    tasks = [asyncio.create_task(asyncio.to_thread(transcriber.warmup))]   # держим ссылки, чтобы GC не собрал
    scheduler.add_job(reset_all_daily_limits, CronTrigger(hour=0, minute=30, timezone=MOSCOW_TZ),
                      id="tg_daily_reset", replace_existing=True)
    scheduler.add_job(check_expired_subscriptions, CronTrigger(hour=1, minute=0, timezone=MOSCOW_TZ),
                      id="tg_check_expired", replace_existing=True)
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await bot.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
