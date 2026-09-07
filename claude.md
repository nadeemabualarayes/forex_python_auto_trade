# CLAUDE.md

## Project Overview
Automated algorithmic trading bot bridging Python with MetaTrader 5 (MT5). The engine runs an intraday mean-reversion scalper (Bollinger touch + RSI extreme) on several symbols at once (`config.SYMBOLS`, Gold `XAUUSD` and Silver `XAGUSD` by default) with an H1 EMA200 trend filter, a server-time session filter, dynamic ATR risk allocation, account-wide circuit breakers, breakeven/trailing stops, spread protection, a file journal, and Telegram telemetry. A second engine, the London-open range breakout (`london.py`, magic 998888, EURUSD/GBPUSD by default), runs in the same loop under its own `Engine` profile (`engines.py`).

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
        ├─ risk.account_breaker / engine_breaker   account-wide daily loss pauses all; loss streak pauses one engine
        ├─ news.NewsFilter               Forex Factory weekly JSON (USD High), UTC wall clock; refresh every 4 h, cache on failure
        └─ engines.build_engines()      Engine profiles: scalper (BB+RSI pin-bar, M5) and london (box breakout, M5)
             └─ strategy.SymbolTrader.step()  per engine x symbol: position? session? news? engine cap? spread? -> signal -> order
                      ├─ scalper: candles.py + technicals.py (M5 BB/RSI/ATR, H1 EMA200)
                      └─ london:  london.py  Asian box 00:00-10:00 server, first break 10:00-14:00, ATR stop, 2R
        ├─ Bot._maybe_sync_history()     every 60 s: history.sync_deals (MT5 deals -> logs/history.db), equity snapshot,
        │                                analytics.pair_trades/build_analytics cached on the Bot
        ├─ Bot._maybe_refresh_charts()   every 60 s: SymbolTrader.frame() -> status.chart_block (candles, bands, RSI, patterns)
        ├─ Bot._publish()                status.build_status (+account/analytics/history) -> web.StatusServer (http://127.0.0.1:8080)
        │                                and publisher.PagesPublisher (force-push gh-pages every 5 min)
        journal.py   logs/bot.log (rotating) + logs/trades.csv (ENTRY/EXIT/SL_MOVE/REJECTED/SKIP)
        telegram_notifier.py
        web/index.html  dashboard (Chart.js, KPI tiles, trade history) polling status.json every 5 s
run_bot.cmd + install_task.ps1   Task Scheduler "ForexBot": start at logon, restart on non-zero exit (-Restart / -Stop / -Uninstall)
simulate.py  dry run: real Bot loop + FakeMT5 + scripted price path (logs/sim/, Telegram prefixed SIMULATION); --london also runs the London engine on the simulated symbol
backtest.py  standalone replay of strategy.generate_signal over MT5 history (same filters/sizing/breakers/trailing)
```

## Conventions
- All clocks are MT5 server time (naive datetime). Daily windows are server-midnight epochs; deals are filtered in Python by `deal.time`.
- News blackout times are compared in UTC against the real wall clock (releases are real-world moments); everything else is server time.
- Every MT5 call that can return `None` is guarded. Symbols without a live tick (`tick.time == 0`) are skipped.
- One entry attempt per closed candle per symbol (`SymbolTrader.last_signal_bar`), whether it fills or is rejected.
- Pure logic lives in plain functions (`strategy.generate_signal`, `position_manager.next_stop`, `execution.lot_for_risk`, `execution.trading_blockers`, `risk.stats_from_deals`, `backtest.run_backtest`) so it is testable without a terminal.
- Each engine has its own magic number; positions, deals, stats, journal notes and dashboard rows are keyed by it. `execution.KNOWN_MAGICS` lists every running engine.

## Commands
- Run bot: `python main.py`
- Tests: `python -m pytest tests -q`
- Dry run: `python simulate.py [--quiet] [--trades N --seed S] [--london]` (N closed trades on a random multi-day path)
- Backtest: `python backtest.py [--engine scalper|london] [--symbol XAUUSD ...] --days 60 [--no-trend] [--no-session] [--csv out.csv] [--telegram]` (`--telegram` sends the per-symbol digest to the bot chat)

## Design notes
See `docs/superpowers/specs/2026-09-06-multi-symbol-enhancements-design.md`.
