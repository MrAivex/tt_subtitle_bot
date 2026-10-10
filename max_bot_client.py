import os
import asyncio
import aiohttp


class MaxBot:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://platform-api2.max.ru"

    @property
    def headers(self):
        return {"Authorization": self.token, "Content-Type": "application/json"}

    async def send_message(self, chat_id: int, text: str, reply_markup=None):
        url = f"{self.base_url}/messages?chat_id={chat_id}"
        payload = {"text": text, "format": "markdown"}
        if reply_markup:
            payload["attachments"] = reply_markup
        try:
            async with aiohttp.ClientSession() as session:
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
            async with aiohttp.ClientSession() as session:
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
            async with aiohttp.ClientSession() as session:
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
        """Загружает файл на сервер по upload_url."""
        try:
            async with aiohttp.ClientSession() as session:
                with open(file_path, "rb") as f:
                    form = aiohttp.FormData()
                    form.add_field("data", f, filename=os.path.basename(file_path))
                    async with session.post(upload_url, data=form) as resp:
                        body = await resp.text()
                        return resp.status == 200
        except Exception as e:
            print(f"[MAX _upload_file] {e}")
            return False

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
            async with aiohttp.ClientSession() as session:
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
        upload_url, token = await self._get_upload_url("file")
        if not upload_url:
            return None
        if not await self._upload_file(upload_url, file_path):
            return None
        return token

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
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=self.headers) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        return data.get("id") or (data.get("message") or {}).get("body", {}).get("mid")
                    else:
                        print(f"[MAX send_video] {resp.status}: {await resp.text()}")
                        return None
        except Exception as e:
            print(f"[MAX send_video] {e}")
            return None

    async def send_document(self, chat_id: int, file_path: str, caption: str = ""):
        token = await self.upload_document(file_path)
        if not token:
            print("[MAX send_document] не удалось загрузить файл")
            return None
        await asyncio.sleep(1)
        url = f"{self.base_url}/messages?chat_id={chat_id}"
        payload = {
            "text": caption,
            "format": "markdown",
            "attachments": [{"type": "file", "payload": {"token": token}}]
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=self.headers) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        return data.get("id") or (data.get("message") or {}).get("body", {}).get("mid")
                    else:
                        print(f"[MAX send_document] {resp.status}: {await resp.text()}")
                        return None
        except Exception as e:
            print(f"[MAX send_document] {e}")
            return None