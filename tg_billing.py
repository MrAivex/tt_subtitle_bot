"""Лимиты и списание для Telegram-пользователей.

Контракт тот же, что у miniapp.Billing (метод charge), поэтому существующий
RenderService работает с TgBilling без изменений: он только зовёт
billing.charge(user_id, chat_id) и получает флаг premium (водяной знак).
"""
from config import TG_ADMIN_IDS, FREE_PERIOD
from database_max import async_session_max, UserTg
from services_tg import get_or_create_user_tg, can_process_video, increment_video_counter


class TgBilling:

    async def ensure_can_start(self, uid: int, chat_id: int) -> UserTg:
        async with async_session_max() as s:
            user = await get_or_create_user_tg(s, uid, chat_id)
        if not FREE_PERIOD and uid not in TG_ADMIN_IDS and not can_process_video(user):
            raise PermissionError("Видео на сегодня закончились — зайди завтра")
        return user

    async def charge(self, uid: int, chat_id: int) -> bool:
        async with async_session_max() as s:
            user = await get_or_create_user_tg(s, uid, chat_id)
            premium = user.active_sub != "default"
            if uid not in TG_ADMIN_IDS:
                if FREE_PERIOD:
                    # дневной счётчик не трогаем, иначе после акции люди упрутся в лимит
                    user.total_videos_processed += 1
                    await s.commit()
                else:
                    await increment_video_counter(user, s)
            return premium
