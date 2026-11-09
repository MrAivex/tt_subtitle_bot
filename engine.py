import os
import subprocess
import platform
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional
import wave
import numpy as np
from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from utils import timed

class VideoEngine:
    def __init__(self, device: str = "cpu"):
        self.device = device
        self._model: Optional[WhisperModel] = None
        
        if platform.system() == "Windows":
            self.ffmpeg = r"D:\Programingg\PO\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
            self.ffprobe = os.path.join(os.path.dirname(self.ffmpeg), "ffprobe.exe")
        else:
            self.ffmpeg = "ffmpeg"
            self.ffprobe = "ffprobe"

    @property
    def model(self) -> WhisperModel:
        if self._model is None:
            compute_type = "float16" if self.device == "cuda" else "int8"
            self._model = WhisperModel("small", device=self.device, compute_type=compute_type, cpu_threads=2)
        return self._model


    def warmup(self):
        """Прогоняет по одному короткому распознаванию, чтобы первый пользователь не ждал."""
        with timed("whisper: прогрев"):
            audio = (np.random.randn(16000 * 3) * 0.01).astype(np.float32)
            # Сначала без VAD: гонит сам энкодер/декодер. Потом с VAD: подгружает его модель.
            for use_vad in (False, True):
                segs, _ = self.model.transcribe(
                    audio, language="ru", beam_size=1,
                    word_timestamps=True, vad_filter=use_vad,
                )
                list(segs)   # генератор ленивый, без этого ничего не посчитается
                

    def _get_font_path(self) -> str:
        candidates = [
            Path(__file__).parent / "fonts" / "roboto-bold.ttf",
            Path(__file__).parent / "fonts" / "arial.ttf",
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf"),
        ]
        for path in candidates:
            if path.exists():
                return str(path)
        return "arial.ttf"

    def get_video_duration(self, video_path: str) -> float:
        cmd = [self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video_path]
        out = subprocess.check_output(cmd, text=True).strip()
        return float(out)

    def get_video_resolution(self, video_path: str) -> tuple:
        cmd = [self.ffprobe, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path]
        out = subprocess.check_output(cmd, text=True).strip()
        w, h = map(int, out.split(","))
        return w, h

    def _measure_text(self, font: ImageFont.FreeTypeFont, text: str):
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _create_text_image(self, text: str, font: ImageFont.FreeTypeFont, text_color: tuple,
                           bg_color: tuple = None, radius: int = 0, padding: int = 4,
                           min_height: int = None, stroke_width: int = 0, stroke_fill: tuple = None) -> Image.Image:
        temp_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        temp_draw = ImageDraw.Draw(temp_img)
        bbox = temp_draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        img_w = text_w + padding * 2
        img_h = max(text_h, min_height) + padding * 2 if min_height else text_h + padding * 2
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        if bg_color is not None:
            draw.rounded_rectangle([(0, 0), (img_w - 1, img_h - 1)], radius=radius, fill=bg_color)
        y_text = (img_h - text_h) // 2 - bbox[1]
        draw.text((padding, y_text), text, font=font, fill=text_color, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return img

    def _create_rounded_rect(self, width: int, height: int, radius: int, color: tuple) -> Image.Image:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([(0, 0), (width - 1, height - 1)], radius=radius, fill=color)
        return img

    # ==========================================================
    # ЭТАП 1: СКАНИРОВАНИЕ ХАЙЛАЙТОВ
    # ==========================================================
    def scan_highlights(self, video_path: str, max_moments: int = 5) -> Dict:
        v_path = Path(video_path).resolve()
        audio_tmp = v_path.parent / f"{v_path.stem}_scan.wav"
        
        try:
            subprocess.run([self.ffmpeg, "-y", "-i", str(v_path), "-ar", "16000", "-ac", "1", str(audio_tmp)],
                           check=True, capture_output=True, text=True)
            moments = self._find_energy_peaks(str(audio_tmp))
            duration = self.get_video_duration(str(v_path))
            clips = self._select_moments(moments, duration, count=max_moments)
            return {"duration": duration, "moments": clips}
        finally:
            if audio_tmp.exists():
                audio_tmp.unlink()

    def _find_energy_peaks(self, audio_path: str, frame_sec: float = 0.5, threshold_percentile: float = 90,
                           min_peak_sec: float = 2.0, merge_gap_sec: float = 3.0) -> List[Dict]:
        with wave.open(audio_path, "rb") as wf:
            sr = wf.getframerate()
            frame_len = int(sr * frame_sec)
            block_frames = sr * 600
            rms_list = []
            leftover = np.empty(0, dtype=np.float32)

            while True:
                raw = wf.readframes(block_frames)
                if not raw: break
                a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                if leftover.size: a = np.concatenate([leftover, a])
                n = len(a) // frame_len
                if n:
                    fr = a[:n * frame_len].reshape(n, frame_len)
                    rms_list.append(np.sqrt(np.einsum('ij,ij->i', fr, fr) / frame_len))
                    leftover = a[n * frame_len:]
                else:
                    leftover = a

        if not rms_list: return []
        rms = np.concatenate(rms_list)
        thr = max(float(np.percentile(rms, threshold_percentile)), 0.02)

        above = rms > thr
        raw_peaks, start = [], None
        for i, a in enumerate(above):
            if a and start is None: start = i
            elif not a and start is not None:
                raw_peaks.append((start, i))
                start = None
        if start is not None: raw_peaks.append((start, len(above)))

        merged = []
        for s, e in raw_peaks:
            if merged and (s - merged[-1][1]) * frame_sec <= merge_gap_sec:
                merged[-1][1] = e
            else:
                merged.append([s, e])

        moments = []
        avg = float(rms.mean()) + 1e-9
        for s, e in merged:
            dur = (e - s) * frame_sec
            if dur >= min_peak_sec:
                moments.append({
                    "start": round(s * frame_sec, 2), "end": round(e * frame_sec, 2),
                    "duration": round(dur, 2), "energy": round(float(rms[s:e].mean() / avg), 2),
                })
        moments.sort(key=lambda m: m["energy"], reverse=True)
        return moments

    def _select_moments(self, moments: List[Dict], video_duration: float, count: int = 5,
                        pad_before: float = 3.0, pad_after: float = 4.0, min_clip_sec: float = 10.0, max_clip_sec: float = 60.0) -> List[Dict]:
        result = []
        for m in moments:
            start = max(0.0, m["start"] - pad_before)
            end = min(video_duration, m["end"] + pad_after)
            if end - start < min_clip_sec:
                center = (m["start"] + m["end"]) / 2
                start = max(0.0, center - min_clip_sec / 2)
                end = min(video_duration, start + min_clip_sec)
            if end - start > max_clip_sec: end = start + max_clip_sec
            if any(not (end <= r["start"] or start >= r["end"]) for r in result): continue
            result.append({"start": round(start, 2), "end": round(end, 2), "energy": m["energy"]})
            if len(result) >= count: break
        result.sort(key=lambda r: r["start"])
        return result

    def cut_clip(self, video_path: str, start: float, end: float, out_path: str):
        subprocess.run([self.ffmpeg, "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", video_path,
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", out_path],
                       check=True, capture_output=True, text=True)


    def crop_to_vertical(self, video_path: str, out_path: str):
        """Центральная обрезка в 9:16 (без растягивания и чёрных полос)."""
        w, h = self.get_video_resolution(video_path)
        target = 9 / 16

        if w / h > target:
            # Широкое видео: режем по бокам
            crop_w = int(h * target) // 2 * 2
            crop_h = h // 2 * 2
        else:
            # Уже вертикальное или уже уже 9:16: режем сверху и снизу
            crop_w = w // 2 * 2
            crop_h = int(w / target) // 2 * 2

        x = (w - crop_w) // 2
        y = (h - crop_h) // 2

        subprocess.run([self.ffmpeg, "-y", "-i", video_path,
                        "-vf", f"crop={crop_w}:{crop_h}:{x}:{y}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-c:a", "copy", out_path],
                       check=True, capture_output=True, text=True)
        


    @staticmethod
    def _vertical_crop_box(w: int, h: int):
        target = 9 / 16
        if w / h > target:
            cw, ch = int(h * target) // 2 * 2, h // 2 * 2
        else:
            cw, ch = w // 2 * 2, int(w / target) // 2 * 2
        return cw, ch, (w - cw) // 2, (h - ch) // 2


    # ---------- ASS-хелперы ----------
    @staticmethod
    def _calc_font_size(video_w: int, video_h: int) -> int:
        """Размер шрифта от размера кадра: вертикальное — от ширины, горизонтальное — от высоты."""
        fs = round(video_w * 0.06) if video_h > video_w else round(video_h * 0.05)
        return max(fs, 18)

    @staticmethod
    def _ass_time(t: float) -> str:
        cs = int(round(max(0.0, t) * 100))
        h, cs = divmod(cs, 360000)
        m, cs = divmod(cs, 6000)
        s, cs = divmod(cs, 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    def _ass_escape(text: str) -> str:
        """Убираем символы, которые ASS считает управляющими."""
        return text.replace("\\", "").replace("{", "(").replace("}", ")")

    @staticmethod
    def _ff_escape(path: str) -> str:
        """Экранирование пути для фильтра ffmpeg (важно для Windows: C:\\...)."""
        return path.replace("\\", "/").replace(":", r"\:")

    def _build_ass(self, lines: List[Dict], video_w: int, video_h: int, video_duration: float,
                   show_watermark: bool, font_family: str, bold: bool) -> str:
        fs = self._calc_font_size(video_w, video_h)
        stroke = max(2, round(fs / 18))              # обводка текста
        pad = max(4, round(fs * 0.16))               # «поля» плашки вокруг слова
        margin_v = max(40, round(video_h * 0.07))    # отступ снизу
        wm_fs = max(14, round(fs * 0.78))
        b = -1 if bold else 0

        out = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {video_w}",
            f"PlayResY: {video_h}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            # Подложка: заливка текста прозрачна, «обводка» = фиолетовая плашка (BorderStyle=3)
            f"Style: Box,{font_family},{fs},&HFFFFFFFF,&HFFFFFFFF,&H00DD4E9D,&H00000000,"
            f"{b},0,0,0,100,100,0,0,3,{pad},0,2,10,10,{margin_v},1",
            # Текст: белый с чёрной обводкой
            f"Style: Text,{font_family},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
            f"{b},0,0,0,100,100,0,0,1,{stroke},0,2,10,10,{margin_v},1",
            # Водяной знак: слева внизу, ~60% непрозрачности
            f"Style: Mark,{font_family},{wm_fs},&H66FFFFFF,&H66FFFFFF,&H66000000,&H00000000,"
            f"{b},0,0,0,100,100,0,0,1,{stroke},0,1,20,20,20,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        for line in lines:
            ws = line["words"]
            words = [self._ass_escape(w["word"]) for w in ws]
            n = len(ws)

            # Текст строки — один раз на всё время строки
            out.append(
                f"Dialogue: 1,{self._ass_time(line['start'])},{self._ass_time(line['end'])},"
                f"Text,,0,0,0,,{' '.join(words)}"
            )

            # Плашка — по одному событию на слово
            for i, w in enumerate(ws):
                nxt = ws[i + 1]["start"] if i + 1 < n else None
                hl_end = w["end"] if nxt is None else min(nxt, max(w["end"] + 0.3, w["start"] + 0.05))
                if hl_end - w["start"] < 0.01:
                    continue
                parts = [f"{{\\3a&H{'00' if j == i else 'FF'}&}}{wd}" for j, wd in enumerate(words)]
                box_text = "{\\3a&HFF&} ".join(parts)
                out.append(
                    f"Dialogue: 0,{self._ass_time(w['start'])},{self._ass_time(hl_end)},"
                    f"Box,,0,0,0,,{box_text}"
                )

        if show_watermark:
            out.append(
                f"Dialogue: 2,{self._ass_time(0)},{self._ass_time(video_duration + 1)},"
                f"Mark,,0,0,0,,@tt_subtitle_bot"
            )

        return "\n".join(out) + "\n"




    # ==========================================================
    # ЭТАП 2: ПОЛНАЯ ОБРАБОТКА С СУБТИТРАМИ
    # ==========================================================
    def process_video(self, input_path: str, user_id: str, is_premium: bool = False,
                      webcam_box: Optional[Dict] = None, vertical: bool = False) -> Dict:
        v_path = Path(input_path).resolve()
        video_dir = v_path.parent
        base_name = v_path.stem

        audio_file = video_dir / f"{base_name}.wav"
        srt_file = video_dir / f"{base_name}.srt"
        ass_file = video_dir / f"{base_name}.ass"
        output_file = video_dir / f"{base_name}_subtitled.mp4"

        try:
            with timed("clip: ffmpeg → wav"):
                subprocess.run([self.ffmpeg, "-y", "-i", str(v_path), "-ar", "16000", "-ac", "1", str(audio_file)],
                               check=True, capture_output=True, text=True)

            with timed("whisper: загрузка модели"):
                model = self.model

            with timed("whisper: распознавание"):
                segments, _ = model.transcribe(
                    str(audio_file), language="ru", word_timestamps=True,
                    beam_size=1, vad_filter=True, condition_on_previous_text=False,
                )
                seg_list = list(segments)   # транскрибация идёт именно здесь, генератор ленивый

            srt_text = ""
            for i, seg in enumerate(seg_list, 1):
                start = str(timedelta(seconds=seg.start))[:-3].replace(".", ",")
                end = str(timedelta(seconds=seg.end))[:-3].replace(".", ",")
                srt_text += f"{i}\n{start} --> {end}\n{seg.text.strip()}\n\n"
            srt_file.write_text(srt_text, encoding="utf-8")

            all_words = [{"word": w.word.strip(), "start": w.start, "end": w.end}
                         for seg in seg_list if seg.words for w in seg.words]
            if not all_words:
                if vertical:
                    self.crop_to_vertical(str(v_path), str(output_file))
                else:
                    subprocess.run([self.ffmpeg, "-y", "-i", str(v_path), "-c", "copy", str(output_file)],
                                   check=True, capture_output=True, text=True)
                return {"video_path": str(output_file), "srt_path": str(srt_file)}

            video_w, video_h = self.get_video_resolution(str(v_path))
            crop_vf = ""
            if vertical:
                cw, ch, cx, cy = self._vertical_crop_box(video_w, video_h)
                crop_vf = f"crop={cw}:{ch}:{cx}:{cy},"
                video_w, video_h = cw, ch   # ASS и шрифт считаются от кадра ПОСЛЕ обрезки
            video_duration = self.get_video_duration(str(v_path))

            # Шрифт и его размер от размера кадра
            font_path = self._get_font_path()
            fs = self._calc_font_size(video_w, video_h)
            measure_font = ImageFont.truetype(font_path, fs)
            font_family, font_style = measure_font.getname()
            bold = "bold" in (font_style or "").lower()

            # Разбивка на строки по реальной ширине (мерим уже в нижнем регистре)
            max_line_width = video_w * 0.88
            space_w = measure_font.getlength(" ")
            lines, cur, cur_w = [], [], 0.0
            for w in all_words:
                word = w["word"].lower()
                if not word:
                    continue
                ww = measure_font.getlength(word)
                gap = space_w if cur else 0.0
                if cur and cur_w + gap + ww > max_line_width:
                    lines.append({"start": cur[0]["start"], "end": cur[-1]["end"], "words": cur})
                    cur, cur_w, gap = [], 0.0, 0.0
                cur.append({"word": word, "start": w["start"], "end": w["end"]})
                cur_w += gap + ww
            if cur:
                lines.append({"start": cur[0]["start"], "end": cur[-1]["end"], "words": cur})

            ass_text = self._build_ass(lines, video_w, video_h, video_duration,
                                       show_watermark=not is_premium,
                                       font_family=font_family, bold=bold)
            ass_file.write_text(ass_text, encoding="utf-8")

            # ass лежит рядом с видео, ffmpeg запускаем из этой папки — путь в фильтре короткий
            fonts_dir = str(Path(font_path).parent)
            vf = (f"{crop_vf}subtitles=filename='{self._ff_escape(ass_file.name)}'"
                  f":fontsdir='{self._ff_escape(fonts_dir)}'")

            cmd = [self.ffmpeg, "-y", "-i", str(v_path),
                   "-vf", vf,
                   "-map", "0:v", "-map", "0:a?",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                   "-c:a", "copy",
                   str(output_file)]
            with timed("clip: рендер ffmpeg"):
                subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=str(video_dir))
            return {"video_path": str(output_file), "srt_path": str(srt_file)}

        finally:
            if ass_file.exists():
                ass_file.unlink()
            if audio_file.exists():
                audio_file.unlink()


    def scan_audio_wav(self, wav_path: str, max_moments: int = 5) -> Dict:
        """Сканирует готовый WAV (16 kHz mono): длительность + моменты."""
        with wave.open(wav_path, "rb") as wf:
            duration = wf.getnframes() / float(wf.getframerate())
        moments = self._find_energy_peaks(wav_path)
        clips = self._select_moments(moments, duration, count=max_moments)
        return {"duration": duration, "moments": clips}