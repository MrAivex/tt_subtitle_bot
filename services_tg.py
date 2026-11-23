"""Пользователи Telegram (таблица users_tg) — то же, что services_max для users_max.

can_process_video и increment_video_counter общие: они работают с полями,
которые есть у обеих моделей. Свои версии — только там, где нужен запрос по UserTg.
"""
from datetime import datetime
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from database_max import UserTg, async_session_max
from subscriptions import DEFAULT_SUB, get_subscription
# общие функции работают с любым пользователем (UserMax / UserTg)
from services_max import can_process_video, increment_video_counter  # noqa: F401 — реэкспорт


async def get_or_create_user_tg(session: AsyncSession, user_id: int, chat_id: int = None) -> UserTg:
    result = await session.execute(select(UserTg).where(UserTg.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        sub = get_subscription(DEFAULT_SUB)
        user = UserTg(
            user_id=user_id,
            chat_id=chat_id,
            active_sub=DEFAULT_SUB,
            video_limit=sub["video_limit"],
            videos_used_today=0,
            total_videos_processed=0,
        )
        session.add(user)
        await session.commit()
    elif chat_id and user.chat_id != chat_id:
        user.chat_id = chat_id
        await session.commit()
    return user


async def reset_all_daily_limits_tg():
    from database_max import async_session_max
    async with async_session_max() as session:
        await session.execute(update(UserTg).values(videos_used_today=0))
        await session.commit()


async def check_expired_subscriptions_tg():
    from database_max import async_session_max
    async with async_session_max() as session:
        now = datetime.now()
        result = await session.execute(
            select(UserTg).where(
                UserTg.subscription_expiry.isnot(None),
                UserTg.subscription_expiry < now
            )
        )
        for user in result.scalars().all():
            default_sub = get_subscription(DEFAULT_SUB)
            user.active_sub = DEFAULT_SUB
            user.video_limit = default_sub["video_limit"]
            user.videos_used_today = 0
            user.subscription_expiry = None
        await session.commit()


async def get_users_stats_tg():
    """(всего пользователей, с активной подпиской) — для /stats."""
    from database_max import async_session_max
    async with async_session_max() as session:
        total = (await session.execute(select(func.count(UserTg.user_id)))).scalar() or 0
        paid = (await session.execute(
            select(func.count(UserTg.user_id)).where(UserTg.active_sub != DEFAULT_SUB)
        )).scalar() or 0
        return total, paid
