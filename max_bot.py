import asyncio
import os
import subprocess
import traceback
import uuid
import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from database_max import async_session_max, init_db_max
from services_max import (
    get_or_create_user,
    can_process_video,
    increment_video_counter,
    set_user_email,
    reset_all_daily_limits,
    check_expired_subscriptions,
    get_top_users,
    activate_subscription,
    update_user_field,
    get_all_user_ids,
    get_users_stats,
)
from subscriptions import SUBSCRIPTIONS
from payments import create_payment
from max_bot_client import MaxBot

import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.getLogger("aiohttp.server").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)         
logging.getLogger("huggingface_hub").setLevel(logging.WARNING) 
logging.getLogger("urllib3").setLevel(logging.WARNING) 
logging.getLogger("faster_whisper").setLevel(logging.WARNING)  

load_dotenv()
MAX_TOKEN = os.getenv("MAX_BOT_TOKEN")
MAX_WEBHOOK_URL = os.getenv("MAX_WEBHOOK_URL")   # https://subtitle-bot.ru/max-webhook
WEBHOOK_PATH = "/max-webhook"
PORT = 8081

ADMIN_IDS = set()
admin_ids_str = os.getenv("MAX_ADMIN_IDS", "")
if admin_ids_str:
    try:
        ADMIN_IDS = set(int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit())
    except ValueError:
        pass

bot = MaxBot(MAX_TOKEN)
scheduler = AsyncIOScheduler()
moscow_tz = timezone("Europe/Moscow")


# ------------------------------------------------------------
# Клавиатуры
# ------------------------------------------------------------
def main_menu_kb():
    return [{
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [{"type": "callback", "text": "📦 Подписки", "payload": "show_subscriptions"}],
                [{"type": "callback", "text": "✉️ Указать email", "payload": "ask_email"}],
                [{"type": "callback", "text": "ℹ️ Помощь", "payload": "help"}],
            ]
        }
    }]


def subscriptions_kb():
    buttons = []
    for sub_id, info in SUBSCRIPTIONS.items():
        if info["price"] > 0:
            buttons.append([{
                "type": "callback",
                "text": f"{info['name']} – {info['price']}₽",
                "payload": f"pay:{sub_id}"
            }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "back_to_menu"}])
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


# ------------------------------------------------------------
# Обработчики
# ------------------------------------------------------------
async def handle_start(chat_id: int, user_id: int):
    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)
    await bot.send_message(
        chat_id,
        "👋 Привет! Я бот, который накладывает анимированные субтитры на видео.\n\n"
        "Просто отправь мне видео — и я верну его с крутыми караоке-субтитрами! 🎬",
        reply_markup=main_menu_kb()
    )


async def handle_ask_email(chat_id: int):
    await bot.send_message(chat_id, "✉️ Отправь свой email одним сообщением (нужен для отправки чеков).")


async def handle_email_input(chat_id: int, user_id: int, email: str):
    if "@" not in email or "." not in email:
        await bot.send_message(chat_id, "❌ Кажется, email невалидный. Попробуй ещё раз: /email")
        return
    async with async_session_max() as session:
        await set_user_email(session, user_id, email)
    await bot.send_message(chat_id, f"✅ Email {email} сохранён!", reply_markup=main_menu_kb())


async def handle_show_subscriptions(chat_id: int):
    lines = ["📦 *Доступные подписки:*"]
    for sub_id, info in SUBSCRIPTIONS.items():
        if info["price"] > 0:
            lines.append(f"• {info['name']} – {info['price']}₽\n  {info['description']}")
    await bot.send_message(chat_id, "\n".join(lines), reply_markup=subscriptions_kb())


async def handle_pay(chat_id: int, user_id: int, sub_id: str):
    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)
        if not user.email:
            await bot.send_message(chat_id, "✉️ Сначала укажи email командой /email")
            return
        await bot.send_message(chat_id, "⏳ Создаю платёж, подожди...")
        try:
            _, url = await create_payment(user_id, sub_id, user.email, platform="max")
            await bot.send_message(chat_id, f"💳 Оплати подписку:\n{url}")
        except Exception as e:
            await bot.send_message(chat_id, f"❌ Ошибка: {e}")


