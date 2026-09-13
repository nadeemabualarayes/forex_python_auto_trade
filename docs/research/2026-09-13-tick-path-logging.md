# Tick-path logging for exit research (scalp-test)

Date: 2026-09-13 · Branch/worktree: `scalp-test` / `C:\Develompent\forex_scalp_test` · Status: implemented and
validated, **not committed, not deployed, bot not restarted**.

## Scope

Make future exit-efficiency research able to know the **actual order** of favourable and adverse price movement
inside every trade. The 147-trade study had to work from M1 highs/lows, which cannot say whether the high or the
low of a minute came first, so every breakeven / trailing / protection counterfactual it produced was a bound, not
a result.

This change is observability only. It adds no filter, changes no entry, exit, stop, target, trailing, breakeven,
session, sizing, risk budget, symbol or configuration value, and sends nothing to Telegram. The pre-registered exit
experiment (protection at +0.5R, delayed trail from +0.75R) was **not** run; the screening script started for the
previous request was stopped before producing results and nothing from it was used.

## Files changed

| File | Change |
| --- | --- |
| `path_recorder.py` | **new** (584 lines) — the recorder plus pure helpers research can reuse |
| `tests/test_path_recorder.py` | **new** (482 lines) — 28 tests |
| `main.py` | +8 / −1 — create the recorder in `run()`, call `observe()` after each `Bot.tick()`, `close()` in `finally` |
| `tests/test_main.py` | +73 — 3 tests for the `run()` hook |

Unchanged (verified with `git diff --quiet`): `strategy.py`, `execution.py`, `config.py`, `risk.py`,
`position_manager.py`, `engines.py`, `journal.py`, `technicals.py`. `logs/trades.csv` and the journal are untouched.

The whole `main.py` change:

```diff
+from path_recorder import PathRecorder
 ...
     bot = Bot(symbols, web, pages, engines)
+    paths = PathRecorder(config.LOG_DIR, [e.magic for e in engines])
     try:
         while True:
             try:
-                time.sleep(bot.tick())
+                delay = bot.tick()
+                started = time.monotonic()
+                paths.observe()                          # research only: after all trading work; never raises
+                time.sleep(max(0.0, delay - (time.monotonic() - started)))
 ...
     finally:
+        paths.close()
```

`observe()` runs only after `tick()` has finished all trading work for that pass, and its duration is taken out of
the sleep, so the loop period stays `tick + delay` exactly as before.

## Data format

Location: `<LOG_DIR>/paths/` (inside `logs/`, which is gitignored). JSON Lines, append-only, one object per line.

* `XAUUSD_<position_id>.jsonl` — everything about one position, in the order it was observed.
* `index.jsonl` — one line per `open`, `resume`, `suspend`, `close` across all positions, for fast scanning.

Everything is keyed by the MT5 position identifier (`pid`, equal to the position ticket and to every deal's
`position_id`), never by timestamp alone. Times are broker server epochs in milliseconds (`*_msc`); `local` is the
PC's wall clock, for diagnostics only.

### Row types (`type`)

**`open`** — written once, at first sight of the position

| field | meaning |
| --- | --- |
| `schema` | 1 |
| `pid`, `symbol`, `side` (`LONG`/`SHORT`), `magic`, `volume` | identity; volume from the opening deal |
| `fill_msc`, `fill_price`, `fill_source` | broker-confirmed fill from the opening deal (`deal`), or the position record if the deal was not yet synced (`position`) |
| `sl0`, `tp0`, `sl0_source` | initial stop/target from the opening order (`order`); `position_first_seen` if unavailable |
| `stop_dist` | \|fill − sl0\| = 1R in price |
| `usd_per_unit_lot` | terminal-priced $ per 1.0 price move per lot (`order_calc_profit`); never `SYMBOL_TRADE_TICK_VALUE` |
| `quote_before_fill` | `{msc, bid, ask}` of the last broker tick at or before the fill, or `null` |
| `gap_ms`, `recorded_local` | the gap threshold in force; when the header was written |

**`tick`** — one row per broker tick from the fill to the exit

