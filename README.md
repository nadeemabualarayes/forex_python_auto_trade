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
├── simulate.py           # Dry run of the live loop against a fake terminal
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

3. Edit `config.py`: set `SYMBOLS` and the risk limits. Copy `.env.example` to `.env` and fill in `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` (or set them as environment variables; `.env` is gitignored and must never be committed).
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

The backtester uses the same signal, trend, session, sizing, and breaker code as the live bot. It fills at the next bar open plus half the median spread, resolves SL/TP against later highs and lows (SL wins a tie), applies the breakeven/ATR trail on each bar close, and does not simulate slippage, commission, or swap. History depth is limited by the terminal's "Max bars in chart" setting.

---

## Dry run (market closed)

```bash
python simulate.py            # sends SIMULATION-prefixed alerts to Telegram
python simulate.py --quiet    # prints them instead
python simulate.py --quiet --trades 20 --seed 1   # random multi-day path, stop after 20 closed trades
```

Drives the real bot loop with a fake terminal and a scripted gold price path: a winning trade that walks through breakeven and trailing to take profit, two stop-outs that trip the circuit breaker, then the daily summary. Output goes to `logs/sim/` so the live journal stays clean.

## Running unattended (your own PC)

GitHub cannot host the bot: it needs a logged-in MetaTrader 5 desktop terminal on a Windows machine. The cheapest always-on option is your own PC with a scheduled task that starts the bot at logon and restarts it whenever it exits with an error.

1. Register the task (run once, from the project folder):

```powershell
powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Start
```

   This creates a Task Scheduler entry named **ForexBot** that runs `run_bot.cmd`, restarts every minute on failure, and has no execution time limit. Console output goes to `logs/console.log`. Set the `BOT_PYTHON` environment variable if `python` on your PATH is not the interpreter you want.

   Other switches: `-Restart` after you change the code, `-Stop` to stop the bot, `-Uninstall` to remove the task. Always use the script rather than Task Scheduler's own *End* button: ending the task only kills the launcher shell and leaves the bot's Python process running.

2. Stop Windows from sleeping: **Settings > System > Power** and set *Screen* and *Sleep* to **Never** while plugged in.

3. Enable automatic logon so the task fires after a reboot without you: run `netplwiz`, untick *Users must enter a user name and password*, and enter your password once. Skip this if the PC is somewhere other people can reach it.

4. Let MetaTrader 5 start with the bot: the bot launches the terminal itself on `mt5.initialize()`, so keep the terminal logged in with *Algo Trading* enabled and *Remember password* ticked.

If the PC is off, so is the bot. For true 24/7 uptime use a Windows VPS instead; the same task script works there.

---

## Status page

While the bot runs it serves a small dashboard from its own process, no extra packages needed. Open <http://127.0.0.1:8080/> on the machine running the bot.

It shows day net P&L, open P&L, wins/losses, entries against the daily cap, loss streak against the breaker limit, an active circuit-breaker banner, what each symbol is waiting on, open positions, and the last 50 journal rows. It refreshes every 5 seconds from `/status.json`.

Settings live in `config.py` under *Status page*: set `WEB_ENABLED = False` to turn it off, change `WEB_PORT` if 8080 is taken, and set `WEB_HOST = "0.0.0.0"` to reach it from your phone on the same Wi-Fi (then use the PC's LAN address). The page is read-only and has no login, so do not expose it to the internet.

---

## Public dashboard on GitHub Pages

The bot can publish the same dashboard to GitHub Pages so you can read it from anywhere. Every 5 minutes it force-pushes `web/index.html` plus the latest `status.json` as a single commit to the `gh-pages` branch, so `main` stays clean. Pushes use the git credentials already stored on the PC and run on a background thread; a failed push is logged and retried at the next interval.

One-time setup on GitHub: **Settings > Pages > Build and deployment > Source: Deploy from a branch**, then pick `gh-pages` and `/ (root)`. The page appears at `https://<user>.github.io/forex_python_auto_trade/` a minute later.

Settings live in `config.py` under *GitHub Pages snapshot*: `PAGES_PUBLISH_ENABLED`, `PAGES_PUBLISH_SECONDS`, `PAGES_BRANCH`, `PAGES_REMOTE`. The data is a few minutes old (the header shows the age) and it is public, so it shows trades and P&L to anyone with the link. Because the repo is public, keep `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` or environment variables only.

---

## Tests

```bash
python -m pytest tests -q
```

The suite covers the signal rule, session and trend gates, position sizing, breakeven/trailing logic, daily statistics, and the backtest engine. It runs without a connected terminal.

---

## Disclaimer

Trading leveraged instruments carries significant risk. Test on a demo account before deploying with real capital.
