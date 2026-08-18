from datetime import datetime, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc
from database import User
from subscriptions import SUBSCRIPTIONS, DEFAULT_SUB, get_subscription

async def get_or_create_user(session: AsyncSession, user_id: int) -> User:
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        sub = get_subscription(DEFAULT_SUB)
        user = User(
            user_id=user_id,
            active_sub=DEFAULT_SUB,
            video_limit=sub["video_limit"],
            videos_used_today=0
        )
        session.add(user)
        await session.commit()
    return user

def can_process_video(user: User) -> bool:
    return user.videos_used_today < user.video_limit

async def increment_video_counter(user: User, session: AsyncSession):
    user.videos_used_today += 1
    user.total_videos_processed += 1
    await session.commit()

async def set_user_email(session: AsyncSession, user_id: int, email: str):
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.email = email
        await session.commit()
        return True
    return False

async def reset_all_daily_limits():
    from database import async_session
    async with async_session() as session:
        await session.execute(
            update(User).values(videos_used_today=0)
        )
        await session.commit()

async def activate_subscription(session: AsyncSession, user_id: int, sub_id: str):
    """Активирует платную подписку и возвращает (sub_name, expiry_date) или None."""
    sub = get_subscription(sub_id)
    if sub["price"] == 0:
        return None   # бесплатную не активируем

    result = await session.execute(select(User).where(User.user_id == user_id))
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
    """Возвращает всех, у кого срок действия платной подписки истёк, на default."""
    from database import async_session
    async with async_session() as session:
        now = datetime.now()
        # Находим пользователей с истекшей платной подпиской (expiry не NULL и меньше now)
        result = await session.execute(
            select(User).where(
                User.subscription_expiry.isnot(None),
                User.subscription_expiry < now
            )
        )
        expired_users = result.scalars().all()
        for user in expired_users:
            default_sub = get_subscription(DEFAULT_SUB)
            user.active_sub = DEFAULT_SUB
            user.video_limit = default_sub["video_limit"]
            user.videos_used_today = 0
            user.subscription_expiry = None
        await session.commit()

async def get_top_users(limit: int = 20) -> list:
    """Возвращает список топ-пользователей (total_videos_processed, user_id)."""
    from database import async_session
    async with async_session() as session:
        result = await session.execute(
            select(User.user_id, User.total_videos_processed)
            .order_by(desc(User.total_videos_processed))
            .limit(limit)
        )
        rows = result.all()
        return [(row.user_id, row.total_videos_processed) for row in rows]

async def update_user_field(session: AsyncSession, user_id: int, field: str, value):
    """
    Обновляет произвольное поле пользователя по user_id.
    Возвращает True при успехе, False при ошибке.
    """
    allowed_fields = {
        "email": str,
        "active_sub": str,
        "video_limit": int,
        "videos_used_today": int,
        "total_videos_processed": int,
    }
    if field not in allowed_fields:
        return False, f"Недопустимое поле. Доступно: {', '.join(allowed_fields.keys())}"

    try:
        # Преобразуем значение к нужному типу
        if allowed_fields[field] == int:
            value = int(value)
        elif allowed_fields[field] == str:
            value = str(value)
    except (ValueError, TypeError):
        return False, f"Неверный тип значения для поля {field}"

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return False, "Пользователь не найден"

    setattr(user, field, value)
    await session.commit()
    return True, f"Поле {field} обновлено для {user_id} -> {value}"