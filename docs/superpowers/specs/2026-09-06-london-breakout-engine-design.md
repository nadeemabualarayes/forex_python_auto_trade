# London breakout engine design (2026-09-06)

Draft for review. Adds a second, independent trading engine to the bot: a London-open range breakout
("Asian box" breakout) running under its own magic number next to the existing pin-bar mean-reversion
scalper. Chosen in chat on 2026-09-06 over an EMA-pullback trend engine because the London open is a
clean institutional liquidity catalyst and confines exposure to a few high-volume hours.

## 1. Goals and non-goals

Goals
- Raise portfolio trade frequency without touching the scalper's edge or its parameters.
- Trade a rule whose trigger is a known liquidity event (London open) rather than an indicator state.
- Keep every engine-specific number in `config.py`, testable without a terminal, and replayable in `backtest.py`.
- Protect the account with one shared daily-loss breaker while letting each engine keep its own entry cap
  and loss-streak limit (the "hybrid" risk policy chosen in chat).

Non-goals (v1)
- Adding EURUSD/GBPUSD to the scalper (they lose under the pin-bar rule in every variant tested).
- Box-edge stops, partial take-profit, pending stop orders at the box edges, an M15 variant.
- Per-engine risk budgets in account currency beyond the fixed `RISK_USD` per trade.

## 2. Evidence behind the defaults

Throwaway replay through `backtest.run_backtest` (same sizing, spread, breaker and exit code as live),
2026-03-10 to 2026-09-04, $5 risk per trade, four symbols, M5:

| Box / entry window (server time) | Buffer | Filter, exit | Trades | Net all | Net FX pair | Net metals | Min PF per symbol |
|---|---|---|---|---|---|---|---|
| 00-10 / 10-17 | 0 | H1 EMA200, fixed 1.5/3 ATR | 278 | +$156 | +$89 | +$67 | 1.12 |
| 00-10 / 10-12 | 0 | same | 162 | +$120 | +$92 | +$28 | 1.02 |
| 00-10 / 10-14 | 0 | same | 212 | +$83 | +$98 | -$15 | 0.85 |
| 00-07 / 07-11 (literal request) | 0.1 ATR | same | 210 | -$6 | -$18 | +$11 | 0.73 |
| 00-07 / 07-11 | 0 | H1 EMA200, 2 ATR stop + trail | 213 | +$110 | +$55 | +$55 | 0.98 |

Per symbol in the first row: EURUSD +$46, GBPUSD +$43, XAUUSD +$47, XAGUSD +$20, every symbol above
profit factor 1.1. With the literal 07:00-11:00 window and no buffer the fixed-exit result was -$31.

Findings that shaped the defaults:
- **Server time is UTC+3.** The London open (08:00 BST) is 10:00 server, so a 07:00-11:00 server window is
  the pre-London lull. The design keys the window to the London open and keeps the hours configurable.
- **Buffer.** A 0 buffer scored best in every window; 0.1 ATR cost $30-50 over six months; 0.25 ATR more.
  A small buffer is kept as a false-break guard because it was requested, at 0.1 ATR.
- **Exit.** Fixed 1.5/3 ATR beat trailing in every London-aligned window; 1:2 exits (1.0/2.0 ATR) lost everywhere.
- **Trend filter.** The H1 EMA200 filter raised the minimum profit factor in every window (fewer, better trades).
- **Symbols.** EURUSD and GBPUSD were positive in every London window; gold and silver flipped sign
  between windows. v1 trades the FX pair and leaves metals as an opt-in.
- **The edge is thin.** Averaged over all buffer/width/exit variants the rule is close to break-even, so
  the rollout below has explicit kill criteria and the EMA-pullback trend rule stays the documented fallback
  (it was positive on metals in all 24 variants tested, +$286 on M15).

## 3. Architecture: engine profiles

One `SymbolTrader` class, parameterised by an `Engine` profile. The scalper becomes profile #1 built from
today's config names, so its live behaviour does not change. The London engine is profile #2.

```text
config.py            scalper knobs (unchanged) + LDN_* block
engines.py  (new)    Engine dataclass + build_engines() -> [scalper, london]   (pure; reads config at build time)
london.py   (new)    pure rule: add_box_columns(df, hours), london_signal(bar)  (no MT5)
strategy.py          SymbolTrader(symbol, engine): gates unchanged, indicators/signal/levels/risk from the engine
execution.py         bot_positions(symbol=None, magic=None), send_market_order(..., engine), modify_sl(position, sl, magic)
risk.py              get_daily_stats(magic, now) unchanged; new combine(stats...) and split breaker helpers
position_manager.py  manage_positions(engine)  (per-engine ATR timeframe, BE/trail, magic)
history.py           sync_deals(store, magics)
main.py              Bot holds engines -> traders; per-engine stats; account breaker; per-engine pause
status.py / web      engine tag on positions, traders, history; per-engine day line
reporting.py         engine name in open/close/summary messages; summary per engine + total
backtest.py          --engine scalper|london ; run_backtest(df, ..., signal=, levels=) ; --telegram digest
simulate.py          FakeMT5 accepts any magic; both engines run on the scripted symbol
```

