# Algorithmic MT5 Trading Engine with Risk Management & Telegram Alerts

An automated execution engine linking **Python** with **MetaTrader 5 (MT5)**, designed for risk-managed intraday trading across multiple asset classes (Forex, Gold, Silver).

---

## Architecture Highlights

1. **Multi-symbol:** one `SymbolTrader` per entry in `config.SYMBOLS`, sharing account-level risk limits.
2. **Dynamic contract valuation:** position size is derived from the symbol's tick value and the USD risk budget per trade.
3. **Volatility-scaled levels:** ATR multipliers set stop loss and take profit instead of fixed points.
4. **Trend filter:** entries only in the direction of the H1 EMA200 (buy above, sell below).
5. **Session filter:** trades only inside a server-time window on weekdays.
6. **Circuit breakers:** daily loss limit, consecutive-loss limit, and a daily entry cap, all computed from MT5 deal history.
7. **Position management:** stop moves to breakeven after 1 ATR of profit, then trails 1 ATR behind price.
8. **Spread guard:** per-symbol spread cap blocks entries in illiquid conditions.
9. **Journal and logs:** rotating `logs/bot.log` plus `logs/trades.csv` with every entry, exit, stop move, and rejection.
10. **Telegram telemetry:** trade open/close alerts, breaker alerts, a heartbeat every few hours, and an end-of-day summary.
11. **Backtester:** replays the live signal code over MT5 history.

---

## Project Structure

```text
├── config.py             # Symbols, risk limits, filters, Telegram creds via env vars
├── technicals.py         # ATR, Bollinger Bands, RSI, trend EMA
├── strategy.py           # Signal rule, session/trend gates, SymbolTrader
├── risk.py               # Daily stats from deal history, breaker, server clock
├── position_manager.py   # Breakeven + ATR trailing stop
├── execution.py          # MT5 bridge: rates, sizing, orders, SL modify
├── journal.py            # Rotating log file + CSV trade journal
├── reporting.py          # Close alerts, heartbeat, daily summary
├── telegram_notifier.py  # Telegram API layer
├── backtest.py           # Standalone backtester
├── main.py               # Orchestrator loop
├── tests/                # pytest suite (no terminal needed)
└── docs/superpowers/specs # Design notes
```

---

## Setup

1. Install and log in to the MetaTrader 5 terminal (Windows) and enable **Algo Trading**.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Edit `config.py`: set `SYMBOLS` and the risk limits. Set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` as environment variables.
4. Start the bot:

```bash
python main.py
```

Logs go to `logs/bot.log`; every trade event is appended to `logs/trades.csv`.

---

## Backtesting

```bash
python backtest.py --symbol XAUUSD --days 60
python backtest.py --symbol XAGUSD --days 90 --no-trend --csv silver.csv
```

The backtester uses the same signal, trend, session, sizing, and breaker code as the live bot. It fills at the next bar open plus half the median spread, resolves SL/TP against later highs and lows (SL wins a tie), and does not simulate the trailing stop, slippage, commission, or swap. History depth is limited by the terminal's "Max bars in chart" setting.

---

## Tests

```bash
python -m pytest tests -q
```

The suite covers the signal rule, session and trend gates, position sizing, breakeven/trailing logic, daily statistics, and the backtest engine. It runs without a connected terminal.

---

## Disclaimer

Trading leveraged instruments carries significant risk. Test on a demo account before deploying with real capital.
