# Profit-protection analysis for the XAUUSD scalp bot (research only)

Date: 2026-09-17 · Branch: `research/small-profit-small-loss` (worktree `C:\Develompent\forex_research_spsl`, at
`scalp-test` `4b0c3a6`) · Script: `docs/research/profit_protection_analysis.py` (new file; it imports the loader of
`small_profit_small_loss_analysis.py`) · Status: **no bot, config, strategy, execution, position-management or risk
file modified; no model implemented; nothing committed, pushed, deployed or restarted; no terminal attached.**

## Conclusion first

**Can partial profit protection materially reduce the large givebacks without destroying the trades that run to
1R? Only at the margin, because the live bot already does most of it.** The live rule (stop to breakeven once the
trade is 1 live ATR ≈ +0.5R ahead, then a 1 ATR trail) had already moved the stop on 160 of the 175 trades that
touched +0.50R. What the predefined models add on top is small:

* **Model A (arm at +0.50R)** changes 11–57 exits and improves the net by **$7.70–$14.73 on 299 trades**
  (expectancy −$0.51 → −$0.46 per trade). All of the gain is the 8 trades whose +0.52…+0.76R peak was too brief for
  the 2-second poll and the live-ATR test, so the live breakeven never fired and they ran back to −1R (−$32.06).
  It cuts only 3–4 of the 67 large winners. It meets every clause of the pre-registered rule, so it is classified
  **PROMISING**, but read that as "a tick-exact breakeven would have saved 8 trades", not as a change in the
  strategy's prospects: the result is still −$137 to −$144 with a profit factor of 0.69–0.70.
* **Model B (arm at +0.75R)** overlaps the live trail. B1/B2 change 1–18 exits for ±$3; B3 (floor +0.50R) is
  tighter than the live trail, gains $11.66 but cuts 9 large winners and prevents only 1 large loss:
  **INCONCLUSIVE**.
* **Model C (arm at +1.00R)** never fires: every trade that touched +1.00R either hit its 1R target or was already
  being trailed 0.5R behind its high, so the real exit always came first. Identical to the actual result:
  **REJECTED** (no effect, not harmful).

The giveback that matters is below the arming levels of every model: **40 trades touched +0.25R and still closed at
a full loss (−$147.40), 30 of them after +0.33R (−$113.34)**; no predefined model touches them, and a floor at
those levels was not tested here (it would be a new pre-registration). Larger still, **88 trades (29%) never reached
+0.25R at all (−$332.88)**, which is more than twice the whole net loss. As in the envelope study, the loss is made
at entry, not at exit.

Recommendation: if a second live experiment is wanted, the only candidate this data supports is making the existing
breakeven rule tick-exact and R-based (Model A2 or A3 behaviour: arm at +0.50R of the *initial* stop on every tick,
floor 0R or +0.10R), expected to add about +$0.05 per trade. It is not a route to profitability and should be
pre-registered as a "recover the 8 missed breakevens" test, if at all. Anything aimed at the −$147 / −$333 pools is
an entry question and is out of this task's scope.

## 1. Methodology (fixed before running)

* **Data.** The same 299 verified tick paths (149 replayed for 7–11 Sep, 150 live-recorded for 13–17 Sep; real
  broker ticks; longs marked at the bid, shorts at the ask; no M1 inference; no interpolation; daily-break quotes with
  a spread above 300 points left out of the marking; the 2 pre-fix and 4 hand-closed trades excluded). R = marked
  P&L / initial risk, where initial risk = |fill − initial stop| × terminal-priced $ per point × lot (mean $3.79).
* **Thresholds.** +0.25R, +0.33R, +0.50R, +0.75R, +1.00R; the first tick at or above each level in recorded order.
  For each: MFE of the whole trade, MAE from the touch to the exit, final result, full loss (≤ −0.9R) and significant
  loss (≤ −0.5R) counts, time from the touch to the exit, and whether the live bot had moved the stop to breakeven or
  better on that trade (from the recorded `sl_move` events).
