from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Integer, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True)
    email = Column(String, nullable=True)
    active_sub = Column(String, default="default")
    video_limit = Column(Integer, default=3)
    videos_used_today = Column(Integer, default=0)
    total_videos_processed = Column(Integer, default=0)   # новая колонка
    subscription_expiry = Column(DateTime, nullable=True)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)