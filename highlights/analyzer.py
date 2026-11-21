# highlights/analyzer.py
"""Умный поиск моментов по аудиодорожке.

Composition root: собирает extractor, curves, picker, scorer.
Публичный API:
    analyze(wav_path, max_moments=5, stop=None)                  — по готовому WAV
    analyze_media(src, wav_path, ffmpeg, max_moments=5, stop=None) — декодирование и анализ параллельно
"""
import logging
import tempfile
from typing import Optional

from .extractor import extract, extract_stream, Yamnet
from .curves import build_curves
from .picker import pick
from .scorer import enrich, finalize, combine
from utils import timed

log = logging.getLogger("timing")


class HighlightAnalyzer:
    def __init__(self, asr: Optional[callable] = None):
        self._asr = asr

    def analyze(self, wav_path: str, max_moments: int = 5, stop=None) -> dict:
        with timed("хайлайты: загрузка YAMNet"):
            yam = Yamnet.load()
        with timed("хайлайты: признаки + YAMNet"):
            res = extract(wav_path, yam)
        return self._finish(res, wav_path, max_moments, stop)

    def analyze_media(self, src, wav_path: str, ffmpeg, max_moments: int = 5, stop=None) -> dict:
        """ffmpeg декодирует один раз: WAV на диск (для Whisper) и PCM в pipe (для анализа)."""
        with timed("хайлайты: загрузка YAMNet"):
            yam = Yamnet.load()

        with tempfile.TemporaryFile() as err:
            p = ffmpeg.start_audio_tee(src, wav_path, err)

            def read(n):
                return p.stdout.read(n)

            try:
                with timed("хайлайты: декодирование + признаки + YAMNet"):
                    res = extract_stream(read, yam)
            except BaseException:
                p.kill()                  # остановка или ошибка: не даём ffmpeg доделывать часы звука
                raise
            finally:
                p.stdout.close()
                rc = p.wait()

            if rc:
                err.seek(0)
                raise RuntimeError("ffmpeg: " + err.read().decode(errors="ignore")[-300:])

        return self._finish(res, wav_path, max_moments, stop)

    def _finish(self, res, wav_path: str, max_moments: int, stop=None) -> dict:
        if res is None:
            return {"duration": 0.0, "moments": []}
        dur, feats, g = res
        n = len(feats["rms"])
        if n < 20:
            return {"duration": dur, "moments": []}

        curves = build_curves(feats, g)
        S = combine(curves)
        use_asr = self._asr is not None
        cands = pick(S, dur, max_moments + 3 if use_asr else max_moments)
        with timed("хайлайты: распознавание кандидатов"):
            enrich(cands, curves, feats, wav_path, self._asr, stop)
        moments = finalize(cands, max_moments)
        return {"duration": dur, "moments": moments}