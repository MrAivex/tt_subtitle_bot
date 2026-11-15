"""Бот только направляет в мини-приложение: вся обработка там."""
from app import bot
from config import MINIAPP_URL
from keyboards import main_menu_kb

_TEXT = ("🎬 Вся обработка в мини-приложении: превью клипов, плеер и скачивание.\n"
         f"Открой его и загрузи видео или ссылку там 👉 {MINIAPP_URL}")


async def handle_video(chat_id: int, user_id: int, att: dict):
    await bot.send_message(chat_id, _TEXT, reply_markup=main_menu_kb())


async def handle_link_download(chat_id: int, user_id: int, url: str):
    await bot.send_message(chat_id, _TEXT, reply_markup=main_menu_kb())