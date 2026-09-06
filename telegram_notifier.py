import requests
import config

def send_telegram(message: str):
    """Send formatted HTML alert via Telegram."""
    if not config.TELEGRAM_TOKEN or config.TELEGRAM_TOKEN.startswith("YOUR_"):
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Telegram Error]: {e}")
