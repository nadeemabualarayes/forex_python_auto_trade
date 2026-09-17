# Pre-Entry Context Study

Date: 2026-09-17 · Branch: `research/small-profit-small-loss` (worktree `C:\Develompent\forex_research_spsl`, at
`scalp-test` `4b0c3a6`) · Status: **stopped at the data inspection. No pre-entry tick data exists for the 299 trades,
so no analysis was run and no analysis script was written.** Nothing was fabricated, inferred from OHLC, fetched from
MT5, or changed on any bot, branch or setting.

## 1. Executive Summary

The question ("was the market measurably different immediately before the bot entered, for eventual winners versus
full-loss trades?") cannot be answered with the data that exists today.

* The 299 verified tick paths begin **at the fill**: in all 299 files the first recorded tick is at or after the
  fill millisecond (median 84 ms after it, maximum 2.06 s; zero ticks before the fill in any file).
* The only pre-fill information is two single quotes per trade: the last broker tick at or before the fill
  (`quote_before_fill`, median 93 ms old, at most 1.17 s) and the journal's order price (1-second timestamp, fill
  within ±2 s). Two points 0–2 s before the fill cannot support 5/10/15/30/60-second windows, momentum, speed,
  spread trend, quote counts or volatility.
* The bot's `SIGNAL` log line gives the closed M1 bar's close, RSI and ATR (the fill follows that bar's close by a
  median 2 s). That is bar-level context, not tick data, and prior bars are not stored anywhere in the logs.
* A partial window can be borrowed from the previous trade's recorded path for 82 trades (its exit lies less than
  60 s before the next fill; 55 within 5 s), but the stretch between that exit and the new fill is unrecorded, and
  such trades are by construction re-entries after a just-closed trade, so the sample would be both incomplete and
  biased. It was not analysed.
* The portable terminal holds a proprietary tick cache on disk (`bases/MetaQuotes-Demo/ticks/XAUUSD/2026{07,08,09}.tkc`,
  121 MB). Its format is undocumented; reading it would be reverse engineering that cannot be validated without
  attaching to the terminal, which this study may not do. The 13 Sep replay audit held the complete tick stream for
  7–11 Sep in memory but wrote only the per-position paths, so no raw archive exists on disk.

**Evidence classification: NO EVIDENCE** — not because the market showed nothing before entry, but because nothing
before entry was recorded. A separate observability step is required before this question can be studied (section 14).

## 2. Available Pre-Entry Data

| source | what it holds before the fill | covers | usable for pre-entry windows? |
| --- | --- | --- | --- |
| Live recorder paths `forex_scalp_test/logs/paths/XAUUSD_<pid>.jsonl` (150 trades, 13–17 Sep) | ticks from the fill to the exit; `quote_before_fill` = the last tick at or before the fill | 0 ticks before the fill; one quote 0–1.2 s old | no |
| Replayed paths `logs/replay_paths_2026-09-07_11/` (149 trades, 7–11 Sep, audited 155/155) | same structure, same content | 0 ticks before the fill | no |
| `logs/trades.csv` (journal) | `ENTRY` row: order price and SL/TP at order time, 1-second timestamp | one quote 0–2 s before the fill | no (single point) |
| `logs/bot.log` `SIGNAL` lines | closed M1 bar close, RSI, ATR, EMA (off), candle pattern | bar-level, closed 2 s (median) to 24 s (90th pct) before the fill | no (OHLC-level; prior bars not stored) |
| `logs/history.db` | deals (fills, exits) and hourly equity snapshots | no quotes | no |
| Previous trade's path | ticks up to that trade's exit | 82 trades have that exit inside their 60-s window; 55 inside 5 s | not reliably: gap to the fill unrecorded, and only re-entries after a stop-out or target |
| Terminal tick cache `mt5_scalp/bases/MetaQuotes-Demo/ticks/XAUUSD/*.tkc` | presumably every tick since July | unknown until decoded | not without a validated decoder or a terminal attach |
| MT5 `copy_ticks_range` (terminal history, back to at least mid-July) | every tick, millisecond stamps | full coverage of all 299 fills | yes, but requires attaching to a terminal, which is excluded here |

Maximum reliable pre-entry window from files today: **one quote, median 93 ms before the fill.**

## 3. Dataset and Methodology

Dataset that would have been used: the same 299 post-sizing-fix strategy trades (172 winners, 127 losers, all 127
full −1R losses; half A 149, half B 150; total net −$151.94), loaded through `small_profit_small_loss_analysis.load_trades`.
Counts and totals were re-verified during the inspection and reconcile with the previous four studies.

Method that was pre-registered and not executed, recorded here so that a future run is bound by it:

* Windows: 5, 10, 15, 30, 60 s ending at the fill millisecond (endpoint documented as the fill; the fill tick itself
  excluded). Features per window: first and last marked price, signed and absolute change, change per second,
  spread at the last pre-fill quote, median and maximum spread, spread change (last minus first), number of quote
  updates, and whether the last 5 s moved faster than the preceding 55 s (acceleration), all from ticks with
  `time_msc < fill_msc` only.
