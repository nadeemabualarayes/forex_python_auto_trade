# Small-profit / small-loss analysis for the XAUUSD scalp bot (phase 1, research only)

Date: 2026-09-17 · Branch: `research/small-profit-small-loss` (own worktree `C:\Develompent\forex_research_spsl`, branched
from `scalp-test` at `4b0c3a6`) · Script: `docs/research/small_profit_small_loss_analysis.py` · Status: **no strategy,
config or risk change made; nothing committed, pushed or deployed; the running bot was not touched.**

## Conclusion first

**The current data does not support a small-profit / small-loss approach as a way to make this strategy profitable.
It does support it as a way to make the losses smaller.** Taking about $1 per trade would indeed destroy the larger
winners (the 69 take-profit exits alone earned +$257 of the +$329 gross profit), and the trades that cause the
loss are mostly ones that never offer any profit to take: 68 of 299 trades (23%) never reached even +$0.50 and went
straight to their stop, for −$254.61 together, more than the whole net loss of −$151.94. No profit target can help
those; a tighter loss cap only makes each of them cheaper.

All five pre-registered envelopes lose less than the live exits but still lose: net −$89 to −$109 on 299 trades
(profit factor 0.41–0.73) against −$151.94 (0.68) for the live exits, and none has a profit factor above 1.0 in
either half of the data. The best of them, **+$1.50 / −$2.00**, cuts the loss by 41% and the maximum drawdown from
$160 to $94, but still loses $0.30 per trade before exit slippage. The −$1.00 stops are the worst idea in the set:
$1 is 100 points on 0.01 lot, about three spreads, so 73–84 trades that actually won are stopped out first.

The exit rule is not what is losing money; the entries are. The 07–12 server session loses under every scenario
(PF 0.39–0.47), and a quarter of all entries move against the trade immediately. Under the user's own rule ("do not
change entries until the research has been reviewed"), the minimum next step is described in section 6, with the
recommendation not to run it as a profitability test.

## 1. Question, data and rules fixed before running

**Question.** Would exiting at a small fixed dollar profit, with a small fixed dollar loss, give a more controlled
profile than the live exits (stop 2 ATR, target 2 ATR, breakeven at 1 ATR then a 1 ATR trail), without increasing risk?

**Pre-registered, not searched.** Thresholds +$0.50 / +$1.00 / +$1.50 / +$2.00; envelopes +$0.50/−$1, +$1/−$1,
+$1/−$2, +$1.50/−$2, +$2/−$2; robustness split into half A (7–11 Sep, replayed ticks) and half B (14–17 Sep, live
recorder); decision rule: an envelope is *supported* only if its net beats the live exits **and** its profit factor is
above 1.0 in **both** halves. No other thresholds were tried.

**Data (files only; no script attached to the live terminal).**

* Every post-sizing-fix strategy trade with a tick path: **299 trades**, fills 2026-09-07 14:33 to 2026-09-17 12:11
  server; 499,102 broker ticks. Excluded: the 2 pre-fix 0.18-lot trades and the 4 positions closed by hand.
* Tick paths: 149 from the 09-13 replay audit (real ticks 7–11 Sep, verified tick-for-tick against the terminal) and
  150 from the live recorder (13–17 Sep). Longs are marked at the bid, shorts at the ask, so every marked P&L
  already pays the spread. Ticks are used in their recorded order; **nothing is inferred from M1 bars and nothing
  is interpolated.** The broker's daily-break quotes (spread above 300 points: 108 ticks in two trades, 106 of them
  in the one trade held across the break) are left out of the marking; that trade's envelopes had resolved hours
  earlier in normal quotes, and leaving these ticks out moves every figure by less than $3.
* Realised net per trade from `history.db` (commission and swap are zero on this demo); order price at entry from
  the journal for slippage; ATR regime and Bollinger penetration from the 09-15 forward report (first 200 trades;
  later trades take ATR from their own stop distance, penetration "n/a").

