"""Обработчики текстовых команд: /start, /help, /email, /pay, /stats."""

from database_max import async_session_max
from services_max import (
    get_or_create_user,
    set_user_email,
    get_users_stats,
)
from keyboards.main_kb import main_menu_kb, subscriptions_kb
from payments import create_payment
from app import bot


async def handle_start(chat_id: int, user_id: int):
    async with async_session_max() as session:
        await get_or_create_user(session, user_id, chat_id)
    await bot.send_message(
        chat_id,
        "👋 Привет! Я бот, который накладывает анимированные субтитры на видео.\n\n"
        "Просто отправь мне видео — и я верну его с крутыми караоке-субтитрами! 🎬",
        reply_markup=main_menu_kb(),
    )


async def handle_ask_email(chat_id: int):
    await bot.send_message(
        chat_id,
        "✉️ Отправь свой email одним сообщением (нужен для отправки чеков).",
    )


async def handle_email_input(chat_id: int, user_id: int, email: str):
    if "@" not in email or "." not in email:
        await bot.send_message(chat_id, "❌ Кажется, email невалидный. Попробуй ещё раз: /email")
        return
    async with async_session_max() as session:
        await set_user_email(session, user_id, email)
    await bot.send_message(
        chat_id,
        f"✅ Email {email} сохранён!",
        reply_markup=main_menu_kb(),
    )


async def handle_show_subscriptions(chat_id: int):
    lines = ["📦 *Доступные подписки:*"]
    from subscriptions import SUBSCRIPTIONS
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


async def handle_stats(chat_id: int, user_id: int, admin_ids: set):
    if user_id not in admin_ids:
        await bot.send_message(chat_id, "Недостаточно прав.")
        return
    total, paid, with_email = await get_users_stats()
    await bot.send_message(
        chat_id,
        f"📊 *Статистика MAX-бота:*\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"💎 С активной подпиской: {paid}\n"
        f"📧 С указанным email: {with_email}",
    )


async def handle_help(chat_id: int):
    await bot.send_message(
        chat_id,
        "🤖 *Справка*\n\n"
        "*🎬 Найти хайлайты* — найду лучшие моменты в твоём видео\n"
        "*📦 Подписки* — оформить премиум\n"
        "/start — начать\n"
        "/email — указать email\n"
        "/help — это сообщение\n\n"
        "Или просто отправь видео — верну с субтитрами!",
        reply_markup=main_menu_kb(),
    )