"""Обработка видео и хайлайтов — самая мясная часть."""

import asyncio
import os
import subprocess
import traceback
import uuid
import logging

from database_max import async_session_max
from services_max import (
    get_or_create_user,
    can_process_video,
    increment_video_counter,
)
from app import bot, engine, session_manager
from config import ADMIN_IDS, MAX_FILE_SIZE_BYTES, MAX_FULL_VIDEO_SEC, MAX_HIGHLIGHTS, MAX_CLIPS_PER_REQUEST
from utils import extract_video_attachment, download_video, format_moment_time

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# Обычное видео (полное субтитрирование)
# ------------------------------------------------------------
async def handle_video(chat_id: int, user_id: int, att: dict):
    """Скачивает видео и показывает меню настроек обработки."""
    is_admin = user_id in ADMIN_IDS

    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)
        if not is_admin and not can_process_video(user):
            await bot.send_message(
                chat_id,
                "😔 Закончились бесплатные видео на сегодня (3/день).\n"
                "Возвращайся завтра или оформи подписку через /pay.",
            )
            return

    status_id = await bot.send_message(chat_id, "📥 Скачиваю видео...")

    # Защита по размеру
    size = att.get("size") or 0
    if size and size > MAX_FILE_SIZE_BYTES:
        await bot.edit_message(chat_id, status_id, "❌ Файл больше 2.5 ГБ — подрежь видео и отправь ещё раз.")
        return

    # Получение URL
    video_url = att.get("url")
    if not video_url and att.get("token"):
        video_url = await bot.get_video_url(att["token"])
    if not video_url:
        await bot.edit_message(chat_id, status_id, "❌ Не удалось получить ссылку на видео.")
        return

    # Скачивание
    os.makedirs("downloads", exist_ok=True)
    input_path = f"downloads/max_{user_id}_{uuid.uuid4().hex[:8]}.mp4"

    try:
        await download_video(video_url, input_path)
    except Exception as e:
        print(f"[VIDEO ERROR] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка скачивания: {type(e).__name__}: {e}")
        return

    # Сохраняем видео в состояние и показываем начальное меню
    session_manager.set_awaiting_video(user_id, chat_id)
    session_manager.set_video_path(user_id, input_path)

    from keyboards import initial_options_kb
    await bot.edit_message(
        chat_id, status_id,
        "🎬 Видео скачано! Что сделать?",
        reply_markup=initial_options_kb()
    )

    # Сохраняем message_id для редактирования
    session_manager.get_state(user_id).message_id = status_id


# ------------------------------------------------------------
# Хайлайты: запуск поиска
# ------------------------------------------------------------
async def handle_find_highlights_start(chat_id: int, user_id: int):
    session_manager.set_awaiting_video(user_id, chat_id)
    await bot.send_message(
        chat_id,
        "🎬 *Поиск хайлайтов*\n\n"
        "Отправь мне видео (до 2 часов, до 2.5 ГБ) — я найду самые крутые моменты!\n\n"
        "💡 Лучше отправляй как ФАЙЛ (скрепка → файл) — тогда без сжатия.\n"
        "⏱️ Сканирование займёт 2-4 минуты.",
    )


