"""Лимиты и списание для единой базы (users_web).

Контракт тот же, что у miniapp.Billing (user / ensure_can_start / charge), поэтому
существующие ScanService и RenderService работают с UnifiedBilling без изменений.
Разница одна: uid здесь — не id мессенджера, а users_web.id.
"""
from miniapp.errors import ApiError
from config import FREE_PERIOD
from database_web import UserWeb, async_session_web
from services_web import (get_or_create_user_web, is_admin_web,
                          can_process_video, increment_video_counter)


class UnifiedBilling:

    async def user(self, uid: int) -> UserWeb:
        async with async_session_web() as s:
            return await get_or_create_user_web(s, uid)

    async def ensure_can_start(self, uid: int) -> UserWeb:
        user = await self.user(uid)
        if not FREE_PERIOD and not await is_admin_web(uid) and not can_process_video(user):
            raise ApiError("Видео на сегодня закончились. Оформи подписку в профиле.", 403)
        return user

    async def charge(self, uid: int, chat_id: int = None) -> bool:
        """chat_id оставлен для совместимости с RenderService — в единой базе не нужен."""
        async with async_session_web() as s:
            user = await get_or_create_user_web(s, uid)
            premium = user.active_sub != "default"
            if not await is_admin_web(uid):
                if FREE_PERIOD:
                    # дневной счётчик не трогаем, иначе после акции люди упрутся в лимит
                    user.total_videos_processed += 1
                    await s.commit()
                else:
                    await increment_video_counter(user, s)
            return premium
