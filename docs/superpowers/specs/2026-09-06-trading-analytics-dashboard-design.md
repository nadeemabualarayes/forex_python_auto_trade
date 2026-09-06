# Trading analytics dashboard design (2026-09-06)

Approved in chat. Adds a persistent trade history, an analytics layer, and a chart-driven dashboard on top of the existing status page (local `web.StatusServer` and the `gh-pages` snapshot from `publisher.py`).

## Goals
- Every bot trade is stored durably, sourced from the broker's deal history rather than from what the bot happened to observe while awake.
- Desk-grade statistics: profit factor, expectancy, drawdown, streaks, holding time, and breakdowns by symbol, direction, hour, weekday, and exit reason.
- One HTML page with charts that works unchanged locally and on GitHub Pages.

## Module layout
| Module | Responsibility |
|---|---|
| `history.py` | `Deal` record, `TradeStore` (SQLite at `config.HISTORY_DB`), incremental `sync_deals()` from MT5, equity snapshots |
| `analytics.py` | Pure functions: pair deals into `Trade`s, `summary()`, `breakdown()`, `daily_pnl()`, `equity_curve()`, `drawdown()` |
| `status.py` | `build_status()` gains `account`, `analytics`, `history` blocks (computed from cached analytics) |
| `main.py` | `Bot` owns a `TradeStore`, syncs deals and snapshots equity every `HISTORY_SYNC_SECONDS`, recomputes analytics after each sync |
| `web/index.html` | KPI strip, Chart.js charts, per-symbol table, trade history table with sort/filter, positions, journal |
| `config.py` | `HISTORY_DB`, `HISTORY_SYNC_SECONDS`, `HISTORY_INCLUDE_ALL_DEALS`, `HISTORY_MAX_TRADES` |

## Data model
**deals** (one row per MT5 deal, primary key `ticket`): `order_id, position_id, symbol, type, entry, magic, reason, volume, price, commission, swap, profit, fee, time, comment`. Written with INSERT OR REPLACE so re-syncing an overlapping window is idempotent.

**equity** (one row per snapshot, primary key `time` epoch): `balance, equity, margin, free_margin, open_pnl`.

Sync: on first run query `history_deals_get` from 2000-01-01; afterwards from `last_deal_time - 1 day` to `now + 2 days` (the overlap catches deals whose commission or swap was amended). Rows are filtered to `config.MAGIC_NUMBER` unless `HISTORY_INCLUDE_ALL_DEALS` is true. `Deal.from_mt5()` copies the MT5 named tuple into a plain dataclass so everything downstream is testable without a terminal; attributes missing on fakes default to zero or empty.

## Trade pairing
A `Trade` is one `position_id` with at least one IN deal and enough OUT volume to close it (tolerance one volume step). Fields: `position_id, symbol, side, volume, entry_time, entry_price, exit_time, exit_price, gross, commission, swap, net, reason, duration_s, hour, weekday`. Multiple OUT deals (partial closes) are summed; the exit price is volume-weighted; the reason is the last OUT deal's reason mapped to `TP`, `SL`, `manual`, or `other`. INOUT deals count as OUT. Positions without a close are ignored (they are the open positions, shown live).

## Metrics (`analytics.summary`)
`trades, wins, losses, win_rate, net, gross_profit, gross_loss, profit_factor, expectancy, avg_win, avg_loss, payoff_ratio, largest_win, largest_loss, max_win_streak, max_loss_streak, avg_duration_s, max_drawdown, max_drawdown_pct, total_commission, total_swap`. Profit factor is `null` when there are no losses. Drawdown is measured on the cumulative net P&L curve ordered by exit time; the percent uses the first known balance from the equity table when available, otherwise `null`.

`breakdown(trades, key)` groups by `symbol`, `side`, `reason`, `hour`, or `weekday` and returns `summary()` per group. `daily_pnl()` returns `[{date, net, trades}]`. `equity_curve()` returns `[{time, cum}]` per closed trade.

## Snapshot payload additions
```
account:   {balance, equity, margin, free_margin, currency}       # None when MT5 has no account
analytics: {summary, by_symbol, by_side, by_reason, by_hour, by_weekday,
            daily (last 90 days), equity_curve (last 1000 points),
            equity_snapshots (hourly, last 30 days)}
history:   [Trade dicts, newest first, last HISTORY_MAX_TRADES]
```
Analytics are recomputed only after a sync (every `HISTORY_SYNC_SECONDS`, default 60) and cached on the `Bot`, so a tick stays cheap.

## Page
- Header pills (bot online, market, breaker) and the KPI strip: equity, balance, today net, total net, profit factor, expectancy, win rate, max drawdown.
- Charts (Chart.js 4, pinned on cdnjs): equity curve with a drawdown chart beneath it, daily P&L bars, net by hour of day, and three small breakdown bars for symbol, direction, and exit reason. Positive and negative values use the status greens and reds already on the page; single-series charts use the accent blue; gridlines are hairline and recessive.
- Tables: per-symbol statistics, open positions, trade history with clickable column sorting and symbol/side filters, recent journal rows.
- Light and dark mode via `prefers-color-scheme`; the page degrades to tables if the chart script cannot load.

## Compatibility
- `simulate.py`'s `FakeMT5` already returns deals with the fields the sync needs; `account_info()` falls through to the real package and returns `None`, which the code treats as "no account".
- `risk.get_daily_stats` is unchanged; the breaker logic still reads MT5 directly.

## Testing
- `tests/test_history.py`: store round-trip on a temp database, idempotent re-sync, incremental window, magic filtering, equity snapshots.
- `tests/test_analytics.py`: pairing with partial closes, every summary metric on a hand-computed set, breakdowns, daily P&L, drawdown.
- `tests/test_status.py`: new blocks present and JSON-serialisable.
- Visual check with headless Chrome screenshots of the page with sample data.

## Out of scope
MAE/MFE (needs tick data), backtest results on the page, authentication for the page, multi-account support.