# ------------------------------------------------------------
# Хайлайты: выбор моментов
# ------------------------------------------------------------
async def handle_select_moments(chat_id: int, user_id: int, text: str):
    """Обрабатывает выбор моментов пользователем."""
    state = session_manager.get_state(user_id)
    if not state:
        await bot.send_message(chat_id, "❌ Сначала нажми '🎬 Найти хайлайты' и отправь видео.")
        return

    if state.processing:  # уже режем, игнорируем дубли
        return
    state.processing = True

    my_video = state.video_path  # ← ЗАФИКСИРОВАЛИ свой файл один раз

    if text.strip().lower() == "/cancel":
        session_manager.clear_state_if_same_video(user_id, my_video)
        from keyboards import main_menu_kb
        await bot.send_message(chat_id, "❌ Отменено.", reply_markup=main_menu_kb())
        return

    try:
        selected_indices = [int(x.strip()) - 1 for x in text.split(",")]
    except ValueError:
        state.processing = False
        await bot.send_message(chat_id, "❌ Введи номера через запятую (например: 1, 3, 5)")
        return

    valid_indices = [i for i in selected_indices if 0 <= i < len(state.moments)]
    if not valid_indices:
        state.processing = False
        await bot.send_message(chat_id, f"❌ Нет таких моментов. Доступно от 1 до {len(state.moments)}.")
        return

    if len(valid_indices) > MAX_CLIPS_PER_REQUEST:
        state.processing = False
        await bot.send_message(chat_id, f"❌ Можно выбрать максимум {MAX_CLIPS_PER_REQUEST} момента.")
        return

    status_id = await bot.send_message(chat_id, f"🎬 Нарезаю {len(valid_indices)} клип(ов)...")

    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)
        is_premium = user.active_sub != "default"
        if user_id not in ADMIN_IDS:
            await increment_video_counter(user, session)

    clips = []
    try:
        for i, idx in enumerate(valid_indices, 1):
            moment = state.moments[idx]
            if state.source_url:
                # Ссылка: качаем ТОЛЬКО выбранный фрагмент
                await bot.edit_message(chat_id, status_id, f"📥 Скачиваю фрагмент {i}/{len(valid_indices)} из интернета...")
                from link_downloader import download_section
                clip_path = f"downloads/clip_{user_id}_{idx}_{uuid.uuid4().hex[:6]}.mp4"
                clip_path = await download_section(state.source_url, moment["start"], moment["end"], clip_path)
            else:
                # Файл: режем локально
                await bot.edit_message(chat_id, status_id, f"✂️ Нарезаю клип {i}/{len(valid_indices)}...")
                clip_path = my_video.replace(".mp4", f"_clip_{idx}.mp4")
                await asyncio.to_thread(engine.cut_clip, my_video, moment["start"], moment["end"], clip_path)

            if state.options.has_subtitles:
                await bot.edit_message(chat_id, status_id, f"🎤 Накладываю субтитры на клип {i}/{len(valid_indices)}...")
                webcam_box = getattr(state, "webcam_box", None)
                result = await asyncio.to_thread(engine.process_video, clip_path, str(user_id), is_premium, webcam_box)
                final_path = result["video_path"]
                if final_path != clip_path and os.path.exists(clip_path):
                    os.remove(clip_path)
            else:
                final_path = clip_path
            clips.append(final_path)
            
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"[CLIP ERROR] {type(e).__name__}: {e}\n{error_details}")
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка нарезки: {type(e).__name__}: {str(e)[:200]}")
        session_manager.clear_state_if_same_video(user_id, my_video)
        return

    await bot.edit_message(chat_id, status_id, "📤 Отправляю клипы...")
    for i, clip in enumerate(clips, 1):
        await bot.send_video(chat_id, clip, caption=f"✅ Клип #{i}")
        if os.path.exists(clip):
            os.remove(clip)

    session_manager.clear_state_if_same_video(user_id, my_video)
    await bot.edit_message(chat_id, status_id, "✅ Готово!")


async def start_processing(chat_id: int, user_id: int):
    """Запускает обработку видео с выбранными настройками."""
    state = session_manager.get_state(user_id)
    if not state or not state.video_path:
        logger.warning(f"[PROCESSING] Видео не найдено для user_id={user_id}.")
        await bot.send_message(chat_id, "ℹ️ Обработка уже завершена. Отправь новое видео.")
        return

    if state.processing:   # ← ДОБАВИТЬ: защита от повторного запуска
        return
    
    state.processing = True  # ← блокируем повторные запуски
    options = state.options
    video_path = state.video_path
    
    # Первое сообщение — сохраняем ID для дальнейшего редактирования
    status_id = await bot.send_message(chat_id, "⚙️ Начинаю обработку...")
    
    try:
        if options.mode == "highlights":
            moments = state.moments                      # ← для ссылок уже готовы
            if not moments:                              # ← для файлов — сканируем
                await bot.edit_message(chat_id, status_id, "🔍 Сканирую видео на крутые моменты (2-4 минуты)...")
                result = await asyncio.to_thread(engine.scan_highlights, video_path, MAX_HIGHLIGHTS)
                moments = result.get("moments", [])
            if not moments:
                await bot.edit_message(chat_id, status_id, "😕 Не нашёл ярких моментов в этом видео.")
                session_manager.clear_state_if_same_video(user_id, video_path)
                return
            session_manager.set_awaiting_moment_selection(user_id, moments)
            lines = ["🎬 *Нашёл крутые моменты!*\n"]
            for i, m in enumerate(moments, 1):
                s, e = m["start"], m["end"]
                lines.append(f"*{i}.* {format_moment_time(s)} – {format_moment_time(e)} ({int(e - s)} сек, громкость x{m['energy']})")
            lines.append("\nКакие моменты нарезать?")
            lines.append("Напиши номера через запятую (например: 1, 3)")
            lines.append("/cancel — отмена.")
            await bot.edit_message(chat_id, status_id, "\n".join(lines))
            state.processing = False
        
        elif options.mode == "full":
            if state.source_url and video_path.endswith(".wav"):
                await bot.edit_message(chat_id, status_id, "📥 Скачиваю полное видео из интернета (может занять минуты)...")
                from link_downloader import download_by_link
                mp4_path = video_path[:-4] + ".mp4"
                full_path = await download_by_link(state.source_url, mp4_path)
                if os.path.exists(video_path):
                    os.remove(video_path)      # wav больше не нужен
                state.video_path = full_path
                video_path = full_path

            # Режим полного субтитрирования
            await bot.edit_message(chat_id, status_id, "🎬 Обрабатываю видео (это займёт время)...")
            
            is_premium = False
            async with async_session_max() as session:
                user = await get_or_create_user(session, user_id, chat_id)
                is_premium = user.active_sub != "default"
                if user_id not in ADMIN_IDS:
                    await increment_video_counter(user, session)
            
            # Проверяем нужно ли накладывать субтитры
            if options.has_subtitles:
                result = await asyncio.to_thread(engine.process_video, video_path, str(user_id), is_premium)
                
                await bot.edit_message(chat_id, status_id, "📤 Отправляю видео...")
                await bot.send_video(chat_id, result["video_path"], caption="✅ Твоё видео с субтитрами!")
                
                if result.get("srt_path"):
                    srt_path = result["srt_path"]
                    txt_path = srt_path.rsplit(".", 1)[0] + ".txt"
                    try:
                        os.rename(srt_path, txt_path)
                    except Exception:
                        txt_path = srt_path
                    await bot.send_document(chat_id, txt_path, caption="📄 Файл субтитров")
            else:
                # Без субтитров — просто отправляем исходное видео
                await bot.edit_message(chat_id, status_id, " Отправляю видео...")
                await bot.send_video(chat_id, video_path, caption="✅ Твоё видео (без субтитров)")
            
            session_manager.clear_state_if_same_video(user_id, video_path)
            await bot.edit_message(chat_id, status_id, "✅ Готово!")
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"[PROCESSING ERROR] {type(e).__name__}: {e}\n{error_details}")
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка обработки: {type(e).__name__}: {str(e)[:200]}")
        session_manager.clear_state_if_same_video(user_id, video_path)


