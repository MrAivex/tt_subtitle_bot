"""Обработчики текстовых команд: /start, /help, /pay, /stats."""

from database_max import async_session_max
from services_max import (
    get_or_create_user,
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
        "Открой мини-приложение, пришли ссылку на видео — и я верну его с крутыми караоке-субтитрами! 🎬",
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
        await bot.send_message(chat_id, await bot.send_message(chat_id, "✉️ Сначала сохрани email в профиле мини-приложения — он нужен для чека."))
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
        "/pay — подписки\n"
        "/start — начать\n"
        "/help — это сообщение\n\n"
        "Открой мини-приложение, пришли ссылку на видео, я найду интересные моменты и наложу субтитры",
        reply_markup=main_menu_kb(),
    )