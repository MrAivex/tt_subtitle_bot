"""tg/db.py — таблица пользователей Telegram (отдельно от users_max, в той же БД)."""
import os

from dotenv import load_dotenv
from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


class BaseTg(DeclarativeBase):
    pass


class UserTg(BaseTg):
    __tablename__ = "users_tg"

    user_id = Column(BigInteger, primary_key=True)
    chat_id = Column(BigInteger, nullable=True)   # в личке chat_id == user_id
    email = Column(String, nullable=True)
    active_sub = Column(String, default="default")
    video_limit = Column(Integer, default=3)
    videos_used_today = Column(Integer, default=0)
    total_videos_processed = Column(Integer, default=0)
    subscription_expiry = Column(DateTime, nullable=True)


engine_tg = create_async_engine(DATABASE_URL, echo=False)
async_session_tg = async_sessionmaker(engine_tg, expire_on_commit=False)


async def init_db_tg():
    async with engine_tg.begin() as conn:
        await conn.run_sync(BaseTg.metadata.create_all)
