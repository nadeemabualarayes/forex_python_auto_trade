# London breakout engine design (2026-09-06)

Implemented 2026-09-07 (plan: docs/superpowers/plans/2026-09-06-london-breakout-engine.md); demo deployment pending. Adds a second, independent trading engine to the bot: a London-open range breakout
("Asian box" breakout) on EURUSD and GBPUSD, running under its own magic number next to the existing
pin-bar mean-reversion scalper, which stays exclusively on XAUUSD and XAGUSD. Chosen in chat on
2026-09-06 because the London open is a clean institutional liquidity catalyst and the rule confines
exposure to a few high-volume hours.

## 1. Goals and non-goals

Goals
- Raise portfolio trade frequency and add FX exposure without touching the scalper's edge or parameters.
- Trade a rule whose trigger is a known liquidity event (London open) rather than an indicator state.
- Keep every engine-specific number in `config.py`, testable without a terminal, replayable in `backtest.py`.
- Protect the account with one shared daily-loss breaker while each engine keeps its own entry cap and
  loss-streak limit (the "hybrid" risk policy chosen in chat).

Non-goals (v1)
- Adding EURUSD/GBPUSD to the scalper (they lose under the pin-bar rule in every variant tested:
  profit factor 0.89 and 0.95, drawdowns $67 and $87).
- Partial take-profit, pending stop orders resting at the box edges, an M15 variant, metals on this engine
  (metals flipped sign between windows; they stay an opt-in via `LDN_SYMBOLS`).

## 2. Evidence behind the defaults

Throwaway replay of the rule through the live backtester's sizing, spread, breaker and exit code,
2026-03-10 to 2026-09-04, $5 risk per trade, M5, one trade per pair per day.

The rule as first specified (box 00:00-07:00 server, entries 07:00-11:00, 2-pip buffer, 2R target) has no edge:

| Stop | EURUSD | GBPUSD | Combined |
|---|---|---|---|
| Opposite box edge | 68 trades, PF 0.67, -$64 | 66 trades, PF 1.47, +$67 | +$3 |
| Box midpoint | 85 trades, PF 1.03, +$7 | 84 trades, PF 0.84, -$40 | -$34 |
| 1.5 ATR | 94 trades, PF 0.65, -$117 | 92 trades, PF 0.97, -$10 | -$127 |

A 3-pip buffer, 1.5R or 3R targets and the H1 trend filter did not change the picture (best cell +$3).

The same rule aligned to the broker clock, with no buffer, a 1.5 ATR stop, a 2R target and the H1 EMA200
filter, is the one configuration positive on both pairs in every window tried:

| Entry window (server) | Trades | EURUSD | GBPUSD | FX net | Min PF |
|---|---|---|---|---|---|
| 10:00-12:00 | 162 | +$39 | +$52 | +$92 | 1.02 |
| 10:00-14:00 | 212 | +$54 | +$44 | +$98 | 0.85 |
| 10:00-17:00 | 278 | +$46 | +$43 | +$89 | 1.12 |

Findings that shaped the defaults:
- **Server time is UTC+3** (last Friday tick 23:59:55 server = 20:59:55 UTC). The London open, 08:00 BST,
  is 10:00 server; 07:00-11:00 server is the pre-London lull. All hours are config knobs.
- **Buffer.** Median M5 ATR is 3.0 pips on EURUSD and 3.7 on GBPUSD, so a 2-pip buffer is 0.5-0.7 ATR of
  late entry per trade and cost $20-60 per window. Default buffer is 0 pips; the knob stays for live tuning.
- **Stop.** Box-edge and midpoint stops with a 2R target won 26-41% of trades against a 33% break-even and
  were negative or flat; the ATR stop is the default and the box stops remain selectable.
- **Trend filter.** The H1 EMA200 gate raised the minimum profit factor in every London-aligned window.
- **The edge is thin**: about $90 over six months, 0.09R per trade. The rollout has explicit kill criteria,
  and the EMA-pullback trend rule on metals (+$286 on M15, positive in all 24 variants) is the documented
  fallback.

## 3. Architecture: engine profiles

One `SymbolTrader` class, parameterised by an `Engine` profile. The scalper becomes profile #1 built from
today's config names, so its live behaviour does not change. The London engine is profile #2.

```text
config.py            scalper knobs (unchanged) + LDN_* block
engines.py  (new)    Engine dataclass + build_engines() -> [scalper, london]   (pure; reads config at build time)
london.py   (new)    pure rule: pip_size, add_box_columns(df), london_signal(bar), london_levels(...)  (no MT5)
strategy.py          SymbolTrader(symbol, engine): gates unchanged; indicators/signal/levels/risk from the engine
execution.py         bot_positions(symbol=None, magic=None), send_market_order(..., engine), modify_sl(position, sl, magic)
risk.py              get_daily_stats(magic, now) unchanged; new combine(stats...), account_breaker, engine_breaker
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
    levels: Callable          # (side, ask, bid, closed bar) -> strategy.Levels | None
    risk_usd: float
    max_trades_per_day: int
    max_consecutive_losses: int
    manage: bool
    breakeven_atr: float
    trail_atr: float
```

