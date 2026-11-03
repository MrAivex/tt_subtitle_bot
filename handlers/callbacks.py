"""Обработка callback'ов от inline-кнопок."""

from app import bot, session_manager
from keyboards import main_menu_kb, processing_options_kb
from handlers.commands import (
    handle_show_subscriptions,
    handle_ask_email,
    handle_pay,
)
from handlers.video import start_processing


async def _update_keyboard(chat_id: int, state):
    """Обновляет клавиатуру настроек."""
    if not state:
        return
    
    text = "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':"
    kb = processing_options_kb(
        has_webcam=state.options.has_webcam,
        format_mode=state.options.format
    )
    
    if state.message_id:
        await bot.edit_message(chat_id, state.message_id, text, reply_markup=kb)
    else:
        # Fallback: если message_id нет, отправляем новое сообщение
        await bot.send_message(chat_id, text, reply_markup=kb)


async def handle_callback(chat_id: int, user_id: int, payload: str):
    """Роутинг callback'ов по payload."""
    state = session_manager.get_state(user_id)
    
    # --- Основные меню ---
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
    
    # --- Настройки обработки ---
    elif payload.startswith("mode:"):
        mode = payload.split(":")[1]
        session_manager.update_options(user_id, mode=mode)
        if state:
            await bot.edit_message(
                chat_id, state.chat_id,
                "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':",
                reply_markup=processing_options_kb(
                    has_webcam=state.options.has_webcam,
                    format_mode=state.options.format,
                    mode=state.options.mode  # ← ДОБАВИТЬ
                )
            )

    elif payload == "webcam:yes":
        session_manager.update_options(user_id, has_webcam=True)
        if state:
            await bot.edit_message(
                chat_id, state.chat_id,
                "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':",
                reply_markup=processing_options_kb(
                    has_webcam=True,
                    format_mode=state.options.format,
                    mode=state.options.mode  # ← ДОБАВИТЬ
                )
            )

    elif payload == "webcam:no":
        session_manager.update_options(user_id, has_webcam=False)
        if state:
            await bot.edit_message(
                chat_id, state.chat_id,
                "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':",
                reply_markup=processing_options_kb(
                    has_webcam=False,
                    format_mode=state.options.format,
                    mode=state.options.mode  # ← ДОБАВИТЬ
                )
            )

    elif payload == "format:original":
        session_manager.update_options(user_id, format="original")
        if state:
            await bot.edit_message(
                chat_id, state.chat_id,
                "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':",
                reply_markup=processing_options_kb(
                    has_webcam=state.options.has_webcam,
                    format_mode="original",
                    mode=state.options.mode  # ← ДОБАВИТЬ
                )
            )

    elif payload == "format:vertical":
        session_manager.update_options(user_id, format="vertical_9_16")
        if state:
            await bot.edit_message(
                chat_id, state.chat_id,
                "🎬 Параметры обработки обновлены. Выбери остальные настройки или нажми '▶️ Начать обработку':",
                reply_markup=processing_options_kb(
                    has_webcam=state.options.has_webcam,
                    format_mode="vertical_9_16",
                    mode=state.options.mode  # ← ДОБАВИТЬ
                )
            )
    
    elif payload == "start_processing":
        await start_processing(chat_id, user_id)