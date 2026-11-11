"""Умный поиск моментов по аудиодорожке.

Что считаем (на каждые 0.5 сек звука):
  • громкость и резкие всплески (onset) — выстрелы, взрывы, серии ударов;
  • «возбуждённость» голоса: громкость и высота тона относительно обычной для видео;
  • (опционально) YAMNet: вероятности «выстрелы», «взрыв», «смех», «крик», «овации»;
  • (опционально) Whisper по самым сильным кандидатам: ключевые слова («убил», «ахаха», «баг»...).

Результат — те же поля, что и раньше (start, end, energy), плюс:
  kind   — основной тип момента (fight / funny / shock / win / absurd / hype)
  tags   — типы, которые тоже выражены
  label  — готовая подпись с эмодзи в конце, например «Бой, серия убийств 🔫😱»
  emoji  — только эмодзи
  score  — итоговая сила момента (0..~1.5)
  snippet— фрагмент речи (если работал Whisper)
"""
import csv
import logging
import os
import re
import wave
import warnings

import numpy as np

log = logging.getLogger("timing")

SR = 16000
FRAME_SEC = 0.5
FR = int(SR * FRAME_SEC)          # 8000 отсчётов в кадре
SUB = 160                         # 10 мс — для поиска резких всплесков
BLOCK_FRAMES = 600                # читаем по 5 минут, чтобы не держать весь стрим в памяти

PAD_BEFORE, PAD_AFTER = 3.0, 4.0
MIN_CLIP, MAX_CLIP = 10.0, 60.0
MIN_SCORE = 0.10

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YAMNET_MODEL = os.getenv("YAMNET_MODEL", os.path.join(BASE_DIR, "models", "yamnet.tflite"))
YAMNET_CLASSES = os.getenv("YAMNET_CLASSES", os.path.join(BASE_DIR, "models", "yamnet_class_map.csv"))
USE_ASR = os.getenv("HIGHLIGHT_ASR", "1") != "0"

# тип -> (название, эмодзи, вес при выборе главного типа)
KINDS = {
    "fight":  ("Бой, серия убийств", "🔫", 1.00),
    "funny":  ("Смешной момент", "😂", 0.95),
    "shock":  ("Шок, неожиданность", "😱", 0.90),
    "win":    ("Победа, овации", "🏆", 0.90),
    "absurd": ("Абсурд, баг", "🤡", 0.90),
    "hype":   ("Эмоциональный всплеск", "🔥", 0.70),
}

# Слова-подсказки для расшифровки (Whisper). Ищем по основам слов.
LEXICON = {
    "fight": r"убил|убит|убью|килл|кильн|снёс|снес[лу]|вынес|выпилил|хедш|хэдш|хэд|дабл|трипл|квадр|"
             r"пентакилл|эйс|\bace\b|зачист|перестрел|файт|замес|тимфайт|разнёс|разнес",
    "funny": r"ха-?ха|ахах|хах|ржу|ржал|ржач|смешн|угар|\bлол|кринж|прикол|шутк|умор|\bору\b|ржак|рофл|хихик",
    "shock": r"не может быть|ничего себе|офигеть|охренеть|\bого+\b|нифига|капец|кошмар|\bвау|ужас|жесть|"
             r"что происходит|не понял|как это|\b(?:а-?){3,}|\b(?:о-?){3,}",
    "win":   r"клатч|победа|победил|выиграл|чемпион|топ[\s-]?1|\bgg\b|\bгг\b|\bвин\b|красав|выжил",
    "absurd": r"\bбаг|глюк|лагает|\bлаг\b|застрял|сломал|что за|странн|абсурд|как так|сам себя|"
              r"телепорт|невозможн|текстур|вылет|зачем он|почему он",
}
_LEX_RE = {k: re.compile(v, re.IGNORECASE) for k, v in LEXICON.items()}


# ---------------------------------------------------------------- утилиты
def _rz(x, floor):
    """Робастный z-score: насколько значение выше «обычного» для этого видео.
    floor — минимальный разброс, чтобы тихие и ровные записи не давали ложных всплесков."""
    x = np.asarray(x, dtype=np.float32)
    if x.size < 8:
        return np.zeros_like(x)
    med = float(np.median(x))
    mad = max(float(np.median(np.abs(x - med))) * 1.4826, floor)
    return np.clip((x - med) / mad, -3.0, 12.0).astype(np.float32)


def _nz(x, lo, hi):
    return np.clip((np.asarray(x, dtype=np.float32) - lo) / (hi - lo), 0.0, 1.0)


