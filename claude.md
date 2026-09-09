# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An automated trading bot that bridges Python with a **MetaTrader 5 desktop terminal** (Windows only; the
terminal must be logged in with Algo Trading enabled). One process runs several independent strategies
("engines") over several symbols, sharing account-wide risk limits, a SQLite trade history, a local web
dashboard, and Telegram telemetry.

Two engines ship today, both driven from the same loop and the same `Engine` profile type (`engines.py`):

| Engine | Magic | Default symbols | Rule |
| --- | --- | --- | --- |
| `scalper` | 998877 | XAUUSD, XAGUSD | M5 mean reversion: Bollinger touch + RSI extreme, confirmed by a pin-bar candle, H1 EMA200 trend filter, ATR SL/TP |
| `london` | 998888 | EURUSD, GBPUSD | M5 London-open breakout: first close beyond the Asian box (00:00–10:00 server) inside 10:00–14:00, ATR stop, 2R target |

## Commands

```bash
python main.py                                  # run the live bot (needs a running MT5 terminal)
python -m pytest tests -q                       # full suite: 207 tests, no terminal required
python -m pytest tests/test_strategy.py -q      # one file
python -m pytest tests/test_strategy.py::test_name -q   # one test
python -m pytest tests -q -k "london and levels"        # by expression

python simulate.py [--quiet] [--trades N --seed S] [--london]
python backtest.py [--engine scalper|london] [--symbol XAUUSD ...] --days 60 \
       [--no-trend] [--no-session] [--spread-points N] [--csv out.csv] [--segments] [--telegram]
```

- `simulate.py` drives the **real** `Bot.tick()` loop against `FakeMT5` and a scripted (or seeded random)
  price path; each pass advances one M5 bar instead of sleeping. Output goes to `logs/sim/` and Telegram
  messages are prefixed `SIMULATION`. It forces `CANDLE_MODE="off"` and `NEWS_FILTER_ENABLED=False`.
- `backtest.py` replays the live `signal`/`levels` callables over MT5 history with the same filters,
  sizing, breakers and trailing. History depth is capped by the terminal's *Max bars in chart*
  (~178 days on M5). It does not model slippage, commission, swap or the news filter.
- Unattended running (Windows Task Scheduler task **ForexBot**):
  `powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Start | -Restart | -Stop | -Uninstall`.
  Always use `-Stop`/`-Restart`, never Task Scheduler's *End* button — that kills only the launcher shell
  (`run_bot.cmd`) and leaves the Python process running.

## System architecture & flow

```text
                 rates / ticks / deals
MT5 Terminal <──────────────────────────────────> execution.py (bridge: rates, sizing, orders, SL modify)
                                                        ▲
        main.py (Bot.tick, every LOOP_SLEEP_SECONDS)    │
        ├─ risk.ServerClock.now()          server wall-clock; keeps advancing when the market is closed
        ├─ risk.daily_stats_by_magic()     per-engine net P&L / streak / entries from deal history
        ├─ reporting.notify_closes()       Telegram + journal for new OUT deals
        ├─ position_manager.manage_positions(engine)   breakeven then ATR trail (per engine)
        ├─ reporting.maybe_heartbeat / maybe_daily_summary
        ├─ risk.account_breaker            combined daily loss  -> pauses every engine
        ├─ risk.engine_breaker             that engine's streak -> pauses that engine only
        ├─ news.NewsFilter                 Forex Factory weekly JSON (USD High), UTC wall clock
        └─ engines.build_engines()         Engine profiles: scalper (M5 BB+RSI+pin bar) and london (M5 box break)
             └─ strategy.SymbolTrader.step()  per engine x symbol:
                    position? session? news? engine cap? spread? -> signal -> levels -> lot -> order
                      ├─ scalper: technicals.py (BB/RSI/ATR + H1 EMA200) + candles.py
                      └─ london:  london.py (Asian box columns, ATR stop, LDN_TP_R target)
        ├─ Bot._maybe_sync_history()   every 60 s: history.sync_deals (MT5 deals -> logs/history.db),
        │                              equity snapshot, analytics.pair_trades/build_analytics cached on Bot
        ├─ Bot._maybe_refresh_charts() every 60 s: SymbolTrader.frame() -> status.chart_block
        └─ Bot._publish()              status.build_status -> web.StatusServer (http://127.0.0.1:8080)
                                       and publisher.PagesPublisher (force-push gh-pages every 5 min)

        journal.py  logs/bot.log (rotating) + logs/trades.csv (ENTRY/EXIT/SL_MOVE/REJECTED/SKIP)
        web/index.html  dashboard (Chart.js, KPI tiles, candles, trade history) polling status.json every 5 s
```

### Layering that matters when editing

- **Pure logic first.** Everything testable without a terminal lives in plain functions:
  `strategy.generate_signal` / `raw_signal` / `trend_allows` / `build_levels`, `london.*`,
  `technicals.*`, `candles.add_patterns`, `position_manager.next_stop`, `execution.lot_for_loss` /
  `lot_for_risk` / `trading_blockers`, `risk.stats_from_deals`, `analytics.*`, `status.build_status`,
  `segments.*`, `backtest.run_backtest`. Keep new logic in this layer and let the MT5-facing wrapper stay thin.