| field | meaning |
| --- | --- |
| `pid`, `seq` | position and a per-position sequence number (1, 2, 3 …; duplicates are detectable) |
| `msc`, `bid`, `ask`, `flags` | the raw broker tick (`copy_ticks_range`, `COPY_TICKS_ALL`), rounded to symbol digits |
| `spread_pts` | (ask − bid) / point |
| `symbol`, `side`, `volume`, `entry`, `sl0`, `tp` | position context at that tick |
| `sl` | stop in force per the broker snapshots (see ambiguity below) |
| `amb` | `true` if the stop, target or volume changed during a bracket that contains this tick |
| `mark` | bid for a long, ask for a short |
| `upnl` | (mark − entry) × side × `usd_per_unit_lot` × volume; `null` if terminal pricing was unavailable |
| `r` | (mark − entry) × side / `stop_dist`; `null` without an initial stop |

**`state`** — broker position snapshot, written at the fill and whenever SL, TP or volume changed:
`anchor_msc`, `prev_anchor_msc`, `sl`, `tp`, `volume`, `broker_profit`, `price_current`.

**`sl_move` / `tp_move` / `volume_change`** — `from`, `to`, `after_msc`, `by_msc`: the change happened after
`after_msc` and no later than `by_msc`.

**`gap`** — `from_msc`, `to_msc`, `ms`: consecutive recorded ticks more than 30 s apart.

**`unavailable`** — `from_msc`, `to_msc`, `error`: the terminal returned no tick data for a fetch. No rows are
invented for the missing span.

**`suspend`** — the bot shut down with the position open: `last_msc`, `anchor_msc`, `sl`, `tp`, `volume`.
**`resume`** — the recorder started and found the position's file: `last_msc`, `reason`.

**`close`** — written once

| field | meaning |
| --- | --- |
| `exit_msc`, `exit_price`, `exit_vwap` | last exit deal; volume-weighted over all exit deals |
| `reason_code`, `reason` | broker deal reason (`SL`, `TP`, `bot`, `manual`, `stopout`, `other`, `unknown`) |
| `label` | `SL` / `BE` / `TRAIL` / `TP` / … — a stop hit refined by where the final stop sat relative to entry |
| `final_sl`, `final_sl_source`, `final_sl_observed` | the stop that fired, from the broker's exit-deal comment `[sl X]` when present (`exit_deal_comment`), otherwise the last snapshot; plus what the snapshots last saw |
| `sl_moved` | whether the stop ever moved (observed move, or final stop ≠ sl0) |
| `deals` | every exit deal: ticket, entry, reason, time_msc, price, volume, profit, comment |
| `path_start_msc`, `path_end_msc`, `n_ticks` | first/last recorded tick and the count |
| `start_lag_ms`, `end_lag_ms`, `max_gap_ms`, `gaps`, `unavailable` | path quality measures |
| `complete`, `incomplete_reasons` | `true` only with no fetch failure, a first tick within 10 s of the fill, a last tick within 10 s of the exit, and no internal gap over 30 s; otherwise each defect is named (`tick_fetch_unavailable`, `no_ticks`, `late_first_tick`, `early_last_tick`, `internal_gap`, `exit_unknown`) |
| `quote_after_exit` | `{msc, bid, ask}` of the first broker tick after the exit, or `null` |
| `closed_while_recorder_down` | `true` when the close was reconciled on a later start |

## Lifecycle and capture design

1. **Detect.** Each pass calls `positions_get()` and keeps positions whose magic belongs to this bot's engines
   (manual trades on the account are ignored). A failed call (`None`) is skipped; a close is never inferred from a
   failed read.
2. **Open.** At first sight: the opening deal gives the fill time and price, the opening order gives the initial
   SL/TP, the terminal prices $ per point, and the last tick at or before the fill is stored.
3. **Every pass while open.** Take a broker snapshot (SL/TP/volume) anchored at the latest tick time, then fetch
   **every tick since the last recorded one** with `copy_ticks_range`. Nothing is sampled: a 2-second loop does not
   limit resolution, because each fetch returns all ticks the terminal holds for the interval. MT5 range queries are
   whole seconds, so fetches overlap by design; `new_ticks()` removes the overlap, including several ticks in the
   same millisecond, so nothing is lost or duplicated.
