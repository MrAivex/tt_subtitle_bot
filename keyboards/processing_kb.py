def processing_options_kb(has_webcam: bool = False, format_mode: str = "original", mode: str = "highlights"):
    """Клавиатура выбора параметров обработки с radio-кнопками."""
    # Группа 1: Режим обработки (в колонку)
    mode_highlights = "✅ 🔪 Нарезать хайлайты" if mode == "highlights" else "🔪 Нарезать хайлайты"
    mode_full = "✅ 📝 Полное субтитрирование" if mode == "full" else "📝 Полное субтитрирование"
    
    # Группа 2: Вебка (взаимоисключающие)
    webcam_yes = "✅ Есть вебка" if has_webcam else "Есть вебка"
    webcam_no = "Нет вебки" if has_webcam else "✅ Нет вебки"
    
    # Группа 3: Формат (взаимоисключающие)
    format_original = "✅ Исходный формат" if format_mode == "original" else "Исходный формат"
    format_vertical = "9:16 (вертикально)" if format_mode == "original" else "✅ 9:16 (вертикально)"
    
    return [{
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [{"type": "callback", "text": mode_highlights, "payload": "mode:highlights"}],
                [{"type": "callback", "text": mode_full, "payload": "mode:full"}],
                [
                    {"type": "callback", "text": webcam_yes, "payload": "webcam:yes"},
                    {"type": "callback", "text": webcam_no, "payload": "webcam:no"}
                ],
                [
                    {"type": "callback", "text": format_original, "payload": "format:original"},
                    {"type": "callback", "text": format_vertical, "payload": "format:vertical"}
                ],
                [{"type": "callback", "text": "▶️ Начать обработку", "payload": "start_processing"}],
            ]
        }
    }]