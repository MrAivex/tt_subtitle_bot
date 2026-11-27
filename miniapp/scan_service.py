"""miniapp/scan_service.py — поиск моментов."""
import asyncio
import time
import traceback

from sources import downloader
from .eta import eta
from .jobs import rm
from .tasks import spawn


class ScanService:
    def __init__(self, analyzer, previews, max_moments: int, ffmpeg, slots: int = 2):
        self._analyzer = analyzer
        self._previews = previews
        self._max = max_moments
        self._slots = asyncio.Semaphore(slots)
        self._ffmpeg = ffmpeg

    async def run(self, job):
        wav = f"downloads/scan_{job.user_id}_{job.id}.wav"
        raw = wav[:-4] + "_raw"          # NEW: тот же stem, что был у download_audio_only, ключ в CANCELLED не меняется
        src = None                       # NEW: файл, из которого ffmpeg декодирует звук
        key = "scan_link" if job.source.__class__.__name__ == "LinkSource" else "scan_file"
        vid_sec = 0.0
        analysis = None
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
                    src = await job.source.audio_input(raw)          # NEW (было prepare_audio(wav))
                finally:
                    tk.cancel()
                job.progress = "Ищу громкие моменты"
                analysis = asyncio.ensure_future(                     # NEW
                    asyncio.to_thread(self._analyzer.analyze_media, src, wav, self._ffmpeg,
                                      self._max, lambda: job.cancelled,
                                      getattr(job, "kinds", None) or None))
                res = await asyncio.shield(analysis)
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
        except asyncio.CancelledError:
            downloader.CANCELLED.add(raw)                             # NEW: тот же ключ, что и раньше
            job.source.cleanup()
            raise
        except Exception as e:
            traceback.print_exc()
            job.eta = 0.0
            job.status, job.error = "error", f"{type(e).__name__}: {str(e)[:150]}"
            job.source.cleanup()
        finally:
            def _cleanup(_f=None):                                    # NEW: чистим и wav, и сырой файл
                rm(wav)
                if src and job.source.is_temp(src):
                    rm(src)

            if analysis is not None and not analysis.done():
                # поток ещё работает: удалим файлы только когда он закончит
                analysis.add_done_callback(lambda f: (f.exception(), _cleanup()))
            else:
                _cleanup()
