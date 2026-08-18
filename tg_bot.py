import asyncio
import os
import subprocess
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
from payments import create_payment
from services import activate_subscription
from subscriptions import SUBSCRIPTIONS

from database import async_session, init_db
from services import (
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
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = set()
admin_ids_str = os.getenv("ADMIN_IDS", "")
if admin_ids_str:
    try:
        ADMIN_IDS = set(int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit())
    except ValueError:
        pass

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

scheduler = AsyncIOScheduler()
moscow_tz = timezone("Europe/Moscow")

class EmailForm(StatesGroup):
    waiting_for_email = State()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await message.answer(
            "Привет! Это бот, который умеет накладывать анимированные субтитры на видео.\n"
            "Отправь видео, а бот сам добавит субтитры и пришлет тебе готовое видео!"
        )

@dp.message(Command("email"))
async def cmd_email(message: Message, state: FSMContext):
    await message.answer("Введи свой email (нужен для отправки чеков):")
    await state.set_state(EmailForm.waiting_for_email)

@dp.message(EmailForm.waiting_for_email)
@dp.message(EmailForm.waiting_for_email)
async def process_email(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Пожалуйста, введи email текстом.")
        return

    email = message.text.strip()
    if "@" not in email or "." not in email:
        await message.answer("Кажется, email невалидный. Попробуй ещё раз. \n"
                             "Перед повторной отправкой email "
                             "снова воспользуйтесь командой /email")
        await state.clear()
        return

    user_id = message.from_user.id
    async with async_session() as session:
        await set_user_email(session, user_id, email)

    data = await state.get_data()
    sub_id = data.get("sub_id")
    if sub_id:
        await message.answer(
            "Email сохранён! Теперь снова выбери подписку через /pay и нажми на неё, чтобы оплатить."
        )
    else:
        await message.answer(f"Email {email} сохранён!")
    await state.clear()

@dp.message(F.video)
async def handle_video(message: Message):
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS

    async with async_session() as session:
        user = await get_or_create_user(session, user_id)

        # Лимит проверяем только для не-админов
        if not is_admin and not can_process_video(user):
            await message.answer(
                "К сожалению у вас закончились бесплатные видео на сегодня.\n "
                "Без подписки доступно 3 видео в день.\n "
                "Возвращайся завтра или можешь оформить подписку."
            )
            return

        # Определяем, является ли подписка платной (не default)
        is_premium = user.active_sub != "default"

        # Скачивание
        status_msg = await message.answer("Скачиваю видео...")
        file_id = message.video.file_id
        file = await bot.get_file(file_id)
        input_path = f"downloads/{file_id}.mp4"
        os.makedirs("downloads", exist_ok=True)
        try:
            await bot.download_file(file.file_path, input_path)
        except Exception as e:
            await status_msg.edit_text(f"Не удалось скачать видео. Ошибка: {e}")
            return

        # Обработка (передаём is_premium)
        await status_msg.edit_text("Расшифровываю речь и накладываю субтитры...")
        try:
            from core import process_video
            result = await asyncio.to_thread(process_video, input_path, str(user_id), is_premium)
        except subprocess.CalledProcessError as e:
            ffmpeg_error = e.stderr.strip() if e.stderr else "нет подробностей"
            if len(ffmpeg_error) > 500:
                ffmpeg_error = ffmpeg_error[:500] + "...\n(обрезано)"
            await status_msg.edit_text(f"Ошибка ffmpeg:\n{ffmpeg_error}")
            return
        except Exception as e:
            await status_msg.edit_text(f"Ошибка: {type(e).__name__}: {e}")
            return

        # Отправка
        await status_msg.edit_text("Отправляю результат...")
        video_file = FSInputFile(result["video_path"])
        await message.answer_video(video_file, caption="Твоё видео с субтитрами!")

        if result.get("srt_path"):
            srt_file = FSInputFile(result["srt_path"])
            await message.answer_document(srt_file, caption="Файл субтитров (SRT)")

        # Счётчик увеличиваем только для не-админов
        if not is_admin:
            await increment_video_counter(user, session)

        await status_msg.delete()

@dp.message(Command("pay"))
async def cmd_pay(message: Message):
    lines = ["📦 <b>Доступные подписки:</b>"]
    kb = InlineKeyboardBuilder()
    for sub_id, sub_info in SUBSCRIPTIONS.items():
        if sub_info["price"] > 0:
            lines.append(f"• {sub_info['name']} – {sub_info['price']}₽\n  {sub_info['description']}")
            kb.button(text=f"{sub_info['name']} – {sub_info['price']}₽", callback_data=f"pay:{sub_id}")
    await message.answer("\n".join(lines), reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pay:"))
async def process_payment(callback_query: types.CallbackQuery, state: FSMContext):
    sub_id = callback_query.data.split(":")[1]
    user_id = callback_query.from_user.id

    async with async_session() as session:
        user = await get_or_create_user(session, user_id)
        if user.email:
            # Email уже есть – сразу создаём платёж
            try:
                payment_id, url = await create_payment(user_id, sub_id, user.email)
                await callback_query.message.answer(f"Оплати подписку по ссылке:\n{url}")
            except Exception as e:
                await callback_query.message.answer(f"Ошибка создания платежа: {e}")
        else:
            # Email нет – просим ввести, запоминая выбранную подписку
            await callback_query.message.answer(
                "Для оплаты нужен email. Введи его сейчас (просто напиши в чат):"
            )
            await state.set_state(EmailForm.waiting_for_email)
            await state.update_data(sub_id=sub_id)
        await callback_query.answer()

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🤖 <b>Справка по командам</b>\n"
        "/start – Начать работу\n"
        "/email – Указать email для оплаты\n"
        "/pay – Купить подписку\n"
        "/help – Это сообщение\n\n"
        "Отправь видео, и я добавлю анимированные субтитры!"
    )

@dp.message(Command("top"))
async def cmd_top(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Недостаточно прав.")
        return

    top = await get_top_users(limit=20)
    if not top:
        await message.answer("Нет данных.")
        return

    lines = ["🏆 Топ-20 пользователей по обработанным видео:"]
    for user_id, count in top:
        lines.append(f"{count} – {user_id}")
    await message.answer("\n".join(lines))

@dp.message(Command("setdb"))
async def cmd_setdb(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Недостаточно прав.")
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer(
            "Использование:\n"
            "/setdb USER_ID FIELD VALUE\n\n"
            "Доступные поля: email, active_sub, video_limit, videos_used_today, total_videos_processed"
        )
        return

    # дальше без изменений

    user_id = int(parts[1])
    field = parts[2].lower()
    value = parts[3]

    async with async_session() as session:
        success, msg = await update_user_field(session, user_id, field, value)
        await message.answer(msg if success else f"❌ {msg}")

@dp.message(Command("sendmsg"))
async def cmd_sendmsg(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Недостаточно прав.")
        return

    # Формат: /sendmsg user_id текст сообщения
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование:\n/sendmsg USER_ID TEXT")
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный user_id.")
        return

    text = parts[2]

    try:
        await bot.send_message(user_id, text)
        await message.answer(f"✅ Сообщение отправлено пользователю {user_id}.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить: {e}")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Недостаточно прав.")
        return

    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("Использование: /broadcast ТЕКСТ")
        return

    user_ids = await get_all_user_ids()
    if not user_ids:
        await message.answer("Нет пользователей для рассылки.")
        return

    success = 0
    failed = 0

    for uid in user_ids:
        try:
            # parse_mode=None, чтобы избежать ошибок при случайных символах
            await bot.send_message(uid, text, parse_mode=None)
            success += 1
        except Exception as e:
            failed += 1
        await asyncio.sleep(0.05)  # щадящий режим, чтобы не превысить лимиты Telegram

    await message.answer(
        f"✅ Рассылка завершена.\n"
        f"Успешно: {success}\n"
        f"Ошибок: {failed}"
    )

async def handle_yookassa_webhook(request: web.Request):
    try:
        data = await request.json()
        event = data.get("event")
        if event == "payment.succeeded":
            payment_info = data["object"]
            meta = payment_info.get("metadata", {})
            user_id = meta.get("user_id")
            sub_id = meta.get("sub_id")

            if user_id and sub_id:
                async with async_session() as session:
                    result = await activate_subscription(session, int(user_id), sub_id)
                    if result:
                        # Отправляем уведомление пользователю
                        bot = request.app['bot']
                        text = (
                            f"🎉 <b>Подписка активирована!</b>\n\n"
                            f"📦 Тариф: {result['sub_name']}\n"
                            f"📆 Действует до: {result['expiry']}\n"
                            f"🔢 Лимит видео в день: {result['video_limit']}\n\n"
                            f"Спасибо за оплату!"
                        )
                        try:
                            await bot.send_message(int(user_id), text)
                        except Exception as e:
                            print(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        return web.Response(text="OK")
    except Exception as e:
        print(f"Webhook error: {e}")
        return web.Response(text="Error", status=500)

async def main():
    await init_db()

    # Устанавливаем список команд (появляется в меню)
    commands = [
        BotCommand(command="start", description="Начать работу / информация"),
        BotCommand(command="email", description="Указать email для оплаты"),
        BotCommand(command="pay", description="Купить подписку"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)

    # Сброс дневных лимитов в 0:30 МСК
    scheduler.add_job(
        reset_all_daily_limits,
        trigger=CronTrigger(hour=0, minute=30, timezone=moscow_tz),
        id="daily_reset",
        replace_existing=True,
    )

    # Проверка истекших подписок каждый день в 1:00 МСК
    scheduler.add_job(
        check_expired_subscriptions,
        trigger=CronTrigger(hour=1, minute=0, timezone=moscow_tz),
        id="check_expired",
        replace_existing=True,
    )

    scheduler.start()

    # Сохраняем бота в приложении для доступа из вебхука
    app = web.Application()
    app['bot'] = bot
    app.router.add_post("/yookassa-webhook", handle_yookassa_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    print("Бот и веб-сервер запущены...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())