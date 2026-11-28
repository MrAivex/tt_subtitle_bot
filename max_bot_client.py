import os
import asyncio
import json

import aiohttp


class MaxBot:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://platform-api2.max.ru"
        self.last_error = ""    # текст последней ошибки (для логов доставки)

    @property
    def headers(self):
        return {"Authorization": self.token, "Content-Type": "application/json"}

    async def send_message(self, chat_id: int, text: str, reply_markup=None):
        url = f"{self.base_url}/messages?chat_id={chat_id}"
        payload = {"text": text, "format": "markdown"}
        if reply_markup:
            payload["attachments"] = reply_markup
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with session.post(url, json=payload, headers=self.headers) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        return (
                            data.get("id")
                            or data.get("message_id")
                            or (data.get("message") or {}).get("body", {}).get("mid")
                        )
                    else:
                        print(f"[MAX send_message] {resp.status}: {await resp.text()}")
                        return None
        except Exception as e:
            print(f"[MAX send_message] {e}")
            return None

    async def edit_message(self, chat_id: int, message_id: str, new_text: str, reply_markup=None):
        url = f"{self.base_url}/messages?chat_id={chat_id}&message_id={message_id}"
        payload = {"text": new_text, "format": "markdown"}
        if reply_markup:
            payload["attachments"] = reply_markup
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with session.put(url, json=payload, headers=self.headers) as resp:
                    return resp.status in (200, 201, 204)
        except Exception as e:
            print(f"[MAX edit_message] {e}")
            return False

    # --- Загрузка медиафайлов ---

    async def _get_upload_url(self, media_type: str):
        """Возвращает (upload_url, token) или (None, None)."""
        url = f"{self.base_url}/uploads?type={media_type}"
        headers = {"Authorization": self.token, "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with session.post(url, headers=headers) as resp:
                    if resp.status not in (200, 201):
                        print(f"[MAX uploads/{media_type}] {resp.status}: {await resp.text()}")
                        return None, None
                    data = await resp.json()
                    return data.get("url"), data.get("token")
        except Exception as e:
            print(f"[MAX uploads/{media_type}] {e}")
            return None, None

    async def _upload_file(self, upload_url: str, file_path: str):
        """Загружает файл. Возвращает token (если в ответе), True (успех без token) или None (ошибка)."""
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                with open(file_path, "rb") as f:
                    form = aiohttp.FormData()
                    form.add_field("data", f, filename=os.path.basename(file_path))
                    async with session.post(upload_url, data=form) as resp:
                        body = await resp.text()
                        if resp.status != 200:
                            # раньше здесь печаталась ошибка, но метод возвращал успех —
                            # доставка шла с неподнятым файлом и падала уже на сообщении
                            print(f"[MAX _upload_file ERROR] status={resp.status}, body={body[:200]}", flush=True)
                            self.last_error = f"загрузка файла: HTTP {resp.status}"
                            return None
                        try:
                            data = json.loads(body)
                            if isinstance(data, dict) and data.get("token"):
                                return data["token"]
                        except Exception:
                            pass
                        return True   # токен не возвращён — используем токен из /uploads
        except Exception as e:
            print(f"[MAX _upload_file] {type(e).__name__}: {e}")
            self.last_error = f"загрузка файла: {type(e).__name__}"
            return None

    async def upload_video(self, video_path: str):
        upload_url, token = await self._get_upload_url("video")
        if not upload_url:
            return None
        if not await self._upload_file(upload_url, video_path):
            return None
        return token

    async def get_video_url(self, video_token: str) -> str | None:
        """GET /videos/{token} → возвращает URL для скачивания (1080p или максимальное доступное)."""
        url = f"{self.base_url}/videos/{video_token}"
        headers = {"Authorization": self.token}
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        print(f"[MAX get_video_url] {resp.status}: {await resp.text()}")
                        return None
                    data = await resp.json()
                    urls = data.get("urls") or {}
                    # Предпочитаем 1080p, но берём любое доступное
                    for key in ("mp4_1080", "mp4_720", "mp4_480", "mp4_360", "mp4_240", "mp4_144", "hls"):
                        if urls.get(key):
                            return urls[key]
                    return None
        except Exception as e:
            print(f"[MAX get_video_url] {e}")
            return None

    async def upload_document(self, file_path: str):
        upload_url, initial_token = await self._get_upload_url("file")
        if not upload_url:
            return None
        result = await self._upload_file(upload_url, file_path)
        if not result:
            return None
        # Для файлов MAX возвращает token из ответа на загрузку
        if isinstance(result, str):
            return result
        return initial_token

    async def send_video(self, chat_id: int, video_path: str, caption: str = ""):
        token = await self.upload_video(video_path)
        if not token:
            print("[MAX send_video] не удалось загрузить видео")
            return None
        # пауза — MAX обрабатывает файл после загрузки
        await asyncio.sleep(2)
        url = f"{self.base_url}/messages?chat_id={chat_id}"
        payload = {
            "text": caption,
            "format": "markdown",
            "attachments": [{"type": "video", "payload": {"token": token}}]
        }
        for attempt in range(12):                      # ~ до 2-3 минут ожидания
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                    async with session.post(url, json=payload, headers=self.headers) as resp:
                        if resp.status in (200, 201):
                            data = await resp.json()
                            return data.get("id") or (data.get("message") or {}).get("body", {}).get("mid")
                        body = await resp.text()
                        if resp.status == 400 and "not.ready" in body:
                            await asyncio.sleep(3 + attempt * 2)   # MAX ещё обрабатывает видео
                            continue
                        print(f"[MAX send_video] {resp.status}: {body}")
                        return None
            except Exception as e:
                print(f"[MAX send_video] {e}")
                return None
        print("[MAX send_video] видео так и не обработалось")
        return None

    async def send_document(self, chat_id: int, file_path: str, caption: str = ""):
        """Файл в чат документом (attachments type=file). Возвращает id сообщения или None.

        После загрузки MAX обрабатывает файл не сразу: ответ «not.ready» на
        сообщении — норма, поэтому ждём и повторяем (как в send_video).
        """
        self.last_error = ""
        token = await self.upload_document(file_path)
        if not token:
            if not self.last_error:
                self.last_error = "не удалось получить URL загрузки файла"
            print("[MAX send_document] не удалось загрузить файл", flush=True)
            return None
        url = f"{self.base_url}/messages?chat_id={chat_id}"
        payload = {
            "text": caption,
            "format": "markdown",
            "attachments": [{"type": "file", "payload": {"token": token}}]
        }
        for attempt in range(12):                      # ~ до 2-3 минут ожидания обработки
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                    async with session.post(url, json=payload, headers=self.headers) as resp:
                        if resp.status in (200, 201):
                            data = await resp.json()
                            return data.get("id") or (data.get("message") or {}).get("body", {}).get("mid")
                        body = await resp.text()
                        if resp.status == 400 and "not.ready" in body:
                            await asyncio.sleep(3 + attempt * 2)   # MAX ещё обрабатывает файл
                            continue
                        self.last_error = f"HTTP {resp.status}: {body[:120]}"
                        print(f"[MAX send_document] {resp.status}: {body}", flush=True)
                        return None
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                print(f"[MAX send_document] {e}", flush=True)
                return None
        self.last_error = "файл так и не обработался на стороне MAX (not.ready)"
        print("[MAX send_document] файл так и не обработался", flush=True)
        return None