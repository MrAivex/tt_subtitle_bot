"""Обработка callback'ов от inline-кнопок."""
import asyncio

from app import bot, session_manager
from keyboards import main_menu_kb, initial_options_kb, highlights_options_kb
from handlers.commands import (
    handle_show_subscriptions,
    handle_ask_email,
    handle_pay,
)
from handlers.video import start_processing


async def _update_highlights_kb(chat_id: int, state):
    """Обновляет клавиатуру настроек хайлайтов."""
    if not state or not state.message_id:
        return
    
    text = "⚙️ Настройки нарезки хайлайтов:"
    kb = highlights_options_kb(
        has_webcam=state.options.has_webcam,
        has_subtitles=state.options.has_subtitles,
        format_mode=state.options.format,
    )
    await bot.edit_message(chat_id, state.message_id, text, reply_markup=kb)


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
    
    # --- Первый экран: выбор режима ---
    elif payload == "choose:highlights":
        session_manager.update_options(user_id, mode="highlights")
        if state and state.message_id:
            await bot.edit_message(
                chat_id, state.message_id,
                "⚙️ Настройки нарезки хайлайтов:",
                reply_markup=highlights_options_kb(
                    has_webcam=state.options.has_webcam,
                    has_subtitles=state.options.has_subtitles,
                    format_mode=state.options.format,
                )
            )
    
    elif payload == "choose:full":
        # Запускаем в фоне, вебхук сразу отвечает OK
        if state and state.message_id and state.stage == "awaiting_options" and not state.processing:
            session_manager.update_options(user_id, mode="full")
            asyncio.create_task(start_processing(chat_id, user_id))
    
    # --- Настройки хайлайтов ---
    elif payload == "hl:webcam":
        if state:
            session_manager.update_options(user_id, has_webcam=not state.options.has_webcam)
            await _update_highlights_kb(chat_id, state)
    
    elif payload == "hl:subtitles":
        if state:
            session_manager.update_options(user_id, has_subtitles=not state.options.has_subtitles)
            await _update_highlights_kb(chat_id, state)
    
    elif payload == "hl:format_original":
        session_manager.update_options(user_id, format="original")
        await _update_highlights_kb(chat_id, state)
    
    elif payload == "hl:format_vertical":
        session_manager.update_options(user_id, format="vertical_9_16")
        await _update_highlights_kb(chat_id, state)
    
    elif payload == "hl:start":
        if state and state.stage == "awaiting_options" and not state.processing:
            asyncio.create_task(start_processing(chat_id, user_id))
    
    elif payload == "hl:back":
        # Возврат к первому меню
        if state and state.message_id:
            await bot.edit_message(
                chat_id, state.message_id,
                "🎬 Видео скачано! Что сделать?",
                reply_markup=initial_options_kb()
            )