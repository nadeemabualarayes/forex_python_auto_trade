# XAUUSD Scalping Bot — "Predator" Strategy Blueprint

## Objective

Build a disciplined, adaptive XAUUSD scalping engine that prioritizes:

1. Capital preservation
2. High-quality trade selection
3. Positive expectancy
4. Controlled drawdown
5. Adaptive risk
6. Aggressive participation only when market conditions justify it

**Important:** No strategy can guarantee profit. The goal is to create a statistically validated edge and avoid low-quality trades.

---

# 1. Current Strategy Foundation

The existing bot already contains:

- XAUUSD M5 scalping
- Bollinger Bands
- RSI extremes
- H1 EMA200 trend filter
- ATR-based risk allocation
- Session filtering
- USD high-impact news filtering
- Spread protection
- Breakeven
- ATR trailing stop
- Daily/account loss breakers
- Loss-streak protection
- Backtesting
- Trade journal / telemetry

The current core concept is intraday mean reversion:
**Bollinger Band touch + RSI extreme + price-action confirmation + H1 trend filter.**

---

# 2. New Trading Philosophy

The bot must NOT think:

> "RSI is oversold, therefore BUY."

It must think:

> "Is this a statistically favorable environment for a long mean-reversion trade?"

Every trade should pass multiple independent filters.

Pipeline:

```text
Market Data
    ↓
Market Regime
    ↓
H1 Trend
    ↓
M5 Volatility
    ↓
Session
    ↓
News Risk
    ↓
Spread
    ↓
Liquidity / Market Conditions
    ↓
Setup Location
    ↓
Momentum Extreme
    ↓
Price Action Confirmation
    ↓
Risk / Reward
    ↓
Confidence Score
    ↓
BUY / SELL / NO TRADE
```

---

# 3. Market Regime Detection

Classify the market before looking for entries.

Possible regimes:

- TREND_UP
- TREND_DOWN
- RANGE
- HIGH_VOLATILITY
- LOW_VOLATILITY
- CHAOTIC / UNSAFE

### Trend

Use H1 EMA200 as a baseline.

Potential additional information:

- EMA200 slope
- Distance from EMA200
- H1 higher highs / higher lows
- H1 lower highs / lower lows

### Important rule

Do not use EMA200 as a blind entry signal.

It is a **regime filter**.

---

# 4. Mean-Reversion LONG Setup

A long setup becomes eligible when:

### Higher timeframe

- H1 market regime is bullish or range-compatible
- Price is not in an extreme uncontrolled selloff

### M5 location

- Price reaches or penetrates the lower Bollinger Band
- Prefer larger deviation from the Bollinger middle line

### Momentum

- RSI reaches an oversold/extreme area
- RSI alone is never sufficient

### Price Action

Require evidence of rejection, for example:

- bullish pin/rejection candle
- bullish engulfing
- strong close away from the low
- reclaim of a local level

### Entry

Enter only after the confirmation candle closes.

---

# 5. Mean-Reversion SHORT Setup

Reverse the long logic:

### Higher timeframe

- H1 market regime bearish or range-compatible
- Avoid uncontrolled upside expansion

### M5 location

- Price reaches or penetrates the upper Bollinger Band

### Momentum

- RSI reaches an overbought/extreme area

### Price Action

Require bearish rejection, such as:

- bearish pin/rejection candle
- bearish engulfing
- strong close away from the high
- rejection of a local level

### Entry

Enter only after the confirmation candle closes.

---

# 6. NO-TRADE Rules

The strongest feature of the bot should be its ability to refuse trades.

Do NOT trade when:

- Spread is abnormal
- High-impact USD news is imminent
- Market is classified as chaotic
- Volatility is outside tested limits
- H1 trend conflicts strongly with the setup
- Price is moving strongly without rejection
- Stop distance is abnormal
- Expected reward is insufficient
- Daily loss limit is reached
- Loss-streak protection is active
- Trading session is outside the validated window

---

# 7. Confidence Score

Create a weighted score from 0–100.

Example:

| Component | Weight |
|---|---:|
| H1 regime | 20 |
| Bollinger location | 15 |
| RSI extreme | 10 |
| Price-action confirmation | 20 |
| Volatility quality | 10 |
| Session quality | 10 |
| Spread quality | 5 |
| News safety | 5 |
| Risk/reward | 5 |

Suggested policy:

- 85–100 = A+ setup
- 75–84 = A setup
- 65–74 = Research only / optional
- <65 = NO TRADE

These thresholds must be validated through backtesting rather than assumed profitable.

---

# 8. ATR Risk Engine

ATR should influence:

- Stop distance
- Position sizing
- Trailing distance
- Volatility classification

Do NOT simply increase lot size because the market is moving more.

Higher volatility can require **smaller position size**.

Risk should be calculated from account equity and stop distance.

---

# 9. Dynamic Risk Modes

## NORMAL

Conditions healthy.

Use normal tested risk.

