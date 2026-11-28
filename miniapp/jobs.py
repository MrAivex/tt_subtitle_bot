"""miniapp/jobs.py — модель задачи и хранилище."""
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from sources.base import MediaSource
from .errors import ApiError

FULL_VIDEO = -1          # ключ в Job.renders для «субтитры на всё видео»


def rm(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


@dataclass
class Job:
    user_id: int
    chat_id: int
    source: MediaSource
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    duration: float = 1.0
    moments: list = field(default_factory=list)
    status: str = "scanning"          # scanning | ready | error
    progress: str = ""
    error: str = ""
    ts: float = field(default_factory=time.time)
    seen: bool = False
    charged: bool = False
    premium: bool = False
    previews: list = field(default_factory=list)
    previews_status: str = "pending"  # pending | done | error
    renders: dict = field(default_factory=dict)   # idx -> {status, path, name, error, extra}
    eta: float = 0.0          # оценка поиска моментов, сек
    eta_ts: float = 0.0
    task: object = None
    cancelled: bool = False
    platform: str = ""        # max / tg / site — откуда запущена задача (для доставки файлов)
    kinds: list = field(default_factory=list)   # выбранные типы моментов (fight/funny/talk); пусто = авто

    @property
    def title(self) -> str:
        return self.source.title

    def preview_path(self, idx: int) -> str:
        """Единая точка правды для имени превью."""
        return f"downloads/prev_{self.id}_{idx}.mp4"

    def busy(self) -> bool:
        return self.status == "scanning" or any(
            r.get("status") == "pending" for r in self.renders.values())

    def public(self, media_token: str) -> dict:
        now = time.time()
        eta_left = (max(0.0, self.eta - (now - self.eta_ts))
                    if self.status == "scanning" and self.eta else 0)
        eta_over = bool(self.status == "scanning" and self.eta and (now - self.eta_ts) > self.eta)
        renders = {}
        for k, v in self.renders.items():
            r = {kk: vv for kk, vv in v.items() if kk not in ("path", "extra", "eta", "eta_ts")}
            if v.get("status") == "pending" and v.get("eta"):
                r["eta_left"] = max(0.0, v["eta"] - (now - v.get("eta_ts", now)))
            renders[str(k)] = r
        return {
            "id": self.id, "status": self.status, "progress": self.progress,
            "error": self.error, "duration": self.duration, "moments": self.moments,
            "previews": self.previews, "previews_status": self.previews_status,
            "title": self.title, "eta_left": eta_left, "eta_over": eta_over,
            "renders": renders, "media_token": media_token, "kinds": self.kinds or [],
        }

    def cleanup(self):
        for i in range(len(self.moments)):
            rm(self.preview_path(i))
        for r in self.renders.values():
            rm(r.get("path"), *r.get("extra", []))
        self.source.cleanup()


class JobStore:
    STALE_SEC = 6 * 3600

    def __init__(self):
        self._jobs: dict = {}
        self._reserved: set = set()

    @contextmanager
    def slot(self, user_id: int):
        """Занимает «место» пользователя на время создания задачи (в том числе на время
        загрузки файла), чтобы две параллельные загрузки не прошли проверку одновременно."""
        self._reserve(user_id)
        try:
            yield
        finally:
            self._reserved.discard(user_id)

    def _reserve(self, user_id: int):
        if user_id in self._reserved or any(
                j.user_id == user_id and j.busy() for j in self._jobs.values()):
            raise ApiError("Предыдущая задача ещё выполняется — дождись окончания", 409)
        now = time.time()
        for k, j in list(self._jobs.items()):
            if not j.busy() and (j.user_id == user_id or now - j.ts > self.STALE_SEC):
                j.cleanup()
                self._jobs.pop(k, None)
        self._reserved.add(user_id)

    def add(self, job: Job) -> Job:
        self._jobs[job.id] = job
        return job

    def get_by_id(self, job_id: str):
        return self._jobs.get(job_id)

    def get_for(self, job_id: str, user_id: int) -> Job:
        job = self._jobs.get(job_id)
        if not job or job.user_id != user_id:
            raise ApiError("Задача не найдена", 404)
        return job

    def latest_for(self, user_id: int):
        mine = [j for j in self._jobs.values() if j.user_id == user_id]
        return max(mine, key=lambda j: j.ts, default=None)

    def drop(self, job: Job):
        self._jobs.pop(job.id, None)