* **Models.** A1–A3 arm at +0.50R with floors −0.25R / 0R / +0.10R; B1–B3 arm at +0.75R with floors 0R / +0.25R /
  +0.50R; C1–C3 arm at +1.00R with floors +0.25R / +0.50R / +0.75R. No look-ahead: a model arms at the first tick
  whose marked R is at or above the arming level; from the **next** tick on, the trade exits at the first tick whose
  marked R is at or below the floor, at that tick's quote. If that never happens, the trade keeps its real exit,
  which already includes the live breakeven and trail. So a model's effect is what it adds *on top of* the real
  management; "protected (affected)" counts only trades whose exit the model changed.
* **Definitions.** Large winner = actual result ≥ +0.75R (67 trades). Large loss = actual ≤ −0.75R (127 trades, all
  full stops). Giveback prevented = Σ (model − actual) over changed trades where positive; new losses caused = the
  negative part (winners cut below their real exit).
* **Decision rule (pre-registered).** PROMISING only if (1) ≥ 5 large losses prevented and ≥ $20 of giveback
  prevented; (2) fewer than half of the large winners cut and $ forfeited < $ prevented; (3) expectancy better than
  the actual exits; (4) net and expectancy better than the actual exits in both halves; (5) the improvement stays
  positive after removing the best single session bucket and the best single direction bucket. REJECTED if (3)
  fails or both halves fail; INCONCLUSIVE otherwise. Reference: actual exits 299 trades / −$151.94 / PF 0.68 /
  max DD $159.86 / expectancy −$0.508.

## 2. Results

Trades: **299** (the same 299 verified tick paths; excluded {'pre-fix': 2, 'closed by hand': 4}); half A 149, half B 150. Actual exits: net -151.94, PF 0.68, max DD 159.86, expectancy -0.508/trade. Mean initial risk $3.79. Large winners (actual >= +0.75R): 67; large losses (<= -0.75R): 127; significant losses (<= -0.50R): 127.

#### Threshold statistics (first touch in tick order)

| threshold | touched | of all | later won | full loss (≤ −0.9R) | significant loss (≤ −0.5R) | mean final R | median final R | mean MFE (whole trade) | mean MAE after touch | worst MAE after touch | median time touch→exit | live BE fired on those |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| +0.25R | 211 | 71% | 171 | 40 | 40 | +0.22 | +0.22 | +0.76 | -0.22 | -1.22 | 184 s | 164 |
| +0.33R | 201 | 67% | 171 | 30 | 30 | +0.28 | +0.23 | +0.78 | -0.12 | -1.22 | 160 s | 164 |
| +0.50R | 175 | 59% | 167 | 8 | 8 | +0.45 | +0.31 | +0.84 | +0.16 | -1.11 | 82 s | 160 |
| +0.75R | 109 | 36% | 108 | 1 | 1 | +0.72 | +0.96 | +0.97 | +0.50 | -1.00 | 38 s | 101 |
| +1.00R | 53 | 18% | 53 | 0 | 0 | +1.02 | +1.00 | +1.07 | +1.01 | +0.77 | 0 s | 49 |

Never reached +0.25R: 88 trades (29%), net -332.88, all {'SL': 87, 'TP': 1}.

#### Givebacks: touched a threshold, then closed at a significant loss (≤ −0.50R)

| touched | then full loss (≤ −0.9R) | then significant loss (≤ −0.5R) | their net $ | of which also touched +0.50R | of which the live breakeven had fired |
| --- | ---: | ---: | ---: | ---: | ---: |
| +0.25R | 40 | 40 | -147.40 | 8 | 0 |
| +0.33R | 30 | 30 | -113.34 | 8 | 0 |
| +0.50R | 8 | 8 | -32.06 | 8 | 0 |
| +0.75R | 1 | 1 | -3.07 | 1 | 0 |

