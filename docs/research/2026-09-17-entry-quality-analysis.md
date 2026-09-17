# Entry-quality analysis for the XAUUSD scalp bot (descriptive research only)

Date: 2026-09-17 · Branch: `research/small-profit-small-loss` (worktree `C:\Develompent\forex_research_spsl`, at
`scalp-test` `4b0c3a6`) · Script: `docs/research/entry_quality_analysis.py` (new research file; imports the loader of
`small_profit_small_loss_analysis.py`) · Status: **no production file modified; no MT5 attach; no restart; nothing
committed, pushed or deployed. No trading recommendation is made.**

## 1. Executive summary

* **The loss is binary and front-loaded.** All 127 losing trades are full −1R stop-outs; there are no small losers,
  because the live breakeven/trail turns every trade that survives long enough into a small win. 88 trades (29%)
  never reach +0.25R (87 of them full losses, −$332.88); their median life is 166 s and their best moment comes
  12 s after the fill. Losers reach their high after a median 30 s, winners after 227 s.
* **The first seconds are spread, not information.** The entry spread is 8.5% of the initial risk (median 31
  points), so nearly every trade opens at about −0.09R; 87% touch −0.10R within 10 s, winners included.
* **A real but weak early signal appears at 30–60 s.** Trades that touch −0.25R within 30 s (53% of all) end as
  full losses 55% of the time versus 28% for the rest; trades that touch +0.25R within 60 s (33%) win 82% of the
  time with an 18% full-loss rate. Both hold in half A and half B. But 55% of eventual winners (and 48% of the large
  winners) also "look bad" in the first 30 s, so the early path shifts the odds two- to three-fold; it does not
  separate good from bad entries.
* **Failure modes of the 127 losers:** immediate adverse move (−0.25R within 30 s, never +0.10R first) 76 trades,
  60% of losers and 59% of the lost dollars; slow / no follow-through 24 (19%); brief favourable move then reversal
  27 (21%). Overlays: the 07–12 session carries 37% of the losers from 30% of the trades; entries at a spread of
  45 points or more lose 51% of the time versus 41%.
* **Existing entry features:** the 07–12 session (expectancy −$1.44 in half A, −$0.60 in half B) and a wide entry
  spread (full-loss rate 46%/53% versus 39%/43% by half) are the only recorded features whose relationship with bad
  outcomes survives the split. RSI depth beyond the 35/65 trigger, Bollinger penetration, ATR regime, candle
  pattern, direction and the 00–07 session are inconsistent between halves: INCONCLUSIVE. The trend filter is off on
  this bot, so it cannot be assessed.
* **Direction:** longs sit deeper under water early (median 30-s MAE −0.27R vs −0.22R), reach −0.25R faster
  (12 s vs 19 s) and +0.25R slower (83 s vs 52 s) in both halves, and have more dead-on-arrival entries (32% vs 26%);
  yet their loss rate (43% vs 42%) and expectancy are not worse, and the SHORT expectancy flips sign between halves.
* **Bottom line:** the problem is primarily immediate adverse movement after entry, i.e. entry timing/location in
  the sense of "price keeps going the way it was going", concentrated in the 07–12 session and worsened by friction
  at wide spreads. It is not direction, not volatility regime, and not the Bollinger/RSI values as recorded.

## 2. Dataset and methodology

* The same **299** post-sizing-fix strategy trades with verified tick paths (149 replayed for 7–11 Sep, 150
  live-recorded 13–17 Sep; pre-fix and hand-closed trades excluded; daily-break quotes with a spread above 300
  points left out; nothing interpolated; tick order preserved). Longs marked at the bid, shorts at the ask.
  R = marked P&L / initial risk, initial risk = |fill − initial stop| × terminal-priced $ per point × lot.
* Windows, thresholds, groups and time buckets are exactly the ones in the task; nothing was searched. "Full
  loss" = final result ≤ −0.9R. "Winner" = net > 0. "Looks bad within 30 s" = touched −0.25R within 30 s, or
  touched −0.10R within 30 s without touching +0.10R in that time (defined before the numbers were read).
* Existing entry features come from records that already exist: the bot's `SIGNAL` log line matched to each
  fill (RSI, M1 ATR, signal-bar close, candle pattern, trend EMA = `nan` because the trend filter is off on this
  bot), the opening order (initial stop → risk), the quote before the fill (spread), the journal (order price) and
  the 15 Sep forward report (Bollinger penetration value and bucket for the first 200 trades). "Fill vs signal-bar
  close" is the adverse distance between the bar close that produced the signal and the actual fill, in R. "RSI
  beyond trigger" is 35 − RSI for longs and RSI − 65 for shorts.
* Halves: A = 7–11 Sep, B = 14–17 Sep. A pattern present in only one half is marked INCONCLUSIVE.
* All tables are the script's output (Appendix); sections 3–12 read them.

## 3. Early-path statistics (Part 1 and 2 tables)

* Median path: −0.10R at 10 s, −0.09R at 30 s, −0.10R at 60 s, back to −0.04R at 120 s and +0.01R at 300 s.
  Median MAE deepens steadily (−0.16R at 5 s, −0.26R at 30 s, −0.42R at 120 s); median MFE is negative until 20 s
  and reaches +0.25R only at the 120-s window.
* Adverse levels are reached far sooner than favourable ones: −0.25R is first touched after a median 15 s
  (231 trades), +0.25R after 63 s (211 trades); −0.50R after 72 s, +0.50R after 141 s.
* Groups by the highest level reached: **A** never +0.25R: 88 trades, 1% win, −$332.88, expectancy −$3.78;
  **B** +0.25R only: 36 trades, 11% win, −$114.21; **C** +0.50R: 66 trades, 89% win, −$5.93 (PF 0.80; the breakeven
  zone); **D** +0.75R: 56 trades, 98% win, +$96.74; **E** +1.00R: 53 trades, 100% win, +$204.34. Initial risk is
  the same in every group ($3.66–$3.86): the losers are not the wide-stop trades.