### 3.1 `Engine` profile (`engines.py`)

```python
@dataclass(frozen=True)
class Engine:
    name: str                 # "scalper" | "london"  (logs, journal note, Telegram, dashboard tag)
    magic: int
    comment: str              # MT5 order comment, e.g. "AlgoBot-LDN"
    symbols: tuple[str, ...]
    timeframe: int            # mt5.TIMEFRAME_*
    lookback: int             # bars fetched on the signal timeframe
    analyse: Callable         # (df, htf_df | None) -> df with indicator columns
    signal: Callable          # (closed bar) -> "BUY" | "SELL" | None
    sl_atr: float
    tp_atr: float
    risk_usd: float
    max_trades_per_day: int
    max_consecutive_losses: int
    manage: bool
    breakeven_atr: float
    trail_atr: float
```

`build_engines()` returns the enabled engines in order (scalper first). The scalper profile wires the
existing `technicals.compute_indicators` + `strategy.generate_signal` and today's config names
(`MAGIC_NUMBER`, `TIMEFRAME`, `RISK_USD_PER_TRADE`, `MAX_TRADES_PER_DAY`, `MAX_CONSECUTIVE_LOSSES`,
`MANAGE_POSITIONS`, ...). Pure signal functions keep reading `config` at call time, as they do now,
so existing tests that monkeypatch `config` still hold.

`init_mt5` receives the union of all engine symbols. A symbol that fails to select is dropped from
every engine that lists it; an engine left with no symbols is disabled with a log line.

### 3.2 London rule (`london.py`, pure)

Configuration (server time, `[start, end)` hours):

```python
LDN_ENABLED = True
LDN_MAGIC_NUMBER = 998878
LDN_SYMBOLS = ["EURUSD", "GBPUSD"]      # metals opt-in
LDN_TIMEFRAME = mt5.TIMEFRAME_M5
LDN_RATES_LOOKBACK = 300                 # covers box + window from 00:00 to 17:00 server on M5
LDN_BOX_START_HOUR = 0
LDN_BOX_END_HOUR = 10                    # London open on this broker (server = UTC+3)
LDN_WINDOW_END_HOUR = 14                 # entries allowed in [BOX_END, WINDOW_END)
LDN_BUFFER_ATR = 0.1                     # break = close beyond box edge +/- buffer * ATR(14)
LDN_MAX_BOX_ATR = 0.0                    # 0 = no box-width filter; else skip days with box > N * ATR
LDN_TREND_FILTER = True                  # H1 EMA200, same helper as the scalper
LDN_SL_ATR = 1.5
LDN_TP_ATR = 3.0
LDN_RISK_USD = 5.0
LDN_MAX_TRADES_PER_DAY = 2               # one per symbol per day by construction
LDN_MAX_CONSECUTIVE_LOSSES = 4
LDN_MANAGE_POSITIONS = False
LDN_BREAKEVEN_ATR = 1.0
LDN_TRAIL_ATR = 2.0
```

`add_box_columns(df)` adds per bar: `box_high`, `box_low` (max high / min low of the same server day's
bars inside the box hours; NaN before the box has any bar), `in_window`, and `first_break`
(True on the first closed bar of the day whose close is beyond an edge by the buffer). It needs `atr`
from `technicals.compute_indicators`, which the engine's `analyse` runs first; the trend EMA is attached
with the existing `attach_trend`.

`london_signal(bar)` returns BUY when `first_break` and close > box_high + buffer, SELL when
first_break and close < box_low - buffer, gated by `trend_allows` when the filter is on, else None.
A first break against the trend still consumes the day's attempt (matches the replay).
"One attempt per closed candle" in `SymbolTrader` remains the guard against re-sending on the same bar.

Because `first_break` is derived from the day's bars, a restart mid-day cannot produce a second entry:
the flag is true on exactly one bar per day whatever the process saw.

Levels and sizing: `strategy.build_levels(side, ask, bid, atr)` with the engine's `sl_atr`/`tp_atr`
(the function gains explicit multiplier arguments; the scalper passes its config values), then
`execution.lot_for_risk` with the engine's `risk_usd`.

Session filter: the scalper's `SESSION_*` and `TRADING_WEEKDAYS` gates still apply to every engine
(weekdays only); the London engine's own window is the tighter gate. The news blackout applies to every engine.

### 3.3 Risk policy (hybrid)

Per tick, `Bot` computes `stats[engine] = get_daily_stats(engine.magic, now)` and
`account = risk.combine(stats.values())` (sums net P&L, entries, wins/losses, merges closed deals in time
order; the account-level loss streak is not used).

- Account breaker: `account.net_pnl <= -MAX_DAILY_LOSS_USD` pauses all engines until the next server day
  (existing Telegram alert, now listing per-engine nets).
- Engine pause: `stats[e].consecutive_losses >= e.max_consecutive_losses` pauses only that engine;
  `stats[e].entries >= e.max_trades_per_day` is the per-engine cap passed to its traders.
  Each pause is logged once and shown on the dashboard; no Telegram spam beyond one message per pause.
