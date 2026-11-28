import os
from datetime import datetime

from sqlalchemy import (Column, BigInteger, String, Integer, Boolean,
                        DateTime, UniqueConstraint)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


class BaseWeb(DeclarativeBase):
    pass


class UserWeb(BaseWeb):
    """Единый пользователь: один человек — одна подписка и одни лимиты,
    независимо от того, откуда он зашёл (MAX / Telegram / сайт).

    Платформенные id живут отдельно, в identities_web («id max / id tg / имя на сайте → пользователь №N»).
    """
    __tablename__ = "users_web"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=True, unique=True)   # имя для входа на сайте
    password_hash = Column(String(256), nullable=True)          # pbkdf2; только у аккаунтов сайта
    chat_id = Column(BigInteger, nullable=True)                 # чат с ботом, если известен
    email = Column(String, nullable=True)
    active_sub = Column(String, default="default")
    video_limit = Column(Integer, default=3)
    videos_used_today = Column(Integer, default=0)
    total_videos_processed = Column(Integer, default=0)
    subscription_expiry = Column(DateTime, nullable=True)


class UserIdentity(BaseWeb):
    """Привязка платформы к единому пользователю.

    У одного UserWeb может быть сколько угодно строк: max + tg + site.
    UNIQUE(platform, ext_id) — один платформенный id принадлежит только одному человеку.
    """
    __tablename__ = "identities_web"
    __table_args__ = (UniqueConstraint("platform", "ext_id", name="uq_identity_platform_ext"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True, nullable=False)
    platform = Column(String(16), nullable=False)   # 'max' | 'tg' | 'site'
    ext_id = Column(String(64), nullable=False)    # id в MAX / id в TG / имя на сайте
    display_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LinkCode(BaseWeb):
    """Одноразовый код привязки: кто введёт его в приложении на другой платформе,
    свой аккаунт вольётся в аккаунт владельца кода (подписка и лимиты владельца остаются).
    """
    __tablename__ = "link_codes_web"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(8), unique=True, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)


engine_web = create_async_engine(DATABASE_URL, echo=False)
async_session_web = async_sessionmaker(engine_web, expire_on_commit=False)


async def init_db_web():
    """Создаёт таблицы единой базы (users_web, identities_web, link_codes_web)."""
    async with engine_web.begin() as conn:
        await conn.run_sync(BaseWeb.metadata.create_all)