async def handle_link_download(chat_id: int, user_id: int, url: str):
    """Ссылка: быстро качаем аудио, размечаем моменты, показываем меню."""
    is_admin = user_id in ADMIN_IDS
    async with async_session_max() as session:
        user = await get_or_create_user(session, user_id, chat_id)
        if not is_admin and not can_process_video(user):
            await bot.send_message(chat_id, "😔 Закончились бесплатные видео на сегодня (3/день).\nВозвращайся завтра или оформи подписку через /pay.")
            return

    from link_downloader import detect_platform, download_audio_only
    platform = detect_platform(url)
    status_id = await bot.send_message(chat_id, f"🔗 Распознал: {platform}. Качаю аудиодорожку (быстро)...")

    os.makedirs("downloads", exist_ok=True)
    wav_path = f"downloads/max_{user_id}_{uuid.uuid4().hex[:8]}.wav"

    try:
        await download_audio_only(url, wav_path)
    except Exception as e:
        logger.error(f"[LINK AUDIO ERROR] {type(e).__name__}: {e}\n{traceback.format_exc()}")
        await bot.edit_message(chat_id, status_id, f"❌ Не удалось скачать аудио: {type(e).__name__}: {str(e)[:150]}")
        return

    await bot.edit_message(chat_id, status_id, "🔍 Сканирую дорожку на крутые моменты...")
    try:
        result = await asyncio.to_thread(engine.scan_audio_wav, wav_path, MAX_HIGHLIGHTS)
    except Exception as e:
        logger.error(f"[SCAN AUDIO ERROR] {type(e).__name__}: {e}\n{traceback.format_exc()}")
        await bot.edit_message(chat_id, status_id, f"❌ Ошибка сканирования: {type(e).__name__}: {str(e)[:150]}")
        if os.path.exists(wav_path):
            os.remove(wav_path)
        return

    moments = result.get("moments", [])

    session_manager.set_awaiting_video(user_id, chat_id)
    state = session_manager.get_state(user_id)
    state.source_url = url
    state.video_path = wav_path   # wav живёт в state для очистки
    state.moments = moments       # моменты УЖЕ готовы
    state.message_id = status_id

    from keyboards import initial_options_kb
    text = (f"🎬 Готово! Нашёл {len(moments)} крутых моментов. Что дальше?"
            if moments else
            "🎬 Дорожка скачана, но ярких моментов не нашёл. Могу наложить субтитры на полное видео.")
    await bot.edit_message(chat_id, status_id, text, reply_markup=initial_options_kb())