* Group A in its first 10 / 30 / 60 s: median MAE −0.23 / −0.33 / −0.51R, median MFE −0.03 / 0.00 / 0.00R;
  92% / 97% / 99% have touched −0.10R and 45% / 76% / 93% have touched −0.25R. Winners in the same windows: MAE
  −0.17 / −0.21 / −0.26R, MFE 0.00 / +0.12 / +0.22R; 27% / 41% / 53% have touched −0.25R and 20% / 54% / 67% have
  touched +0.10R. The earliest visible difference is at 30 s: a winner has typically recovered to breakeven and
  shown +0.12R, a group-A trade is at −0.25R and has shown nothing.

## 4. Early adverse movement (Part 3 table)

* −0.10R within 10 s: 87% of trades; their full-loss rate (44%) equals the base rate. This level is the spread.
* −0.25R within 30 s: 157 trades (53%); 55% end as full losses, 45% still win; median final R −1.00. The trades
  that did not touch it: 28% full losses, 72% winners. Within 60 s: 201 trades (67%), 54% vs 18%.
* −0.33R within 60 s: 149 trades (50%); 56% full losses vs 29%. Within 10 s: only 50 trades and 50%.
* The pattern is monotone in level and time but never sharp: even the worst cell (−0.33R within 120 s, 183 trades)
  still contains 42% eventual winners. A "bad start" exists as a population shift, not as a signature.

## 5. Early favourable movement (Part 4 table)

* +0.10R within 30 s: 128 trades (43%), 73% win, 27% full losses; not reaching it: 46% win.
* +0.25R within 60 s: 100 trades (33%), 82% win, 18% full losses, median final +0.24R; not reaching it: 45% win.
* +0.50R within 60 s: 35 trades, 94% win; within 120 s: 75 trades, 95% win, 5% full losses.
* Yes, a trade that moves favourably quickly has materially better odds (roughly 4:1 at +0.25R within 60 s versus
  1:1 overall), and the effect grows with level and time. But only a third of trades do so, and the half that
  eventually win without an early favourable move are the ones any early rule would sacrifice.

## 6. Speed analysis (Part 5 table)

* Winners: median R at 10 / 30 / 60 s = −0.06 / 0.00 / +0.06; time to +0.10R 27 s, to +0.25R 61 s; MFE reached
  after 227 s of a 269-s median life.
* Losers (= full losses): −0.12 / −0.19 / −0.31; 52% ever touch +0.10R (median 28 s when they do); MFE after 30 s,
  then a 251-s decline to the stop. Group A: −0.14 / −0.25 / −0.41, MFE at 12 s, life 166 s.
* Time to −0.10R is 0–1 s for everyone (spread). Time to −0.25R: 17 s (winners) vs 13 s (losers): almost the same.
  The speed difference is on the favourable side and in the timing of the high, not in how fast the trade goes
  under water.

## 7. Spread analysis (Part 6 table)

* Medians: entry spread 31 points (winners 29, losers 32, never-+0.25R 34.5); max spread in the first 10 s 45 vs
  44–48; average in the first 30 s 30 vs 34. The differences are small but consistently in the same direction.
* The upper quartile (≥ 45 points at entry, 47 trades): full-loss rate 51% vs 41%, expectancy −$1.13 vs −$0.39.
  Half A 46% vs 39%, half B 53% vs 43%: the direction survives the split, the size is modest. As a share of risk the
  entry spread is 8–9% in every group.
* Spread is a contributing friction on a strategy with 8.5%-of-risk entry cost, not the cause of the immediate
  adverse moves (those trades enter at the same median spread as the others: 32 points).

## 8. Existing entry-feature analysis (Part 7 tables)

* **RSI**: medians identical across outcomes (32.9 all, 33.1 winners, 32.6 losers). Depth beyond the trigger is
  non-monotone: 0–2.5 points → 30% full losses, 2.5–5 → 53%, 5–10 → 48%, 10+ → 40%. The 0–2.5 bucket is −$0.25 in
  half A and +$0.16 in half B; ≥ 5 vs < 5 full-loss rates are 40%/40% in A and 47%/42% in B. INCONCLUSIVE.
* **Bollinger penetration** (200 trades): medians 0.32 winners vs 0.41 losers. Buckets flip between halves
  ("small" +$0.75 in A, −$1.76 in B; "deep" −$0.78 in A, +$0.76 in B). INCONCLUSIVE.
* **ATR regime**: NORMAL is worst (46% full losses, −$0.42 / −$1.18), HIGH is best (30%, +$0.51 / +$0.24, 27
  trades), LOW in between. Same sign in both halves but HIGH is 17 + 10 trades. Weak / small-sample.
* **Fill vs signal-bar close**: median +0.04R adverse in every outcome group; filling ≥ 0.10R worse than the bar
  close (84 trades) has a *lower* loss rate (36%). Not a factor.
* **Candle pattern**: 289 of 299 signals had no pattern (`CANDLE_MODE` off on this bot); the 10 with one are too
  few to say anything.
* **Trend filter**: off on this bot (`ema=nan`), cannot be assessed. **Lot 0.02** (28 trades, the low-ATR entries):
  54% full losses, −$1.12, but −$2.67 in A vs −$0.39 in B: INCONCLUSIVE.
* **Session and direction**: see sections 9 and 10. Session 07–12 is the strongest recorded feature.

## 9. Session analysis, first 60 seconds (Part 8 table)

