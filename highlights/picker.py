# highlights/picker.py
"""Выбор моментов из итоговой кривой интереса."""
import numpy as np

PAD_BEFORE, PAD_AFTER = 3.0, 4.0
MIN_CLIP, MAX_CLIP = 10.0, 60.0
MIN_SCORE = 0.10


def pick(S, dur, count, clip_sec=0):
    """Выбрать top-k моментов из кривой интереса S.

    Возвращает список dict: {"start", "end", "peak"}.
    """
    S = S.copy()
    n = len(S)
    out = []
    while len(out) < count:
        i = int(np.argmax(S))
        peak = float(S[i])
        if peak < MIN_SCORE:
            break
        thr = max(peak * 0.5, MIN_SCORE * 0.5)
        a = i
        while a > 0 and S[a - 1] >= thr and i - a < 60:
            a -= 1
        b = i
        while b < n - 1 and S[b + 1] >= thr and b - i < 60:
            b += 1
        start = max(0.0, a * 0.5 - PAD_BEFORE)
        end = min(dur, (b + 1) * 0.5 + PAD_AFTER)
        if end - start < MIN_CLIP:
            c = (a + b + 1) * 0.5 / 2
            start = max(0.0, c - MIN_CLIP / 2)
            end = min(dur, start + MIN_CLIP)
            start = max(0.0, end - MIN_CLIP)
        if end - start > MAX_CLIP:
            start = max(0.0, i * 0.5 - 0.4 * MAX_CLIP)
            end = min(dur, start + MAX_CLIP)
        if clip_sec:                      # длина задана: пик в первой трети клипа
            start = max(0.0, i * 0.5 - 0.35 * clip_sec)
            end = min(dur, start + clip_sec)
            start = max(0.0, end - clip_sec)
        lo = max(0, int(start / 0.5) - 4)
        hi = min(n, int(end / 0.5) + 5)
        S[lo:hi] = -1.0
        out.append({"start": round(start, 2), "end": round(end, 2), "peak": peak})
    return out