async def handle_video_by_token(chat_id: int, user_id: int, video_token: str):
    """Получает URL видео по токену, скачивает и обрабатывает."""
    is_admin = user_id in ADMIN_IDS

    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)

        if not is_admin and not can_process_video(user):
            await bot.send_message(
                chat_id,
                "😔 Закончились бесплатные видео на сегодня (3/день).\n"
                "Возвращайся завтра или оформи подписку через /pay."
            )
            return

        is_premium = user.active_sub != "default"

        status_id = await bot.send_message(chat_id, "📥 Готовлю видео к скачиванию...")

        # Получаем URL по токену
        video_url = await bot.get_video_url(video_token)
        if not video_url:
            if status_id:
                await bot.edit_message(chat_id, status_id, "❌ Не удалось получить ссылку на видео.")
            return

        if status_id:
            await bot.edit_message(chat_id, status_id, "📥 Скачиваю видео...")

        os.makedirs("downloads", exist_ok=True)
        input_path = f"downloads/max_{user_id}_{uuid.uuid4().hex[:8]}.mp4"

        # Скачивание
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session_http:
                async with session_http.get(video_url) as r:
                    if r.status != 200:
                        raise Exception(f"HTTP {r.status}")
                    with open(input_path, "wb") as f:
                        f.write(await r.read())
        except Exception as e:
            print(f"[VIDEO ERROR] {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            if status_id:
                await bot.edit_message(chat_id, status_id, f"❌ Ошибка: {type(e).__name__}: {e}")
            return

        # Обработка
        if status_id:
            await bot.edit_message(chat_id, status_id, "🎬 Обрабатываю видео...")
        try:
            from core import process_video
            result = await asyncio.to_thread(process_video, input_path, str(user_id), is_premium)
        except subprocess.CalledProcessError as e:
            err = (e.stderr or "")[:500]
            if status_id:
                await bot.edit_message(chat_id, status_id, f"❌ Ошибка ffmpeg:\n{err}")
            return
        except Exception as e:
            print(f"[PROCESS VIDEO ERROR] {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            if status_id:
                await bot.edit_message(chat_id, status_id, f"❌ Ошибка: {type(e).__name__}: {e}")
            return

        # Отправка видео
        if status_id:
            await bot.edit_message(chat_id, status_id, "📤 Отправляю видео...")

        sent = await bot.send_video(chat_id, result["video_path"], caption="✅ Твоё видео с субтитрами!")

        if result.get("srt_path"):
            srt_path = result["srt_path"]
            # MAX не принимает .srt — переименуем в .txt
            txt_path = srt_path.rsplit(".", 1)[0] + ".txt"
            try:
                os.rename(srt_path, txt_path)
            except Exception:
                txt_path = srt_path
            await bot.send_document(chat_id, txt_path, caption="📄 Файл субтитров")

        if not is_admin:
            await increment_video_counter(user, session)

        if status_id:
            try:
                await bot.edit_message(chat_id, status_id, "✅ Готово!")
            except Exception:
                pass


# ------------------------------------------------------------
# Вебхук-обработчик MAX
# ------------------------------------------------------------
async def handle_max_webhook(request: web.Request):
    try:
        data = await request.json()
        update_type = data.get("update_type") or data.get("type")

        # --- bot_started ---
        if update_type == "bot_started":
            user_id = int(data.get("user", {}).get("user_id", 0))
            chat_id = int(data.get("chat_id", 0))
            if user_id and chat_id:
                await handle_start(chat_id, user_id)
            return web.Response(text="OK")

        # --- message_created ---
        if update_type == "message_created":
            msg = data.get("message", {})
            user_id = int(msg.get("sender", {}).get("user_id", 0))
            chat_id = int(msg.get("recipient", {}).get("chat_id") or msg.get("chat_id") or 0)
            body = msg.get("body", {})
            text = (body.get("text") or "").strip()
            attachments = body.get("attachments") or []

            if not user_id or not chat_id:
                return web.Response(text="OK")

            # Команды
            if text.startswith("/start"):
                await handle_start(chat_id, user_id)
                return web.Response(text="OK")
            
            if text.startswith("/help"):
                await bot.send_message(
                    chat_id,
                    "🤖 *Справка*\n\n"
                    "/start — начать\n"
                    "/email — указать email\n"
                    "/pay — купить подписку\n"
                    "/help — это сообщение\n\n"
                    "Отправь видео — верну с субтитрами!",
                    reply_markup=main_menu_kb()
                )
                return web.Response(text="OK")

            if text.startswith("/stats"):
                if user_id not in ADMIN_IDS:
                    await bot.send_message(chat_id, "Недостаточно прав.")
                    return web.Response(text="OK")
                
                total, paid, with_email = await get_users_stats()
                await bot.send_message(
                    chat_id,
                    f"📊 *Статистика MAX-бота:*\n\n"
                    f"👥 Всего пользователей: {total}\n"
                    f"💎 С активной подпиской: {paid}\n"
                    f"📧 С указанным email: {with_email}"
                )
                return web.Response(text="OK")
            
            if text.startswith("/email"):
                await handle_ask_email(chat_id)
                return web.Response(text="OK")
            if text.startswith("/pay"):
                async with async_session_max() as session:
                    user = await get_or_create_user(session, user_id, chat_id)
                await handle_show_subscriptions(chat_id)
                return web.Response(text="OK")

            # Видео?
            video_token = None
            for att in attachments:
                att_type = str(att.get("type", "")).lower()
                if att_type == "video":
                    video_token = (att.get("payload") or {}).get("token")
                    if video_token:
                        break

            if video_token:
                asyncio.create_task(handle_video_by_token(chat_id, user_id, video_token))
                return web.Response(text="OK")

            # Проверяем — может это email?
            if text and "@" in text and "." in text:
                await handle_email_input(chat_id, user_id, text)
                return web.Response(text="OK")

            return web.Response(text="OK")

        # --- message_callback ---
        if update_type == "message_callback":
            cb = data.get("callback", {})
            payload = cb.get("payload", "")
            msg = data.get("message", {})
            chat_id = int(msg.get("recipient", {}).get("chat_id") or msg.get("chat_id") or 0)
            user_id = int(cb.get("user", {}).get("user_id", 0))

            if not chat_id:
                return web.Response(text="OK")

            if payload == "show_subscriptions":
                await handle_show_subscriptions(chat_id)
            elif payload == "ask_email":
                await handle_ask_email(chat_id)
            elif payload == "help":
                await bot.send_message(chat_id, "🤖 Отправь видео — верну с субтитрами!")
            elif payload == "back_to_menu":
                await bot.send_message(chat_id, "📋 Главное меню:", reply_markup=main_menu_kb())
            elif payload.startswith("pay:"):
                sub_id = payload.split(":")[1]
                await handle_pay(chat_id, user_id, sub_id)

            return web.Response(text="OK")

        return web.Response(text="OK")
    except Exception as e:
        print(f"[MAX webhook] {e}")
        return web.Response(text="OK")


# ------------------------------------------------------------
# Вебхук ЮKassa для MAX
# ------------------------------------------------------------
async def handle_yookassa_webhook_max(request: web.Request):
    try:
        data = await request.json()
        if data.get("event") != "payment.succeeded":
            return web.Response(text="OK")
        meta = data.get("object", {}).get("metadata", {})
        if meta.get("platform") != "max":
            return web.Response(text="OK")   # не наш платёж

        user_id = int(meta.get("user_id"))
        sub_id = meta.get("sub_id")

        async with async_session_max() as session:
            result = await activate_subscription(session, user_id, sub_id)
            if result:
                # отправляем уведомление
                async with async_session_max() as s2:
                    user = await get_or_create_user(s2, user_id)
                    if user.chat_id:
                        await bot.send_message(
                            user.chat_id,
                            f"🎉 *Подписка активирована!*\n\n"
                            f"📦 Тариф: {result['sub_name']}\n"
                            f"📆 До: {result['expiry']}\n"
                            f"🔢 Лимит: {result['video_limit']}/день"
                        )
        return web.Response(text="OK")
    except Exception as e:
        print(f"[YooKassa webhook MAX] {e}")
        return web.Response(text="OK")


# ------------------------------------------------------------
# Запуск
# ------------------------------------------------------------
async def register_webhook():
    url = "https://platform-api.max.ru/subscriptions"
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    payload = {"url": MAX_WEBHOOK_URL, "event_types": ["message_created", "bot_started", "message_callback"]}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status in (200, 201):
                    print(f"✅ MAX webhook зарегистрирован: {MAX_WEBHOOK_URL}")
                else:
                    print(f"⚠️ MAX webhook: {resp.status} {await resp.text()}")
    except Exception as e:
        print(f"❌ MAX webhook error: {e}")


async def main():
    await init_db_max()
    await register_webhook()

    # Планировщик
    scheduler.add_job(reset_all_daily_limits, CronTrigger(hour=0, minute=30, timezone=moscow_tz),
                      id="daily_reset", replace_existing=True)
    scheduler.add_job(check_expired_subscriptions, CronTrigger(hour=1, minute=0, timezone=moscow_tz),
                      id="check_expired", replace_existing=True)
    scheduler.start()

    # Веб-сервер
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_max_webhook)
    app.router.add_post("/yookassa-webhook", handle_yookassa_webhook_max)
    app.router.add_post("/yookassa-webhook-max", handle_yookassa_webhook_max)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print(f"✅ MAX-бот запущен на порту {PORT}")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())