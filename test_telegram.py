import requests
import config

url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
payload = {
    "chat_id": config.TELEGRAM_CHAT_ID,
    "text": "✅ <b>Telegram test</b> from mt5_algo_bot",
    "parse_mode": "HTML",
}
r = requests.post(url, json=payload, timeout=10)
print("HTTP", r.status_code)
print("ok:", r.json().get("ok"), "message_id:", r.json().get("result", {}).get("message_id"))
