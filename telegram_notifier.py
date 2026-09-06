import requests
import config
from journal import log


def send_telegram(message: str) -> None:
    """Send formatted HTML alert via Telegram. Never raises."""
    if not config.TELEGRAM_TOKEN or config.TELEGRAM_TOKEN.startswith("YOUR_"):
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code != 200:
            log.warning("Telegram HTTP %s: %s", r.status_code, r.text[:200])
    except Exception as e:
        log.warning("Telegram error: %s", e)
