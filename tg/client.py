"""tg/client.py — тонкий клиент Telegram Bot API на aiohttp (без новых зависимостей)."""
import logging
from typing import Optional

import aiohttp

log = logging.getLogger("tg")


class TgBot:
    def __init__(self, token: str, proxy: Optional[str] = None):
        self.token = token
        self._base = f"https://api.telegram.org/bot{token}/"
        self._proxy = proxy
        self._session: Optional[aiohttp.ClientSession] = None

    def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._session

    async def call(self, method: str, **params):
        """Вызов метода Bot API. Возвращает result или None при ошибке."""
        try:
            async with self._s().post(self._base + method, json=params, proxy=self._proxy) as r:
                data = await r.json(content_type=None)
        except Exception as e:
            log.warning(f"[TG {method}] {type(e).__name__}: {e}")
            return None
        if not data.get("ok"):
            log.warning(f"[TG {method}] {data.get('error_code')}: {data.get('description')}")
            return None
        return data.get("result")

    async def send_message(self, chat_id: int, text: str, reply_markup: dict = None,
                           parse_mode: str = "HTML"):
        params = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                  "link_preview_options": {"is_disabled": True}}
        if reply_markup:
            params["reply_markup"] = reply_markup
        res = await self.call("sendMessage", **params)
        return (res or {}).get("message_id")

    async def answer_callback(self, callback_id: str, text: str = None):
        params = {"callback_query_id": callback_id}
        if text:
            params["text"] = text
        await self.call("answerCallbackQuery", **params)

    async def set_webhook(self, url: str, secret: str):
        return await self.call("setWebhook", url=url, secret_token=secret,
                               allowed_updates=["message", "callback_query"])

    async def set_menu_button(self, url: str, text: str = "🎬 Открыть"):
        """Кнопка слева от поля ввода: открывает мини-приложение."""
        return await self.call("setChatMenuButton", menu_button={
            "type": "web_app", "text": text, "web_app": {"url": url}})

    async def set_commands(self):
        return await self.call("setMyCommands", commands=[
            {"command": "start", "description": "Начать"},
            {"command": "pay", "description": "Подписки"},
            {"command": "help", "description": "Справка"},
        ])

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
