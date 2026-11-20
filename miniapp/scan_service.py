"""miniapp/scan_service.py — поиск моментов."""
import asyncio
import traceback
import time

from .jobs import rm
from .tasks import spawn
from .eta import eta
from sources import downloader


class ScanService:
    def __init__(self, analyzer, previews, max_moments: int, slots: int = 2):
        self._analyzer = analyzer
        self._previews = previews
        self._max = max_moments
        self._slots = asyncio.Semaphore(slots)

    async def run(self, job):
        wav = f"downloads/scan_{job.user_id}_{job.id}.wav"
        key = "scan_link" if job.source.__class__.__name__ == "LinkSource" else "scan_file"
        vid_sec = 0.0
        try:
            try:
                vid_sec = await job.source.duration()
            except Exception:
                pass
            job.eta, job.eta_ts = eta.estimate(key, vid_sec), time.time()
            async with self._slots:
                t0 = time.time()
                async def ticker():
                    while True:
                        p = downloader.PROGRESS.get(getattr(job.source, "url", ""), "")
                        job.progress = f"Скачиваю звук {p}".strip()
                        await asyncio.sleep(2)

                job.progress = "Скачиваю звук"
                tk = asyncio.create_task(ticker())
                try:
                    await job.source.prepare_audio(wav)
                finally:
                    tk.cancel()
                job.progress = "Ищу громкие моменты"
                res = await asyncio.to_thread(self._analyzer.analyze, wav, self._max)
                eta.record(key, vid_sec or res["duration"], time.time() - t0)
            job.eta = 0.0
            job.duration = max(res["duration"], 1.0)
            job.moments = res["moments"]
            job.status = "ready"
            job.progress = ""
            if job.moments:
                spawn(self._previews.run(job))
            else:
                job.previews_status = "done"
        except Exception as e:
            traceback.print_exc()
            job.eta = 0.0
            msg = str(e)
            if "DownloadError" in type(e).__name__ or "fragment" in msg.lower():
                msg = "Не удалось скачать видео по ссылке. Попробуй ещё раз или загрузи файл"
            job.status, job.error = "error", msg[:150]
            job.source.cleanup()
        finally:
            rm(wav)
