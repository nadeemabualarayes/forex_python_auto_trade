# Multi-symbol enhancements design (2026-09-06)

Approved in chat. Extends the single-symbol XAUUSD scalper into a multi-symbol engine with trend/session filters, position management, journaling, reporting, and a backtester.

## Module layout
| Module | Responsibility |
|---|---|
| `config.py` | `SYMBOLS` list, all tunables, Telegram creds from env |
| `technicals.py` | ATR / Bollinger / RSI on the trading TF, EMA for the trend TF |
| `risk.py` | Account-level daily stats from MT5 deal history: net P&L, loss streak, entries today, closed trades; breaker decision |
| `strategy.py` | Pure signal function + `SymbolTrader` (per-symbol state, spread/session/trend gates, sizing, order) |
| `position_manager.py` | Breakeven then ATR trailing stop on every open bot position |
| `journal.py` | Rotating file log + `logs/trades.csv` (entries, exits, SL moves) |
| `reporting.py` | Close notifications, heartbeat, end-of-day summary |
| `execution.py` | MT5 bridge: rates, sizing, market order, SL modify |
| `backtest.py` | Standalone replay of `strategy.generate_signal` over MT5 history |
| `main.py` | Orchestrator loop |

## Defaults
Trend: H1 EMA200 (buy above, sell below). Session: 07:00-20:00 server time Mon-Fri. Breakeven at 1.0 ATR, trail 1.0 ATR. Max 6 entries/day account-wide. Heartbeat every 4h. Summary 23:00 server time. Symbols: XAUUSD, XAGUSD.

## Time handling
All clocks use MT5 server time derived from `symbol_info_tick().time` (naive datetime via UTC conversion). Daily windows are computed as server-midnight epochs and deals are filtered in Python by `deal.time`, avoiding the local-vs-server ambiguity in `history_deals_get`.

## Error handling
Per-iteration try/except with Telegram alert and MT5 reconnect (unchanged). All MT5 calls that can return `None` are guarded.

## Testing
`tests/conftest.py` installs a fake `MetaTrader5` module so pure logic (signal, session, sizing, trailing SL, daily stats, backtest trade resolution) runs under pytest without the terminal. `backtest.py` doubles as an end-to-end check of the strategy code.

## Out of scope (v1)
Trailing stop simulation in the backtester; Telegram command interface; per-symbol risk budgets.
