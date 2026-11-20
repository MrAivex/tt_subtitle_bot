# highlights/analyzer.py
"""Умный поиск моментов по аудиодорожке.

Composition root: собирает extractor, curves, picker, scorer.
Публичный API: analyze(wav_path, max_moments=5, asr=None) -> {"duration", "moments"}
"""
import logging
from typing import Optional

from .extractor import extract, Yamnet
from .curves import build_curves
from .picker import pick
from .scorer import enrich, finalize, combine
from utils import timed

log = logging.getLogger("timing")


class HighlightAnalyzer:
    def __init__(self, asr: Optional[callable] = None):
        self._asr = asr

    def analyze(self, wav_path: str, max_moments: int = 5, stop=None) -> dict:
        from utils import timed
        with timed("хайлайты: загрузка YAMNet"):
            yam = Yamnet.load()
        with timed("хайлайты: признаки + YAMNet"):
            res = extract(wav_path, yam)
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
