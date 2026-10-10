from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc
from database_max import UserMax
from subscriptions import DEFAULT_SUB, get_subscription


async def get_or_create_user(session: AsyncSession, user_id: int, chat_id: int = None) -> UserMax:
    result = await session.execute(select(UserMax).where(UserMax.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        sub = get_subscription(DEFAULT_SUB)
        user = UserMax(
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


def can_process_video(user: UserMax) -> bool:
    return user.videos_used_today < user.video_limit


async def increment_video_counter(user: UserMax, session: AsyncSession):
    user.videos_used_today += 1
    user.total_videos_processed += 1
    await session.commit()


async def set_user_email(session: AsyncSession, user_id: int, email: str):
    result = await session.execute(select(UserMax).where(UserMax.user_id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.email = email
        await session.commit()
        return True
    return False


async def reset_all_daily_limits():
    from database_max import async_session_max
    async with async_session_max() as session:
        await session.execute(update(UserMax).values(videos_used_today=0))
        await session.commit()


async def activate_subscription(session: AsyncSession, user_id: int, sub_id: str):
    sub = get_subscription(sub_id)
    if sub["price"] == 0:
        return None
    result = await session.execute(select(UserMax).where(UserMax.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    duration = sub.get("duration_days", 0)
    expiry = datetime.now() + timedelta(days=duration) if duration > 0 else None
    user.active_sub = sub_id
    user.video_limit = sub["video_limit"]
    user.videos_used_today = 0
    user.subscription_expiry = expiry
    await session.commit()
    return {
        "sub_name": sub["name"],
        "expiry": expiry.strftime("%d.%m.%Y %H:%M") if expiry else "навсегда",
        "video_limit": sub["video_limit"]
    }


async def check_expired_subscriptions():
    from database_max import async_session_max
    async with async_session_max() as session:
        now = datetime.now()
        result = await session.execute(
            select(UserMax).where(
                UserMax.subscription_expiry.isnot(None),
                UserMax.subscription_expiry < now
            )
        )
        for user in result.scalars().all():
            default_sub = get_subscription(DEFAULT_SUB)
            user.active_sub = DEFAULT_SUB
            user.video_limit = default_sub["video_limit"]
            user.videos_used_today = 0
            user.subscription_expiry = None
        await session.commit()


async def get_top_users(limit: int = 20):
    from database_max import async_session_max
    async with async_session_max() as session:
        result = await session.execute(
            select(UserMax.user_id, UserMax.total_videos_processed)
            .order_by(desc(UserMax.total_videos_processed))
            .limit(limit)
        )
        return [(r.user_id, r.total_videos_processed) for r in result.all()]


async def update_user_field(session: AsyncSession, user_id: int, field: str, value):
    allowed = {
        "email": str, "active_sub": str, "video_limit": int,
        "videos_used_today": int, "total_videos_processed": int,
    }
    if field not in allowed:
        return False, f"Недопустимое поле. Доступно: {', '.join(allowed.keys())}"
    try:
        value = allowed[field](value)
    except (ValueError, TypeError):
        return False, f"Неверный тип значения для {field}"
    result = await session.execute(select(UserMax).where(UserMax.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return False, "Пользователь не найден"
    setattr(user, field, value)
    await session.commit()
    return True, f"Поле {field} обновлено: {value}"


async def get_all_user_ids():
    from database_max import async_session_max
    async with async_session_max() as session:
        result = await session.execute(select(UserMax.user_id))
        return result.scalars().all()