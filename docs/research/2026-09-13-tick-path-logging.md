# Tick-path logging for exit research (scalp-test)

Date: 2026-09-13 · Branch/worktree: `scalp-test` / `C:\Develompent\forex_scalp_test` · File schema: **2**

## Status

* **Schema 1** of the recorder (with its tests, the `run()` hook and the first version of this note) is in commit
  `8c4061d` on `scalp-test`, made at 13:05 under the repository owner's git identity and pushed to
  `origin/scalp-test`. That commit was not made from the Claude session that wrote the code.
* **Schema 2** (this note) is in the working tree, uncommitted. With approval, the scalp-test bot (task
  `ForexScalpTest`) was restarted with it at 16:09:30 (configuration identical to the previous start: scalper, magic
  998811, XAUUSD, $5.00/trade, cap 60/day). It had run schema 1 from 13:19:57 while the market was closed, recording
  nothing.
* At start-up the discovery scan recorded the two positions that closed within 15 minutes of the market's last tick
  on Friday 11 Sep (`found_via: "deal_history"`), both checked against the terminal: 58424220335 (SL at the initial
  stop, 5,578 ticks, all equal to the terminal's, stop proven by the exit comment, 0 ambiguous) and 58424404413
  (TRAIL, 924 ticks, all equal, stop move known only from the exit comment, so all 924 ambiguous about the stop).
  They predate the recorder; exclude them from forward-collected samples if needed.
* `main` is untouched.

## Scope

Make future exit-efficiency research able to know the **actual order** of favourable and adverse price movement
inside every trade. The 147-trade study had to work from M1 highs/lows, which cannot say whether the high or the
low of a minute came first, so every breakeven / trailing / protection counterfactual it produced was a bound, not
a result.

This change is observability only. It adds no filter, changes no entry, exit, stop, target, trailing, breakeven,
session, sizing, risk budget, symbol or configuration value, and sends nothing to Telegram. The pre-registered exit
experiment (protection at +0.5R, delayed trail from +0.75R) was **not** run.

## What the replay audit changed (schema 1 to schema 2)

Every real scalp-test position was replayed through the recorder's live code path (see "Replay audit" below). The
audit found two defects, and reviewing their fixes found two more:

1. **Positions that open and close between two passes got no file.** Position 58343386760 lived 1.38 s (fill
   08:30:02.874, TP 08:30:04.254) and fell between two 2-second passes. Schema 2 scans recent deal history every
   60 s of server time and records such positions from the terminal's tick history (`found_via: "deal_history"`).
2. **`quote_after_exit` was `null` on 4 of 155 positions.** The first quote after the exit arrived 0.07 to 0.57 s
   after the recorder had already written the close. Schema 2 holds the close for up to 10 s until that quote
   arrives; a tick fetch that fails at close time is retried within the same window instead of leaving the path
   incomplete.
3. **Ticks stamped past the exit** (found in review; the replay cannot produce it). The terminal's position list can
   lag its tick feed, so a pass may still list a position after ticks past its exit have arrived and been written.
   Schema 2 counts them in `ticks_after_exit`, computes the path end, tick count and completeness from ticks at or
   before the exit, takes `quote_after_exit` from the first of them, and `load_path` returns them apart
   (`after_exit`), never as part of the path.
4. **A closed file could be reopened.** A position missing from the list for more than 60 s with no exit deal is
   closed as `exit_unknown`; if it then reappeared, schema 1 appended a second `open` header to the closed file.
   Schema 2 never writes to a file that holds a close.

## Files (against `07ff91d`, the scalp-test commit before any recorder work)

| File | Change |
| --- | --- |
| `path_recorder.py` | **new**, 703 lines: the recorder plus pure helpers research can reuse |
| `tests/test_path_recorder.py` | **new**, 708 lines, 37 tests |
| `main.py` | +7 / −1: create the recorder in `run()`, `observe()` after each `Bot.tick()`, `close()` in `finally` |
| `tests/test_main.py` | +82: 4 tests for the `run()` hook |
| `docs/research/path_recorder_replay_audit.py` | **new**, 415 lines: the replay audit (read-only) |
| `docs/research/2026-09-13-path-recorder-replay-audit.txt` | **new**: its output |

Unchanged (checked with `git diff --quiet`): `strategy.py`, `execution.py`, `config.py`, `risk.py`,
`position_manager.py`, `engines.py`, `journal.py`, `technicals.py`, `candles.py`, `london.py`, `news.py`,
`reporting.py`, `history.py`, `analytics.py`, `status.py`. `logs/trades.csv` and the journal are untouched.

The whole `main.py` change:

```diff
+from path_recorder import PathRecorder
 ...
     bot = Bot(symbols, web, pages, engines)
+    paths = PathRecorder(config.LOG_DIR, [e.magic for e in engines], symbols)
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
the sleep, so the loop period stays `tick + delay` exactly as before. `symbols` (the tradable symbols) gives the
recorder the server clock for its deal-history scan.

## Data format

Location: `<LOG_DIR>/paths/` (inside `logs/`, which is gitignored). JSON Lines, append-only, one object per line.

* `XAUUSD_<position_id>.jsonl`: everything about one position, in the order it was observed.
* `index.jsonl`: one line per `open`, `resume`, `suspend`, `close` across all positions, for fast scanning.

Everything is keyed by the MT5 position identifier (`pid`, equal to the position ticket and to every deal's
`position_id`), never by timestamp alone. Times are broker server epochs in milliseconds (`*_msc`); `local` is the
PC's wall clock, for diagnostics only. Read files with `path_recorder.load_path(path)`.

### Row types (`type`)

**`open`**: written once

| field | meaning |
| --- | --- |
| `schema` | 2 |
| `pid`, `symbol`, `side` (`LONG`/`SHORT`), `magic`, `volume` | identity; volume from the opening deal |
| `fill_msc`, `fill_price`, `fill_source` | broker-confirmed fill from the opening deal (`deal`), or the position record if the deal was not yet synced (`position`) |
| `sl0`, `tp0`, `sl0_source` | initial stop/target from the opening order (`order`); `position_first_seen` if unavailable |
| `stop_dist` | abs(fill − sl0) = 1R in price |
| `usd_per_unit_lot` | terminal-priced $ per 1.0 price move per lot (`order_calc_profit`); never `SYMBOL_TRADE_TICK_VALUE` |
| `quote_before_fill` | `{msc, bid, ask}` of the last broker tick at or before the fill, or `null` |
| `found_via` | `positions` (a pass listed it while open) or `deal_history` (the scan found it after it had closed) |
| `gap_ms`, `recorded_local` | the gap threshold in force; when the header was written |

**`tick`**: one row per broker tick from the fill to the exit

| field | meaning |
| --- | --- |
| `pid`, `seq` | position and a per-position sequence number (1, 2, 3 …; duplicates are detectable) |
| `msc`, `bid`, `ask`, `flags` | the raw broker tick (`copy_ticks_range`, `COPY_TICKS_ALL`), rounded to symbol digits |
| `spread_pts` | (ask − bid) / point |
| `symbol`, `side`, `volume`, `entry`, `sl0`, `tp` | position context at that tick |
| `sl` | stop in force according to the broker snapshots |
| `amb` | `true` when the stop, target or volume in force at this tick is not known: the tick lies inside a change bracket, or after the last snapshot of a position whose exit does not prove the stop unchanged. The value shown is the last one seen before the uncertainty |
| `mark` | bid for a long, ask for a short |
| `upnl` | (mark − entry) × side × `usd_per_unit_lot` × volume; `null` if terminal pricing was unavailable |
| `r` | (mark − entry) × side / `stop_dist`; `null` without an initial stop |

**`state`**: broker position snapshot, written at the fill and whenever SL, TP or volume changed:
`anchor_msc` (latest tick time when the snapshot was read), `prev_anchor_msc`, `sl`, `tp`, `volume`,
`broker_profit`, `price_current`.

**`sl_move` / `tp_move` / `volume_change`**: `from`, `to`, `amb_after_msc`, `amb_until_msc`. Ticks with
`msc <= amb_after_msc` were under `from`, ticks with `msc > amb_until_msc` under `to`; ticks in between carry
`amb: true`. An `sl_move` with `note: "seen_only_in_exit_deal"` is a stop move no snapshot saw, known only from the
broker's exit comment; its bracket runs from the last snapshot to the exit.

**`gap`**: `from_msc`, `to_msc`, `ms`: consecutive recorded ticks more than 30 s apart.

**`unavailable`**: `from_msc`, `to_msc`, `error`: the terminal returned no tick data for a fetch. No rows are
invented for the missing span.

**`suspend`**: the bot shut down with the position open: `last_msc`, `anchor_msc`, `sl`, `tp`, `volume`.
**`resume`**: the recorder started and found the position's file: `last_msc`, `reason`.

**`close`**: written once

| field | meaning |
| --- | --- |
| `exit_msc`, `exit_price`, `exit_vwap` | last exit deal; volume-weighted over all exit deals |
| `reason_code`, `reason` | broker deal reason (`SL`, `TP`, `bot`, `manual`, `stopout`, `other`, `unknown`) |
| `label` | `SL` / `BE` / `TRAIL` / `TP` / …: a stop hit refined by where the final stop sat relative to entry |
| `final_sl`, `final_sl_source`, `final_sl_observed` | the stop that fired, from the broker's exit comment `[sl X]` when present (`exit_deal_comment`), otherwise the last snapshot (`last_snapshot`); plus what the snapshots last saw |
| `sl_moved` | whether the stop ever moved (observed move, or final stop different from sl0) |
| `tail_after_msc`, `tail_verified` | anchor of the last snapshot; `true` when the broker's exit stop equals the last stop seen, which proves no move after it (stops only tighten). Otherwise ticks after `tail_after_msc` carry `amb: true` |
| `deals` | every exit deal: ticket, entry, reason, time_msc, price, volume, profit, comment |
| `path_start_msc`, `path_end_msc`, `n_ticks` | first/last tick at or before the exit, and the count |
| `ticks_after_exit` | tick rows written before the terminal dropped the position but stamped after its exit (normally 0; excluded from every other field) |
| `start_lag_ms`, `end_lag_ms`, `max_gap_ms`, `gaps`, `unavailable` | path quality measures |
| `complete`, `incomplete_reasons` | `true` only with no fetch failure, a first tick within 10 s of the fill, a last tick within 10 s of the exit, and no internal gap over 30 s; otherwise each defect is named (`tick_fetch_unavailable`, `no_ticks`, `late_first_tick`, `early_last_tick`, `internal_gap`, `exit_unknown`) |
| `quote_after_exit` | `{msc, bid, ask}` of the first broker tick after the exit, if one arrived within 10 s of it; `null` otherwise |
| `closed_while_recorder_down` | `true` when the close was reconciled on a later start |
| `found_via` | as in `open` |

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
   ticks inside the bracket are flagged `amb`. The exact stop in force at those ticks is never guessed. The brackets
   rely on the bot's design: stops are modified only inside `Bot.tick()`, which never runs while the recorder reads.
5. **Close.** When the position disappears, the recorder waits (up to 60 s) for the exit deal, fetches the remaining
   ticks up to the exit millisecond, and waits (up to 10 s) for the first quote after the exit, retrying a failed
   fetch in that time. Nothing is written or committed while it waits. The final stop comes from the broker's exit
   comment when present; ticks after the last snapshot are flagged unless the exit stop proves the stop unchanged;
   ticks already written past the exit are counted and excluded.
6. **Discovery.** Every 60 s of server time (the latest tick time of the bot's symbols, which stops with the market)
   the last 15 minutes of deal history are scanned. A bot position that is not listed, has no file and is fully
   closed is recorded from the terminal's history: fill from the opening deal, initial stop from the opening order,
   every tick from the fill to the exit, and `found_via: "deal_history"`. No snapshot ever saw its stop after the
   fill, so its ticks carry `amb: true` unless the exit proves the stop never moved.
7. **Shutdown and restart.** `close()` writes `suspend` for open positions. On the next start, an open position with
   an existing file is resumed from its last recorded tick and the missing stretch is fetched from the terminal's tick
   history, so the path stays continuous. Positions that were opened, logged, and then closed while the recorder was
   down are finalised from the index on start-up (`closed_while_recorder_down: true`). A file that holds a close is
   never written to again.
8. **Writes.** One append per position per pass, only after the rows are built. Recorder state advances only after
   the write succeeds, so a failed write is retried from the same point instead of silently skipping ticks, and a
   close is never written twice. `observe()` and `close()` catch every exception and log each distinct message once.

Cost measured against the real terminal: 0.02–0.05 ms per 2-second fetch, 0.05–0.15 ms per 10-minute restart
backfill, 0.05 ms (median; 0.14 ms max) per deal-history scan, once a minute. Storage is about 276 bytes per tick:
0.25–1.5 MB per trade on the positions validated, roughly 20 MB per trading day at the current trade rate.

## Reconstructing MFE / MAE and ordering

For a position file loaded with `path_recorder.load_path(path)` (ticks from the fill to the exit only; `after_exit`
holds any rows written past the exit):

* **Marking.** A long is marked at the **bid** and a short at the **ask**, the prices each could actually be
  closed at. Every tick row already carries `mark` and `r`.
* **MFE / MAE in R.** Maximum and minimum of `r` over the tick rows. In price units: `r × stop_dist`.
* **Ordering.** `threshold_touches(ticks, long, entry, stop_dist, levels)` returns the first millisecond each R level
  was touched (positive levels favourable, negative adverse). `first_reached(ticks, long, entry, stop_dist, a, b)`
  answers "was +0.5R reached before −0.5R?" with `a`, `b`, `neither`, or `same_tick` when both were first touched in
  the same millisecond.
* **Would a stop rule have fired?** Walk the tick rows in order and apply the rule's stop against `mark`. Where a
  rule needs the live stop, use `sl` and treat rows with `amb: true` as undetermined, not as either outcome.
* **Found in deal history.** Price paths of `found_via: "deal_history"` positions are as complete as any other, but
  their live stop is known only at the fill (and at the exit when `tail_verified`), so stop-dependent rules are
  undetermined on their `amb` rows.

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
* **Positions no pass listed** are found only if they closed within 15 minutes (server time) of a scan. A position
  whose whole life fell inside a longer outage (an order sent just before a crash and closed more than 15 minutes
  before the next start) is not captured. A position closed by hand is found only while its opening deal is inside
  the scan window, because a manual exit deal carries magic 0, not the bot's.
* **`quote_after_exit` is `null`** when no quote arrived within about 10 s of the exit (market close, daily break).
* **A position missing from the terminal's list for more than 60 s without an exit deal** is closed as `exit_unknown`;
  if it reappears, the rest of its life is not recorded.
* **Sleep and history retention.** While the PC sleeps the terminal receives no ticks. The resume backfill relies on
  the terminal fetching history from the server; any span it cannot provide is flagged as `gap` or `unavailable`,
  never filled in. Backfill also depends on how far back the terminal keeps tick history.
* **Scope.** Only this bot's magic numbers are recorded; the scalp-test instance currently runs XAUUSD only.
* **Disk.** About 20 MB per trading day at the current pace; `logs/paths/` is not rotated.

## Tests and results

Full suite on `scalp-test`: **244 passed** (203 existing + 37 recorder + 4 hook), none failed.

Recorder tests (`tests/test_path_recorder.py`) cover:

* long marks at bid, short at ask; R from the initial stop distance; unrealised P&L from terminal pricing, never
  guessed
* overlapping fetches, including several ticks in the same millisecond, neither lost nor duplicated
* which R threshold a tick sequence reached first, for longs and shorts; `same_tick` reported rather than resolved
* stop-change brackets and the `amb` flag, including a tick exactly at the snapshot anchor
* completeness verdicts naming each defect
* an end-to-end path from fill to exit: only ticks in [fill, exit], `seq` 1..n, stop move bracketed, unverified
  close tail flagged, close fields, quote after exit, index rows
* pairing by position id with two interleaved positions, a short marked at the ask, a manual position ignored
* a partial close keeps the same position id, records the volume change, and reports the volume-weighted exit
* shutdown writes `suspend`; a restart resumes with a backfill and no duplicates
* unavailable tick data logged as `unavailable`, no rows invented, path marked incomplete once the wait runs out
* a failed `positions_get` never produces a close; `observe()` and `close()` never raise
* a position closed while the recorder was down is finalised on the next start; the recorder waits for the exit deal
* a failed write is retried without losing or duplicating ticks; a close is written once even if the index write
  fails
* the final stop taken from the broker's exit comment when the move was never observed; a tail proven by an equal
  exit stop; a late stop move recorded with its bracket and its tail flagged
* the close waits for the first quote after the exit, the wait is bounded, and a fetch failure at close is retried
* ticks written past the exit are cut from the path, counted, and supply the quote after the exit
* a file that holds a close is never written again, within a run or after a restart
* a position opened and closed between two passes is found in deal history (a short, marked at the ask, every
  tick ambiguous about the stop); manual, stale, still-open and already-recorded positions are left alone
* in `run()`: `observe()` after each completed tick only, `close()` on shutdown even when the first tick stops the
  loop, the time spent recording taken out of the sleep, and the tradable symbols handed to the recorder

The discovery tests were mutation-checked: removing the magic filter, the still-open check, the 15-minute window, the
scan itself, or its repetition each makes a test fail.

Read-only spot check against the real terminal before the audit (four closed scalp-test positions into a scratch
folder; no bot, no orders, nothing written under the bot's `logs/`):

| position | side | exit | ticks | complete | checks |
| --- | --- | --- | --- | --- | --- |
| 58424404413 | LONG | TRAIL | 924 | yes | final stop = exit fill 4344.19; quote before fill ask = fill price |
| 58424220335 | LONG | SL | 5,578 | yes | exit = stop 4343.68 = last tick bid; −0.5R at +149.9 s, +0.25R never |
| 58423246980 | LONG | TP | 1,673 | yes | +0.25/+0.5/+0.75/+1R all before −0.5R |
| 58424049405 | SHORT | TRAIL | 1,966 | yes | fill = quote bid; every tick marked at the ask; labelled TRAIL from the broker comment `[sl 4351.43]` alone |

## Replay audit (every real scalp-test position)

Script `docs/research/path_recorder_replay_audit.py`; output `docs/research/2026-09-13-path-recorder-replay-audit.txt`.

**Method.** The MT5 terminal is read once, read-only: every XAUUSD tick from 7 to 11 Sep 2026 (2,043,998 ticks), every
deal and order of the 155 bot positions, and the stop moves the bot journaled. A replay terminal then answers the
recorder's calls the way the real one would have at each moment: only ticks that had already arrived, only positions
open at that moment (with the stop the journal says was in force), only deals already executed. The recorder's own
`observe()` / `close()` run over that history at the bot's 2-second cadence, with its waits on replay time, while two
faults are injected: a bot restart while a position is open (16 positions), and the bot down from mid-trade until
7 s after the exit (14 positions). Every file is then checked against ground truth. Nothing touches the bot, its logs
or any order; files go to a scratch folder.

**Schema 1 run:** 150/155 positions passed every check. The five failures were the 1.38 s position with no file and
the four null `quote_after_exit` values described above; every other check passed on all 154 recorded files.

**Schema 2 run (this code):**

| check (155 positions) | result |
| --- | --- |
| file with exactly one `open` and one `close` row | 155/155 |
| recorded ticks equal every real tick in [fill, exit] | 155/155 (277,999 recorded, 277,999 real) |
| `seq` continuous 1..n, no duplicates | 155/155 |
| `quote_before_fill` equals the real tick at or before the fill | 155/155 |
| `quote_after_exit` equals the first real tick after the exit (within 10 s) | 155/155 |
| stop on every non-ambiguous tick equals the stop in force | 155/155 (0 wrong ticks; 13,452 ambiguous, 4.8%) |
| exit label agrees with the deal reason and the journaled stop moves | 155/155 |
| exit label agrees with the 147-trade report | 147/147 |
| realised R from the deals equals R from the exit price | 155/155 (max difference 0.0000R) |
| **all checks** | **155/155** |
| restart while open: pass / `resume` marker present | 16/16 / 16/16 |
| down across the exit: pass / `closed_while_recorder_down` present | 14/14 / 14/14 |

* Route: 154 positions recorded while listed; 1 found in deal history (58343386760, TP, 25 ticks, every check
  passes). Ticks written past an exit: 0 (the replay cannot produce that race; it is covered by a unit test).
* Completeness: 154/155 complete. The exception, 58401835044, is a 157-minute long held across the daily break,
  where the broker sent no ticks for over 30 s; `internal_gap` is the correct verdict.
* Stop evidence: the close tail was proven by the broker's exit stop on 109/155 positions; the final stop came from
  the exit comment on 115/155.
* Exit labels: SL 61, TRAIL 54, TP 36, closed by hand 4.
* Storage: 77.1 MB for 155 positions (median 356 KB, max 2.30 MB). Replay: 29,232 passes in 1,234.5 s.
* What this audit cannot show: the stop truth is the bot's journal (1-second resolution), which is also what the
  replay terminal serves, so the stop check validates the recorder's bracketing, not the journal's timing; real
  process restarts are modelled as new recorder objects; live terminal latency and load are not reproduced.

## Strategy behaviour unchanged

* No file that decides, sizes, places, manages or closes trades was modified (see "Files").
* `path_recorder.py` contains no `order_send`, `order_check`, stop modification, position close, journal write or
  Telegram call. Its only MT5 calls are `positions_get`, `symbol_info`, `symbol_info_tick`, `copy_ticks_range`,
  `history_deals_get`, `history_orders_get`, `order_calc_profit` and `last_error`.
* The recorder runs after `Bot.tick()` completes, never inside it, and cannot raise into the loop.
* The loop period is preserved: the sleep is shortened by exactly the recording time.
* No configuration value was added or changed; the $5 risk budget, terminal-first sizing and the sizing fix are intact.

## Next research step

1. **Collect.** Done: the scalp-test bot runs schema 2 since 16:09:30 on 2026-09-13, configuration unchanged.
2. **Audit the first trading day** before trusting the data: every closed strategy position in the deal history has
   exactly one `close` row; at least 95% are `complete: true`; zero duplicate `seq`; `ticks_after_exit` is 0 or
   explained; the recorded tick count for a sample of positions equals an offline `copy_ticks_range` over the same
   interval; exit labels agree with the deal history. `docs/research/path_recorder_replay_audit.py` already does
   these checks for replayed history and is the template for checking the live files.
3. **Accumulate** at least 150 closed positions with complete paths from the unchanged strategy, and keep manual
   trading off this account so the sample stays clean.
4. **Only then** run the pre-registered exit analysis (protection at +0.5R versus delayed trail from +0.75R) on the
   recorded paths, with thresholds fixed in advance and results reported against the current exit system.
