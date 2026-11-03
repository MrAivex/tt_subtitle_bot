"""Обработка callback'ов от inline-кнопок."""

from app import bot
from keyboards import main_menu_kb
from handlers.commands import (
    handle_show_subscriptions,
    handle_ask_email,
    handle_pay,
)


async def handle_callback(chat_id: int, user_id: int, payload: str):
    """Роутинг callback'ов по payload."""
    if payload == "find_highlights":
        from handlers.video import handle_find_highlights_start
        await handle_find_highlights_start(chat_id, user_id)
    elif payload == "show_subscriptions":
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