- Two engines may hold positions in the same symbol at the same time (hedging account); both use the
  H1 EMA200 filter so they never take opposite sides. Each carries its own `risk_usd`.

`risk.breaker_reason(stats)` is split into `account_breaker(account)` and `engine_breaker(engine, stats)`,
both pure and unit-tested.

### 3.4 Execution, positions, trailing

- `bot_positions(symbol=None, magic=None)`: `magic=None` means "any engine's positions" (set of all
  engine magics), used by the dashboard, heartbeat and equity snapshot; traders pass their engine's magic.
- `send_market_order(..., engine)` stamps `engine.magic` and `engine.comment`; the Telegram open message
  gains an "Engine" line; the journal note carries the engine name.
- `modify_sl(position, new_sl, magic)`.
- `manage_positions(engine)` runs only for engines with `manage=True` (the London engine default is off,
  the scalper stays off) using the engine's timeframe for ATR and its BE/trail multiples.

### 3.5 History, analytics, dashboard, reporting

- `sync_deals(store, magics)` pulls every engine's deals; `Deal.magic` already exists, so `pair_trades`
  is unchanged and `trade_dicts` adds `engine` from a `{magic: name}` map (unknown magics show as `other`).
- `build_status` gains `engines: [{name, magic, symbols, entries, max_entries, net_pnl, wins, losses,
  consecutive_losses, paused}]`; `positions[*]` and `history[*]` gain `engine`; `day` stays the account
  view; `traders[*]` gain `engine`. `index.html`: engine column in positions and history (with a filter
  option), a one-line per-engine day strip under the KPI tiles. No other layout changes.
- `Reporter`: open/close messages name the engine; heartbeat shows entries per engine against its cap;
  daily summary lists per-engine net and the account total. `notify_closes` uses the combined closed list.
- `warn_if_trading_blocked` and the startup message list every engine with its symbols.

### 3.6 Backtest and simulation

- `backtest.py --engine london [--symbol EURUSD GBPUSD] --days 180 [--telegram]` selects the engine profile
  (`--symbol` defaults to the engine's own symbol list; `--engine` defaults to `scalper`):
  indicators via `engine.analyse`, entries via `engine.signal`, levels via the engine's multipliers, the
  engine's daily cap and streak limit, and `MANAGE_POSITIONS` from the engine. `run_backtest` takes the
  signal/levels callables as parameters (default: scalper) so it stays pure and testable. The `--telegram`
  digest names the engine.
- `simulate.py`: `FakeMT5` accepts orders with any magic and filters `positions_get`/`history_deals_get`
  by the requested magic; when both engines are enabled both run on the scripted symbol so the dry run
  exercises two magics, the combined breaker and the engine tags end to end.

## 4. Error handling

Unchanged per-iteration try/except in `main.run`. A failure inside one engine's trader is logged and does
not stop the other engine (each `trader.step` call is wrapped, matching the loop's existing style).
Every MT5 call that can return `None` stays guarded. `add_box_columns` tolerates days with no box bars
(holiday/late start) by yielding NaN edges, so no signal fires.

## 5. Testing

Unit (no terminal), following the repo's pure-function convention:
- `london.py`: box edges per day, NaN before the box, first-break exactly once per day, buffer applied,
  width filter, window bounds inclusive/exclusive, trend gate consumes the attempt, DST-free server hours.
- `engines.py`: scalper profile mirrors today's config; London profile from `LDN_*`; disabled engine omitted.
- `risk.py`: `combine` sums correctly; account breaker fires on the combined net; engine breaker only on
  its own streak; entry cap per engine.
- `execution.py`: `bot_positions` filters by magic set; order request carries the engine's magic/comment.
- `status.py`: engine block, tags on positions/history.
- `backtest.py`: `--engine london` replays a synthetic day with one box and one break; scalper path unchanged.
- `main.py`: tick with two engines; one engine paused, the other still steps.
- Existing 114 tests keep passing without modification of their assertions (only fixture wiring may change).

Integration: `python simulate.py --trades 40` with both engines enabled; `python backtest.py --engine london
--symbol EURUSD GBPUSD --days 180 --telegram` must reproduce the table in section 2 within rounding.

## 6. Rollout and kill criteria

1. Land the engine-profile refactor first (scalper behaviour identical: same tests, same journal rows).
2. Land the London engine, run the backtest digest to Telegram, dry-run with `simulate.py`.
3. Deploy to the demo bot (`install_task.ps1 -Restart`), both engines on, London on EURUSD and GBPUSD.
4. Four-week trial. Stop the London engine (set `LDN_ENABLED = False`) if, after 40 closed trades, its
   profit factor is below 0.9 or its drawdown exceeds $80, and fall back to the EMA-pullback trend engine
   design for the next iteration.

## 7. Implementation phases

- Phase 1: `engines.py`, `SymbolTrader(symbol, engine)`, magic-aware execution/risk/history/status,
  `manage_positions(engine)`, `run_backtest` callables, scalper-only wiring. Ships with zero behaviour change.
- Phase 2: `london.py`, `LDN_*` config, London profile, backtest `--engine`, dashboard/reporting tags,
  simulator support, rollout.
