"""Минимальный клиент Telegram Bot API (aiohttp), в стиле max_bot_client.py.

Без внешних зависимостей. Что умеем:
  sendMessage / editMessageText / answerCallbackQuery / sendChatAction
  sendVideo (multipart, лимит Bot API — 50 МБ)
  getFile + скачивание (лимит Bot API — 20 МБ)
  setWebhook (с secret_token — проверка, что апдейты шлёт сам Telegram)

Если api.telegram.org недоступен напрямую (например, в РФ), задайте в .env:
  TG_API_PROXY=socks5h://user:pass@host:port   (или http://host:port)
Для socks нужен пакет aiohttp-socks (есть в requirements.txt).
"""
import asyncio
import os

import aiohttp


class TgBot:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.file_url = f"https://api.telegram.org/file/bot{token}"

    def _session(self) -> aiohttp.ClientSession:
        """Сессия через прокси, если задан TG_API_PROXY; иначе — напрямую."""
        proxy = os.getenv("TG_API_PROXY", "")
        if proxy:
            try:
                from aiohttp_socks import ProxyConnector
                return aiohttp.ClientSession(connector=ProxyConnector.from_url(proxy))
            except ImportError:
                print("[TG] TG_API_PROXY задан, но пакет aiohttp-socks не установлен — иду напрямую",
                      flush=True)
        return aiohttp.ClientSession()

    # ---------- базовые вызовы ----------

    async def api(self, method: str, payload: dict):
        """POST JSON → result или None. 429 (flood control) пережидаем."""
        for attempt in range(3):
            try:
                async with self._session() as session:
                    async with session.post(f"{self.base_url}/{method}", json=payload) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        if resp.status == 429 and attempt < 2:
                            wait = int(resp.headers.get("Retry-After") or 3)
                            print(f"[TG {method}] 429, жду {wait}с", flush=True)
                            await asyncio.sleep(wait)
                            continue
                        print(f"[TG {method}] {resp.status}: {(await resp.text())[:300]}", flush=True)
                        return None
            except Exception as e:
                print(f"[TG {method}] {e}", flush=True)
                return None
        return None

    async def _result(self, method: str, payload: dict):
        data = await self.api(method, payload)
        return (data or {}).get("result")

    # ---------- сообщения ----------

    async def send_message(self, chat_id: int, text: str, reply_markup=None,
                           parse_mode: str = "HTML") -> int | None:
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = await self._result("sendMessage", payload)
        return res.get("message_id") if res else None

    async def edit_message_text(self, chat_id: int, message_id: int, text: str,
                                reply_markup=None, parse_mode: str = "HTML") -> bool:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        # «message is not modified» не считается ошибкой — просто ничего не изменилось
        return bool(await self.api("editMessageText", payload))

    async def answer_callback_query(self, callback_query_id: str, text: str = None) -> bool:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return bool(await self.api("answerCallbackQuery", payload))

    async def send_chat_action(self, chat_id: int, action: str = "upload_video") -> bool:
        return bool(await self.api("sendChatAction", {"chat_id": chat_id, "action": action}))

    # ---------- файлы ----------

    async def download_file(self, file_id: str, out_path: str) -> str | None:
        """Скачивает файл через getFile. Bot API отдаёт максимум 20 МБ."""
        info = await self._result("getFile", {"file_id": file_id})
        if not info or not info.get("file_path"):
            print("[TG download_file] не получил file_path", flush=True)
            return None
        url = f"{self.file_url}/{info['file_path']}"
        try:
            async with self._session() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        print(f"[TG download_file] {resp.status}: {(await resp.text())[:200]}", flush=True)
                        return None
                    with open(out_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1 << 20):
                            f.write(chunk)
            return out_path
        except Exception as e:
            print(f"[TG download_file] {e}", flush=True)
            return None

    async def send_video(self, chat_id: int, video_path: str, caption: str = "",
                         parse_mode: str = "HTML") -> int | None:
        """Видео multipart'ом (лимит Bot API — 50 МБ). Возвращает message_id."""
        for attempt in range(3):
            try:
                async with self._session() as session:
                    with open(video_path, "rb") as f:
                        form = aiohttp.FormData()
                        form.add_field("video", f, filename=os.path.basename(video_path),
                                       content_type="video/mp4")
                        form.add_field("chat_id", str(chat_id))
                        if caption:
                            form.add_field("caption", caption)
                        if parse_mode:
                            form.add_field("parse_mode", parse_mode)
                        async with session.post(f"{self.base_url}/sendVideo", data=form) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                return (data.get("result") or {}).get("message_id")
                            if resp.status == 429 and attempt < 2:
                                wait = int(resp.headers.get("Retry-After") or 3)
                                print(f"[TG sendVideo] 429, жду {wait}с", flush=True)
                                await asyncio.sleep(wait)
                                continue
                            print(f"[TG sendVideo] {resp.status}: {(await resp.text())[:300]}", flush=True)
                            return None
            except Exception as e:
                print(f"[TG sendVideo] {e}", flush=True)
                return None
        return None

    # ---------- вебхук ----------

    async def set_webhook(self, url: str, secret_token: str = "",
                          allowed_updates: list = None) -> bool:
        payload = {
            "url": url,
            "allowed_updates": allowed_updates or ["message", "callback_query"],
            "drop_pending_updates": True,
        }
        if secret_token:
            payload["secret_token"] = secret_token
        return bool(await self.api("setWebhook", payload))
