# highlights/scorer.py
"""Объединение кривых в итоговую кривую, enrichment через ASR, label."""
import logging
import wave
from typing import Optional

import numpy as np

from highlights.kinds import apply_text, label

log = logging.getLogger("timing")


def combine(cats):
    """Итоговая сила = главный тип + бонус за совпадение нескольких."""
    from highlights.kinds import KINDS
    vals = np.stack([KINDS[k][2] * np.asarray(cats[k], dtype=np.float32) for k in KINDS])
    srt = -np.sort(-vals, axis=0)
    return srt[0] + 0.3 * srt[1] + 0.15 * srt[2]


def _read_segment(path, start, end):
    with wave.open(path, "rb") as wf:
        wf.setpos(int(start * 16000))
        raw = wf.readframes(int((end - start) * 16000))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def enrich(candidates, curves, wav_path, asr: Optional[callable] = None):
    """Добавить к каждому кандидату: cats, energy, text, score."""
    from highlights.kinds import KINDS
    USE_ASR = True  # TODO: вынести в config
    n = len(curves["rms"])
    mean_rms = float(curves["rms"].mean()) + 1e-9

    for c in candidates:
        a, b = int(c["start"] / 0.5), min(n, int(c["end"] / 0.5) + 1)
        c["cats"] = {k: float(curves[k][a:b].max()) for k in KINDS}
        c["energy"] = round(float(curves["rms"][a:b].mean() / mean_rms), 2)
        c["text"] = ""
        if asr is not None and USE_ASR:
            try:
                seg_end = min(c["end"], c["start"] + 45.0)
                audio = _read_segment(wav_path, c["start"], seg_end)
                c["text"] = (asr(audio) or "").strip().lower()
                c["cats"] = apply_text(c["cats"], c["text"], seg_end - c["start"])
            except Exception as e:
                log.warning(f"[HIGHLIGHTS] ASR не сработал: {type(e).__name__}: {e}")
        c["score"] = float(combine(c["cats"]))


def finalize(candidates, max_moments):
    """Отсортировать и вернуть финальные moments."""
    candidates.sort(key=lambda c: c["score"], reverse=True)
    candidates = candidates[:max_moments]
    candidates.sort(key=lambda c: c["start"])

    moments = []
    for c in candidates:
        kind, tags, emoji, label_text = label(c["cats"])
        m = {"start": c["start"], "end": c["end"], "energy": c["energy"],
             "score": round(c["score"], 2), "kind": kind, "tags": tags,
             "emoji": emoji, "label": label_text}
        if c["text"]:
            m["snippet"] = c["text"][:67] + "…" if len(c["text"]) > 70 else c["text"]
        moments.append(m)
        log.info(f"[HIGHLIGHTS] {c['start']:.0f}-{c['end']:.0f}s {label_text} score={c['score']:.2f} "
                 + " ".join(f"{k}={v:.2f}" for k, v in c["cats"].items()))
    return moments
