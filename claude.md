# CLAUDE.md

## Project Overview
Automated algorithmic trading bot bridging Python with MetaTrader 5 (MT5). The engine executes intraday scalping strategies across multiple asset classes (Gold `XAUUSD`, Silver `XAGUSD`, Forex pairs) using dynamic ATR risk allocation, daily circuit breakers, spread protection, and real-time Telegram telemetry.

## System Architecture & Flow
```text
┌─────────────────┐       Tick & Rates       ┌─────────────────┐
│                 ├─────────────────────────►│  technicals.py   │
│   MT5 Terminal  │                          │  (ATR/BB/RSI)   │
│                 │◄─────────────────────────┼────────┬────────┘
└────────┬────────┘      Deals & Orders      └────────┼────────┘
         │                                            │ Signal
         ▼                                            ▼
┌─────────────────┐   Trade/Kill Notifications ┌─────────────────┐
│   main.py       ├───────────────────────────►│ telegram_      │
│   (Event Loop)  │                            │ notifier.py     │
└─────────────────┘                            └─────────────────┘