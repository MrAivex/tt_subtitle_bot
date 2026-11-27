"""tg/billing.py — лимиты видео и списание (Telegram). Интерфейс как у miniapp.billing.Billing."""
from config import FREE_PERIOD
from miniapp.errors import ApiError
from .db import async_session_tg
from .services import can_process_video, get_or_create_user, increment_video_counter
from .settings import TG_ADMIN_IDS


class TgBilling:
    async def user(self, uid: int, chat_id: int = None):
        # В личке с ботом chat_id == user_id, поэтому «нажми Старт» в Telegram не нужен:
        # мини-апп можно открыть и по прямой ссылке t.me/<bot>/<app>.
        async with async_session_tg() as s:
            return await get_or_create_user(s, uid, chat_id or uid)

    async def ensure_can_start(self, uid: int):
        user = await self.user(uid)
        if not FREE_PERIOD and uid not in TG_ADMIN_IDS and not can_process_video(user):
            raise ApiError("Видео на сегодня закончились. Оформи подписку в профиле.", 403)
        return user

    async def charge(self, uid: int, chat_id: int) -> bool:
        async with async_session_tg() as s:
            user = await get_or_create_user(s, uid, chat_id or uid)
            premium = user.active_sub != "default"
            if uid not in TG_ADMIN_IDS:
                if FREE_PERIOD:
                    # дневной счётчик не трогаем, иначе после акции люди упрутся в лимит
                    user.total_videos_processed += 1
                    await s.commit()
                else:
                    await increment_video_counter(user, s)
            return premium