| session | n | median MAE 60 s | median MFE 60 s | +0.25R by 60 s | −0.25R by 60 s | never +0.25R | full loss | expectancy (A / B) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00–07 | 74 | −0.37R | +0.09R | 31% | 72% | 36% | 47% | −$0.77 (+0.35 / −1.28) |
| 07–12 | 91 | −0.33R | +0.10R | 29% | 69% | 36% | 52% | −$1.07 (−1.44 / −0.60) |
| 12–17 | 70 | −0.30R | +0.21R | 47% | 60% | 19% | 34% | +$0.09 (+0.27 / −0.15) |
| 17–24 | 64 | −0.31R | +0.13R | 28% | 67% | 23% | 33% | −$0.05 (+0.08 / −0.21) |

07–12 has the highest full-loss rate and is negative in both halves; 12–17 has the best early path (fewest
dead-on-arrival entries, most +0.25R within a minute). 00–07 looks as bad as 07–12 overall but is positive in half A
(23 trades) and very negative in half B (51): INCONCLUSIVE. Descriptive only; no session is recommended for blocking.

## 10. LONG / SHORT analysis (Part 9 table)

* Longs: median 30-s MAE −0.27R (−0.25 / −0.29 by half) vs shorts −0.22R (−0.22 / −0.22); 60-s MFE +0.09R vs
  +0.19R; time to +0.25R 83 s vs 52 s; time to −0.25R 12 s vs 19 s; never-+0.25R 32% vs 26% (31/34 vs 23/28 by
  half); −0.25R within 30 s: 58% vs 46%.
* So longs have the worse early path on every measure, in both halves. But full-loss rate (43% vs 42%), win rate
  (57% vs 58%) and expectancy (−$0.50 vs −$0.52) are the same, and the SHORT expectancy is −$0.15 in half A and
  −$0.84 in half B. The early-path difference is robust; a P&L difference is not present. Not a basis for blocking.

## 11. Half A / half B robustness (Part 10 table)

Survives the split (same direction, similar size): the share of dead-on-arrival trades (28% / 31%); the full-loss
rate of trades touching −0.25R within 30 s (54% / 56%) against the rest (about 28%); the win rate of trades touching
+0.25R within 60 s (80% / 84%); the higher full-loss rate at entry spreads ≥ 45 points (46 / 53 vs 39 / 43); the
07–12 session's negative expectancy (−1.44 / −0.60); the long side's deeper early MAE. Half B is worse than half A
throughout (expectancy −$0.67 vs −$0.35; more trades touch −0.25R early: 57% vs 48%).

INCONCLUSIVE (one half only or sign flip): 00–07 session, SHORT expectancy, every Bollinger bucket, RSI depth, lot
0.02, and the +0.10R-within-10-s win rate (60% / 79%).

## 12. Failure-mode classification (Part 12 tables)

Mutually exclusive by path shape, losing trades only (127, all full losses):

| failure mode | trades | share of losers | net | note |
| --- | ---: | ---: | ---: | --- |
| 1. Immediate adverse move (−0.25R within 30 s, never +0.10R before) | 76 | 60% | −$284.41 | median 30-s MAE −0.39R, median MFE +0.01R; entry spread the same as everyone's (32) |
| 2. Slow / no follow-through (never +0.25R, not immediate) | 24 | 19% | −$99.17 | drifts, peaks +0.17R, then stops out |
| 3. Brief favourable move then reversal (reached +0.25R, then −1R) | 27 | 21% | −$97.63 | the "giveback" trades of the previous study |
| 4. Spread / friction dominated | — | — | — | not a stand-alone mode: wide-spread entries lose more often (51% vs 41%) but are 19% of losers and enter into every mode |
| 5. Session-specific weakness | overlay | 37% of losers in 07–12 (30% of trades) | | the only session effect that survives both halves |
| 6. Direction-specific weakness | overlay | 57% of losers are long, 57% of trades are long | | no excess loss |
| 7. Volatility / regime mismatch | overlay | LOW 35%, HIGH 6% of losers, in proportion to their trade counts | | none visible |
| 8. Deep Bollinger penetration | overlay | 22% of losers, 43% loss rate = base rate | | none visible |
| 9. Other feature pattern | overlay | RSI ≥ 5 beyond trigger: 67% of losers, 43% loss rate = base rate | | none visible |

Common: mode 1 (three fifths of the losers and of the lost money). Present but secondary: modes 2 and 3 (a fifth
each). Rare or absent as causes: direction, regime, Bollinger depth, RSI depth, fill drift. Session 07–12 and wide
spreads are amplifiers, not modes.

## 13. Limitations

* 299 trades over 8 trading days; segment cells of 27–90 trades; both halves negative. Percentages that differ by
  under ten points between groups of this size should be read as "no visible difference".
* The tick path begins at the fill; nothing before the fill (the bar that produced the signal, the tick flow
  before entry) is in the recording, so "what a good entry looks like" is described from the fill onward only.
* "Full loss" and "winner" are outcomes of the live exit rules (2 ATR stop, 2 ATR target, breakeven at 1 ATR,
  1 ATR trail); a different exit system would draw the groups differently.
* Bollinger penetration exists for 200 trades; RSI/ATR come from the signal bar; the trend filter and candle
  confirmation are off on this bot, so their influence cannot be measured here.
* The replayed half A paths inherit any defect of the 13 Sep replay (verified 155/155 at the time).
* No threshold, window or bucket was chosen after seeing results; the descriptive cut at 45 points of spread is the
  observed upper quartile and is used only to describe two populations.

## 14. Final research conclusion (the Part 13 questions)

1. **Losing trades that look bad within 30 s:** 102 of 127 (80%). (All losers are full losses.)
2. **Eventual winners that look bad within 30 s:** 94 of 172 (55%); 32 of the 67 large winners (48%).
3. **Is there an early signal without future information?** Yes, in tick order only: touching −0.25R within 30 s
   raises the full-loss rate from 28% to 55%; touching +0.25R within 60 s lowers it from 55% to 18% and raises the
   win rate to 82%. It is a shift in odds, not a separation: half of the early-bad trades still win.