Trades that touched +0.50R and still closed at a significant loss:

| fill | side | risk $ | MFE R | +0.50R after | live SL moves | BE fired | final R | final $ | exit |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 09-07 16:06 | SHORT | 3.97 | +0.52 | 91 s | 0 | no | -1.00 | -3.97 | SL |
| 09-08 10:39 | LONG | 4.31 | +0.53 | 141 s | 0 | no | -1.00 | -4.31 | SL |
| 09-09 12:47 | LONG | 4.90 | +0.52 | 24 s | 0 | no | -1.00 | -4.90 | SL |
| 09-09 20:07 | SHORT | 3.07 | +0.76 | 341 s | 0 | no | -1.00 | -3.07 | SL |
| 09-10 07:30 | LONG | 4.52 | +0.55 | 71 s | 0 | no | -1.00 | -4.52 | SL |
| 09-14 14:37 | LONG | 4.08 | +0.55 | 250 s | 0 | no | -1.00 | -4.08 | SL |
| 09-15 22:06 | LONG | 3.24 | +0.55 | 163 s | 0 | no | -1.00 | -3.24 | SL |
| 09-16 11:19 | SHORT | 3.97 | +0.53 | 42 s | 0 | no | -1.00 | -3.97 | SL |

Live breakeven check: of the 175 trades that touched +0.50R tick-exactly, the live stop was moved to breakeven or better on 160; of the 109 that touched +0.75R, on 101. (The live rule needs 1 *live* ATR at a 2-second poll, not 0.5R tick-exact.)

#### Predefined protection models (on top of the real exits)

| model | arm | floor | armed | protected (affected) | trades | wins | losses | win% | gross profit | gross loss | net | expectancy | PF | max DD | longest losing streak | large winners cut | $ forfeited on them | large losses prevented | $ giveback prevented | $ new losses caused (winners cut below their real exit) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| actual | | | | | 299 | 172 | 127 | 57.5% | +329.27 | -481.21 | **-151.94** | -0.508 | 0.68 | 159.86 | 4 | | | | | |
| A1 | +0.50R | -0.25R | 175 | 11 | 299 | 169 | 130 | 56.5% | +317.67 | -461.91 | **-144.24** | -0.482 | 0.69 | 152.16 | 4 | 3 | -14.82 | 8 | +22.52 | -14.82 |
| A2 | +0.50R | +0.00R | 175 | 19 | 299 | 161 | 138 | 53.8% | +315.07 | -452.61 | **-137.54** | -0.460 | 0.70 | 148.33 | 4 | 3 | -11.72 | 8 | +29.97 | -15.57 |
| A3 | +0.50R | +0.10R | 175 | 57 | 299 | 177 | 122 | 59.2% | +312.68 | -449.89 | **-137.21** | -0.459 | 0.70 | 149.07 | 4 | 4 | -15.20 | 8 | +37.13 | -22.40 |
| B1 | +0.75R | +0.00R | 109 | 1 | 299 | 172 | 127 | 57.5% | +329.27 | -478.34 | **-149.07** | -0.499 | 0.69 | 156.99 | 4 | 0 | +0.00 | 1 | +2.87 | +0.00 |
| B2 | +0.75R | +0.25R | 109 | 18 | 299 | 173 | 126 | 57.9% | +326.93 | -478.14 | **-151.21** | -0.506 | 0.68 | 159.13 | 4 | 1 | -2.66 | 1 | +5.33 | -4.60 |
| B3 | +0.75R | +0.50R | 109 | 48 | 299 | 173 | 126 | 57.9% | +337.86 | -478.14 | **-140.28** | -0.469 | 0.71 | 149.20 | 4 | 9 | -16.63 | 1 | +28.33 | -16.67 |
| C1 | +1.00R | +0.25R | 53 | 0 | 299 | 172 | 127 | 57.5% | +329.27 | -481.21 | **-151.94** | -0.508 | 0.68 | 159.86 | 4 | 0 | +0.00 | 0 | +0.00 | +0.00 |
| C2 | +1.00R | +0.50R | 53 | 0 | 299 | 172 | 127 | 57.5% | +329.27 | -481.21 | **-151.94** | -0.508 | 0.68 | 159.86 | 4 | 0 | +0.00 | 0 | +0.00 | +0.00 |
| C3 | +1.00R | +0.75R | 53 | 0 | 299 | 172 | 127 | 57.5% | +329.27 | -481.21 | **-151.94** | -0.508 | 0.68 | 159.86 | 4 | 0 | +0.00 | 0 | +0.00 | +0.00 |

