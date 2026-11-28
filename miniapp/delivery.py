"""miniapp/delivery.py — готовые клипы документом в чат MAX.

Миниapp MAX рендерит клипы сам, а скачивание из вебвью там не работает
(<a download> уводит на сайт). Поэтому большая кнопка «Скачать» шлёт готовые
файлы сообщением в чат — столько раз, сколько нажал пользователь.
"""
import logging
from pathlib import Path

from config import MAX_TOKEN

log = logging.getLogger("timing")


class MaxDelivery:
    """Тонкая обёртка над MaxBot: отправка готового файла документом в чат MAX."""

    def __init__(self, bot=None):
        from max_bot_client import MaxBot
        # клиент лёгкий: сетевых соединений при создании нет
        self._bot = bot or (MaxBot(MAX_TOKEN) if MAX_TOKEN else None)

    async def deliver(self, chat_id: int, path: str, name: str, label: str = "") -> bool:
        """Отправить файл пользователю MAX; True — дошёл. Повторный вызов шлёт заново."""
        if self._bot is None or not chat_id:
            log.warning("[DELIVERY] max: нет токена или chat_id — файл не отправлен")
            return False
        caption = f"🎬 {Path(name).stem or 'clip'}"
        if label:
            caption += f" · {label}"
        try:
            ok = await self._bot.send_document(int(chat_id), path, caption=caption)
        except Exception:
            log.exception("[DELIVERY] max chat=%s: исключение при отправке %s", chat_id, name)
            return False
        if ok:
            log.info(f"[DELIVERY] max chat={chat_id}: {name}")
        else:
            reason = getattr(self._bot, "last_error", "")
            log.warning(f"[DELIVERY] max chat={chat_id}: не доставился {name}"
                        + (f" — {reason}" if reason else ""))
        return ok
