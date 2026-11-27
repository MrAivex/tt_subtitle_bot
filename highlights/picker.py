# highlights/picker.py
"""Выбор моментов из кривой интереса."""
import numpy as np

PAD_BEFORE, PAD_AFTER = 3.0, 4.0
MIN_CLIP, MAX_CLIP = 10.0, 60.0
MIN_SCORE = 0.10
WIN_FRAMES = 60          # до какого соседнего кадра тянуть «примыкающий интерес»


def pick(S, dur, count, min_clip=MIN_CLIP, max_clip=MAX_CLIP,
         pad_before=PAD_BEFORE, pad_after=PAD_AFTER,
         min_score=MIN_SCORE, win_frames=WIN_FRAMES):
    """Выбрать top-k моментов из кривой интереса S.

    Параметры под каждый тип моментов (см. kinds.CAT_PARAMS): файты — короткие
    окна 2–5 с и почти без запаса по бокам, смешные — до минуты, разговорники —
    до двух минут. Возвращает список dict: {"start", "end", "peak"}.
    """
    S = S.copy()
    n = len(S)
    win = max(2, int(win_frames))
    out = []
    while len(out) < count:
        i = int(np.argmax(S))
        peak = float(S[i])
        if peak < min_score:
            break
        thr = max(peak * 0.5, min_score * 0.5)
        a = i
        while a > 0 and S[a - 1] >= thr and i - a < win:
            a -= 1
        b = i
        while b < n - 1 and S[b + 1] >= thr and b - i < win:
            b += 1
        start = max(0.0, a * 0.5 - pad_before)
        end = min(dur, (b + 1) * 0.5 + pad_after)
        if end - start < min_clip:
            c = (a + b + 1) * 0.5 / 2
            start = max(0.0, c - min_clip / 2)
            end = min(dur, start + min_clip)
            start = max(0.0, end - min_clip)
        if end - start > max_clip:
            # до max_clip: центр примерно на пике, но не раньше начала интереса (a),
            # иначе окно залезает в уже занятую предыдущим мометом зону
            start = max(a * 0.5 - pad_before, i * 0.5 - 0.4 * max_clip)
            end = min(dur, start + max_clip)
            if end - start < max_clip:            # упёрлись в конец видео — сдвигаем старт
                start = max(0.0, end - max_clip)
        lo = max(0, int(start / 0.5) - 4)
        hi = min(n, int(end / 0.5) + 5)
        S[lo:hi] = -1.0
        out.append({"start": round(start, 2), "end": round(end, 2), "peak": peak})
    return out
