# Algorithmic MT5 Trading Engine with Risk Management & Telegram Alerts

An automated execution engine linking **Python** with **MetaTrader 5 (MT5)**, designed for risk-managed intraday trading across multiple asset classes (Forex, Gold, Silver).

---

## 📌 Architecture Highlights

1. **Dynamic Contract Valuation:** Computes exact position sizing (`lot`) for any symbol based on real-time tick value and risk allowance in USD.
2. **Dynamic Volatility Bands:** Uses ATR (Average True Range) multipliers instead of hardcoded point targets.
3. **Daily Circuit Breaker:** Ceases execution if cumulative daily loss exceeds the defined threshold or consecutive losses hit the limit.
4. **Spread Guard:** Blocks execution during illiquid market openings or volatility spikes.
5. **Instant Telegram Telemetry:** Real-time push notifications for deal execution and kill-switch activations.

---

## ⚙️ Project Structure

```text
├── config.py             # User parameters, symbol selection (Telegram creds via env vars)
├── technicals.py         # ATR, Bollinger Bands, and RSI computation
├── execution.py          # MT5 bridge, order formatting, and position sizing
├── telegram_notifier.py  # Telegram API notification layer
├── main.py               # Main event loop and circuit breaker checks
├── requirements.txt      # Python dependencies
└── README.md             # Project documentation
```

---

## 🚀 Setup

1. Install and log in to the MetaTrader 5 terminal (Windows) and enable **Algo Trading**.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Edit `config.py`: set `SYMBOL` and risk limits. Set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` as environment variables.
4. Start the bot:

```bash
python main.py
```

---

## ⚠️ Disclaimer

Trading leveraged instruments carries significant risk. Test on a demo account before deploying with real capital.