4. **Stop/target changes.** A change is only visible between two snapshots, so it is written with its bracket and the
   ticks inside the bracket are flagged `amb`. The exact stop in force at those ticks is never guessed.
5. **Close.** When the position disappears, the recorder waits (up to 60 s) for the exit deal, then fetches the
   remaining ticks up to the exit millisecond, records the first tick after it, the final stop (from the broker's
   exit comment when available), and the completeness verdict.
6. **Shutdown and restart.** `close()` writes `suspend` for open positions. On the next start, an open position with
   an existing file is resumed from its last recorded tick and the missing stretch is fetched from the terminal's tick
   history, so the path stays continuous. Positions that were opened, logged, and then closed while the recorder was
   down are finalised from the index on start-up (`closed_while_recorder_down: true`).
7. **Writes.** One append per position per pass, only after the rows are built. Recorder state advances only after
   the write succeeds, so a failed write is retried from the same point instead of silently skipping ticks, and a
   close is never written twice. `observe()` and `close()` catch every exception and log each distinct message once.

Cost measured against the real terminal: 0.02–0.05 ms per 2-second fetch, 0.05–0.15 ms per 10-minute restart
backfill. Storage is about 276 bytes per tick: 0.25–1.5 MB per trade on the positions validated, roughly 20 MB per
trading day at the current trade rate.

## Reconstructing MFE / MAE and ordering

For a position file loaded with `path_recorder.load_path(path)`:

* **Marking.** A long is marked at the **bid** and a short at the **ask** — the prices each could actually be
  closed at. Every tick row already carries `mark` and `r`.
* **MFE / MAE in R.** Maximum and minimum of `r` over the tick rows. In price units: `r × stop_dist`.
* **Ordering.** `threshold_touches(ticks, long, entry, stop_dist, levels)` returns the first millisecond each R level
  was touched (positive levels favourable, negative adverse). `first_reached(ticks, long, entry, stop_dist, a, b)`
  answers "was +0.5R reached before −0.5R?" with `a`, `b`, `neither`, or `same_tick` when both were first touched in
  the same millisecond.
* **Would a stop rule have fired?** Walk the tick rows in order and apply the rule's stop against `mark`. Where a
  rule needs the live stop, use `sl` and treat rows with `amb: true` as undetermined, not as either outcome.

Example from a real position (58423246980, TP exit): +0.25R at +34.0 s, +0.5R at +74.7 s, +0.75R at +133.0 s, +1R at
+229.1 s after the fill, and −0.5R never touched.

## Limitations

* **Broker ticks, not the order book.** The path is the quote stream the terminal received. Fills can differ from
  the recorded quotes; the fill itself always comes from the deal, and `quote_before_fill` shows the quote it
  executed against.
* **Millisecond resolution.** Ticks sharing a millisecond cannot be ordered in time; `first_reached` reports
  `same_tick` rather than choosing.
* **Stop changes are bracketed, not timestamped.** Snapshots happen once per loop (~2 s, up to 60 s while the account
  breaker has entries paused), so a stop move is known only to lie inside its bracket, and ticks inside it carry
  `amb`. The stop that actually fired is exact when the broker's exit comment carries it.
* **Stops filled at their level.** On this broker, stop exits fill at the stop price even when the last recorded tick
  was already beyond it; research must use the deal price for the exit, not the last tick.
* **Invisible positions.** A position that opens and closes entirely while the bot is not running never appears in
  the index and is not captured.
* **Sleep and history retention.** While the PC sleeps the terminal receives no ticks. The resume backfill relies on
  the terminal fetching history from the server; any span it cannot provide is flagged as `gap` or `unavailable`,
  never filled in. Backfill also depends on how far back the terminal keeps tick history.
* **Scope.** Only this bot's magic numbers are recorded; the scalp-test instance currently runs XAUUSD only.
* **Disk.** About 20 MB per trading day at the current pace; `logs/paths/` is not rotated.

## Tests and results

Full suite on `scalp-test`: **234 passed** (203 existing + 28 recorder + 3 hook), none failed.