- **`engines.Engine` is the extension point.** A frozen dataclass bundling magic, comment, symbols,
  timeframe, lookback, trend flag, the `analyse`/`signal`/`levels` callables, and the risk knobs.
  `SymbolTrader`, `manage_positions`, `Reporter`, `status.engine_block` and `backtest` all read the
  profile instead of module-level config, so **adding an engine is adding a profile** in
  `engines.build_engines()` plus its pure signal module.
- **`Bot` keeps two engine lists.** `self.all_engines` (original symbols) drives history, stats, breakers
  and the dashboard; `self.engines` is the subset whose symbols the terminal actually offers and drives
  traders and chart refresh.
- **Analytics is deal-derived, not journal-derived.** The broker's deal history is the source of truth, so
  trades that closed while the bot was down still show up on the next `sync_deals`. `logs/trades.csv` is a
  human journal, not state.

## Conventions and gotchas

- **Clocks.** All bot logic uses MT5 *server* time as a naive `datetime` (this broker is UTC+3, so the
  London open is hour 10). Daily windows are server-midnight epochs and deals are filtered in Python by
  `deal.time`. The one exception: **news blackouts compare against the real UTC wall clock**, because
  releases are real-world moments.
- **Never trust `SYMBOL_TRADE_TICK_VALUE`.** The demo reports gold/silver tick values ~10x too low, which
  once sized a silver trade at ‑$46 against a $5 budget. `execution.calculate_dynamic_lot` prices the stop
  with the terminal's own `order_calc_profit`; the field is a fallback only for symbols verified against
  the terminal (`verify_tick_value` / `TICK_VALUE_TRUSTED`), and an unverified symbol the terminal cannot
  price gets **no lot** rather than a guessed one.
- **Guard every MT5 call that can return `None`**, and skip symbols with no live tick (`tick.time == 0`).
- **One entry attempt per closed candle per symbol** (`SymbolTrader.last_signal_bar`), whether it fills,
  is rejected, or is skipped. Signals are always read off `df.iloc[-2]`, the last *closed* bar.
- **No look-ahead in the trend filter.** `technicals.attach_trend` shifts the H1 EMA one bar forward before
  the `merge_asof`, so a signal bar only sees an H1 bar that had already closed.
- **Magic numbers key everything** — positions, deals, stats, journal notes, dashboard rows.
  `execution.KNOWN_MAGICS` is populated by `Bot.__init__` via `set_known_magics`; `bot_positions()` with no
  magic means "any engine of this bot", never "any position on the account".
- **Risk policy is hybrid.** Account-wide daily loss (`MAX_DAILY_LOSS_USD`) pauses everything; a loss
  streak pauses only the engine that owns it (`Engine.max_consecutive_losses`).
- **Secrets stay in `.env`** (gitignored; see `.env.example`). `config.py` is committed and reads
  `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` from the environment — token/credential literals were leaked here
  once already. An empty token silently disables Telegram.
- **Nothing in the reporting/status/publishing path may break trading.** `_publish`, `_maybe_sync_history`
  and `_maybe_refresh_charts` swallow their exceptions; a per-symbol `step()` failure is logged and
  announced once, and only a missing terminal is allowed to propagate so `run()` reconnects.
- **Exit code 1 is meaningful:** Task Scheduler only restarts a task that *failed*, so `run()` returns 1
  when MT5 is unusable at startup and 0 on a manual stop.
- The file is tracked in git as lowercase **`claude.md`**; writing `CLAUDE.md` on this case-insensitive
  filesystem is fine, but do not add a second entry.

## Tests

`tests/conftest.py` supplies a stand-in `MetaTrader5` module when the real package is absent (so the suite
runs off-Windows) and applies three autouse fixtures: logs and the journal are redirected to `tmp_path`,
`TELEGRAM_TOKEN` is blanked, `CANDLE_MODE` is forced to `"off"` (tests that want candlestick confirmation
opt in themselves), and `NEWS_FILTER_ENABLED` is turned off. Tests that need a terminal fake one; none of
them talks to MT5 or the network.

## Configuration

`config.py` is the single knob panel, grouped by section: symbols/timeframe, account-wide risk, indicators,
candlestick mode, news filter, trend filter, session filter, position management, the `LDN_*` London block,
reporting cadence, logging, loop timing, the status page, history/analytics, Telegram, and the GitHub Pages
snapshot. Comments there record *why* a value was chosen (which sweep or incident), so keep that habit when
changing one. Notable current settings: `MANAGE_POSITIONS = False` (trailing cut winners in the 2026‑09‑06
sweep), `CANDLE_MODE = "confirm"` with pin-bar patterns only, and a 24h session window.

## Design notes

- `docs/superpowers/specs/` — multi-symbol enhancements, analytics dashboard, London breakout engine designs.
- `docs/superpowers/plans/` — the implementation plans those specs were executed from.
- `docs/research/` — segmented backtest digests and the XAUUSD scalper blueprint.
