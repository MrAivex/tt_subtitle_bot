"""webapp/chat_delivery.py — готовые клипы уходят в чат мессенджера файлом (документом).

Миниapp рендерит клипы сам (RenderService), но скачивание из браузера не всегда
удобно (в миниapp MAX — особенно). Поэтому готовый файл дополнительно присылается
документом в чат: Telegram (sendDocument) или MAX (attachments type=file).

Кому слать: платформа текущей сессии (job.platform); для сайта — любая
мессенджерная привязка аккаунта. У Telegram личный чат совпадает с id
пользователя (identity.ext_id); для MAX нужен chat_id (берём из users_max,
куда его пишет MAX-бот, иначе из users_web).
"""
import logging
import traceback
from pathlib import Path

from config import MAX_TOKEN, TG_TOKEN, TG_UPLOAD_LIMIT
from max_bot_client import MaxBot
from tg_bot_client import TgBot

log = logging.getLogger("timing")


class ChatDelivery:
    def __init__(self, tg: TgBot = None, max_bot: MaxBot = None):
        # клиенты лёгкие: сетевых соединений при создании нет
        self._tg = tg or (TgBot(TG_TOKEN) if TG_TOKEN else None)
        self._max = max_bot or (MaxBot(MAX_TOKEN) if MAX_TOKEN else None)

    # ---------- кому доставлять ----------

    async def _targets(self, job) -> list:
        """[(«tg»|«max», chat_id), …] — кому можно прислать файл."""
        try:
            from database_web import async_session_web
            from services_web import get_user_web, list_identities
            async with async_session_web() as s:
                user = await get_user_web(s, job.user_id)
                idents = await list_identities(job.user_id)
        except Exception:
            traceback.print_exc()
            return []

        tg_id = next((i for i in idents if i.platform == "tg"), None)
        mx_id = next((i for i in idents if i.platform == "max"), None)

        prefer = {"tg": ("tg",), "max": ("max",), "site": ("tg", "max")}.get(
            job.platform or "", ("tg", "max"))
        out = []
        for plat in prefer:
            if plat == "tg" and tg_id and self._tg is not None:
                try:
                    out.append(("tg", int(tg_id.ext_id)))   # личный чат в TG = id пользователя
                except (TypeError, ValueError):
                    pass
            elif plat == "max" and mx_id and self._max is not None:
                chat = await self._max_chat(job, user, mx_id)
                if chat:
                    out.append(("max", chat))
        return out

    async def _max_chat(self, job, user, ident) -> int | None:
        """chat_id MAX-диалога: сначала старая users_max (её заполняет MAX-бот),
        иначе users_web.chat_id (достоверен, если задача шла из MAX)."""
        try:
            from database_max import async_session_max, UserMax
            from sqlalchemy import select
            async with async_session_max() as smax:
                row = (await smax.execute(
                    select(UserMax).where(UserMax.user_id == int(ident.ext_id)))).scalar_one_or_none()
                if row and row.chat_id:
                    return int(row.chat_id)
        except Exception:
            pass                                    # старой таблицы нет — не страшно
        if job.platform == "max" and user and user.chat_id:
            try:
                return int(user.chat_id)
            except (TypeError, ValueError):
                return None
        return None

    # ---------- доставка ----------

    async def deliver(self, job, idx: int, path: str, name: str):
        targets = await self._targets(job)
        if not targets:
            return
        m = job.moments[idx] if 0 <= idx < len(job.moments) else {}
        caption = f"{m.get('emoji', '🎬')} {Path(name).stem}"
        if m.get("label"):
            caption += f" · {m['label']}"
        for plat, chat_id in targets:
            try:
                if plat == "tg":
                    if Path(path).stat().st_size > TG_UPLOAD_LIMIT:
                        await self._tg.send_message(
                            chat_id, f"📦 {Path(name).stem} получился больше 50 МБ — "
                                     f"забери его в приложении.")
                        continue
                    ok = await self._tg.send_document(chat_id, path, caption=caption)
                else:
                    ok = await self._max.send_document(chat_id, path, caption=caption)
                if ok:
                    log.info(f"[DELIVERY] {plat} chat={chat_id}: {name}")
                else:
                    log.warning(f"[DELIVERY] {plat} chat={chat_id}: не доставился {name}")
            except Exception:
                traceback.print_exc()