4. **How early?** Nothing meaningful before about 20 s (the first −0.10R is the spread and hits 87% of trades by
   10 s). The difference is visible at 30 s and clearest at 60 s; by 120 s the two populations are largely sorted
   (never-+0.25R trades are at −0.41R, winners at +0.06R at 60 s).
5. **Strong enough to justify a future research experiment?** Strong enough to justify a *pre-registered study* of
   time-boxed entry behaviour (for example how the −0.25R-within-30-s and +0.25R-within-60-s populations behave
   under alternative rules), with the explicit cost that any early-exit rule would touch 55% of the winners. Not
   strong enough to expect a large effect, and not a basis for a rule now.
6. **Strongest existing feature descriptively associated with bad outcomes:** the 07–12 session (52% full losses,
   expectancy −$1.07), followed by entry spread ≥ 45 points (51% full losses). RSI, Bollinger, ATR, candle, drift
   and direction are not.
7. **Survives half A / half B?** 07–12 yes (−$1.44 / −$0.60); wide spread yes in direction (46 / 53 vs 39 / 43);
   the long side's worse early path yes; the early −0.25R / +0.25R odds shift yes. Bollinger, RSI, 00–07, SHORT
   P&L: no (INCONCLUSIVE).
8. **The problem is primarily immediate adverse movement** (60% of losers, 59% of the lost dollars), with lack of
   follow-through and brief-move-then-reversal each a fifth; the 07–12 session and wide entry spreads amplify it;
   direction, volatility regime and the recorded Bollinger/RSI entry-location measures do not explain it. In plain
   terms: the strategy buys weakness and sells strength on M1, and in three cases out of five that lose, the
   weakness or strength simply continues for the next minute.

No trading recommendation follows from this note.

## Appendix: script output

Trades: **299** (excluded {'pre-fix': 2, 'closed by hand': 4}); winners 172, losers 127, full losses (final ≤ −0.9R) 127, never +0.25R 88, reached +0.50R 175; half A 149, half B 150. SIGNAL line matched for 299 trades; penetration value for 200. Median trade duration 260 s (winners 269 s, full losses 251 s).

#### Part 1. Early path by window (all 299 trades; a window that outlives the trade covers its whole life)

| window | trades with a tick in it | median MFE | median MAE | median R at end | reached +0.25R | +0.33R | +0.50R | −0.25R | −0.50R | −0.75R | −1.00R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 s | 299 | -0.04 | -0.16 | -0.10 | 4 (1%) | 2 (1%) | 1 (0%) | 62 (21%) | 2 (1%) | 1 (0%) | 1 (0%) |
| 10 s | 299 | -0.01 | -0.19 | -0.10 | 14 (5%) | 6 (2%) | 2 (1%) | 99 (33%) | 9 (3%) | 1 (0%) | 1 (0%) |
| 20 s | 299 | 0.02 | -0.22 | -0.09 | 35 (12%) | 24 (8%) | 7 (2%) | 132 (44%) | 23 (8%) | 4 (1%) | 1 (0%) |
| 30 s | 299 | 0.07 | -0.26 | -0.09 | 59 (20%) | 40 (13%) | 15 (5%) | 157 (53%) | 37 (12%) | 14 (5%) | 3 (1%) |
| 60 s | 299 | 0.13 | -0.33 | -0.10 | 100 (33%) | 68 (23%) | 35 (12%) | 201 (67%) | 71 (24%) | 27 (9%) | 10 (3%) |
| 120 s | 299 | 0.25 | -0.42 | -0.04 | 150 (50%) | 127 (42%) | 75 (25%) | 217 (73%) | 124 (41%) | 65 (22%) | 30 (10%) |
| 300 s | 299 | 0.47 | -0.54 | 0.01 | 198 (66%) | 180 (60%) | 140 (47%) | 229 (77%) | 159 (53%) | 107 (36%) | 74 (25%) |

| first touch of | trades | median s | mean s | 25th pct s | 75th pct s |
| --- | ---: | ---: | ---: | ---: | ---: |
| +0.25R | 211 | 63 | 106 | 28 | 133 |
| -0.25R | 231 | 15 | 33 | 5 | 40 |
| +0.50R | 175 | 141 | 196 | 68 | 277 |
| -0.50R | 176 | 72 | 111 | 35 | 152 |

#### Part 2. Groups by the highest favourable level reached

| group | trades | win rate | net | expectancy | PF | avg initial risk $ | median MFE | median MAE | mean time to first +0.10R | mean time to +0.25R | mean time to first −0.10R | mean time to −0.25R | full losses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A never +0.25R | 88 | 1% | -332.88 | -3.78 | 0.00 | 3.86 | 0.02 | -1.02 | 87 s | n/a s | 4 s | 20 s | 87 |
| B +0.25R | 36 | 11% | -114.21 | -3.17 | 0.01 | 3.66 | 0.36 | -1.04 | 52 s | 122 s | 16 s | 85 s | 32 |
| C +0.50R | 66 | 89% | -5.93 | -0.09 | 0.80 | 3.70 | 0.61 | -0.29 | 67 s | 109 s | 3 s | 23 s | 7 |
| D +0.75R | 56 | 98% | +96.74 | +1.73 | 32.51 | 3.84 | 0.87 | -0.36 | 60 s | 116 s | 4 s | 30 s | 1 |
| E +1.00R | 53 | 100% | +204.34 | +3.86 | inf | 3.80 | 1.03 | -0.36 | 52 s | 80 s | 10 s | 25 s | 0 |

Group A versus winners in the first 10 / 30 / 60 seconds:

