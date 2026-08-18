import os
import re
import subprocess
import platform
from datetime import timedelta
from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------
# 1. Автоопределение ffmpeg
# ------------------------------------------------------------
FFMPEG_ENV = os.getenv("FFMPEG_PATH")
if FFMPEG_ENV:
    FFMPEG = FFMPEG_ENV
else:
    if platform.system() == "Windows":
        FFMPEG = r"D:\Programingg\PO\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
    else:
        FFMPEG = "ffmpeg"
if platform.system() == "Windows":
    FFMPEG = os.path.normpath(FFMPEG)

if platform.system() == "Windows":
    FFPROBE = os.path.join(os.path.dirname(FFMPEG), "ffprobe.exe")
else:
    FFPROBE = "ffprobe"

# ------------------------------------------------------------
# 2. Автоопределение шрифта
# ------------------------------------------------------------
def get_font_path():
    env_font = os.getenv("FONT_PATH")
    if env_font:
        return env_font

    roboto_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "roboto-bold.ttf")
    if os.path.exists(roboto_path):
        return roboto_path
    local_font = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "arial.ttf")
    if os.path.exists(local_font):
        return local_font
    if platform.system() == "Linux":
        candidates = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
    return "arial.ttf"

# ------------------------------------------------------------
# 3. Whisper (GPU, если доступна)
# ------------------------------------------------------------
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
try:
    import torch
    if WHISPER_DEVICE == "cuda" and not torch.cuda.is_available():
        WHISPER_DEVICE = "cpu"
except ImportError:
    WHISPER_DEVICE = "cpu"

MODEL = WhisperModel("medium", device=WHISPER_DEVICE, compute_type="float16" if WHISPER_DEVICE == "cuda" else "int8")

# ------------------------------------------------------------
# 4. Вспомогательные функции
# ------------------------------------------------------------
def get_video_resolution(video_path: str) -> tuple:
    cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path]
    out = subprocess.check_output(cmd, text=True).strip()
    w, h = map(int, out.split(","))
    return w, h

def get_video_duration(video_path: str) -> float:
    cmd = [FFPROBE, "-v", "error", "-show_entries", "format=duration",
           "-of", "csv=p=0", video_path]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)

def measure_text(font, text: str):
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

def create_text_image(text: str, font: ImageFont.FreeTypeFont, text_color: tuple,
                      bg_color: tuple = None, radius: int = 0, padding: int = 4,
                      min_height: int = None, stroke_width: int = 0, stroke_fill: tuple = None) -> Image.Image:
    temp_img = Image.new("RGBA", (1, 1), (0,0,0,0))
    temp_draw = ImageDraw.Draw(temp_img)
    bbox = temp_draw.textbbox((0,0), text, font=font, stroke_width=stroke_width)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img_w = text_w + padding * 2
    img_h = max(text_h, min_height) + padding * 2 if min_height else text_h + padding * 2

    img = Image.new("RGBA", (img_w, img_h), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    if bg_color is not None:
        draw.rounded_rectangle([(0, 0), (img_w-1, img_h-1)], radius=radius, fill=bg_color)

    # Центрируем текст (учитываем baseline bbox[1])
    y_text = (img_h - text_h) // 2 - bbox[1]
    draw.text((padding, y_text), text, font=font, fill=text_color, stroke_width=stroke_width, stroke_fill=stroke_fill)
    return img

def create_rounded_rect(width: int, height: int, radius: int, color: tuple) -> Image.Image:
    """Создаёт прозрачное изображение с закруглённым прямоугольником заданного цвета."""
    img = Image.new("RGBA", (width, height), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (width-1, height-1)], radius=radius, fill=color)
    return img