* Direction normalisation: for a LONG, favourable = price rising into the entry is **adverse to the mean-reversion
  entry's premise but favourable to the position**; to avoid that ambiguity the study would report *signed movement
  in the direction of the trade* (LONG: end − start; SHORT: start − end; positive = the market was already moving the
  way the trade needed) and state it exactly that way.
* Comparison: winners vs full losses (n, median, mean, 25th–75th percentile, difference), no scoring or ranking;
  halves A/B; sessions; LONG/SHORT; the immediate-adverse group (76 trades) against the rest.
* Leakage tests: synthetic paths with ticks at and after the fill asserting they never enter any window.

None of this ran, because the inputs do not exist.

## 4. Pre-Entry Price Movement

Not measurable: no path contains a tick before the fill. The single pre-fill quote gives a price but no movement.

## 5. Pre-Entry Spread

Only the spread of the last quote before the fill is known (this is the "entry spread" of the entry-quality study:
median 31 points; winners 29, losers 32, never-+0.25R 34.5; entries at ≥ 45 points had a 51% full-loss rate against
41%, in both halves). Whether the spread was widening or contracting into the entry, and whether it was unusually
high relative to the preceding minute, cannot be determined.

## 6. Pre-Entry Momentum / Movement Speed

Not measurable. The only bar-level proxy on file, the signal bar's close versus the fill price ("fill drift"), was
already examined: median +0.04R adverse for every outcome group, no relationship with outcomes.

## 7. Winner vs Full-Loss Comparison

Not performed (no pre-entry features). Outcome populations verified for a future run: 172 winners, 127 full losses,
76 immediate-adverse failures (−0.25R within 30 s without +0.10R first), 88 never-+0.25R trades.

## 8. First-Half vs Second-Half Robustness

Not applicable. Halves verified: 149 (7–11 Sep) + 150 (14–17 Sep) = 299; both would be usable once tick windows exist.

## 9. Session Breakdown

Not applicable (session counts on file: 00–07 74, 07–12 91, 12–17 70, 17–24 64).

## 10. Direction Breakdown

Not applicable (LONG 170, SHORT 129).

## 11. Immediate-Adverse Failure Hypothesis

"Losing entries are more likely to happen immediately after a sharp directional move": **untested, no evidence either
way.** The 76 immediate-adverse failures are identified and their fill times are known to the millisecond, so the
hypothesis is fully testable once pre-fill ticks are available; nothing on file today speaks to it.

## 12. What the Data Can and Cannot Explain

Can: everything from the fill onward (the four previous studies). Cannot: any tick-level statement about the market
before the fill. The one pre-fill quantity that exists, the spread of the last quote, has already been reported.

## 13. Limitations

* This is a data-availability finding, not a market finding.
* The borrowed-window subset (82 trades) was deliberately not analysed: it is biased toward re-entries after a
  just-closed trade and every one of its windows has an unrecorded gap ending at the fill.
* The terminal's `.tkc` cache almost certainly contains the needed ticks, but using it requires either a validated
  decoder or an attach; both are outside this study's rules and the latter is unsafe while the bot runs (15 Sep incident).

## 14. Final Research Conclusion

1. **Is there meaningful information before entry?** Unknown: it was never recorded.
2. **Does it distinguish winners from full-loss trades?** Cannot be tested with the current files.
3. **Does the relationship survive both halves?** Not applicable.
4. **Does it explain the immediate-adverse failure group?** Not testable yet; the group and its fill times are ready.
5. **Is the evidence strong enough to justify a separate future validation experiment?** The *question* is justified
   (it is the one limitation every previous study named), but it needs an observability step first, not a validation
   experiment. Two ways exist to obtain the data, neither done here and both needing approval:
   * **Retrospective, complete:** a read-only extraction of `copy_ticks_range(fill − 120 s, fill)` for all 299 fills
     from a terminal no bot is using (the scalp terminal while the bot is stopped, or another logged-in terminal),
     saved as files next to the paths. The terminal keeps tick history back to July, so all 299 windows can be
     reconstructed exactly, and the pre-registered method above can run unchanged.
   * **Prospective:** extend `path_recorder._start` (research branch only) to store the last 120 s of ticks before
     the fill in the `open` row instead of the single `quote_before_fill` (it already fetches a 10-s window there),
     so every future trade carries its pre-entry context; about ten lines plus a test.
   Until one of these exists, this line of research should **end here**, and forward validation should simply continue.

**Classification: NO EVIDENCE (data not recorded).** No trading rule, no bot change, no feature is proposed.

## Inspection record

* Verified: 299 trades; 172 winners / 127 full losses; halves 149 + 150; total net −$151.94; every path's first tick
  ≥ fill (min 0 ms, median 84 ms, max 2,058 ms); `quote_before_fill` present in 299/299 (age median 93 ms, max
  1,171 ms); journal `ENTRY` rows matched 299/299 (fill − order time within −2…+2 s); `SIGNAL` lines matched 299/299
  (fill − bar close: median 2 s, 90th percentile 24 s); `history.db` tables: `deals`, `equity`; replay folder holds only
  the 155 path files and `index.jsonl`; `.tkc` tick caches present for 2026-07/08/09 (121 MB), not read.
* No production file, configuration, branch other than the research branch, process or terminal was touched; no
  analysis script was created for this study.
