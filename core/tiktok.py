# core/tiktok.py
"""Раскладка «как в TikTok»: вебка стримера сверху, сам стрим снизу — всё в 1080x1920.

Вебка на видео ищется автоматически: берём один кадр (~15% длины клипа), находим
лицо детектором OpenCV (Haar-каскад) и вырезаем вокруг него квадрат — это и есть
зона веб-камеры. Если OpenCV не установлен или лица нет — считаем, что вебки
нет: видео просто центрально обрезается в 9:16 (см. FFmpeg.compose_tiktok).

OpenCV не является обязательной зависимостью: без него бот продолжает работать,
формат TikTok деградирует до обычной обрезки 9:16.
"""
import subprocess


def detect_webcam_box(ffmpeg_bin, path, src_w: int, src_h: int, at_sec: float,
                      thumb_w: int = 640):
    """(x, y, side, side) квадрата веб-камеры в пикселях исходника, или None.

    Кадр берётся на at_sec, уменьшается до thumb_w и ищется самое крупное лицо.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("[TIKTOK] opencv не установлен (pip install opencv-python-headless) — "
              "вебку не ищу, будет кроп 9:16", flush=True)
        return None
    try:
        thumb_h = max(2, round(src_h * thumb_w / src_w))
        p = subprocess.run(
            [ffmpeg_bin, "-y", "-nostats", "-loglevel", "error",
             "-ss", f"{max(0.0, at_sec):.2f}", "-i", str(path),
             "-frames:v", "1", "-vf", f"scale={thumb_w}:{thumb_h}",
             "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            capture_output=True, timeout=90)
        data = p.stdout
        if p.returncode or len(data) < thumb_w * thumb_h:
            return None
        gray = np.frombuffer(data[:thumb_w * thumb_h], np.uint8).reshape(thumb_h, thumb_w)

        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=6,
            minSize=(max(24, thumb_w // 16), max(24, thumb_w // 16)))
        if faces is None or len(faces) == 0:
            return None
        x, y, fw, fh = max(faces, key=lambda f: int(f[2]) * int(f[3]))  # самое крупное лицо

        # квадрат с запасом вокруг лица (лицо занимает ~половину кадра веб-камеры)
        kx, ky = src_w / thumb_w, src_h / thumb_h
        cx, cy = (x + fw / 2) * kx, (y + fh / 2) * ky
        side = max(fw, fh) * 1.9 * kx
        bx = max(0, round(cx - side / 2))
        by = max(0, round(cy - side / 2))
        side = int(min(side, src_w - bx, src_h - by)) // 2 * 2
        bx, by = bx // 2 * 2, by // 2 * 2          # чётные размеры — требование libx264
        if side < 64:
            return None
        return bx, by, side, side
    except Exception as e:
        print(f"[TIKTOK] поиск веб-камеры не удался ({type(e).__name__}: {e})", flush=True)
        return None


def tiktok_filters(box) -> str:
    """filter_complex для ffmpeg: на выходе 1080x1920 [v].

    С вебкой: верхняя половина — вебка (crop квадрата, cover), нижняя — весь кадр
    (cover, получается «немного увеличенным»). Без вебки: центральный кроп 9:16.
    """
    if not box:
        # вебки нет — просто обрезаем видео в 9:16, как просили
        return ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1[v]")
    bx, by, bw, bh = box
    cam = (f"crop={bw}:{bh}:{bx}:{by},"
           "scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1,"
           "pad=1080:1920:0:0:color=black")
    stream = ("scale=1080:960:force_original_aspect_ratio=increase,"
              "crop=1080:960,setsar=1")
    return (f"[0:v]{cam}[cam];[0:v]{stream}[str];"
            "[cam][str]overlay=0:960[v]")