`build_engines()` returns the enabled engines in order (scalper first). The scalper profile wires
`technicals.compute_indicators`, `strategy.generate_signal`, `strategy.build_levels` (reading
`SL_ATR_MULTIPLIER`/`TP_ATR_MULTIPLIER` at call time) and today's config names (`MAGIC_NUMBER`,
`TIMEFRAME`, `RISK_USD_PER_TRADE`, `MAX_TRADES_PER_DAY`, `MAX_CONSECUTIVE_LOSSES`, `MANAGE_POSITIONS`, ...).
Pure signal and level functions keep reading `config` at call time, as they do now, so existing tests
that monkeypatch `config` still hold.

`init_mt5` receives the union of all engine symbols. A symbol that fails to select is dropped from every
engine that lists it; an engine left with no symbols is disabled with a log line.

### 3.2 London rule (`london.py`, pure)

Configuration (server time, `[start, end)` hours):

```python
LDN_ENABLED = True
LDN_MAGIC_NUMBER = 998888
LDN_SYMBOLS = ["EURUSD", "GBPUSD"]      # metals opt-in
LDN_TIMEFRAME = mt5.TIMEFRAME_M5
LDN_RATES_LOOKBACK = 300                 # covers box + window from 00:00 to 17:00 server on M5
LDN_BOX_START_HOUR = 0
LDN_BOX_END_HOUR = 10                    # London open on this broker (server clock = UTC+3)
LDN_WINDOW_END_HOUR = 14                 # entries allowed in [BOX_END, WINDOW_END)
LDN_BUFFER_PIPS = 0.0                    # break = close beyond the edge by this many pips (0 tested best)
LDN_MAX_BOX_ATR = 0.0                    # 0 = no box-width filter; else skip days with box > N * ATR(14)
LDN_TREND_FILTER = True                  # H1 EMA200, same helper as the scalper
LDN_SL_MODE = "atr"                      # "atr" | "box_opposite" | "box_mid"
LDN_SL_ATR = 1.5                         # stop distance when LDN_SL_MODE == "atr"
LDN_TP_R = 2.0                           # target = LDN_TP_R x stop distance
LDN_RISK_USD = 5.0
LDN_MAX_TRADES_PER_DAY = 2               # one per pair per day by construction
LDN_MAX_CONSECUTIVE_LOSSES = 4
LDN_MANAGE_POSITIONS = False
LDN_BREAKEVEN_ATR = 1.0
LDN_TRAIL_ATR = 2.0
```

`pip_size(point, digits)`: `point * 10` for 3- and 5-digit symbols, else `point`.

`add_box_columns(df, pip)` adds per bar: `box_high`, `box_low` (max high / min low of the same server
day's bars inside the box hours, carried on every bar of that day; NaN on days without box bars; breaks
are only evaluated inside the entry window, so this is not look-ahead), `in_window`, and `first_break` (True on the
first closed bar of the day inside the window whose close is beyond an edge by `LDN_BUFFER_PIPS` pips and,
when `LDN_MAX_BOX_ATR` > 0, whose box is narrower than that many ATR). It needs `atr` from
`technicals.compute_indicators`, which the engine's `analyse` runs first; the trend EMA is attached with
the existing `attach_trend`.

`london_signal(bar)` returns BUY when `first_break` and close > box_high + buffer, SELL when `first_break`
and close < box_low - buffer, gated by `trend_allows` when the filter is on, else None. A first break
against the trend still consumes the day's attempt (matches the replay). "One attempt per closed candle"
in `SymbolTrader` remains the guard against re-sending on the same bar.

`london_levels(side, ask, bid, bar)` returns `strategy.Levels` or None. Entry is ask (BUY) / bid (SELL).
Stop by mode: `atr` -> entry -/+ `LDN_SL_ATR` x ATR; `box_opposite` -> box_low for BUY, box_high for SELL;
`box_mid` -> the box midpoint. If the stop distance is not positive the function returns None and the
trader records a SKIP. Target = entry +/- `LDN_TP_R` x stop distance. Sizing uses `execution.lot_for_risk`
with the stop distance and `LDN_RISK_USD`; a zero lot is a SKIP as today.

Because `first_break` is derived from the day's bars, a restart mid-day cannot produce a second entry:
the flag is true on exactly one bar per day whatever the process saw.

Session filter: the scalper's `SESSION_*` and `TRADING_WEEKDAYS` gates still apply to every engine
(weekdays only); the London engine's own window is the tighter gate. The news blackout applies to every
engine. Spread caps come from `MAX_ALLOWED_SPREAD_POINTS`, which gains entries for EURUSD (10) and GBPUSD (15).

