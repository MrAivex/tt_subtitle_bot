"""Обработка callback'ов от inline-кнопок."""

from app import bot
from keyboards import main_menu_kb, processing_options_kb
from handlers.commands import (
    handle_show_subscriptions,
    handle_ask_email,
    handle_pay,
)
from handlers.video import start_processing


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
    
    # --- Новые callback'и для настроек обработки ---
    elif payload.startswith("mode:"):
        mode = payload.split(":")[1]
        from app import session_manager
        session_manager.update_options(user_id, mode=mode)
        state = session_manager.get_state(user_id)
        if state:
            await bot.edit_message(
                chat_id, 
                state.chat_id,  # используем chat_id из состояния
                "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':",
                reply_markup=processing_options_kb(
                    has_webcam=state.options.has_webcam,
                    format_mode=state.options.format
                )
            )
    
    elif payload == "toggle:webcam":
        from app import session_manager
        state = session_manager.get_state(user_id)
        if state:
            session_manager.update_options(user_id, has_webcam=not state.options.has_webcam)
            await bot.edit_message(
                chat_id,
                state.chat_id,
                "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':",
                reply_markup=processing_options_kb(
                    has_webcam=state.options.has_webcam,
                    format_mode=state.options.format
                )
            )
    
    elif payload == "toggle:format":
        from app import session_manager
        state = session_manager.get_state(user_id)
        if state:
            new_format = "vertical_9_16" if state.options.format == "original" else "original"
            session_manager.update_options(user_id, format=new_format)
            await bot.edit_message(
                chat_id,
                state.chat_id,
                "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':",
                reply_markup=processing_options_kb(
                    has_webcam=state.options.has_webcam,
                    format_mode=state.options.format
                )
            )
    
    elif payload == "start_processing":
        await start_processing(chat_id, user_id)