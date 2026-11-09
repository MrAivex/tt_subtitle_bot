from subscriptions import SUBSCRIPTIONS
from config import BOT_USERNAME


def main_menu_kb():
    return [{"type": "inline_keyboard", "payload": {"buttons": [
        [{"type": "open_app", "text": "🎬 Открыть приложение", "web_app": BOT_USERNAME}],
    ]}}]


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