A floor at or below the level where the live breakeven/trail already sits changes little: the real exit arrives first. 'Protected' counts only trades whose exit the model actually changed.

#### Robustness: halves and the decision rule

Rule: PROMISING only if: (1) >= 5 large losses (<= -0.75R) prevented AND >= $20 of giveback prevented; (2) fewer than half of the large winners (>= +0.75R) are cut AND $ forfeited < $ prevented; (3) expectancy better than the actual exits; (4) net AND expectancy better than the actual exits in BOTH halves; (5) the overall improvement stays positive after removing the single best session bucket and the single best direction bucket. REJECTED if (3) fails or both halves fail. INCONCLUSIVE otherwise.

| model | half A net (exp, PF) | half B net (exp, PF) | overall net (exp, PF) | (1) givebacks | (2) winners kept | (3) expectancy | (4) both halves | (5) not one bucket | verdict |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| actual | -51.96 (-0.349, 0.77) | -99.98 (-0.667, 0.61) | -151.94 (-0.508, 0.68) | | | | | | |
| A1 | -47.40 (-0.318, 0.78) | -96.84 (-0.646, 0.61) | -144.24 (-0.482, 0.69) | yes (8 prevented, +22.52) | yes (3/67 cut, -14.82) | yes | yes | yes (best session +4.14, best side +5.19) | **PROMISING** |
| A2 | -40.39 (-0.271, 0.80) | -97.15 (-0.648, 0.61) | -137.54 (-0.460, 0.70) | yes (8 prevented, +29.97) | yes (3/67 cut, -15.57) | yes | yes | yes (best session +6.89, best side +10.68) | **PROMISING** |
| A3 | -42.96 (-0.288, 0.79) | -94.25 (-0.628, 0.62) | -137.21 (-0.459, 0.70) | yes (8 prevented, +37.13) | yes (4/67 cut, -22.40) | yes | yes | yes (best session +9.54, best side +13.30) | **PROMISING** |
| B1 | -49.09 (-0.329, 0.78) | -99.98 (-0.667, 0.61) | -149.07 (-0.499, 0.69) | no (1 prevented, +2.87) | yes (0/67 cut, +0.00) | yes | no | yes (best session +2.87, best side +2.87) | **INCONCLUSIVE** |
| B2 | -49.03 (-0.329, 0.78) | -102.18 (-0.681, 0.60) | -151.21 (-0.506, 0.68) | no (1 prevented, +5.33) | yes (1/67 cut, -4.60) | yes | no | no (best session +4.32, best side +1.33) | **INCONCLUSIVE** |
| B3 | -41.19 (-0.276, 0.81) | -99.09 (-0.661, 0.62) | -140.28 (-0.469, 0.71) | no (1 prevented, +28.33) | yes (9/67 cut, -16.67) | yes | yes | yes (best session +5.86, best side +8.10) | **INCONCLUSIVE** |
| C1 | -51.96 (-0.349, 0.77) | -99.98 (-0.667, 0.61) | -151.94 (-0.508, 0.68) | no (0 prevented, +0.00) | no (0/67 cut, +0.00) | no | no | no (best session +0.00, best side +0.00) | **REJECTED** |
| C2 | -51.96 (-0.349, 0.77) | -99.98 (-0.667, 0.61) | -151.94 (-0.508, 0.68) | no (0 prevented, +0.00) | no (0/67 cut, +0.00) | no | no | no (best session +0.00, best side +0.00) | **REJECTED** |
| C3 | -51.96 (-0.349, 0.77) | -99.98 (-0.667, 0.61) | -151.94 (-0.508, 0.68) | no (0 prevented, +0.00) | no (0/67 cut, +0.00) | no | no | no (best session +0.00, best side +0.00) | **REJECTED** |