def _smooth(c, w_mean=16, w_max=17):
    """Плотность события за ~8 сек (среднее) + пик (максимум). Серия убийств даёт больше одного выстрела."""
    k = np.ones(w_mean, np.float32) / w_mean
    mean = np.convolve(c, k, mode="same")[: len(c)]
    pad = w_max // 2
    mx = np.lib.stride_tricks.sliding_window_view(np.pad(c, pad), w_max).max(axis=1)
    return (0.6 * mean + 0.4 * mx).astype(np.float32)


def _combine(cats):
    """Итоговая сила = главный тип + небольшой бонус за совпадение нескольких (бой + крик = клатч)."""
    vals = np.stack([KINDS[k][2] * np.asarray(cats[k], dtype=np.float32) for k in KINDS])
    srt = -np.sort(-vals, axis=0)
    return srt[0] + 0.3 * srt[1] + 0.15 * srt[2]


# ---------------------------------------------------------------- YAMNet (необязательно)
def _get_interpreter_cls():
    for mod, attr in (("ai_edge_litert.interpreter", "Interpreter"),
                      ("tflite_runtime.interpreter", "Interpreter")):
        try:
            m = __import__(mod, fromlist=[attr])
            return getattr(m, attr)
        except Exception:
            continue
    try:
        import tensorflow as tf  # type: ignore
        return tf.lite.Interpreter
    except Exception:
        return None


class _Yamnet:
    GROUPS = {
        "gun":   ("Gunshot, gunfire", "Machine gun", "Fusillade", "Artillery fire", "Cap gun"),
        "boom":  ("Explosion", "Boom"),
        "laugh": ("Laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"),
        "scream": ("Screaming", "Shout", "Yell", "Battle cry", "Whoop"),
        "cheer": ("Cheering", "Applause", "Clapping"),
    }

    def __init__(self, interpreter, names):
        self.it = interpreter
        self.it.allocate_tensors()
        inp = self.it.get_input_details()[0]
        out = self.it.get_output_details()[0]
        self.inp_idx, self.out_idx = inp["index"], out["index"]
        self.win = int(np.prod(inp["shape"]))
        if self.win < FR:                       # модель с динамической длиной входа
            self.win = 15600
            self.it.resize_tensor_input(self.inp_idx, [self.win])
            self.it.allocate_tensors()
        self.inp_shape = tuple(self.it.get_input_details()[0]["shape"])
        self.group_idx = []
        for g, wanted in self.GROUPS.items():
            idx = [i for i, n in enumerate(names) if n in wanted]
            if not idx:
                log.warning(f"[YAMNET] нет классов для группы {g}")
            self.group_idx.append(np.array(idx, dtype=int))
        self.tail_len = max(self.win - FR, 0)

    @classmethod
    def load(cls):
        if not (os.path.exists(YAMNET_MODEL) and os.path.exists(YAMNET_CLASSES)):
            log.info(f"[YAMNET] модель не найдена ({YAMNET_MODEL}) — работаем без неё")
            return None
        Interp = _get_interpreter_cls()
        if Interp is None:
            log.warning("[YAMNET] нет ai-edge-litert / tflite-runtime — работаем без YAMNet")
            return None
        try:
            with open(YAMNET_CLASSES, encoding="utf-8") as f:
                rd = csv.reader(f)
                next(rd)
                names = [row[2] for row in rd]
            return cls(Interp(model_path=YAMNET_MODEL, num_threads=2), names)
        except Exception as e:
            log.warning(f"[YAMNET] не удалось загрузить: {type(e).__name__}: {e}")
            return None

    def run_block(self, tail, block):
        """block: n*FR отсчётов. Возвращает (n, число_групп): оценка для окна, заканчивающегося в конце кадра j."""
        n = len(block) // FR
        data = np.concatenate([tail, block]) if len(tail) else block
        g = np.zeros((n, len(self.group_idx)), np.float32)
        for j in range(n):
            chunk = data[j * FR: j * FR + self.win]
            if len(chunk) < self.win:
                chunk = np.pad(chunk, (0, self.win - len(chunk)))
            self.it.set_tensor(self.inp_idx, chunk.astype(np.float32).reshape(self.inp_shape))
            self.it.invoke()
            vec = np.asarray(self.it.get_tensor(self.out_idx)).reshape(-1, 521).max(axis=0)
            for gi, idx in enumerate(self.group_idx):
                if idx.size:
                    g[j, gi] = vec[idx].max()
        new_tail = data[-self.tail_len:] if self.tail_len else np.zeros(0, np.float32)
        return g, new_tail