**Envelope mechanics.** Entries unchanged. The trade exits at the first tick whose marked P&L is at or beyond the
target or the loss cap, at that tick's quote (so a gap past the level counts for or against the trade; a real
take-profit order would fill at the level or better, a real stop at the level: both conservative). If neither level
is touched before the real exit, the trade keeps its real exit ("unresolved"; 0–3 trades per envelope, 22 for
+$2/−$2). Exit slippage is shown separately at $0.02 and $0.05 per trade; the observed entry slippage against the
order price is median $0.00, mean +$0.012.

## 2. Results

Scale: mean risk at the initial stop $3.79 (range $2.35–$5.99), so +$1.00 is 26% of 1R and −$2.00 is 53% of 1R on
average; the live breakeven move comes at 1 ATR = 50% of 1R (about +$1.89). Spread at the fill: mean $0.35,
median $0.32, max $1.12.

Trades analysed: **299** strategy trades with a tick path, fills 2026-09-07 14:33 -> 2026-09-17 12:11 server; excluded: {'pre-fix': 2, 'closed by hand': 4}. Half A (replayed ticks, 09-07..09-11): 149; half B (live recorder, 09-14..): 150. Incomplete paths kept: 1. Ticks: 498,994. Lots: {0.01: 271, 0.02: 28}. Penetration known for 200 trades (from the 09-15 report). Ticks with a spread above 300 points (daily-break quotes) left out of the marking: 108 ticks in 2 trade(s): {58401835044: 106, 58425437911: 2}.

Risk at the initial stop: mean $3.79, min $2.35, max $5.99. Spread at the fill (bid/ask x lot): mean $0.352, median $0.320, max $1.120. Entry slippage vs the order price (+ = worse): mean $+0.012, median $+0.000, worst $+2.53, best $-0.57 (299 matched).

### Baseline: what actually happened (same trades)

| scenario | trades | wins | losses | win% | gross profit | gross loss | net | expectancy | PF | max DD | longest losing streak |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| actual exits (SL 2 ATR / TP 2 ATR / BE+trail) | 299 | 172 | 127 | 57.5% | +329.27 | -481.21 | **-151.94** | -0.508 | 0.68 | 159.86 | 4 |

Actual net by exit label: SL 127x -481.21, TRAIL 103x +71.84, TP 69x +257.43.

### 1–3. Trades that reached +$0.50 / +$1.00 / +$1.50 / +$2.00 before closing

| threshold | reached | of all | later won | later lost | mean final P&L of those | median | final ≤ −$2.50 (full stop) | final ≤ −$3.50 | mean MAE after the touch | worst MAE after touch | median time to touch | exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| +$0.50 | 231 | 77% | 172 | 59 | +0.44 | +0.67 | 59 | 42 | -1.42 | -5.14 | 33 s | TRAIL 103, TP 69, SL 59 |
| +$1.00 | 207 | 69% | 171 | 36 | +0.92 | +0.80 | 36 | 25 | -0.71 | -5.14 | 78 s | TRAIL 103, TP 68, SL 36 |
| +$1.50 | 187 | 63% | 170 | 17 | +1.37 | +1.03 | 17 | 15 | +0.04 | -5.05 | 116 s | TRAIL 102, TP 68, SL 17 |
| +$2.00 | 157 | 53% | 149 | 8 | +1.85 | +1.42 | 8 | 7 | +0.65 | -4.92 | 137 s | TRAIL 81, TP 68, SL 8 |

MAE after the touch = the lowest marked P&L between the first touch of the threshold and the exit (a mean of −2.00 means that, on average, these trades later fell to −$2.00 before closing).

Never reached +$0.50: 68 trades (23%), net -254.61, exits {'SL': 68}.

#### 3. Trades that reached +$1.00 and then closed at a full loss (≤ −$3.50)

25 of the 207 trades that touched +$1.00 (of 299) ended at −$3.50 or worse; their net -103.82. With ≤ −$2.50 as the cut: 36 trades.