Recorder tests (`tests/test_path_recorder.py`) cover:

* long marks at bid, short at ask; R from the initial stop distance; unrealised P&L from terminal pricing, never
  guessed
* overlapping fetches, including several ticks in the same millisecond, neither lost nor duplicated
* which R threshold a tick sequence reached first, for longs and shorts; `same_tick` reported rather than resolved
* stop-change brackets and the `amb` flag
* completeness verdicts naming each defect
* an end-to-end path from fill to exit: only ticks in [fill, exit], `seq` 1..n, stop move bracketed, close fields,
  quote after exit, index rows
* pairing by position id with two interleaved positions, a short marked at the ask, a manual position ignored
* a partial close keeps the same position id, records the volume change, and reports the volume-weighted exit
* shutdown writes `suspend`; a restart resumes with a backfill and no duplicates
* unavailable tick data logged as `unavailable`, no rows invented, path marked incomplete
* a failed `positions_get` never produces a close
* `observe()` and `close()` never raise
* a position closed while the recorder was down is finalised on the next start
* the recorder waits for the exit deal before closing
* a failed write is retried without losing or duplicating ticks; a close is written once even if the index write
  fails
* the final stop taken from the broker's exit comment when the move was never observed
* in `run()`: `observe()` after each completed tick only, `close()` on shutdown even when the first tick stops the
  loop, and the time spent recording taken out of the sleep

Read-only validation against the real terminal (four real closed scalp-test positions replayed through the recorder
into a scratch folder; no bot, no orders, nothing written under the bot's `logs/`):

| position | side | exit | ticks | complete | checks |
| --- | --- | --- | --- | --- | --- |
| 58424404413 | LONG | TRAIL | 924 | yes | final stop = exit fill 4344.19; quote before fill ask = fill price |
| 58424220335 | LONG | SL | 5,578 | yes | exit = stop 4343.68 = last tick bid; −0.5R at +149.9 s, +0.25R never |
| 58423246980 | LONG | TP | 1,673 | yes | +0.25/+0.5/+0.75/+1R all before −0.5R |
| 58424049405 | SHORT | TRAIL | 1,966 | yes | fill = quote bid; every tick marked at the ask; labelled TRAIL from the broker comment `[sl 4351.43]` alone |

All four: ticks strictly ordered, `seq` continuous, first tick at or after the fill, last tick at or before the exit,
start lag 1–84 ms, end lag 27–28 ms.

## Strategy behaviour unchanged

* No file that decides, sizes, places, manages or closes trades was modified (see "Files changed").
* `path_recorder.py` contains no `order_send`, `order_check`, stop modification, position close, journal write or
  Telegram call. Its only MT5 calls are `positions_get`, `symbol_info`, `symbol_info_tick`, `copy_ticks_range`,
  `history_deals_get`, `history_orders_get`, `order_calc_profit` and `last_error`.
* The recorder runs after `Bot.tick()` completes, never inside it, and cannot raise into the loop.
* The loop period is preserved: the sleep is shortened by exactly the recording time.
* No configuration value was added or changed; the $5 risk budget, terminal-first sizing and the sizing fix are intact.
* Nothing was committed, pushed or deployed. The bot was not restarted.

Operational note: both bots have been stopped since about 12:04 today (tasks in Ready state, market closed for the
weekend). The recorder takes effect only when the scalp-test bot is next started, which is your decision.

## Next research step

1. **Start collecting.** Restart the scalp-test bot with this code before the Monday open (requires your approval;
   configuration unchanged).
2. **Audit the first trading day** before trusting the data: every closed strategy position in the deal history has
   exactly one `close` row; at least 95% are `complete: true`; zero duplicate `seq`; the recorded tick count for a
   sample of positions equals an offline `copy_ticks_range` over the same interval; exit labels agree with the deal
   history.
3. **Accumulate** at least 150 closed positions with complete paths from the unchanged strategy, and keep manual
   trading off this account so the sample stays clean.
4. **Only then** run the pre-registered exit analysis (protection at +0.5R versus delayed trail from +0.75R) on the
   recorded paths, with thresholds fixed in advance and results reported against the current exit system.