| population | n | window | median MFE | median MAE | median R at end | reached +0.10R by then | reached −0.10R | reached −0.25R | no tick yet |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A never +0.25R | 88 | 10 s | -0.03 | -0.23 | -0.14 | 8% | 92% | 45% | 0 |
| A never +0.25R | 88 | 30 s | -0.00 | -0.33 | -0.25 | 17% | 97% | 76% | 0 |
| A never +0.25R | 88 | 60 s | 0.00 | -0.51 | -0.41 | 22% | 99% | 93% | 0 |
| winners | 172 | 10 s | -0.00 | -0.17 | -0.06 | 20% | 84% | 27% | 0 |
| winners | 172 | 30 s | 0.12 | -0.21 | -0.00 | 54% | 89% | 41% | 0 |
| winners | 172 | 60 s | 0.22 | -0.26 | 0.06 | 67% | 91% | 53% | 0 |
| full losses | 127 | 10 s | -0.02 | -0.21 | -0.12 | 12% | 91% | 41% | 0 |
| full losses | 127 | 30 s | 0.01 | -0.29 | -0.19 | 28% | 94% | 69% | 0 |
| full losses | 127 | 60 s | 0.03 | -0.44 | -0.31 | 35% | 97% | 86% | 0 |
| large winners ≥ +0.75R | 67 | 10 s | -0.01 | -0.19 | -0.07 | 19% | 84% | 34% | 0 |
| large winners ≥ +0.75R | 67 | 30 s | 0.16 | -0.22 | 0.06 | 60% | 85% | 43% | 0 |
| large winners ≥ +0.75R | 67 | 60 s | 0.27 | -0.26 | 0.12 | 76% | 90% | 52% | 0 |

Base rates for the whole set: full loss 42%, profitable 58%, mean final R -0.13, median 0.07.

#### Part 3. Early adverse movement: reaching a level within a time (only the tick path decides)

| level | within | trades reaching it | eventually full loss | eventually profitable | mean final R | median final R | trades NOT reaching it | their full-loss rate | their win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| -0.10R | 10 s | 259 (87%) | 44% | 56% | -0.17 | 0.07 | 40 | 30% | 70% |
| -0.10R | 30 s | 273 (91%) | 44% | 56% | -0.17 | 0.06 | 26 | 27% | 73% |
| -0.10R | 60 s | 280 (94%) | 44% | 56% | -0.16 | 0.06 | 19 | 21% | 79% |
| -0.10R | 120 s | 285 (95%) | 44% | 56% | -0.16 | 0.06 | 14 | 14% | 86% |
| -0.15R | 10 s | 194 (65%) | 47% | 53% | -0.20 | 0.04 | 105 | 34% | 66% |
| -0.15R | 30 s | 235 (79%) | 48% | 52% | -0.22 | 0.03 | 64 | 23% | 77% |
| -0.15R | 60 s | 255 (85%) | 47% | 53% | -0.19 | 0.04 | 44 | 18% | 82% |
| -0.15R | 120 s | 261 (87%) | 47% | 53% | -0.20 | 0.04 | 38 | 11% | 89% |
| -0.20R | 10 s | 139 (46%) | 50% | 50% | -0.23 | -1.00 | 160 | 36% | 64% |
| -0.20R | 30 s | 191 (64%) | 52% | 48% | -0.28 | -1.00 | 108 | 25% | 75% |
| -0.20R | 60 s | 225 (75%) | 52% | 48% | -0.27 | -1.00 | 74 | 14% | 86% |
| -0.20R | 120 s | 235 (79%) | 51% | 49% | -0.26 | -1.00 | 64 | 11% | 89% |
| -0.25R | 10 s | 99 (33%) | 53% | 47% | -0.25 | -1.00 | 200 | 38% | 62% |
| -0.25R | 30 s | 157 (53%) | 55% | 45% | -0.32 | -1.00 | 142 | 28% | 72% |
| -0.25R | 60 s | 201 (67%) | 54% | 46% | -0.31 | -1.00 | 98 | 18% | 82% |
| -0.25R | 120 s | 217 (73%) | 54% | 46% | -0.31 | -1.00 | 82 | 11% | 89% |
| -0.33R | 10 s | 50 (17%) | 50% | 50% | -0.20 | -0.48 | 249 | 41% | 59% |
| -0.33R | 30 s | 96 (32%) | 56% | 44% | -0.32 | -1.00 | 203 | 36% | 64% |
| -0.33R | 60 s | 149 (50%) | 56% | 44% | -0.34 | -1.00 | 150 | 29% | 71% |
| -0.33R | 120 s | 183 (61%) | 58% | 42% | -0.35 | -1.00 | 116 | 18% | 82% |

#### Part 4. Early favourable movement