| fill (server) | side | lot | risk $ | MFE $ | touched +$1 after | final $ | exit | how |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 09-07 16:06 | SHORT | 0.01 | 3.97 | +2.06 | 47 s | -3.97 | SL | peaked at 52% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-08 10:39 | LONG | 0.01 | 4.31 | +2.30 | 98 s | -4.31 | SL | peaked at 53% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-08 15:13 | LONG | 0.01 | 4.61 | +1.30 | 17 s | -4.61 | SL | peaked at 28% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-09 07:00 | LONG | 0.02 | 4.08 | +1.34 | 141 s | -4.08 | SL | peaked at 33% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-09 12:47 | LONG | 0.02 | 4.90 | +2.54 | 17 s | -4.90 | SL | peaked at 52% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-10 04:01 | SHORT | 0.01 | 4.44 | +1.89 | 5 s | -4.44 | SL | peaked at 43% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-10 07:30 | LONG | 0.02 | 4.52 | +2.50 | 46 s | -4.52 | SL | peaked at 55% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-10 14:48 | LONG | 0.01 | 3.66 | +1.11 | 125 s | -3.66 | SL | peaked at 30% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-10 22:47 | LONG | 0.01 | 4.13 | +1.84 | 17 s | -4.26 | SL | peaked at 45% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-11 03:01 | SHORT | 0.01 | 3.60 | +1.20 | 6 s | -3.60 | SL | peaked at 33% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-11 03:46 | SHORT | 0.01 | 4.72 | +1.16 | 917 s | -4.72 | SL | peaked at 25% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-11 20:13 | SHORT | 0.01 | 4.27 | +1.51 | 78 s | -4.27 | SL | peaked at 35% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-14 14:37 | LONG | 0.02 | 4.08 | +2.24 | 240 s | -4.08 | SL | peaked at 55% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-14 19:11 | SHORT | 0.01 | 4.41 | +1.54 | 227 s | -4.41 | SL | peaked at 35% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-15 04:56 | SHORT | 0.01 | 4.62 | +1.91 | 71 s | -4.62 | SL | peaked at 41% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-15 11:44 | LONG | 0.01 | 3.62 | +1.37 | 152 s | -3.62 | SL | peaked at 38% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-15 15:10 | LONG | 0.01 | 3.58 | +1.46 | 283 s | -3.58 | SL | peaked at 41% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-16 01:15 | LONG | 0.02 | 3.62 | +1.30 | 123 s | -3.62 | SL | peaked at 36% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-16 11:17 | SHORT | 0.01 | 3.82 | +1.43 | 132 s | -3.82 | SL | peaked at 37% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-16 11:19 | SHORT | 0.01 | 3.97 | +2.09 | 1 s | -3.97 | SL | peaked at 53% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-16 14:51 | LONG | 0.01 | 3.60 | +1.22 | 255 s | -3.60 | SL | peaked at 34% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-16 15:43 | SHORT | 0.01 | 4.27 | +1.67 | 23 s | -4.27 | SL | peaked at 39% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-17 04:59 | LONG | 0.01 | 4.66 | +1.50 | 64 s | -4.66 | SL | peaked at 32% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-17 08:55 | SHORT | 0.01 | 4.09 | +1.77 | 69 s | -4.09 | SL | peaked at 43% of 1R, stop never moved (breakeven needs ~+50% of 1R) |
| 09-17 10:02 | SHORT | 0.01 | 4.14 | +2.04 | 17 s | -4.14 | SL | peaked at 49% of 1R, stop never moved (breakeven needs ~+50% of 1R) |

### 4. Pre-registered envelopes (exit at the first tick at or beyond +profit / −loss, entries unchanged)

| envelope | trades | wins | losses | win% | gross profit | gross loss | net | expectancy | PF | max DD | longest losing streak | unresolved | mean overshoot at target | mean overshoot at stop |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline (actual) | 299 | 172 | 127 | 57.5% | +329.27 | -481.21 | **-151.94** | -0.508 | 0.68 | 159.86 | 4 | | | |
| +$0.50 / −$1.00 | 299 | 132 | 167 | 44.1% | +75.91 | -184.87 | **-108.96** | -0.364 | 0.41 | 109.46 | 8 | 0 | +0.075 | -0.107 |
| +$1.00 / −$1.00 | 299 | 104 | 195 | 34.8% | +111.02 | -214.91 | **-103.89** | -0.347 | 0.52 | 105.81 | 11 | 1 | +0.069 | -0.102 |
| +$1.00 / −$2.00 | 299 | 170 | 129 | 56.9% | +182.71 | -275.73 | **-93.02** | -0.311 | 0.66 | 97.13 | 4 | 2 | +0.076 | -0.134 |
| +$1.50 / −$2.00 | 299 | 148 | 151 | 49.5% | +233.47 | -322.45 | **-88.98** | -0.298 | 0.72 | 93.53 | 5 | 3 | +0.092 | -0.132 |
| +$2.00 / −$2.00 | 299 | 138 | 161 | 46.2% | +249.30 | -343.18 | **-93.88** | -0.314 | 0.73 | 102.29 | 7 | 22 | +0.081 | -0.129 |

