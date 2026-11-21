# highlights/extractor.py
"""Извлечение фич из аудиодорожки: RMS, onset, спектральный центроид, f0, YAMNet."""
import logging
import os
import warnings
from typing import Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

SR = 16000
FRAME_SEC = 0.5
FR = int(SR * FRAME_SEC)          # 8000 отсчётов в кадре
SUB = 160                         # 10 мс — для поиска резких всплесков
BLOCK_FRAMES = 600                # читаем по 5 минут, чтобы не держать весь стрим в памяти

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAMNET_MODEL = os.getenv("YAMNET_MODEL", os.path.join(BASE_DIR, "models", "yamnet.tflite"))
YAMNET_CLASSES = os.getenv("YAMNET_CLASSES", os.path.join(BASE_DIR, "models", "yamnet_class_map.csv"))


def _get_interpreter_cls():
    """Попробовать ai-edge-litert → tflite_runtime → tensorflow."""
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


class Yamnet:
    """Обёртка над TFLite-моделью YAMNet для распознавания звуковых событий."""

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
    def load(cls) -> Optional["Yamnet"]:
        if not (os.path.exists(YAMNET_MODEL) and os.path.exists(YAMNET_CLASSES)):
            log.info(f"[YAMNET] модель не найдена ({YAMNET_MODEL}) — работаем без неё")
            return None
        Interp = _get_interpreter_cls()
        if Interp is None:
            log.warning("[YAMNET] нет ai-edge-litert / tflite-runtime — работаем без YAMNet")
            return None
        try:
            import csv
            with open(YAMNET_CLASSES, encoding="utf-8") as f:
                rd = csv.reader(f)
                next(rd)
                names = [row[2] for row in rd]
            return cls(Interp(model_path=YAMNET_MODEL,
                              num_threads=int(os.getenv("YAMNET_THREADS", "4"))), names)
        except Exception as e:
            log.warning(f"[YAMNET] не удалось загрузить: {type(e).__name__}: {e}")
            return None

    def run_block(self, tail, block) -> Tuple[np.ndarray, np.ndarray]:
        """block: n*FR отсчётов. Возвращает (n, число_групп) и новый tail."""
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


# ---------------------------------------------------------------- фичи кадров

def _f0_track(fr: np.ndarray) -> np.ndarray:
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


def _block_features(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """RMS, onset-счётчик, спектральный центроид, f0 для блока отсчётов."""
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


# ---------------------------------------------------------------- главная функция извлечения

def extract(wav_path: str, yam: Optional[Yamnet] = None):
    import wave
    with wave.open(wav_path, "rb") as wf:
        if wf.getframerate() != SR or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError("ожидается WAV 16 кГц, моно, 16 бит")
        return extract_stream(lambda n: wf.readframes(n // 2), yam)



def extract_stream(read, yam: Optional[Yamnet] = None):
    """read(n_bytes) -> bytes (s16le, 16 кГц, моно); пустые байты = конец."""
    rms_l, ons_l, cen_l, f0_l, g_l = [], [], [], [], []
    tail = np.zeros(yam.tail_len if yam else 0, np.float32)
    total = 0
    while True:
        raw = read(FR * BLOCK_FRAMES * 2)
        raw = raw[: len(raw) // 2 * 2]
        if not raw:
            break
        total += len(raw) // 2
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
    dur = total / float(SR)
    feats = dict(rms=np.concatenate(rms_l), ons=np.concatenate(ons_l),
                 cen=np.concatenate(cen_l), f0=np.concatenate(f0_l))
    g = None
    if yam and g_l:
        g = np.concatenate(g_l)
        g = np.maximum(g, np.vstack([g[1:], np.zeros((1, g.shape[1]), np.float32)]))
    return dur, feats, g
