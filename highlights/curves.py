# highlights/curves.py
"""Кривые интереса по типам моментов: fight, funny, shock, win, absurd, hype, talk.

Каждая кривая — массив float длины n (количество кадров).
talk — плотность непрерывной речи (есть f0): по ней ищутся «разговорники» —
длинные куски до 2 минут, где стример непрерывно что-то рассказывает.
"""
import numpy as np


def _rz(x, floor):
    """Робастный z-score: насколько значение выше «обычного» для этого видео."""
    x = np.asarray(x, dtype=np.float32)
    if x.size < 8:
        return np.zeros_like(x)
    med = float(np.median(x))
    mad = max(float(np.median(np.abs(x - med))) * 1.4826, floor)
    return np.clip((x - med) / mad, -3.0, 12.0).astype(np.float32)


def _nz(x, lo, hi):
    return np.clip((np.asarray(x, dtype=np.float32) - lo) / (hi - lo), 0.0, 1.0)


def _smooth(c, w_mean=16, w_max=17):
    """Плотность события за ~8 сек (среднее) + пик (максимум). Окна настраиваются:
    для talk — длиннее (32 кадра ≈ 16 с)."""
    k = np.ones(w_mean, np.float32) / w_mean
    mean = np.convolve(c, k, mode="same")[: len(c)]
    pad = w_max // 2
    mx = np.lib.stride_tricks.sliding_window_view(np.pad(c, pad), w_max).max(axis=1)
    return (0.6 * mean + 0.4 * mx).astype(np.float32)


def build_curves(feats, g):
    """Построить кривые интереса по типам.

    Возвращает dict: {"fight", "funny", "shock", "win", "absurd", "hype"}.
    """
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

    # разговорники: плотность речи — голос есть (f0 не NaN) и это не перестрелка
    voiced = (~np.isnan(f0)).astype(np.float32)
    talk = _smooth(voiced, 32, 33)
    if g is not None:
        talk = talk * (1.0 - 0.6 * _nz(np.maximum(gun, boom), 0.05, 0.5))

    raw = dict(fight=fight, funny=funny, shock=shock, win=win, absurd=zero, hype=hype,
               talk=talk)
    return {k: _smooth(v.astype(np.float32)) if k != "talk" else v
            for k, v in raw.items()}
