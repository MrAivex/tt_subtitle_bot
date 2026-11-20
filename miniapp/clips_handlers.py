"""miniapp/clips_handlers.py — HTTP-эндпоинты задач: запуск, статус, превью, скачивание."""
import os
import uuid
from urllib.parse import quote

from aiohttp import web

from config import MAX_CLIPS_PER_REQUEST, MAX_FILE_SIZE_BYTES
from sources import detect_platform
from sources.file_source import FileSource
from sources.link_source import LinkSource
from .errors import ApiError
from .jobs import FULL_VIDEO, Job, rm
from .tasks import spawn

VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm")


class ClipsHandlers:
    def __init__(self, jobs, billing, scan, render, signer, ffmpeg, downloader):
        self._jobs = jobs
        self._billing = billing
        self._scan = scan
        self._render = render
        self._signer = signer
        self._ffmpeg = ffmpeg
        self._dl = downloader

    def routes(self):
        return [
            web.get("/active", self.active),
            web.post("/scan", self.scan),
            web.post("/upload", self.upload),
            web.get("/jobs/{id}", self.job),
            web.post("/jobs/{id}/prepare", self.prepare),
            web.get("/jobs/{id}/preview/{idx}", self.preview),
            web.get("/jobs/{id}/download/{idx}", self.download),
        ]

    # ---------- вспомогательное ----------

    def _pub(self, job: Job) -> dict:
        return job.public(self._signer.sign(job.id))

    def _job(self, request) -> Job:
        return self._jobs.get_for(request.match_info["id"], request["uid"])

    @staticmethod
    async def _save(field, path: str):
        size = 0
        try:
            with open(path, "wb") as f:
                while chunk := await field.read_chunk(1 << 20):
                    size += len(chunk)
                    if size > MAX_FILE_SIZE_BYTES:
                        raise ApiError("Файл больше 2.5 ГБ")
                    f.write(chunk)
        except BaseException:
            rm(path)
            raise

    # ---------- запуск ----------

    async def scan(self, request):
        uid = request["uid"]
        url = ((await request.json()).get("url") or "").strip()
        if not detect_platform(url):
            raise ApiError("Не узнаю ссылку. Подойдут YouTube, Twitch, TikTok, Google Drive и Яндекс.Диск.")
        user = await self._billing.ensure_can_start(uid)
        with self._jobs.slot(uid):
            job = self._jobs.add(Job(uid, user.chat_id, LinkSource(url)))
        spawn(self._scan.run(job))
        return web.json_response(self._pub(job))

    async def upload(self, request):
        uid = request["uid"]
        user = await self._billing.ensure_can_start(uid)
        with self._jobs.slot(uid):          # место занято на всё время загрузки файла
            field = await (await request.multipart()).next()
            if field is None:
                raise ApiError("Файл не получен")
            filename = getattr(field, "filename", "") or ""
            stem, ext = os.path.splitext(filename)
            if ext.lower() not in VIDEO_EXT:
                raise ApiError("Нужен видеофайл: mp4, mov, avi, mkv или webm")
            path = f"downloads/max_{uid}_{uuid.uuid4().hex[:10]}{ext.lower()}"
            await self._save(field, path)
            job = self._jobs.add(Job(uid, user.chat_id, FileSource(path, stem, self._ffmpeg)))
        spawn(self._scan.run(job))
        return web.json_response(self._pub(job))

    # ---------- статус ----------

    async def job(self, request):
        job = self._job(request)
        if job.status == "error":
            job.seen = True
        return web.json_response(self._pub(job))

    async def active(self, request):
        job = self._jobs.latest_for(request["uid"])
        if job and job.status == "error":
            if job.seen:
                job = None
            else:
                job.seen = True
        return web.json_response({"job": self._pub(job) if job else None})

    # ---------- рендер ----------

    async def prepare(self, request):
        job = self._job(request)
        body = await request.json()
        idx = int(body.get("idx", FULL_VIDEO))
        if idx == FULL_VIDEO:
            raise ApiError("Субтитры на всё видео отключены — выбери клипы")
        if idx != FULL_VIDEO:
            if not 0 <= idx < len(job.moments):
                raise ApiError("Неверный момент")
            active = [k for k, v in job.renders.items()
                      if k != FULL_VIDEO and v.get("status") in ("pending", "ready")]
            if idx not in job.renders and len(active) >= MAX_CLIPS_PER_REQUEST:
                raise ApiError(f"Не больше {MAX_CLIPS_PER_REQUEST} клипов за раз")
        if job.status != "ready":
            raise ApiError("Задача сейчас занята", 409)
        cur = job.renders.get(idx)
        if cur and cur["status"] in ("pending", "ready"):
            return web.json_response(self._pub(job))
        job.renders[idx] = {"status": "pending"}
        spawn(self._render.run(job, idx, bool(body.get("subtitles", True)),
                               bool(body.get("vertical", False))))
        return web.json_response(self._pub(job))

    # ---------- файлы ----------

    async def preview(self, request):
        job = self._job(request)
        path = job.preview_path(int(request.match_info["idx"]))
        if not os.path.exists(path):
            raise ApiError("Превью ещё не готово", 404)
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    async def download(self, request):
        job = self._job(request)
        idx = int(request.match_info["idx"])
        r = job.renders.get(idx)
        if not r or r["status"] != "ready" or not os.path.exists(r.get("path", "")):
            raise ApiError("Файл ещё не готов", 404)
        # ASCII-имя для старых клиентов + настоящее (кириллица) по RFC 5987
        plain = "full_subtitled.mp4" if idx == FULL_VIDEO else f"clip_{idx + 1}.mp4"
        disp = f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(r['name'])}"
        return web.FileResponse(r["path"], headers={
            "Content-Disposition": disp, "Cache-Control": "no-store"})