#### Spread and slippage

| envelope | net | net − $0.02/trade exit slippage | net − $0.05/trade | spread at fill as % of the target | trades resolved by target / stop / unresolved |
| --- | ---: | ---: | ---: | ---: | --- |
| +$0.50 / −$1.00 | -108.96 | -114.94 | -123.91 | 70% | 132 / 167 / 0 |
| +$1.00 / −$1.00 | -103.89 | -109.87 | -118.84 | 35% | 103 / 195 / 1 |
| +$1.00 / −$2.00 | -93.02 | -99.00 | -107.97 | 35% | 169 / 128 / 2 |
| +$1.50 / −$2.00 | -88.98 | -94.96 | -103.93 | 23% | 146 / 150 / 3 |
| +$2.00 / −$2.00 | -93.88 | -99.86 | -108.83 | 18% | 117 / 160 / 22 |

The marked path already pays the spread (a long is marked at the bid, a short at the ask), so every envelope result includes the $0.35 average spread at entry. Entry slippage is real (the recorded fill). The two extra columns charge an assumed market-order exit slippage of $0.02 and $0.05 per trade (observed entry slippage: median $+0.000, mean $+0.012). Overshoot = how far past the level the touching tick already was (positive at the target helps, negative at the stop hurts); a real take-profit order would fill at the level or better, a real stop at the level, so both are conservative.

#### Robustness: the two halves (pre-registered rule: an envelope is *supported* only if its net beats the baseline AND its PF > 1.0 in BOTH halves)

| envelope | half A net (PF) | half B net (PF) | overall net (PF) | verdict |
| --- | ---: | ---: | ---: | --- |
| baseline (actual) | -51.96 (0.77) | -99.98 (0.61) | -151.94 (0.68) | |
| +$0.50 / −$1.00 | -45.41 (0.47) | -63.55 (0.36) | -108.96 (0.41) | better than baseline overall but not in both halves |
| +$1.00 / −$1.00 | -43.09 (0.58) | -60.80 (0.46) | -103.89 (0.52) | better than baseline overall but not in both halves |
| +$1.00 / −$2.00 | -35.28 (0.72) | -57.74 (0.61) | -93.02 (0.66) | better than baseline overall but not in both halves |
| +$1.50 / −$2.00 | -41.17 (0.74) | -47.81 (0.71) | -88.98 (0.72) | better than baseline overall but not in both halves |
| +$2.00 / −$2.00 | -43.21 (0.74) | -50.67 (0.71) | -93.88 (0.73) | better than baseline overall but not in both halves |

#### Where the difference comes from (envelope minus actual, per trade)

| envelope | winners capped (actual > envelope) | forfeited $ | losers cut short | saved $ | actual winners turned into envelope losses | cost $ | unresolved (kept real exit) | net change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| +$0.50 / −$1.00 | 70 | -145.48 | 127 | +395.47 | 73 | -215.62 | 0 | +42.98 |
| +$1.00 / −$1.00 | 46 | -104.75 | 127 | +376.30 | 84 | -248.97 | 1 | +48.05 |
| +$1.00 / −$2.00 | 75 | -150.85 | 125 | +306.03 | 32 | -135.32 | 2 | +58.92 |
| +$1.50 / −$2.00 | 57 | -110.25 | 125 | +254.14 | 36 | -154.88 | 3 | +62.96 |
| +$2.00 / −$2.00 | 50 | -80.04 | 125 | +227.16 | 38 | -166.03 | 22 | +58.06 |

