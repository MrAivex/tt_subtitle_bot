def initial_options_kb():
    """Первое меню: выбор между хайлайтами и полным субтитрированием."""
    return [{
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [{"type": "callback", "text": "🔪 Нарезать хайлайты", "payload": "choose:highlights"}],
                [{"type": "callback", "text": "📝 Наложить субтитры", "payload": "choose:full"}],
            ]
        }
    }]


def highlights_options_kb(has_webcam: bool = False, has_subtitles: bool = True, 
                          format_mode: str = "original"):
    """Меню настроек нарезки хайлайтов."""
    # Toggle-кнопки с галочкой/крестиком
    webcam_text = "✅ Вебка" if has_webcam else "❌ Вебка"
    subs_text = "✅ Субтитры" if has_subtitles else "❌ Субтитры"
    
    # Взаимоисключающие кнопки формата
    format_original = "✅ Исходный" if format_mode == "original" else "Исходный"
    format_vertical = "✅ 9:16" if format_mode == "vertical_9_16" else "9:16"
    
    return [{
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {"type": "callback", "text": webcam_text, "payload": "hl:webcam"},
                    {"type": "callback", "text": subs_text, "payload": "hl:subtitles"},
                ],
                [
                    {"type": "callback", "text": format_original, "payload": "hl:format_original"},
                    {"type": "callback", "text": format_vertical, "payload": "hl:format_vertical"},
                ],
                [{"type": "callback", "text": "▶️ Начать нарезку", "payload": "hl:start"}],
                [{"type": "callback", "text": "🔙 Назад", "payload": "hl:back"}],
            ]
        }
    }]