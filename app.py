"""Общие объекты приложения. Импортируются всеми модулями."""

from max_bot_client import MaxBot
from engine import VideoEngine
from session_manager import SessionManager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import MAX_TOKEN

# Единые экземпляры (singleton-подобно)
bot = MaxBot(MAX_TOKEN)
engine = VideoEngine(device="cpu")
session_manager = SessionManager()
scheduler = AsyncIOScheduler()