#### By session (server hour of the fill)

| session (server hour of the fill) | n | baseline net (PF, win%) | +0.5/−1.0 net (PF, win%) | +1.0/−1.0 net (PF, win%) | +1.0/−2.0 net (PF, win%) | +1.5/−2.0 net (PF, win%) | +2.0/−2.0 net (PF, win%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00-07 | 74 | -57.06 (0.57, 53%) | -35.49 (0.31, 38%) | -29.47 (0.47, 32%) | -27.22 (0.62, 54%) | -24.58 (0.70, 49%) | -30.71 (0.65, 45%) |
| 07-12 | 91 | -97.68 (0.46, 48%) | -34.26 (0.40, 43%) | -43.56 (0.39, 29%) | -58.63 (0.43, 46%) | -69.79 (0.43, 36%) | -67.00 (0.47, 34%) |
| 12-17 | 70 | +6.10 (1.07, 66%) | -16.49 (0.57, 51%) | -9.52 (0.78, 44%) | -10.64 (0.82, 63%) | -13.88 (0.81, 53%) | -10.39 (0.87, 50%) |
| 17-24 | 64 | -3.30 (0.96, 67%) | -22.72 (0.41, 45%) | -21.34 (0.53, 36%) | +3.47 (1.08, 69%) | +19.27 (1.42, 66%) | +14.22 (1.27, 61%) |

#### By direction

| direction | n | baseline net (PF, win%) | +0.5/−1.0 net (PF, win%) | +1.0/−1.0 net (PF, win%) | +1.0/−2.0 net (PF, win%) | +1.5/−2.0 net (PF, win%) | +2.0/−2.0 net (PF, win%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LONG | 170 | -85.24 (0.70, 57%) | -79.80 (0.32, 38%) | -81.52 (0.39, 29%) | -56.85 (0.65, 56%) | -62.10 (0.67, 48%) | -61.16 (0.69, 45%) |
| SHORT | 129 | -66.70 (0.66, 58%) | -29.16 (0.56, 53%) | -22.37 (0.72, 43%) | -36.17 (0.69, 58%) | -26.88 (0.80, 52%) | -32.72 (0.77, 47%) |

#### By ATR regime (M1 ATR at the signal; LOW < 1.647, HIGH ≥ 2.343)

| ATR regime (M1 ATR at the signal; LOW < 1.647, HIGH ≥ 2.343) | n | baseline net (PF, win%) | +0.5/−1.0 net (PF, win%) | +1.0/−1.0 net (PF, win%) | +1.0/−2.0 net (PF, win%) | +1.5/−2.0 net (PF, win%) | +2.0/−2.0 net (PF, win%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LOW | 110 | -36.49 (0.75, 60%) | -34.56 (0.47, 47%) | -30.56 (0.59, 38%) | -12.49 (0.86, 63%) | -13.18 (0.88, 55%) | -19.37 (0.83, 53%) |
| NORMAL | 162 | -126.40 (0.57, 54%) | -64.08 (0.38, 42%) | -62.75 (0.47, 33%) | -57.98 (0.62, 56%) | -58.73 (0.68, 48%) | -63.07 (0.68, 43%) |
| HIGH | 27 | +10.95 (1.28, 70%) | -10.32 (0.39, 44%) | -10.58 (0.47, 33%) | -22.55 (0.34, 41%) | -17.07 (0.50, 41%) | -11.44 (0.67, 41%) |

#### By Bollinger penetration (known for the first 200 trades only)

| Bollinger penetration (known for the first 200 trades only) | n | baseline net (PF, win%) | +0.5/−1.0 net (PF, win%) | +1.0/−1.0 net (PF, win%) | +1.0/−2.0 net (PF, win%) | +1.5/−2.0 net (PF, win%) | +2.0/−2.0 net (PF, win%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| touch | 29 | -22.95 (0.56, 52%) | -4.60 (0.67, 55%) | -0.91 (0.94, 48%) | -6.26 (0.75, 59%) | -15.63 (0.56, 41%) | -10.11 (0.72, 41%) |
| small | 61 | +0.30 (1.00, 67%) | -15.72 (0.54, 51%) | -11.93 (0.70, 43%) | -8.75 (0.82, 62%) | -3.92 (0.93, 56%) | -12.98 (0.79, 51%) |
| medium | 45 | -34.00 (0.56, 56%) | -14.97 (0.45, 44%) | -12.34 (0.59, 38%) | -17.72 (0.60, 56%) | -23.77 (0.57, 44%) | -27.17 (0.52, 42%) |
| deep | 65 | -30.78 (0.71, 57%) | -31.15 (0.30, 38%) | -37.18 (0.31, 25%) | -30.15 (0.55, 52%) | -25.76 (0.65, 48%) | -21.97 (0.71, 45%) |
| n/a | 99 | -64.51 (0.62, 55%) | -42.52 (0.35, 40%) | -41.53 (0.45, 31%) | -30.14 (0.67, 57%) | -19.90 (0.81, 52%) | -21.65 (0.80, 47%) |

For scale: with the current 2 ATR stop the mean risk per trade is $3.79, so +$1.00 is on average 26% of 1R and −$2.00 is 53% of 1R; the live breakeven move happens at 1 ATR = 50% of 1R (about +$1.89 on average).

## 3. Reading the results

### 3.1 How far the trades get (questions 1–3)

* 77% of trades reach +$0.50, 69% +$1.00, 63% +$1.50, 53% +$2.00. Median time to +$1.00: 78 s.
* Of the 207 trades that touched +$1.00, 171 ended positive and 36 negative; 25 ended at a full loss (≤ −$3.50,
  together −$103.82). Every one of the 25 peaked between 25% and 55% of 1R and was stopped at its original stop:
  the live breakeven move needs +50% of 1R, which they never or only briefly reached. This is the "reaches +$1 then
  closes at −$4" pattern, and it is real: 12% of all trades.
* The mirror image matters more: **68 trades (23%) never reached +$0.50**, all stopped out, net −$254.61. The
  other 231 trades net **+$102.67**. The strategy's loss is concentrated in entries that are wrong from the first
  tick, and no profit-taking rule touches them.
* After touching +$1.00 the average trade later dipped to −$0.71 before closing; after +$1.50 it stayed at +$0.04
  or better on average. Small targets are reached often; the question is what they cost on the winners.

### 3.2 What the envelopes do (question 4)

* Every envelope loses less than the live exits (−$89 to −$109 vs −$151.94) and none makes money; none passes
  the pre-registered rule (profit factor 0.36–0.74 in the halves). Charging $0.02 of exit slippage per trade costs
  a further $6; $0.05 costs $15.
* The decomposition table shows the trade-off the question asked about. For +$1.00 / −$2.00: 75 winners are
  capped (−$150.85 forfeited), 125 losers are cut short (+$306.03 saved), and 32 trades that actually won are
  turned into −$2 losses (−$135.32). The saved amount is large only because the loss cap is far inside the live
  stop; the forfeited and flipped amounts together (−$286) eat almost all of it.
* The −$1.00 stop is inside the noise: with a $0.35 spread and a 100-point cap, 73 (+$0.50/−$1) and 84 (+$1/−$1)
  actual winners are stopped out first. Win rates fall to 44% and 35%.
* A wider target does not rescue it either: +$2/−$2 forfeits least (−$80) but flips 38 winners and leaves 22 trades
  unresolved.
* Drawdown and streaks: the envelopes with a −$2 cap reduce max drawdown from $160 to $94–$102 with the same
  longest losing streak (4–7). That is the "more controlled" part of the request, and it is the one thing the data
  supports.

### 3.3 Segments

* **Session.** 07–12 loses under every scenario (PF 0.39–0.47); no exit rule fixes it. 17–24 is the only segment
  where an envelope turns positive (+$1.50/−$2: +$19.27, PF 1.42 on 64 trades; +$1/−$2 and +$2/−$2 also slightly
  positive). It is a small sample, it is a post-hoc cell, and the session was under-sampled by the PC sleep
  outages; treat it as a hypothesis for a pre-registered test, not a result.
* **Direction.** Longs lose more than shorts under every scenario; the envelopes narrow the gap for shorts
  (−$67 → −$22 to −$36) more than for longs (−$85 → −$57 to −$82).
* **ATR regime.** LOW-ATR trades improve most under a −$2 cap (−$36 → −$12), because $2 is close to their 1R.
  HIGH-ATR trades, the only regime that was positive live (+$10.95, 27 trades), turn negative under every envelope:
  a fixed dollar envelope is tightest exactly where the market moves most.
* **Bollinger penetration.** "touch" entries are the only bucket where the tight envelopes help (−$23 → −$1 to −$6);
  "small" entries, flat live, lose under all envelopes; "deep" stays negative everywhere. Known for 200 trades only.

## 4. Limitations

* 299 trades over 8 trading days; both halves are negative for every scenario, so the sign of the conclusion is not
  a sampling accident, but segment cells of 27–74 trades are.
* Envelope exits are simulated at the marked tick, not with resting orders; unresolved trades keep their real exit.
* Fixed dollar envelopes mix lot sizes (271 × 0.01, 28 × 0.02) and ATR levels: +$1 is 13–43% of 1R depending on
  the trade. That is what was asked; an R-based envelope would be a different experiment.
* Bollinger penetration is unknown for the last 99 trades.
* No tick data was fetched for this study; the replayed 7–11 Sep paths come from the audited replay, so any defect
  in that replay would carry over (it passed 155/155 checks).

## 5. Does the data support a second experiment?

**As a profitability experiment: no.** The predefined envelopes leave the strategy losing $0.30–$0.36 per trade
with PF below 0.75 in every split. Running one live would only confirm a smaller loss rate.

**As a loss-profile experiment: only with that stated purpose.** If the goal is explicitly "same entries, lose less
per trade and draw down less while entry research continues", the least bad predefined envelope is
**+$1.50 / −$2.00** (net −$88.98, PF 0.72, both halves within $7 of each other, 3 unresolved trades). Expected
result on the same entry quality: about −$0.30 per trade, max drawdown roughly 40% lower, win rate about 50%.

## 6. Minimum necessary change, if the experiment is wanted (NOT implemented)

On the research branch only, keeping every entry rule, the SL/TP orders, the risk budget and the position count:

1. `config.py`: one new block, off by default:
   `EXIT_ENVELOPE_USD = None` (live behaviour) or `(1.50, 2.00)` (research), plus a comment naming this note.
2. `position_manager.py`: in `manage_positions`, before the breakeven/trail logic, if the envelope is set, read the
   position's marked P&L from the live quote (bid for a long, ask for a short, times the terminal-priced $ per point
   and the volume, the same arithmetic as `path_recorder.unrealized`) and close the position by market order when
   it is at or beyond +profit or −loss. The broker-side SL/TP stay as backstops; the breakeven/trail logic is skipped
   while the envelope is active so the two do not fight.
3. A pure helper (`envelope_exit(long, entry, bid, ask, usd_per_unit_lot, volume, profit, loss) -> "target" |
   "stop" | None`) with unit tests, plus one `manage_positions` test with a fake terminal.
4. Journal the exit as `EXIT reason=ENVELOPE_TARGET|ENVELOPE_STOP` so the forward report can separate it.
5. Run it on a separate demo account or after `scalp-test` has finished its validation window, never on both at once,
   with a pre-registered stop condition (e.g. 150 trades, then compare the realised loss rate with this note's
   −$0.30/trade prediction).

Roughly 40 lines of code plus tests. It changes exits, so it is out of scope until you have reviewed this note.

## 7. What was and was not done

* Created branch `research/small-profit-small-loss` from `scalp-test` (`4b0c3a6`) in its own worktree
  `C:\Develompent\forex_research_spsl`, so the directory the live bot runs from stays on `scalp-test`.
* Added `docs/research/small_profit_small_loss_analysis.py` and this note on the research branch (untracked, not
  committed). Copied the replayed tick paths into the research worktree's gitignored `logs/` folder.
* No file outside `docs/research/` was created or edited on any branch. `main` and `scalp-test` were not modified.
  No commit, no push, no deployment, no bot restart, no terminal attach.