#### By session

| session | n | actual net (exp, PF) | A1 net (exp, PF) | A2 net (exp, PF) | A3 net (exp, PF) | B1 net (exp, PF) | B2 net (exp, PF) | B3 net (exp, PF) | C1 net (exp, PF) | C2 net (exp, PF) | C3 net (exp, PF) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00-07 | 74 | -57.06 (-0.77, 0.57) | -57.06 (-0.77, 0.57) | -58.33 (-0.79, 0.56) | -63.64 (-0.86, 0.52) | -57.06 (-0.77, 0.57) | -57.41 (-0.78, 0.57) | -52.32 (-0.71, 0.61) | -57.06 (-0.77, 0.57) | -57.06 (-0.77, 0.57) | -57.06 (-0.77, 0.57) |
| 07-12 | 91 | -97.68 (-1.07, 0.46) | -93.54 (-1.03, 0.46) | -90.79 (-1.00, 0.47) | -88.14 (-0.97, 0.48) | -97.68 (-1.07, 0.46) | -101.22 (-1.11, 0.44) | -93.49 (-1.03, 0.48) | -97.68 (-1.07, 0.46) | -97.68 (-1.07, 0.46) | -97.68 (-1.07, 0.46) |
| 12-17 | 70 | +6.10 (+0.09, 1.07) | +5.60 (+0.08, 1.07) | +9.23 (+0.13, 1.12) | +11.59 (+0.17, 1.16) | +6.10 (+0.09, 1.07) | +6.40 (+0.09, 1.07) | +2.97 (+0.04, 1.03) | +6.10 (+0.09, 1.07) | +6.10 (+0.09, 1.07) | +6.10 (+0.09, 1.07) |
| 17-24 | 64 | -3.30 (-0.05, 0.96) | +0.76 (+0.01, 1.01) | +2.35 (+0.04, 1.03) | +2.98 (+0.05, 1.04) | -0.43 (-0.01, 0.99) | +1.02 (+0.02, 1.01) | +2.56 (+0.04, 1.03) | -3.30 (-0.05, 0.96) | -3.30 (-0.05, 0.96) | -3.30 (-0.05, 0.96) |

#### By direction

| direction | n | actual net (exp, PF) | A1 net (exp, PF) | A2 net (exp, PF) | A3 net (exp, PF) | B1 net (exp, PF) | B2 net (exp, PF) | B3 net (exp, PF) | C1 net (exp, PF) | C2 net (exp, PF) | C3 net (exp, PF) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LONG | 170 | -85.24 (-0.50, 0.70) | -80.05 (-0.47, 0.70) | -74.56 (-0.44, 0.72) | -71.94 (-0.42, 0.73) | -85.24 (-0.50, 0.70) | -85.84 (-0.50, 0.70) | -81.68 (-0.48, 0.71) | -85.24 (-0.50, 0.70) | -85.24 (-0.50, 0.70) | -85.24 (-0.50, 0.70) |
| SHORT | 129 | -66.70 (-0.52, 0.66) | -64.19 (-0.50, 0.67) | -62.98 (-0.49, 0.67) | -65.27 (-0.51, 0.65) | -63.83 (-0.49, 0.67) | -65.37 (-0.51, 0.67) | -58.60 (-0.45, 0.70) | -66.70 (-0.52, 0.66) | -66.70 (-0.52, 0.66) | -66.70 (-0.52, 0.66) |

