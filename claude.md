# CLAUDE.md

## Project Overview
Automated algorithmic trading bot bridging Python with MetaTrader 5 (MT5). The engine runs an intraday mean-reversion scalper (Bollinger touch + RSI extreme) on several symbols at once (`config.SYMBOLS`, Gold `XAUUSD` and Silver `XAGUSD` by default) with an H1 EMA200 trend filter, a server-time session filter, dynamic ATR risk allocation, account-wide circuit breakers, breakeven/trailing stops, spread protection, a file journal, and Telegram telemetry.

## System Architecture & Flow
```text
                 rates / ticks / deals
MT5 Terminal <──────────────────────────────────> execution.py (bridge: rates, sizing, orders, SL modify)
                                                        ▲
        main.py (Bot.tick, every LOOP_SLEEP_SECONDS)    │
        ├─ risk.ServerClock.now()        server wall-clock, keeps advancing when market closed
        ├─ risk.get_daily_stats()        net P&L / streak / entries from deal history (server day)
        ├─ reporting.notify_closes()     Telegram + journal for new OUT deals
        ├─ position_manager.manage_positions()   breakeven then ATR trail on open bot positions
        ├─ reporting.maybe_heartbeat / maybe_daily_summary
        ├─ risk.breaker_reason()         pause entries on daily loss / loss streak
        └─ strategy.SymbolTrader.step()  per symbol: position? session? cap? spread? -> signal -> order
                 └─ technicals.py  ATR/BB/RSI on M5, EMA200 on H1 (attach_trend uses last *closed* H1 bar)
        journal.py   logs/bot.log (rotating) + logs/trades.csv (ENTRY/EXIT/SL_MOVE/REJECTED/SKIP)
        telegram_notifier.py
simulate.py  dry run: real Bot loop + FakeMT5 + scripted price path (logs/sim/, Telegram prefixed SIMULATION)
backtest.py  standalone replay of strategy.generate_signal over MT5 history (same filters/sizing/breakers)
```

## Conventions
- All clocks are MT5 server time (naive datetime). Daily windows are server-midnight epochs; deals are filtered in Python by `deal.time`.
- Every MT5 call that can return `None` is guarded. Symbols without a live tick (`tick.time == 0`) are skipped.
- One entry attempt per closed candle per symbol (`SymbolTrader.last_signal_bar`), whether it fills or is rejected.
- Pure logic lives in plain functions (`strategy.generate_signal`, `position_manager.next_stop`, `execution.lot_for_risk`, `risk.stats_from_deals`, `backtest.run_backtest`) so it is testable without a terminal.

## Commands
- Run bot: `python main.py`
- Tests: `python -m pytest tests -q`
- Dry run: `python simulate.py [--quiet]`
- Backtest: `python backtest.py --symbol XAUUSD --days 60 [--no-trend] [--no-session] [--csv out.csv]`

## Design notes
See `docs/superpowers/specs/2026-09-06-multi-symbol-enhancements-design.md`.