| level | within | trades reaching it | eventually full loss | eventually profitable | mean final R | median final R | trades NOT reaching it | their full-loss rate | their win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| +0.10R | 10 s | 49 (16%) | 31% | 69% | 0.01 | 0.09 | 250 | 45% | 55% |
| +0.10R | 30 s | 128 (43%) | 27% | 73% | 0.11 | 0.18 | 171 | 54% | 46% |
| +0.10R | 60 s | 160 (54%) | 28% | 72% | 0.11 | 0.18 | 139 | 59% | 41% |
| +0.10R | 120 s | 200 (67%) | 28% | 72% | 0.10 | 0.18 | 99 | 73% | 27% |
| +0.15R | 10 s | 32 (11%) | 31% | 69% | -0.02 | 0.11 | 267 | 44% | 56% |
| +0.15R | 30 s | 100 (33%) | 28% | 72% | 0.12 | 0.20 | 199 | 50% | 50% |
| +0.15R | 60 s | 143 (48%) | 26% | 74% | 0.15 | 0.19 | 156 | 58% | 42% |
| +0.15R | 120 s | 183 (61%) | 25% | 75% | 0.15 | 0.19 | 116 | 71% | 29% |
| +0.20R | 10 s | 23 (8%) | 30% | 70% | 0.03 | 0.10 | 276 | 43% | 57% |
| +0.20R | 30 s | 83 (28%) | 27% | 73% | 0.14 | 0.21 | 216 | 49% | 51% |
| +0.20R | 60 s | 122 (41%) | 22% | 78% | 0.22 | 0.23 | 177 | 56% | 44% |
| +0.20R | 120 s | 168 (56%) | 20% | 80% | 0.21 | 0.22 | 131 | 71% | 29% |
| +0.25R | 10 s | 14 (5%) | 29% | 71% | 0.00 | 0.10 | 285 | 43% | 57% |
| +0.25R | 30 s | 59 (20%) | 25% | 75% | 0.18 | 0.22 | 240 | 47% | 53% |
| +0.25R | 60 s | 100 (33%) | 18% | 82% | 0.27 | 0.24 | 199 | 55% | 45% |
| +0.25R | 120 s | 150 (50%) | 17% | 83% | 0.27 | 0.24 | 149 | 68% | 32% |
| +0.33R | 10 s | 6 (2%) | 33% | 67% | 0.01 | 0.07 | 293 | 43% | 57% |
| +0.33R | 30 s | 40 (13%) | 20% | 80% | 0.28 | 0.27 | 259 | 46% | 54% |
| +0.33R | 60 s | 68 (23%) | 16% | 84% | 0.29 | 0.23 | 231 | 50% | 50% |
| +0.33R | 120 s | 127 (42%) | 15% | 85% | 0.33 | 0.27 | 172 | 63% | 37% |
| +0.50R | 10 s | 2 (1%) | 0% | 100% | 0.07 | 0.07 | 297 | 43% | 57% |
| +0.50R | 30 s | 15 (5%) | 7% | 93% | 0.50 | 0.90 | 284 | 44% | 56% |
| +0.50R | 60 s | 35 (12%) | 6% | 94% | 0.46 | 0.28 | 264 | 47% | 53% |
| +0.50R | 120 s | 75 (25%) | 5% | 95% | 0.43 | 0.27 | 224 | 55% | 45% |

#### Part 5. Speed of the move (medians; 'n/a' = never reached)

| population | n | R at 10 s | R at 30 s | R at 60 s | R/s over first 30 s | time to +0.10R | time to +0.25R | time to −0.10R | time to −0.25R | share reaching +0.10R | share reaching −0.10R | time to MFE | duration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| winners | 172 | -0.06 | -0.00 | 0.06 | -0.0001 | 27 s | 61 s | 1 s | 17 s | 100% | 94% | 227 s | 269 s |
| losers (net ≤ 0) | 127 | -0.12 | -0.19 | -0.31 | -0.0063 | 28 s | 69 s | 0 s | 13 s | 52% | 100% | 30 s | 251 s |
| full losses | 127 | -0.12 | -0.19 | -0.31 | -0.0063 | 28 s | 69 s | 0 s | 13 s | 52% | 100% | 30 s | 251 s |
| never +0.25R | 88 | -0.14 | -0.25 | -0.41 | -0.0082 | 26 s | n/a s | 0 s | 12 s | 31% | 100% | 12 s | 166 s |
| reached +0.50R | 175 | -0.07 | -0.00 | 0.06 | -0.0002 | 28 s | 61 s | 1 s | 13 s | 100% | 94% | 224 s | 270 s |

#### Part 6. Spread around the entry (points; 1 point = $0.01 on 0.01 lot; medians, with the 75th percentile in brackets)

| population | n | spread at entry | min spread first 10 s | max spread first 10 s | avg spread first 30 s | max spread first 60 s | entry spread as % of initial risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 299 | 31 (39) | 18 (24) | 45 (52) | 32 (40) | 49 (55) | 8.5% |
| winners | 172 | 29 (38) | 17 (24) | 44 (51) | 30 (39) | 48 (55) | 8.0% |
| losers | 127 | 32 (41) | 19 (25) | 47 (53) | 34 (40) | 51 (55) | 9.2% |
| full losses | 127 | 32 (41) | 19 (25) | 47 (53) | 34 (40) | 51 (55) | 9.2% |
| never +0.25R | 88 | 34 (44) | 20 (25) | 48 (54) | 34 (42) | 52 (56) | 9.2% |
| reached +0.50R | 175 | 29 (38) | 17 (23) | 44 (51) | 30 (38) | 47 (55) | 8.2% |

Entry spread ≥ 45 points (top quarter): 47 trades, full-loss rate 51%, win rate 49%, expectancy -1.13; below 45: 252 trades, full-loss rate 41%, win rate 59%, expectancy -0.39. (45 points is the observed upper quartile, used only to describe the two populations.)

#### Part 7. Existing entry features (as recorded at the time: SIGNAL log line, opening order, 09-15 report)

Numeric features, medians (25th–75th percentile):

| feature | all | winners | losers | full losses | never +0.25R |
| --- | ---: | ---: | ---: | ---: | ---: |
| RSI at the signal bar | 32.90 (25.80–70.40) n=299 | 33.10 (25.10–70.90) n=172 | 32.60 (26.50–70.10) n=127 | 32.60 (26.50–70.10) n=127 | 31.50 (25.60–70.60) n=88 |
| RSI beyond the 35/65 trigger (points) | 7.10 (3.30–13.00) n=299 | 7.40 (2.80–13.00) n=172 | 6.90 (3.90–12.50) n=127 | 6.90 (3.90–12.50) n=127 | 7.85 (4.40–13.30) n=88 |
| M1 ATR at the signal | 1.81 (1.46–2.09) n=299 | 1.83 (1.45–2.11) n=172 | 1.81 (1.46–2.08) n=127 | 1.81 (1.46–2.08) n=127 | 1.83 (1.56–2.09) n=88 |
| initial risk $ | 3.82 (3.21–4.30) n=299 | 3.83 (3.10–4.32) n=172 | 3.79 (3.30–4.27) n=127 | 3.79 (3.30–4.27) n=127 | 3.86 (3.41–4.34) n=88 |
| fill vs signal-bar close, adverse, in R | 0.04 (-0.04–0.11) n=299 | 0.04 (-0.03–0.12) n=172 | 0.04 (-0.05–0.09) n=127 | 0.04 (-0.05–0.09) n=127 | 0.04 (-0.03–0.09) n=88 |
| Bollinger penetration (first 200) | 0.35 (0.15–0.70) n=200 | 0.32 (0.15–0.72) n=118 | 0.41 (0.17–0.68) n=82 | 0.41 (0.17–0.68) n=82 | 0.38 (0.15–0.66) n=57 |
| entry spread (points) | 31.00 (24.00–39.00) n=299 | 29.00 (23.00–38.00) n=172 | 32.00 (25.00–41.00) n=127 | 32.00 (25.00–41.00) n=127 | 34.50 (25.00–44.00) n=88 |

