def processing_options_kb(has_webcam: bool = False, format_mode: str = "original"):
    """Клавиатура выбора параметров обработки."""
    webcam_text = "✅ Есть вебка" if has_webcam else " Нет вебки"
    format_text = "📱 9:16 (вертикально)" if format_mode == "vertical_9_16" else "🖥️ Исходный формат"
    
    return [{
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {"type": "callback", "text": "🔪 Нарезать хайлайты", "payload": "mode:highlights"},
                    {"type": "callback", "text": "📝 Полное субтитрирование", "payload": "mode:full"}
                ],
                [
                    {"type": "callback", "text": webcam_text, "payload": "toggle:webcam"}
                ],
                [
                    {"type": "callback", "text": format_text, "payload": "toggle:format"}
                ],
                [
                    {"type": "callback", "text": "▶️ Начать обработку", "payload": "start_processing"}
                ],
            ]
        }
    }]