## DEFENSIVE

Triggered by:

- consecutive losses
- elevated volatility
- abnormal spread
- declining daily P&L

Reduce risk and/or require a higher confidence score.

## KILL

Triggered by:

- daily drawdown limit
- abnormal execution conditions
- severe market conditions
- repeated losses beyond validated threshold

Stop opening new positions.

---

# 10. Trade Management

The bot should distinguish between:

### Initial Stop

Placed immediately with the trade.

### Breakeven

Move stop only after statistically validated favorable movement.

Avoid moving to breakeven too early.

### Trailing

ATR-based trailing can be used when the trade develops.

Trailing must not destroy the expected payoff distribution.

### Exit

Possible exits:

1. Fixed R target
2. Bollinger middle-band reversion
3. Opposite signal
4. Time-based exit
5. Volatility deterioration

All exit methods must be compared using backtests.

---

# 11. Gold-Specific Research

Test XAUUSD separately by:

- London session
- London/NY overlap
- New York session
- Asian session

Also segment results by:

- Low volatility
- Normal volatility
- High volatility
- News day
- Non-news day
- Trend regime
- Range regime

The objective is to discover:

> WHERE and WHEN the strategy actually has an edge.

---

# 12. Backtesting Protocol

Never optimize using one backtest only.

Minimum research process:

### Phase 1 — Baseline

Run the current strategy.

Record:

- Number of trades
- Win rate
- Average win
- Average loss
- Profit factor
- Expectancy
- Max drawdown
- Sharpe-like risk-adjusted metrics if available
- Consecutive losses
- Long vs short performance
- Session performance

### Phase 2 — Add one filter

Change ONE major variable/filter at a time.

### Phase 3 — Compare

Keep the change only if it improves the out-of-sample results.

### Phase 4 — Walk-forward

Separate:

- Training period
- Validation period
- Out-of-sample period

Avoid overfitting.

---

# 13. What NOT To Do

Never:

- Martingale after losses
- Double lot size to recover
- Remove stops
- Move stops farther because a trade is losing
- Trade every signal
- Optimize exclusively for win rate
- Optimize exclusively for total profit
- Use future candles in signal calculations
- Change many parameters simultaneously
- Trust a strategy because of one profitable backtest

---

# 14. The Real KPI

The bot should optimize for **expectancy**, not win rate.

Basic expectancy:

```text
Expectancy =
(Win Rate × Average Win)
-
(Loss Rate × Average Loss)
```

Example:

```text
Win rate = 45%
Average win = +2R
Average loss = -1R

Expectancy =
0.45 × 2 - 0.55 × 1
= +0.35R per trade
```

A strategy can therefore be profitable without winning most trades.

---

# 15. Research Questions

Before declaring the bot "smart", answer:

1. Which session has the highest expectancy?
2. Is LONG better than SHORT?
3. Which RSI extreme works best?
4. How far beyond the Bollinger Band should price move?
5. Which candle confirmation performs best?
6. What ATR regime is best?
7. What spread threshold is safe?
8. How close to news should trading stop?
9. Does EMA200 improve results?
10. Does breakeven improve or hurt expectancy?
11. Does ATR trailing improve or hurt expectancy?
12. What is the maximum safe consecutive-loss threshold?
13. What daily drawdown limit protects the account without killing the edge?
14. Which combinations produce the highest-quality trades?

---

# 16. Implementation Architecture

Keep the strategy modular.

Suggested components:

```text
market_regime.py
trend_filter.py
volatility_filter.py
session_filter.py
news_filter.py
spread_filter.py
setup_detector.py
price_action.py
confidence.py
risk_engine.py
trade_manager.py
```

The core strategy should remain testable without MT5.

---

# 17. Golden Rule

The bot is not paid for trading.

It is paid for finding **good opportunities**.

Therefore:

```text
GOOD SETUP → TRADE
WEAK SETUP → WAIT
BAD MARKET → STOP
```

The best scalper may spend long periods doing absolutely nothing.

That is not failure.

That is discipline.

---

# 18. Final Mission

Build the XAUUSD engine so that it behaves like a disciplined professional systematic trader:

- Aggressive only when conditions are excellent
- Conservative when conditions deteriorate
- Never revenge trades
- Never martingales
- Never removes risk controls
- Learns from historical statistics
- Uses multiple confirmations
- Protects capital first
- Searches for positive expectancy
- Continuously validates every major change through backtesting

## Target

Not:

> "Maximum number of trades."

Not:

> "Maximum win rate."

Instead:

> **Maximum sustainable risk-adjusted expectancy with controlled drawdown.**

---

# Next Engineering Step

Inspect and improve these files first:

1. `strategy.py`
2. `technicals.py`
3. `config.py`
4. `backtest.py`
5. `position_manager.py`
6. `execution.py`
7. `risk.py`

Then run a baseline XAUUSD backtest before changing parameters.

Only after the baseline is recorded should optimization begin.