Categorical features (share of the category that ended as a full loss / never reached +0.25R / won; expectancy $):

| feature | value | trades | full loss | never +0.25R | win | expectancy | half A exp (n) | half B exp (n) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| direction | LONG | 170 | 43% | 32% | 57% | -0.50 | -0.49 (88) | -0.52 (82) |
| direction | SHORT | 129 | 42% | 26% | 58% | -0.52 | -0.15 (61) | -0.84 (68) |
| session | 00-07 | 74 | 47% | 36% | 53% | -0.77 | 0.35 (23) | -1.28 (51) |
| session | 07-12 | 91 | 52% | 36% | 48% | -1.07 | -1.44 (51) | -0.60 (40) |
| session | 12-17 | 70 | 34% | 19% | 66% | 0.09 | 0.27 (40) | -0.15 (30) |
| session | 17-24 | 64 | 33% | 23% | 67% | -0.05 | 0.08 (35) | -0.21 (29) |
| ATR regime | LOW | 110 | 40% | 25% | 60% | -0.33 | -0.54 (47) | -0.18 (63) |
| ATR regime | NORMAL | 162 | 46% | 32% | 54% | -0.78 | -0.42 (85) | -1.18 (77) |
| ATR regime | HIGH | 27 | 30% | 30% | 70% | 0.41 | 0.51 (17) | 0.24 (10) |
| Bollinger penetration bucket | touch | 29 | 48% | 34% | 52% | -0.79 | -0.34 (23) | -2.53 (6) |
| Bollinger penetration bucket | small | 61 | 33% | 25% | 67% | 0.00 | 0.75 (43) | -1.76 (18) |
| Bollinger penetration bucket | medium | 45 | 44% | 31% | 56% | -0.76 | -1.15 (31) | 0.11 (14) |
| Bollinger penetration bucket | deep | 65 | 43% | 28% | 57% | -0.47 | -0.78 (52) | 0.76 (13) |
| Bollinger penetration bucket | n/a | 99 | 45% | 31% | 55% | -0.65 | n/a (0) | -0.65 (99) |
| candle pattern at the signal bar | - | 289 | 43% | 30% | 57% | -0.55 | -0.39 (143) | -0.70 (146) |
| candle pattern at the signal bar | hammer | 2 | 50% | 0% | 50% | -1.43 | n/a (0) | -1.43 (2) |
| candle pattern at the signal bar | hanging_man | 4 | 0% | 0% | 100% | 1.62 | 1.59 (3) | 1.73 (1) |
| candle pattern at the signal bar | inverted_hammer | 1 | 100% | 100% | 0% | -3.66 | -3.66 (1) | n/a (0) |
| candle pattern at the signal bar | shooting_star | 3 | 33% | 0% | 67% | 1.98 | 1.03 (2) | 3.88 (1) |
| RSI beyond trigger (points) | 0–2.5 | 54 | 30% | 17% | 70% | -0.05 | -0.25 (27) | 0.16 (27) |
| RSI beyond trigger (points) | 2.5–5 | 49 | 53% | 35% | 47% | -1.32 | -0.73 (26) | -1.99 (23) |
| RSI beyond trigger (points) | 5–10 | 82 | 48% | 30% | 52% | -0.62 | -0.25 (42) | -1.02 (40) |
| RSI beyond trigger (points) | 10+ | 114 | 40% | 32% | 60% | -0.30 | -0.29 (54) | -0.30 (60) |
| trend filter | off | 299 | 42% | 29% | 58% | -0.51 | -0.35 (149) | -0.67 (150) |
| lot | 0.01 | 271 | 41% | 29% | 59% | -0.44 | -0.20 (140) | -0.71 (131) |
| lot | 0.02 | 28 | 54% | 36% | 46% | -1.12 | -2.67 (9) | -0.39 (19) |

#### Part 8. First 60 seconds by session

| session | n | median MAE 60 s | median MFE 60 s | +0.25R within 60 s | −0.25R within 60 s | reached +0.50R (any time) | never +0.25R | full loss | expectancy | half A exp (n) | half B exp (n) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00-07 | 74 | -0.37 | 0.09 | 31% | 72% | 50% | 36% | 47% | -0.77 | 0.35 (23) | -1.28 (51) |
| 07-12 | 91 | -0.33 | 0.10 | 29% | 69% | 49% | 36% | 52% | -1.07 | -1.44 (51) | -0.60 (40) |
| 12-17 | 70 | -0.30 | 0.21 | 47% | 60% | 70% | 19% | 34% | 0.09 | 0.27 (40) | -0.15 (30) |
| 17-24 | 64 | -0.31 | 0.13 | 28% | 67% | 69% | 23% | 33% | -0.05 | 0.08 (35) | -0.21 (29) |

#### Part 9. LONG versus SHORT (early path)

