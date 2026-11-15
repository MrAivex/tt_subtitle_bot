"""miniapp/billing.py — лимиты видео и списание."""
from config import ADMIN_IDS
from database_max import async_session_max
from services_max import get_or_create_user, can_process_video, increment_video_counter
from .errors import ApiError


class Billing:
    async def user(self, uid: int, chat_id: int = None):
        async with async_session_max() as s:
            if chat_id:
                return await get_or_create_user(s, uid, chat_id)
            return await get_or_create_user(s, uid)

    async def ensure_can_start(self, uid: int):
        user = await self.user(uid)
        if not user.chat_id:
            raise ApiError("Сначала нажми «Старт» в чате с ботом")
        if uid not in ADMIN_IDS and not can_process_video(user):
            raise ApiError("Видео на сегодня закончились. Оформи подписку в профиле.", 403)
        return user

    async def charge(self, uid: int, chat_id: int) -> bool:
        """Списывает одно видео. Возвращает True, если у пользователя премиум."""
        async with async_session_max() as s:
            user = await get_or_create_user(s, uid, chat_id)
            premium = user.active_sub != "default"
            if uid not in ADMIN_IDS:
                await increment_video_counter(user, s)
            return premium
