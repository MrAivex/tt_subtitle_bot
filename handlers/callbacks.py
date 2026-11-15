"""Callback'и inline-кнопок: оплата и возврат в меню."""
from app import bot
from keyboards import main_menu_kb
from handlers.commands import handle_pay


async def handle_callback(chat_id: int, user_id: int, payload: str):
    if payload == "back_to_menu":
        await bot.send_message(chat_id, "📋 Главное меню:", reply_markup=main_menu_kb())
    elif payload.startswith("pay:"):
        await handle_pay(chat_id, user_id, payload.split(":", 1)[1])