| direction | half | n | median MAE 30 s | median MAE 60 s | median MFE 60 s | median time to +0.25R | median time to −0.25R | never +0.25R | −0.25R within 30 s | full loss | win | expectancy |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LONG | all | 170 | -0.27 | -0.34 | 0.09 | 83 s | 12 s | 32% | 58% | 43% | 57% | -0.50 |
| LONG | A | 88 | -0.25 | -0.31 | 0.15 | 61 s | 15 s | 31% | 50% | 40% | 60% | -0.49 |
| LONG | B | 82 | -0.29 | -0.38 | 0.05 | 94 s | 10 s | 34% | 66% | 46% | 54% | -0.52 |
| SHORT | all | 129 | -0.22 | -0.31 | 0.19 | 52 s | 19 s | 26% | 46% | 42% | 58% | -0.52 |
| SHORT | A | 61 | -0.22 | -0.32 | 0.20 | 51 s | 19 s | 23% | 46% | 39% | 61% | -0.15 |
| SHORT | B | 68 | -0.22 | -0.29 | 0.17 | 56 s | 20 s | 28% | 46% | 44% | 56% | -0.84 |

#### Part 10. Half A (7–11 Sep) versus half B (14–17 Sep): the key early-path findings

| finding | half A | half B | overall |
| --- | ---: | ---: | ---: |
| trades | 149 | 150 | 299 |
| expectancy $ | -0.35 | -0.67 | -0.51 |
| never +0.25R (share) | 28% | 31% | 29% |
| full-loss rate | 40% | 45% | 42% |
| median MAE first 30 s | -0.25 | -0.27 | -0.26 |
| median MFE first 30 s | 0.09 | 0.05 | 0.07 |
| reached -0.10R within 10 s: share of trades | 85% | 88% | 87% |
| … their full-loss rate | 43% | 46% | 44% |
| reached -0.25R within 30 s: share of trades | 48% | 57% | 53% |
| … their full-loss rate | 54% | 56% | 55% |
| reached -0.25R within 60 s: share of trades | 64% | 71% | 67% |
| … their full-loss rate | 54% | 55% | 54% |
| reached -0.33R within 60 s: share of trades | 46% | 54% | 50% |
| … their full-loss rate | 54% | 58% | 56% |
| reached +0.10R within 10 s: share of trades | 17% | 16% | 16% |
| … their win rate | 60% | 79% | 69% |
| reached +0.25R within 30 s: share of trades | 23% | 17% | 20% |
| … their win rate | 74% | 76% | 75% |
| reached +0.25R within 60 s: share of trades | 37% | 30% | 33% |
| … their win rate | 80% | 84% | 82% |
| reached +0.33R within 60 s: share of trades | 25% | 21% | 23% |
| … their win rate | 86% | 81% | 84% |
| winners: median time to +0.10R (s) | 24 | 32 | 27 |
| full losses: median time to −0.10R (s) | 0 | 1 | 0 |
| entry spread ≥ 45 pts: full-loss rate | 46% | 53% | 51% |
| entry spread < 45 pts: full-loss rate | 39% | 43% | 41% |
| 07-12 session expectancy $ | -1.44 | -0.60 | -1.07 |
| LONG expectancy $ / SHORT expectancy $ | -0.49 / -0.15 | -0.52 / -0.84 | -0.50 / -0.52 |
| RSI beyond trigger ≥ 5: full-loss rate | 40% | 47% | 43% |
| RSI beyond trigger < 5: full-loss rate | 40% | 42% | 41% |

#### Part 12. Failure modes of the losing trades (path shape first, then overlays)

| failure mode (mutually exclusive, path shape) | losing trades | share of losers | net $ | full losses | median MAE 30 s | median MFE | median entry spread |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 immediate adverse move (−0.25R within 30 s, never +0.10R before) | 76 | 60% | -284.41 | 76 | -0.39 | 0.01 | 32 |
| 2 slow / no follow-through (never +0.25R, not immediate) | 24 | 19% | -99.17 | 24 | -0.20 | 0.17 | 32 |
| 3 brief favourable move then reversal (reached +0.25R, then lost) | 27 | 21% | -97.63 | 27 | -0.18 | 0.37 | 32 |

Overlays (a losing trade can carry several; share of losers and of all trades with that trait):

| overlay | losers with it | share of losers | all trades with it | loss rate among them | full-loss rate among them |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 spread/friction: entry spread ≥ 45 pts | 24 | 19% | 47 | 51% | 51% |
| 5 session 07-12 | 47 | 37% | 91 | 52% | 52% |
| 6 direction LONG | 73 | 57% | 170 | 43% | 43% |
| 7 ATR regime LOW | 44 | 35% | 110 | 40% | 40% |
| 7 ATR regime HIGH | 8 | 6% | 27 | 30% | 30% |
| 8 deep Bollinger penetration | 28 | 22% | 65 | 43% | 43% |
| 9 RSI ≥ 5 points beyond trigger | 85 | 67% | 196 | 43% | 43% |
| 9 filled ≥ 0.10R worse than the signal-bar close | 30 | 24% | 84 | 36% | 36% |

Base rates: loss rate 42%, full-loss rate 42%.

#### Part 13. Direct answers (numbers)

* 'Looks bad within 30 s' = reached −0.25R within 30 s, or reached −0.10R within 30 s without ever reaching +0.10R in that time.
* Losers (net ≤ 0) that look bad within 30 s: 102 of 127 (80%); full losses: 102 of 127 (80%).
* Winners that look bad within 30 s: 94 of 172 (55%); large winners (≥ +0.75R): 32 of 67.
* At 10 s: −0.25R reached by 99 trades → full-loss rate 53%, win rate 47%; +0.25R reached by 14 → win rate 71%, full-loss rate 29%; neither yet: 186 trades.
* At 30 s: −0.25R reached by 157 trades → full-loss rate 55%, win rate 45%; +0.25R reached by 59 → win rate 75%, full-loss rate 25%; neither yet: 95 trades.
* At 60 s: −0.25R reached by 201 trades → full-loss rate 54%, win rate 46%; +0.25R reached by 100 → win rate 82%, full-loss rate 18%; neither yet: 33 trades.
