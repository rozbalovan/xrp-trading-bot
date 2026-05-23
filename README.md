# 🔁 XRP Trading Bot

> Real-time XRP/USDT trading bot with Telegram controls.

Strategy: 5m L12 breakout with TP/SL management. Manual and auto modes.

## ⚡ Features

- **Auto trading** — configurable breakout strategy
- **Manual controls** — buy/sell/close via Telegram buttons
- **Position sizing** — risk-based
- **Real-time P&L** — open position tracking
- **Journal** — trade log

## 🚀 Quick Start

```bash
git clone https://github.com/rozbalovan/xrp-trading-bot.git
cd xrp-trading-bot
pip install ccxt requests
cp .env.example .env
# Edit .env with your keys
python trading_bot.py
```

## 📱 Telegram Commands

| Button | Action |
|--------|--------|
| 📊 Status | Current price, balance, position |
| 🟢 Buy LONG | Open long position |
| 🔴 Close | Close current position |
| 📋 Journal | Trade history |
| ⚙️ Config | Settings |
| 🔄 Refresh | Update data |

## ⚙️ Strategy

- **Timeframe:** 5m
- **Confirmation:** L12 breakout
- **TP:** +2%
- **SL:** -5%
- **Position sizing:** Risk-based allocation

---

*Built by [@rozbalovan](https://github.com/rozbalovan)*
