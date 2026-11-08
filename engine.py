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
            self._model = WhisperModel("small", device=self.device, compute_type=compute_type)
        return self._model

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

    # ==========================================================
    # ЭТАП 2: ПОЛНАЯ ОБРАБОТКА С СУБТИТРАМИ
    # ==========================================================
    def process_video(self, input_path: str, user_id: str, is_premium: bool = False, 
                  webcam_box: Optional[Dict] = None) -> Dict:
        v_path = Path(input_path).resolve()
        video_dir = v_path.parent
        base_name = v_path.stem

        audio_file = video_dir / f"{base_name}.wav"
        srt_file = video_dir / f"{base_name}.srt"
        output_file = video_dir / f"{base_name}_subtitled.mp4"
        temp_img_dir = video_dir / "temp_sub_img"
        temp_img_dir.mkdir(exist_ok=True)

        try:
            subprocess.run([self.ffmpeg, "-y", "-i", str(v_path), "-ar", "16000", "-ac", "1", str(audio_file)],
                           check=True, capture_output=True, text=True)
            segments, _ = self.model.transcribe(
                str(audio_file), language="ru", word_timestamps=True,
                beam_size=1,                       # 1 луч вместо 5 — намного быстрее
                vad_filter=True,                   # пропускает тишину
                condition_on_previous_text=False,  # меньше галлюцинаций
            )
            seg_list = list(segments)

            srt_text = ""
            for i, seg in enumerate(seg_list, 1):
                start = str(timedelta(seconds=seg.start))[:-3].replace(".", ",")
                end = str(timedelta(seconds=seg.end))[:-3].replace(".", ",")
                srt_text += f"{i}\n{start} --> {end}\n{seg.text.strip()}\n\n"
            srt_file.write_text(srt_text, encoding="utf-8")

            font_path = self._get_font_path()
            pillow_font = ImageFont.truetype(font_path, 36)
            white, black_stroke, purple_bg = (255, 255, 255, 255), (0, 0, 0, 255), (157, 78, 221, 240)
            radius, padding, line_height = 12, 6, 36 + 12

            all_words = [{"word": w.word.strip(), "start": w.start, "end": w.end} for seg in seg_list if seg.words for w in seg.words]
            if not all_words:
                subprocess.run([self.ffmpeg, "-y", "-i", str(v_path), "-c", "copy", str(output_file)], check=True, capture_output=True, text=True)
                return {"video_path": str(output_file), "srt_path": str(srt_file)}

            video_w, video_h = self.get_video_resolution(str(v_path))
            video_duration = self.get_video_duration(str(v_path))
            max_line_width = video_w - 40
            lines, cur_line, cur_width = [], [], 0
            space_w, _ = self._measure_text(pillow_font, " ")

            for w in all_words:
                w_w, _ = self._measure_text(pillow_font, w["word"])
                gap = space_w if cur_line else 0
                if cur_line and cur_width + gap + w_w > max_line_width:
                    lines.append({"text": " ".join(x["word"] for x in cur_line), "start": cur_line[0]["start"], "end": cur_line[-1]["end"], "words": cur_line})
                    cur_line, cur_width, gap = [], 0, 0
                cur_line.append(w)
                cur_width += w_w + gap
            if cur_line:
                lines.append({"text": " ".join(x["word"] for x in cur_line), "start": cur_line[0]["start"], "end": cur_line[-1]["end"], "words": cur_line})

            overlays = []
            for line_idx, line in enumerate(lines):
                words_in_line = line["words"]
                lower_words = [w["word"].strip().lower() for w in words_in_line]
                full_text = " ".join(lower_words)
                full_w, _ = self._measure_text(pillow_font, full_text)
                x_start = (video_w - full_w) // 2
                total_height = line_height
                y_line = video_h - total_height - 80

                current_x = x_start
                for i, w in enumerate(words_in_line):
                    word_clean = w["word"].strip().lower()
                    word_w, _ = self._measure_text(pillow_font, word_clean)
                    rect_w = word_w + padding * 2
                    rect_img = self._create_rounded_rect(rect_w, line_height, radius, purple_bg)
                    
                    rect_png_path = temp_img_dir / f"rect_{line_idx:04d}_{w['start']:.2f}.png"
                    rect_img.save(str(rect_png_path))
                    
                    overlays.append({"start": w["start"], "end": w["end"], "x": current_x, "y": y_line, "png": str(rect_png_path)})
                    current_x += word_w
                    if i < len(words_in_line) - 1:
                        space_w, _ = self._measure_text(pillow_font, " ")
                        current_x += space_w

                text_img = self._create_text_image(full_text, pillow_font, white, None, radius, padding, min_height=line_height, stroke_width=2, stroke_fill=black_stroke)
                text_png_path = temp_img_dir / f"line_{line_idx:04d}.png"
                text_img.save(str(text_png_path))
                overlays.append({"start": line["start"], "end": line["end"], "x": x_start, "y": y_line, "png": str(text_png_path)})

            if not is_premium:
                watermark_font = ImageFont.truetype(font_path, 28)
                watermark_img = self._create_text_image("@tt_subtitle_bot", watermark_font, white, None, 0, 6, None, 2, black_stroke)
                alpha = watermark_img.split()[3].point(lambda p: int(p * 0.6))
                watermark_img.putalpha(alpha)
                watermark_png_path = temp_img_dir / "watermark.png"
                watermark_img.save(str(watermark_png_path))
                overlays.append({"start": 0.0, "end": video_duration, "x": 20, "y": video_h - watermark_img.height - 20, "png": str(watermark_png_path)})

            inputs = [str(v_path)]
            filter_parts = []
            current_label = "0:v"
            next_label_idx = 1

            for idx, ov in enumerate(overlays):
                png_abs = str(Path(ov["png"]).resolve()).replace("\\", "/")
                inputs.append(png_abs)
                input_label = f"{next_label_idx}:v"
                next_label_idx += 1
                output_label = "[final]" if idx == len(overlays) - 1 else f"[tmp{idx}]"
                filter_parts.append(f"[{current_label}][{input_label}]overlay={ov['x']}:{ov['y']}:enable='between(t,{ov['start']},{ov['end']})'{output_label}")
                current_label = output_label.strip("[]")

            if filter_parts:
                cmd = [self.ffmpeg, "-y"] + [item for p in inputs for item in ["-i", p]] + [
                    "-filter_complex", ";".join(filter_parts),
                    "-map", "[final]", "-map", "0:a",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",   # ← вместо дефолтного medium
                    "-c:a", "copy",
                    str(output_file)
                ]
            else:
                cmd = [self.ffmpeg, "-y", "-i", str(v_path), "-c", "copy", str(output_file)]

            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"video_path": str(output_file), "srt_path": str(srt_file)}
        
        finally:
            for f in temp_img_dir.glob("*.png"):
                f.unlink(missing_ok=True)
            try:
                temp_img_dir.rmdir()
            except (FileNotFoundError, OSError):
                pass
            if audio_file.exists():
                audio_file.unlink()


    def scan_audio_wav(self, wav_path: str, max_moments: int = 5) -> Dict:
        """Сканирует готовый WAV (16 kHz mono): длительность + моменты."""
        with wave.open(wav_path, "rb") as wf:
            duration = wf.getnframes() / float(wf.getframerate())
        moments = self._find_energy_peaks(wav_path)
        clips = self._select_moments(moments, duration, count=max_moments)
        return {"duration": duration, "moments": clips}