#### By ATR regime

| ATR regime | n | actual net (exp, PF) | A1 net (exp, PF) | A2 net (exp, PF) | A3 net (exp, PF) | B1 net (exp, PF) | B2 net (exp, PF) | B3 net (exp, PF) | C1 net (exp, PF) | C2 net (exp, PF) | C3 net (exp, PF) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LOW | 110 | -36.49 (-0.33, 0.75) | -28.29 (-0.26, 0.79) | -26.48 (-0.24, 0.80) | -24.95 (-0.23, 0.81) | -36.49 (-0.33, 0.75) | -39.90 (-0.36, 0.73) | -41.47 (-0.38, 0.72) | -36.49 (-0.33, 0.75) | -36.49 (-0.33, 0.75) | -36.49 (-0.33, 0.75) |
| NORMAL | 162 | -126.40 (-0.78, 0.57) | -120.78 (-0.75, 0.58) | -116.60 (-0.72, 0.58) | -114.87 (-0.71, 0.59) | -123.53 (-0.76, 0.58) | -122.26 (-0.75, 0.58) | -109.10 (-0.67, 0.62) | -126.40 (-0.78, 0.57) | -126.40 (-0.78, 0.57) | -126.40 (-0.78, 0.57) |
| HIGH | 27 | +10.95 (+0.41, 1.28) | +4.83 (+0.18, 1.12) | +5.54 (+0.21, 1.14) | +2.61 (+0.10, 1.07) | +10.95 (+0.41, 1.28) | +10.95 (+0.41, 1.28) | +10.29 (+0.38, 1.27) | +10.95 (+0.41, 1.28) | +10.95 (+0.41, 1.28) | +10.95 (+0.41, 1.28) |

Verdicts: A1 PROMISING, A2 PROMISING, A3 PROMISING, B1 INCONCLUSIVE, B2 INCONCLUSIVE, B3 INCONCLUSIVE, C1 REJECTED, C2 REJECTED, C3 REJECTED.

## 3. Reading the results

### 3.1 Threshold statistics

* 71% of trades reach +0.25R, 59% +0.50R, 36% +0.75R, 18% +1.00R. Once +0.75R is touched, 108 of 109 trades end
  positive; after +1.00R, 53 of 53 (the 1R target is usually the exit; median time from +1.00R to exit is 0 s).
* After touching +0.25R the average trade still dips to −0.22R; after +0.50R its later low is +0.16R on average.
  The dangerous zone is +0.25R…+0.50R: 40 trades touched +0.25R and then lost in full, and 30 of them had reached
  +0.33R. Only 8 of the 40 ever reached +0.50R.
* The live breakeven fired on 164 of the 211 trades that touched +0.25R, but that is because most of those went on
  to +0.50R; none of the 40 full-loss givebacks had a stop move, because 32 never reached the live trigger and the
  other 8 peaked too briefly (0.52–0.76R for a few seconds) for a 2-second loop that also re-measures ATR live.

### 3.2 Models

* **A1/A2/A3** (arm +0.50R): 175 trades arm; 11/19/57 exits change. Each prevents exactly the 8 missed-breakeven
  losses (+$22.52 to +$37.13) and cuts 3–4 large winners (−$11.72 to −$22.40). Net +$7.70 / +$14.40 / +$14.73.
  Max drawdown $160 → $148–152. Both halves improve; the best single session (17–24) or direction (LONG) explains
  less than half of the gain. A3 also changes 57 exits, mostly trades the live trail would have closed slightly
  lower; its 4 cut winners include winners that later ran to their target.
* **B1/B2** (arm +0.75R, floors 0R / +0.25R): the live trail already sits at or above these floors once +0.75R is
  reached, so 1 and 18 exits change, for +$2.87 and −$0.73. **B3** (floor +0.50R) is a tighter trail: +$11.66, but 9
  large winners cut for 1 large loss prevented; fails the giveback clause.
