from subscriptions import SUBSCRIPTIONS


def main_menu_kb():
    return [{
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [{"type": "callback", "text": "🎬 Найти хайлайты", "payload": "find_highlights"}],
                [{"type": "callback", "text": "📦 Подписки", "payload": "show_subscriptions"}],
                [{"type": "callback", "text": "✉️ Указать email", "payload": "ask_email"}],
                [{"type": "callback", "text": "ℹ️ Помощь", "payload": "help"}],
            ]
        }
    }]


def subscriptions_kb():
    buttons = []
    for sub_id, info in SUBSCRIPTIONS.items():
        if info["price"] > 0:
            buttons.append([{
                "type": "callback",
                "text": f"{info['name']} – {info['price']}₽",
                "payload": f"pay:{sub_id}"
            }])
    buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "back_to_menu"}])
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]