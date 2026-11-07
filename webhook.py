"""Обработчик вебхука MAX мессенджера."""

import asyncio
import os
from aiohttp import web

from app import bot, session_manager
from config import ADMIN_IDS
from utils import extract_video_attachment
from handlers.commands import (
    handle_start,
    handle_help,
    handle_stats,
    handle_ask_email,
    handle_show_subscriptions,
)
from handlers.video import handle_video, handle_scan_video, handle_select_moments, handle_link_download


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
                await handle_help(chat_id)
                return web.Response(text="OK")
            if text.startswith("/stats"):
                await handle_stats(chat_id, user_id, ADMIN_IDS)
                return web.Response(text="OK")
            if text.startswith("/email"):
                await handle_ask_email(chat_id)
                return web.Response(text="OK")
            if text.startswith("/pay"):
                await handle_show_subscriptions(chat_id)
                return web.Response(text="OK")


            # --- Ссылка на видео (YouTube, Twitch, TikTok, диски) ---
            from link_downloader import extract_url, detect_platform
            url = extract_url(text)
            if url and detect_platform(url):
                if state and state.stage == "awaiting_moment_selection":
                    session_manager.clear_state(user_id)
                asyncio.create_task(handle_link_download(chat_id, user_id, url))
                return web.Response(text="OK")


            # Хайлайты: пользователь выбирает моменты
            state = session_manager.get_state(user_id)
            if state and state.stage == "awaiting_moment_selection" and text:
                asyncio.create_task(handle_select_moments(chat_id, user_id, text))
                return web.Response(text="OK")

            # Видео
            att_info = extract_video_attachment(attachments)
            if attachments and not att_info:
                print("[MAX] attachments:", attachments, flush=True)

            if att_info:
                stage = state.stage if state else None
                if stage == "awaiting_moment_selection":
                    # прислал новое видео во время выбора моментов — начинаем заново
                    session_manager.clear_state(user_id)
                    stage = "awaiting_options"
                
                # Создаём состояние если нет
                if not state:
                    session_manager.set_awaiting_video(user_id, chat_id)
                
                asyncio.create_task(handle_video(chat_id, user_id, att_info))
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

            from handlers.callbacks import handle_callback
            await handle_callback(chat_id, user_id, payload)
            return web.Response(text="OK")

        return web.Response(text="OK")
    except Exception as e:
        print(f"[MAX webhook] {e}")
        return web.Response(text="OK")