* **C1–C3**: no trade affected. After +1.00R the target fills or the trail is already 0.5R behind the high.

### 3.3 Halves and segments

* Half A (7–11 Sep) and half B (14–17 Sep) both improve under A1–A3 and B3, by $3–12 each; half B stays at PF
  0.61–0.62 under every model.
* Sessions: the models add a few dollars in 07–12 and 17–24 and subtract in 00–07 (A3 −$6.58 there); 12–17 is the
  only positive session before and after. Directions: LONG gains more than SHORT under A. ATR: LOW gains most
  under A (+$8 to +$12); HIGH, the only positive regime (27 trades), loses $5–8 under A because a tick-exact
  breakeven closes some of its runners on noise. None of these cells is large enough to conclude anything on its own.

### 3.4 Givebacks versus large winners

The requested balance ("reduce the large givebacks without destroying the 1R/2R+ trades") comes out as follows
for the best predefined models:

| model | large losses prevented | $ prevented | large winners cut | $ forfeited | net change |
| --- | ---: | ---: | ---: | ---: | ---: |
| A2 (arm +0.50R, floor 0R) | 8 of 127 | +$29.97 | 3 of 67 | −$15.57 | +$14.40 |
| A3 (arm +0.50R, floor +0.10R) | 8 of 127 | +$37.13 | 4 of 67 | −$22.40 | +$14.73 |
| B3 (arm +0.75R, floor +0.50R) | 1 of 127 | +$28.33 | 9 of 67 | −$16.67 | +$11.66 |

Eight of 127 large losses is 6%; the other 119 never reached +0.50R and are out of reach of every model tested.

## 4. Limitations

* 299 trades, 8 trading days, both halves negative; the model effects are $8–15, i.e. 5–10% of the loss, driven by
  8 trades. That is enough to say the effect is small and consistent, not enough to size it.
* Model exits are simulated at the marked quote of the touching tick; the live bot would use a stop order (fills at
  the level) placed with a 2-second poll, so a live version would sit between the model and the current behaviour.
* Models are layered on the real exits, which already contain the live breakeven and trail; they cannot show what a
  protection rule would do *instead of* the trail, only in addition to it.
* The floors below +0.50R that the giveback statistics point at (+0.25R / +0.33R) were not simulated: they are not
  among the predefined models and would need their own pre-registration.
* ATR regime for the last 99 trades is derived from each trade's own stop distance; Bollinger penetration was not
  used here.

## 5. Final recommendation

* **Models C: REJECTED** (no effect). **Models B: INCONCLUSIVE** (overlap with the live trail; B3 trades winners
  for losses). **Models A: PROMISING under the pre-registered rule, with a small effect** (+$8 to +$15 on 299 trades,
  from 8 missed breakevens).
* The only change this data supports for a future live experiment is a **tick-exact, R-based breakeven** (arm at
  +0.50R of the initial stop, floor 0R or +0.10R) replacing the current "1 live ATR at poll time" trigger. Expected
  effect about +$0.05 per trade and a slightly lower drawdown; it does not change the sign of the strategy. If run,
  it should be pre-registered as recovering the missed breakevens, with a stop condition, and not on the live
  `scalp-test` account while its validation continues.
* The larger givebacks (touched +0.25R…+0.33R, then −1R: 40 trades, −$147) and the immediate losers (88 trades,
  −$333) are entry-quality problems. No exit or protection rule tested in this or the previous study changes that.

## 6. What was and was not done

* Added two files on the research branch, both untracked and uncommitted: this note and
  `docs/research/profit_protection_analysis.py`. No existing `.py`, `.cmd`, config, strategy, execution,
  position-management or risk file was modified on any branch.
* `main` and `scalp-test` untouched; the live bot (process started 2026-09-15 19:06) and its terminal were neither
  restarted nor attached to; all data came from files.
