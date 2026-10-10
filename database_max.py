import os
from sqlalchemy import Column, BigInteger, String, Integer, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

class BaseMax(DeclarativeBase):
    pass

class UserMax(BaseMax):
    __tablename__ = "users_max"

    user_id = Column(BigInteger, primary_key=True)
    chat_id = Column(BigInteger, nullable=True)   # для отправки сообщений
    email = Column(String, nullable=True)
    active_sub = Column(String, default="default")
    video_limit = Column(Integer, default=3)
    videos_used_today = Column(Integer, default=0)
    total_videos_processed = Column(Integer, default=0)
    subscription_expiry = Column(DateTime, nullable=True)

engine_max = create_async_engine(DATABASE_URL, echo=False)
async_session_max = async_sessionmaker(engine_max, expire_on_commit=False)

async def init_db_max():
    async with engine_max.begin() as conn:
        await conn.run_sync(BaseMax.metadata.create_all)