# ------------------------------------------------------------
# 5. Основная функция обработки видео
# ------------------------------------------------------------
def process_video(input_path: str, user_id: str, is_premium: bool = False) -> dict:
    input_abs = os.path.abspath(input_path)
    video_dir = os.path.dirname(input_abs)
    base_name = os.path.splitext(os.path.basename(input_abs))[0]
    ext = os.path.splitext(input_abs)[1]

    audio_file = base_name + ".wav"
    srt_file = base_name + ".srt"
    output_file = base_name + "_subtitled.mp4"

    old_cwd = os.getcwd()
    os.chdir(video_dir)

    temp_img_dir = "temp_sub_img"
    os.makedirs(temp_img_dir, exist_ok=True)

    try:
        video_w, video_h = get_video_resolution(base_name + ext)
        video_duration = get_video_duration(base_name + ext)

        # 1. Извлечение аудио
        subprocess.run([FFMPEG, "-y", "-i", base_name + ext,
                        "-ar", "16000", "-ac", "1", audio_file],
                       check=True, capture_output=True, text=True)

        # 2. Распознавание с word timestamps
        segments, _ = MODEL.transcribe(audio_file, language="ru", word_timestamps=True)
        seg_list = list(segments)

        # 3. SRT для пользователя
        srt_text = ""
        for i, seg in enumerate(seg_list, 1):
            start = str(timedelta(seconds=seg.start))[:-3].replace(".", ",")
            end = str(timedelta(seconds=seg.end))[:-3].replace(".", ",")
            srt_text += f"{i}\n{start} --> {end}\n{seg.text.strip()}\n\n"
        with open(srt_file, "w", encoding="utf-8") as f:
            f.write(srt_text)

        # 4. Шрифт и цвета
        font_path = get_font_path()
        font_size = 36
        pillow_font = ImageFont.truetype(font_path, font_size)
        white = (255, 255, 255, 255)          # белый текст
        black_stroke = (0, 0, 0, 255)         # чёрная обводка
        purple_bg = (157, 78, 221, 240)       # сиреневый полупрозрачный
        radius = 12
        padding = 6                           # уменьшенный отступ
        line_height = font_size + padding * 2 # компактная высота плашки

        # 5. Список всех слов
        all_words = []
        for seg in seg_list:
            if seg.words:
                for w in seg.words:
                    all_words.append({"word": w.word.strip(), "start": w.start, "end": w.end})

        if not all_words:
            subprocess.run([FFMPEG, "-y", "-i", base_name + ext, "-c", "copy", output_file],
                           check=True, capture_output=True, text=True)
            if os.path.exists(audio_file):
                os.remove(audio_file)
            return {"video_path": os.path.join(video_dir, output_file), "srt_path": srt_file}

        # 6. Разбивка на строки
        max_line_width = video_w - 40
        lines = []
        cur_line = []
        cur_width = 0
        space_w, _ = measure_text(pillow_font, " ")

        for w in all_words:
            w_w, _ = measure_text(pillow_font, w["word"])
            gap = space_w if cur_line else 0
            if cur_line and cur_width + gap + w_w > max_line_width:
                lines.append({
                    "text": " ".join(x["word"] for x in cur_line),
                    "start": cur_line[0]["start"],
                    "end": cur_line[-1]["end"],
                    "words": cur_line
                })
                cur_line = []
                cur_width = 0
                gap = 0
            cur_line.append(w)
            cur_width += w_w + gap

        if cur_line:
            lines.append({
                "text": " ".join(x["word"] for x in cur_line),
                "start": cur_line[0]["start"],
                "end": cur_line[-1]["end"],
                "words": cur_line
            })

        # 7. Генерация PNG и overlays (чёрный текст + жёлтые плашки для слов)
        overlays = []

        for line_idx, line in enumerate(lines):
            words_in_line = line["words"]
            lower_words = [w["word"].strip().lower() for w in words_in_line]
            full_text = " ".join(lower_words)
            full_w, _ = measure_text(pillow_font, full_text)
            x_start = (video_w - full_w) // 2

            total_height = line_height
            y_line = video_h - total_height - 80   # отступ снизу

            # --- Фиолетовые прямоугольники для активного слова ---
            current_x = x_start
            for i, w in enumerate(words_in_line):
                word_clean = w["word"].strip().lower()
                word_w, _ = measure_text(pillow_font, word_clean)

                rect_w = word_w + padding * 2
                rect_img = create_rounded_rect(rect_w, line_height, radius, purple_bg)

                rect_png = f"rect_{line_idx:04d}_{w['start']:.2f}.png"
                rect_png_path = os.path.join(temp_img_dir, rect_png)
                rect_img.save(rect_png_path)

                x_word = current_x
                overlays.append({
                    "start": w["start"],
                    "end": w["end"],
                    "x": x_word,
                    "y": y_line,
                    "png": rect_png_path
                })

                current_x += word_w
                if i < len(words_in_line) - 1:
                    space_w, _ = measure_text(pillow_font, " ")
                    current_x += space_w

            # --- Белый текст строки с чёрной обводкой (поверх прямоугольников) ---
            text_img = create_text_image(
                full_text, pillow_font, white, None,
                radius, padding, min_height=line_height,
                stroke_width=2, stroke_fill=black_stroke
            )
            text_png = f"line_{line_idx:04d}.png"
            text_png_path = os.path.join(temp_img_dir, text_png)
            text_img.save(text_png_path)
            overlays.append({
                "start": line["start"],
                "end": line["end"],
                "x": x_start,
                "y": y_line,
                "png": text_png_path
            })

        # --- Водяной знак @tg_bot (правый верхний угол, всё видео) ---
        if not is_premium:
            watermark_text = "@tt_subtitle_bot"
            watermark_font_size = 28
            watermark_font = ImageFont.truetype(font_path, watermark_font_size)
            # Создаём картинку с белым текстом и чёрной обводкой, полупрозрачную
            watermark_img = create_text_image(
                watermark_text, watermark_font, white, None,
                radius=0, padding=6, min_height=None,
                stroke_width=2, stroke_fill=black_stroke
            )
            # Сделаем её чуть прозрачнее (альфа-канал умножим)
            from PIL import ImageEnhance
            alpha = watermark_img.split()[3]
            alpha = alpha.point(lambda p: int(p * 0.6))   # 60% непрозрачности
            watermark_img.putalpha(alpha)
            
            watermark_png = "watermark.png"
            watermark_png_path = os.path.join(temp_img_dir, watermark_png)
            watermark_img.save(watermark_png_path)
            
            # Позиция: правый верхний угол с отступом 20 пикселей
            x_watermark = 20
            y_watermark = video_h - watermark_img.height - 20
            overlays.append({
                "start": 0.0,
                "end": video_duration,
                "x": x_watermark,
                "y": y_watermark,
                "png": watermark_png_path
            })

        # 8. Сборка ffmpeg команды
        inputs = [base_name + ext]
        filter_parts = []
        current_label = "0:v"
        next_label_idx = 1

        for idx, ov in enumerate(overlays):
            png_abs = os.path.abspath(ov["png"]).replace("\\", "/")
            inputs.append(png_abs)
            input_label = f"{next_label_idx}:v"
            next_label_idx += 1
            output_label = "[final]" if idx == len(overlays) - 1 else f"[tmp{idx}]"
            filter_parts.append(
                f"[{current_label}][{input_label}]overlay={ov['x']}:{ov['y']}:enable='between(t,{ov['start']},{ov['end']})'{output_label}"
            )
            current_label = output_label.strip("[]")

        if filter_parts:
            filter_complex = ";".join(filter_parts)
            cmd = [FFMPEG, "-y"] + [item for p in inputs for item in ["-i", p]] + [
                "-filter_complex", filter_complex,
                "-map", "[final]",
                "-map", "0:a",
                "-c:a", "copy",
                output_file
            ]
        else:
            cmd = [FFMPEG, "-y", "-i", base_name + ext, "-c", "copy", output_file]

        subprocess.run(cmd, check=True, capture_output=True, text=True)

        # 9. Удаление временных файлов
        for ov in overlays:
            try:
                os.remove(ov["png"])
            except:
                pass
        try:
            os.rmdir(temp_img_dir)
        except:
            pass
        if os.path.exists(audio_file):
            os.remove(audio_file)

        result_video = os.path.join(video_dir, output_file)
        result_srt = os.path.join(video_dir, srt_file)

    finally:
        os.chdir(old_cwd)

    return {"video_path": result_video, "srt_path": result_srt}