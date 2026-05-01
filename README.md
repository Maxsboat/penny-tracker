# 💰 Penny Stock Tracker

An EDGAR-driven penny stock research tool for OTC/Pink Sheet investors. Built around the bankruptcy/litigation arbitrage strategy — finding companies where the market has priced in total loss but the underlying asset value remains intact.

## The Strategy This App Encodes

1. **Find** companies in Chapter 11 or active litigation via EDGAR filing scanner
2. **Read** the 10-K for core business health and management quality
3. **Assess** whether the liability (lawsuit, asbestos, patent defense) is the *only* problem
4. **Buy** at pennies when the market treats it as worthless
5. **Wait** for reorganization plan approval or settlement
6. **Exit** when the market reprices

## Features

- **🔍 Scanner** — EDGAR full-text search for bankruptcy, patent, asbestos, class action, settlement filings
- **📋 Watchlist** — Track OTC tickers with price, volume spikes, RSI, momentum signals
- **📄 SEC Filings** — Pull 8-K and 10-K filings per ticker with litigation classification
- **⚖️ Litigation Watch** — Targeted search for litigation catalysts (wins, settlements, plan approvals)
- **📰 News** — RSS filtered for watchlist tickers and OTC market events

## Stack

- [Streamlit](https://streamlit.io)
- [SEC EDGAR API](https://efts.sec.gov) — free, no API key required
- [yfinance](https://github.com/ranaroussi/yfinance) — OTC price/volume data
- [feedparser](https://feedparser.readthedocs.io) — RSS news
- [Plotly](https://plotly.com) — candlestick charts

## Local Setup

```bash
git clone https://github.com/Maxsboat/penny-tracker.git
cd penny-tracker
pip install -r requirements.txt
mkdir .streamlit
cat > .streamlit/secrets.toml << 'EOF'
APP_PASSWORD = "penny2024"
EOF
python3.11 -m streamlit run app.py
```

## Streamlit Cloud Deploy

1. Push to GitHub (public repo)
2. Connect at [share.streamlit.io](https://share.streamlit.io)
3. Entry point: `app.py`
4. Add secret: `APP_PASSWORD = "penny2024"`
5. Deploy → set custom subdomain `penny-tracker`

## Volume Spike Flag

A 🔥 flag appears when today's volume is 2x or more the 20-day average — often the first signal that institutional or informed money is moving into a depressed stock.

## Signal Logic

| Signal | Condition |
|--------|-----------|
| 🟢 Momentum up | 5-day MA > 20-day MA |
| 🔴 Momentum down | 5-day MA < 20-day MA |
| 🔵 Oversold | RSI < 35 — watch for reversal |
| 🟡 Overbought | RSI > 65 |

## Notes

- OTC tickers may have thin data on yfinance — if price shows "—" the ticker may use a different format
- EDGAR search returns companies, not always tickers — use [OTC Markets](https://www.otcmarkets.com) to look up the ticker from the company name
- Some OTC tickers require ".PK" suffix on yfinance

## ⚠️ Disclaimer

OTC and penny stocks carry substantial risk including total loss of investment. This tool is for research only and is not investment advice.