### 3.3 Risk policy (hybrid)

Per tick, `Bot` computes `stats[engine] = get_daily_stats(engine.magic, now)` and
`account = risk.combine(stats.values())` (sums net P&L, entries, wins/losses, merges closed deals in time
order; the account-level loss streak is not used).

- Account breaker: `account.net_pnl <= -MAX_DAILY_LOSS_USD` pauses all engines until the next server day
  (existing Telegram alert, now listing per-engine nets).
- Engine pause: `stats[e].consecutive_losses >= e.max_consecutive_losses` pauses only that engine;
  `stats[e].entries >= e.max_trades_per_day` is the per-engine cap passed to its traders.
  Each pause is logged once and shown on the dashboard; one Telegram message per pause.
- Two engines may hold positions in the same symbol at the same time (hedging account); with the default
  symbol lists they never share a symbol. Each carries its own `risk_usd`.

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
  consecutive_losses, paused}]`; `positions[*]`, `traders[*]` and `history[*]` gain `engine`; `day` stays
  the account view. `index.html`: engine column in positions and history (with a filter option) and a
  one-line per-engine day strip under the KPI tiles. No other layout changes.
- `Reporter`: open/close messages name the engine; heartbeat shows entries per engine against its cap;
  daily summary lists per-engine net and the account total. `notify_closes` uses the combined closed list.
- `warn_if_trading_blocked` and the startup message list every engine with its symbols.

### 3.6 Backtest and simulation

- `backtest.py --engine london [--symbol EURUSD GBPUSD] --days 180 [--telegram]` selects the engine profile
  (`--symbol` defaults to the engine's own symbol list; `--engine` defaults to `scalper`): indicators via
  `engine.analyse`, entries via `engine.signal`, levels via `engine.levels`, the engine's daily cap, streak
  limit and `manage` flag. `run_backtest` takes the signal/levels callables as parameters (default: scalper)
  so it stays pure and testable. The `--telegram` digest names the engine.
- `simulate.py`: `FakeMT5` accepts orders with any magic and filters `positions_get`/`history_deals_get`
  by the requested magic; when both engines are enabled both run on the scripted symbol so the dry run
  exercises two magics, the combined breaker and the engine tags end to end.

## 4. Error handling

Unchanged per-iteration try/except in `main.run`. A failure inside one engine's trader is logged and does
not stop the other engine (each `trader.step` call is wrapped, matching the loop's existing style).
Every MT5 call that can return `None` stays guarded. `add_box_columns` tolerates days with no box bars
(holiday, late start) by yielding NaN edges, so no signal fires.

## 5. Testing

Unit (no terminal), following the repo's pure-function convention:
- `london.py`: pip size per digits; box edges per day; NaN before the box; first-break exactly once per day;
  buffer in pips applied; width filter; window bounds inclusive/exclusive; trend gate consumes the attempt;
  `london_levels` for the three stop modes, 2R target, None on a non-positive stop distance.
- `engines.py`: scalper profile mirrors today's config; London profile from `LDN_*`; disabled engine omitted.
- `risk.py`: `combine` sums correctly; account breaker fires on the combined net; engine breaker only on
  its own streak; entry cap per engine.
- `execution.py`: `bot_positions` filters by magic set; order request carries the engine's magic/comment.
- `status.py`: engine block, tags on positions/history.
- `backtest.py`: `--engine london` replays a synthetic day with one box and one break; scalper path unchanged.
- `main.py`: tick with two engines; one engine paused, the other still steps.
- Existing 114 tests keep passing without changes to their assertions (only fixture wiring may change).

Integration: `python simulate.py --trades 40` with both engines enabled; `python backtest.py --engine london
--days 180 --telegram` must reproduce the 10:00-14:00 row in section 2 within rounding.

## 6. Rollout and kill criteria

1. Land the engine-profile refactor first (scalper behaviour identical: same tests, same journal rows).
2. Land the London engine, run the backtest digest to Telegram, dry-run with `simulate.py`.
3. Deploy to the demo bot (`install_task.ps1 -Restart`), both engines on, London on EURUSD and GBPUSD.
4. Four-week trial. Disable the London engine (`LDN_ENABLED = False`) if, after 40 closed trades, its
   profit factor is below 0.9 or its drawdown exceeds $80, and fall back to the EMA-pullback trend engine
   design for the next iteration.

## 7. Implementation phases

- Phase 1: `engines.py`, `SymbolTrader(symbol, engine)`, magic-aware execution/risk/history/status,
  `manage_positions(engine)`, `run_backtest` callables, scalper-only wiring. Ships with zero behaviour change.
- Phase 2: `london.py`, `LDN_*` config, London profile, backtest `--engine`, dashboard/reporting tags,
  simulator support, rollout.
