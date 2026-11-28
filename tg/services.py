"""tg/services.py — то же, что services_max, но для таблицы users_tg."""
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from subscriptions import DEFAULT_SUB, get_subscription
from .db import UserTg, async_session_tg


async def get_or_create_user(session: AsyncSession, user_id: int, chat_id: int = None) -> UserTg:
    result = await session.execute(select(UserTg).where(UserTg.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        sub = get_subscription(DEFAULT_SUB)
        user = UserTg(
            user_id=user_id, chat_id=chat_id, active_sub=DEFAULT_SUB,
            video_limit=sub["video_limit"], videos_used_today=0, total_videos_processed=0,
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            # параллельно создали (например, /start и открытие мини-аппа одновременно)
            await session.rollback()
            result = await session.execute(select(UserTg).where(UserTg.user_id == user_id))
            user = result.scalar_one()
    elif chat_id and user.chat_id != chat_id:
        user.chat_id = chat_id
        await session.commit()
    return user


def can_process_video(user: UserTg) -> bool:
    return user.videos_used_today < user.video_limit


async def increment_video_counter(user: UserTg, session: AsyncSession):
    user.videos_used_today += 1
    user.total_videos_processed += 1
    await session.commit()


async def set_user_email(session: AsyncSession, user_id: int, email: str) -> bool:
    result = await session.execute(select(UserTg).where(UserTg.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return False
    user.email = email
    await session.commit()
    return True


async def reset_all_daily_limits():
    async with async_session_tg() as session:
        await session.execute(update(UserTg).values(videos_used_today=0))
        await session.commit()


async def activate_subscription(session: AsyncSession, user_id: int, sub_id: str):
    sub = get_subscription(sub_id)
    if sub["price"] == 0:
        return None
    result = await session.execute(select(UserTg).where(UserTg.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None

    duration = sub.get("duration_days", 0)
    now = datetime.now()
    # активная подписка продлевается, иначе считаем от текущего момента
    base = user.subscription_expiry if user.subscription_expiry and user.subscription_expiry > now else now
    expiry = base + timedelta(days=duration) if duration > 0 else None

    user.active_sub = sub_id
    user.video_limit = sub["video_limit"]
    user.videos_used_today = 0
    user.subscription_expiry = expiry
    await session.commit()
    return {
        "sub_name": sub["name"],
        "expiry": expiry.strftime("%d.%m.%Y %H:%M") if expiry else "навсегда",
        "video_limit": sub["video_limit"],
    }


async def check_expired_subscriptions():
    async with async_session_tg() as session:
        result = await session.execute(
            select(UserTg).where(UserTg.subscription_expiry.isnot(None),
                                 UserTg.subscription_expiry < datetime.now()))
        default = get_subscription(DEFAULT_SUB)
        for user in result.scalars().all():
            user.active_sub = DEFAULT_SUB
            user.video_limit = default["video_limit"]
            user.videos_used_today = 0
            user.subscription_expiry = None
        await session.commit()


async def get_users_stats():
    """(всего_пользователей, с_активной_подпиской, с_почтой)."""
    async with async_session_tg() as session:
        total = (await session.execute(select(func.count(UserTg.user_id)))).scalar() or 0
        paid = (await session.execute(
            select(func.count(UserTg.user_id)).where(UserTg.active_sub != DEFAULT_SUB))).scalar() or 0
        with_email = (await session.execute(
            select(func.count(UserTg.user_id)).where(UserTg.email.isnot(None)))).scalar() or 0
        return total, paid, with_email
