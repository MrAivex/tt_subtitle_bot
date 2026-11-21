# core/ffmpeg_tools.py
"""Единственное место, где вызывается ffmpeg/ffprobe.

Путь к бинарникам берётся из FFMPEG_BIN / FFPROBE_BIN (.env). Если не заданы — из PATH.
"""
import os
import subprocess
from pathlib import Path


class FFmpeg:
    def __init__(self, ffmpeg=None, ffprobe=None):
        self.ffmpeg = ffmpeg or os.getenv("FFMPEG_BIN", "ffmpeg")
        self.ffprobe = ffprobe or os.getenv("FFPROBE_BIN", "ffprobe")

    def _run(self, args: list, **kw):
        p = subprocess.run([self.ffmpeg, "-y", *args], capture_output=True, text=True, **kw)
        if p.returncode:
            raise RuntimeError(f"ffmpeg: {p.stderr[-300:]}")
        return p

    # ---------- информация о файле ----------
    def duration(self, path) -> float:
        out = subprocess.check_output(
            [self.ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], text=True).strip()
        return float(out)

    def resolution(self, path) -> tuple:
        out = subprocess.check_output(
            [self.ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
            text=True).strip()
        w, h = map(int, out.split(","))
        return w, h

    @staticmethod
    def vertical_crop_box(w: int, h: int) -> tuple:
        """(ширина, высота, x, y) центральной вырезки 9:16. Размеры чётные — требование libx264."""
        target = 9 / 16
        if w / h > target:                       # широкое видео: режем по бокам
            cw, ch = int(h * target) // 2 * 2, h // 2 * 2
        else:                                    # уже вертикальное: режем сверху и снизу
            cw, ch = w // 2 * 2, int(w / target) // 2 * 2
        return cw, ch, (w - cw) // 2, (h - ch) // 2

    @staticmethod
    def filter_escape(path: str) -> str:
        """Экранирование пути для фильтра ffmpeg (важно для Windows: C:\\...)."""
        return str(path).replace("\\", "/").replace(":", r"\:")

    # ---------- операции ----------
    def extract_wav(self, src, dst):
        """Звук в WAV 16 кГц моно — формат, который ждут анализатор и Whisper."""
        self._run(["-i", str(src), "-vn", "-ar", "16000", "-ac", "1", str(dst)])

    def cut_clip(self, src, start, end, dst):
        """Нарезка клипа в полном качестве."""
        self._run(["-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(src),
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2",
                   "-c:a", "aac", "-b:a", "128k", str(dst)])

    def make_preview(self, src, start, end, dst, max_height=360):
        """Лёгкое превью (360p, со звуком) для плеера."""
        try:
            w, h = self.resolution(src)
            vf = f"scale=-2:{max_height}" if w >= h else f"scale={max_height}:-2"
        except Exception:
            vf = f"scale=-2:{max_height}"
        self._run(["-ss", f"{max(0.0, start):.2f}", "-i", str(src),
                   "-t", f"{max(1.0, end - start):.2f}",
                   "-vf", vf,
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                   "-c:a", "aac", "-b:a", "64k",
                   "-threads", "2", "-movflags", "+faststart", str(dst)])
        return dst

    def faststart(self, path):
        """moov в начало файла — браузер сможет мотать превью, не скачав его целиком."""
        tmp = str(path) + ".fs.mp4"
        try:
            self._run(["-i", str(path), "-c", "copy", "-movflags", "+faststart", tmp])
        except RuntimeError:
            if os.path.exists(tmp):
                os.remove(tmp)
            return path            # не получилось — оставляем файл как есть
        os.replace(tmp, path)
        return path

    def copy(self, src, dst):
        """Копия без перекодирования."""
        self._run(["-i", str(src), "-c", "copy", str(dst)])

    def crop_vertical(self, src, dst):
        """Центральная обрезка в 9:16 (без растягивания и чёрных полос)."""
        w, h = self.resolution(src)
        cw, ch, x, y = self.vertical_crop_box(w, h)
        self._run(["-i", str(src), "-vf", f"crop={cw}:{ch}:{x}:{y}",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2",
                   "-c:a", "copy", str(dst)])

    def burn_ass(self, src, ass_path, fonts_dir, dst, crop_box=None):
        """Вжигает ASS-субтитры (и, если задан crop_box, сначала обрезает кадр)."""
        ass = Path(ass_path)
        crop = ""
        if crop_box:
            cw, ch, x, y = crop_box
            crop = f"crop={cw}:{ch}:{x}:{y},"
        vf = (f"{crop}subtitles=filename='{self.filter_escape(ass.name)}'"
              f":fontsdir='{self.filter_escape(fonts_dir)}'")
        # запускаем из папки с .ass — путь в фильтре короткий; src и dst должны быть абсолютными
        self._run(["-i", str(src), "-vf", vf,
                   "-map", "0:v", "-map", "0:a?",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2",
                   "-c:a", "copy", str(dst)], cwd=str(ass.parent))


    def extract_wav_speech(self, src, dst):
        """Звук для распознавания: срезаем гул и выравниваем громкость речи."""
        self._run(["-i", str(src), "-vn", "-ar", "16000", "-ac", "1",
                   "-af", "highpass=f=80,dynaudnorm=f=150:g=15",
                   str(dst)])


    def start_audio_tee(self, src, wav_dst, err_file):
        """Один проход декодирования: WAV на диск (для Whisper) + сырой PCM в stdout (для анализа)."""
        return subprocess.Popen(
            [self.ffmpeg, "-y", "-nostats", "-loglevel", "error", "-i", str(src),
            "-map", "0:a:0", "-ar", "16000", "-ac", "1", "-f", "wav", str(wav_dst),
            "-map", "0:a:0", "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1"],
            stdout=subprocess.PIPE, stderr=err_file, bufsize=1 << 20)