# ---------------------------------------------------------------- признаки кадров
def _f0_track(fr):
    """Грубая высота основного тона (Гц) по 4 окнам на кадр; NaN, если голоса нет."""
    n = fr.shape[0]
    offs = (500, 2500, 4500, 6500)
    w = np.stack([fr[:, o:o + 1024] for o in offs], axis=1).reshape(-1, 1024)
    w = w - w.mean(axis=1, keepdims=True)
    level = np.sqrt((w ** 2).mean(axis=1))
    spec = np.fft.rfft(w, 2048, axis=1)
    ac = np.fft.irfft(spec * np.conj(spec), axis=1)[:, :1024]
    lo, hi = SR // 400, SR // 75
    seg = ac[:, lo:hi]
    k = seg.argmax(axis=1)
    peak = seg[np.arange(len(seg)), k] / (ac[:, 0] + 1e-9)
    f0 = SR / (k + lo)
    ok = (peak > 0.35) & (level > 0.01)
    f0 = np.where(ok, f0, np.nan).reshape(n, 4)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(f0, axis=1)


def _block_features(x):
    n = len(x) // FR
    fr = x[: n * FR].reshape(n, FR)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    sub = fr.reshape(n, FR // SUB, SUB)
    db = 10 * np.log10((sub ** 2).mean(axis=2) + 1e-10)
    jump = np.diff(db, axis=1)
    ons = ((jump > 9.0) & (db[:, 1:] > -45.0)).sum(axis=1).astype(np.float32)
    spec = np.abs(np.fft.rfft(fr, axis=1))
    freqs = np.fft.rfftfreq(FR, 1.0 / SR)
    cen = ((spec * freqs).sum(axis=1) / (spec.sum(axis=1) + 1e-9)).astype(np.float32)
    return rms.astype(np.float32), ons, cen, _f0_track(fr).astype(np.float32)


def _extract(path, yam):
    rms_l, ons_l, cen_l, f0_l, g_l = [], [], [], [], []
    tail = np.zeros(yam.tail_len if yam else 0, np.float32)
    with wave.open(path, "rb") as wf:
        if wf.getframerate() != SR or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError("ожидается WAV 16 кГц, моно, 16 бит")
        dur = wf.getnframes() / float(SR)
        while True:
            raw = wf.readframes(FR * BLOCK_FRAMES)
            if not raw:
                break
            a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            pad = (-len(a)) % FR
            if pad:
                a = np.concatenate([a, np.zeros(pad, np.float32)])
            r, o, c, f = _block_features(a)
            rms_l.append(r); ons_l.append(o); cen_l.append(c); f0_l.append(f)
            if yam:
                g, tail = yam.run_block(tail, a)
                g_l.append(g)
    if not rms_l:
        return None
    feats = dict(rms=np.concatenate(rms_l), ons=np.concatenate(ons_l),
                 cen=np.concatenate(cen_l), f0=np.concatenate(f0_l))
    g = None
    if yam and g_l:
        g = np.concatenate(g_l)
        g = np.maximum(g, np.vstack([g[1:], np.zeros((1, g.shape[1]), np.float32)]))  # окно покрывает 2 кадра
    return dur, feats, g


# ---------------------------------------------------------------- кривые интереса по типам
def _curves(feats, g):
    rms = feats["rms"]
    db = 20 * np.log10(rms + 1e-6)
    loud = rms > 0.003
    z_rms = _rz(db, 3.0)
    z_ons = _rz(feats["ons"], 1.5)
    z_cen = _rz(feats["cen"], 300.0) * loud
    f0 = feats["f0"]
    voiced = ~np.isnan(f0)
    z_f0 = np.zeros_like(rms)
    if voiced.sum() >= 8:
        z_f0[voiced] = _rz(f0[voiced], 15.0)

    excite = np.clip(0.55 * z_rms + 0.30 * z_f0 + 0.15 * z_cen, 0, None)
    fight_dsp = _nz(z_ons, 1.5, 5.0) * _nz(z_rms, 0.0, 2.0)
    hype = _nz(excite, 1.0, 4.0)
    shock = _nz(excite, 2.5, 5.0) * 0.7

    n = len(rms)
    zero = np.zeros(n, np.float32)
    if g is not None:
        gun, boom, laugh, scream, cheer = (g[:, i] for i in range(5))
        fight = np.maximum.reduce([fight_dsp * 0.8, _nz(gun, 0.03, 0.35), _nz(boom, 0.05, 0.5) * 0.7])
        funny = _nz(laugh, 0.05, 0.4)
        shock = np.maximum(_nz(scream, 0.05, 0.4), shock)
        win = _nz(cheer, 0.05, 0.4)
        hype = hype * 0.8
    else:
        fight, funny, win = fight_dsp, zero, zero

    raw = dict(fight=fight, funny=funny, shock=shock, win=win, absurd=zero, hype=hype)
    return {k: _smooth(v.astype(np.float32)) for k, v in raw.items()}


# ---------------------------------------------------------------- выбор моментов
def _pick(S, dur, count):
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
        start = max(0.0, a * FRAME_SEC - PAD_BEFORE)
        end = min(dur, (b + 1) * FRAME_SEC + PAD_AFTER)
        if end - start < MIN_CLIP:
            c = (a + b + 1) * FRAME_SEC / 2
            start = max(0.0, c - MIN_CLIP / 2)
            end = min(dur, start + MIN_CLIP)
            start = max(0.0, end - MIN_CLIP)
        if end - start > MAX_CLIP:
            start = max(0.0, i * FRAME_SEC - 0.4 * MAX_CLIP)
            end = min(dur, start + MAX_CLIP)
        lo = max(0, int(start / FRAME_SEC) - 4)
        hi = min(n, int(end / FRAME_SEC) + 5)
        S[lo:hi] = -1.0
        out.append({"start": round(start, 2), "end": round(end, 2), "peak": peak})
    return out


def _read_segment(path, start, end):
    with wave.open(path, "rb") as wf:
        wf.setpos(int(start * SR))
        raw = wf.readframes(int((end - start) * SR))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _apply_text(cats, text, seg_sec):
    """Подмешивает слова из расшифровки к оценкам типов."""
    cats = dict(cats)
    for kind, rx in _LEX_RE.items():
        hits = len(rx.findall(text))
        if hits:
            cats[kind] = min(1.0, cats[kind] + 0.5 * min(hits, 3) / 3)
    words = len(text.split())
    if seg_sec > 0 and words / seg_sec > 3.2:        # быстрая речь — эмоции
        cats["hype"] = min(1.0, cats["hype"] + 0.15)
    return cats


def _label(cats):
    ranked = sorted(((KINDS[k][2] * cats[k], k) for k in KINDS), reverse=True)
    top_v, top_k = ranked[0]
    if top_v < 0.08:
        return "hype", ["hype"], "🔊", "Громкий момент 🔊"
    tags, emoji = [top_k], KINDS[top_k][1]
    for v, k in ranked[1:]:
        if len(tags) < 2 and v >= 0.6 * top_v and v >= 0.2:
            tags.append(k)
            emoji += KINDS[k][1]
    return top_k, tags, emoji, f"{KINDS[top_k][0]} {emoji}"


# ---------------------------------------------------------------- главная функция
def analyze_audio(wav_path, max_moments=5, asr=None):
    """wav_path: WAV 16 кГц моно. asr(audio_float32) -> str (необязательно).
    Возвращает {"duration": сек, "moments": [...]} — формат совместим со старым scan_audio_wav."""
    yam = _Yamnet.load()
    res = _extract(wav_path, yam)
    if res is None:
        return {"duration": 0.0, "moments": []}
    dur, feats, g = res
    n = len(feats["rms"])
    if n < 20:
        return {"duration": dur, "moments": []}

    curves = _curves(feats, g)
    S = _combine(curves)
    use_asr = asr is not None and USE_ASR
    cands = _pick(S, dur, max_moments + 3 if use_asr else max_moments)
    mean_rms = float(feats["rms"].mean()) + 1e-9

    for c in cands:
        a, b = int(c["start"] / FRAME_SEC), min(n, int(c["end"] / FRAME_SEC) + 1)
        c["cats"] = {k: float(curves[k][a:b].max()) for k in KINDS}
        c["energy"] = round(float(feats["rms"][a:b].mean() / mean_rms), 2)
        c["text"] = ""
        if use_asr:
            try:
                seg_end = min(c["end"], c["start"] + 45.0)
                audio = _read_segment(wav_path, c["start"], seg_end)
                c["text"] = (asr(audio) or "").strip().lower()
                c["cats"] = _apply_text(c["cats"], c["text"], seg_end - c["start"])
            except Exception as e:
                log.warning(f"[HIGHLIGHTS] ASR не сработал: {type(e).__name__}: {e}")
        c["score"] = float(_combine(c["cats"]))

    cands.sort(key=lambda c: c["score"], reverse=True)
    cands = cands[:max_moments]
    cands.sort(key=lambda c: c["start"])

    moments = []
    for c in cands:
        kind, tags, emoji, label = _label(c["cats"])
        m = {"start": c["start"], "end": c["end"], "energy": c["energy"],
             "score": round(c["score"], 2), "kind": kind, "tags": tags,
             "emoji": emoji, "label": label}
        if c["text"]:
            m["snippet"] = c["text"][:67] + "…" if len(c["text"]) > 70 else c["text"]
        moments.append(m)
        log.info(f"[HIGHLIGHTS] {c['start']:.0f}-{c['end']:.0f}s {label} score={c['score']:.2f} "
                 + " ".join(f"{k}={v:.2f}" for k, v in c["cats"].items()))
    return {"duration": dur, "moments": moments}
