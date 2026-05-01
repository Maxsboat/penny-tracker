import streamlit as st
import yfinance as yf
import feedparser
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import re
from datetime import datetime, timedelta
import json
import re

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Penny Stock Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { max-width: 1200px; margin: 0 auto; }
    .stock-card {
        background: #1e2130;
        border-radius: 8px;
        padding: 14px 16px;
        margin: 6px 0;
        border-left: 4px solid #ffd600;
    }
    .signal-buy  { color: #00c853; font-weight: 700; }
    .signal-wait { color: #ff5252; font-weight: 700; }
    .signal-bk   { color: #ff9800; font-weight: 700; }
    .filing-card {
        background: #1e2130;
        border-left: 3px solid #4a9eff;
        border-radius: 0 6px 6px 0;
        padding: 10px 14px;
        margin: 6px 0;
    }
    .filing-bk   { border-left-color: #ff9800 !important; }
    .filing-lit  { border-left-color: #ff5252 !important; }
    .filing-settle { border-left-color: #00c853 !important; }
    .scanner-card {
        background: #1a2a1a;
        border-left: 4px solid #00c853;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 6px 0;
    }
    .tag {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75em;
        font-weight: 700;
        margin-right: 4px;
    }
    .tag-bk      { background: #3d2800; color: #ff9800; }
    .tag-lit     { background: #2d0000; color: #ff5252; }
    .tag-settle  { background: #002d00; color: #00c853; }
    .tag-volume  { background: #001a3d; color: #4a9eff; }
    .tag-short   { background: #2d002d; color: #e040fb; }
    h1 { font-size: 1.8em !important; }
    .stTabs [data-baseweb="tab"] { font-size: 0.95em; padding: 8px 16px; }
</style>
""", unsafe_allow_html=True)

# ─── Password Protection ───────────────────────────────────────────────────────
def check_password():
    if st.session_state.get("authenticated"):
        return True
    st.markdown("# 💰 Penny Stock Tracker")
    pwd = st.text_input("Password", type="password", key="pw_input")
    if st.button("Enter", key="pw_btn"):
        correct = st.secrets.get("APP_PASSWORD", "penny2024")
        if pwd == correct:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False

if not check_password():
    st.stop()

# ─── Session State for Watchlist ──────────────────────────────────────────────
if "watchlist" not in st.session_state:
    st.session_state.watchlist = [
        "CENN", "SNDL", "NAKD", "MULN", "BBIG"
    ]
if "notes" not in st.session_state:
    st.session_state.notes = {}
if "manual_flags" not in st.session_state:
    st.session_state.manual_flags = {}

# ─── EDGAR API Functions ──────────────────────────────────────────────────────
EDGAR_HEADERS = {"User-Agent": "PennyTracker research@pennytacker.com"}

@st.cache_data(ttl=3600)
def get_ticker_from_cik(cik):
    """Look up ticker symbol from SEC CIK number"""
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=EDGAR_HEADERS, timeout=10
        )
        data = r.json()
        cik_int = int(cik)
        for key, val in data.items():
            if val.get("cik_str") == cik_int:
                return val.get("ticker", ""), val.get("title", "")
        return "", ""
    except Exception:
        return "", ""
    try:
        url = "https://efts.sec.gov/LATEST/search-index?q=%22{}%22&dateRange=custom&startdt=2020-01-01&forms=10-K".format(ticker)
        r = requests.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK={ticker}&type=10-K&dateb=&owner=include&count=1&search_text=&action=getcompany&output=atom",
            headers=EDGAR_HEADERS, timeout=10
        )
        cik_match = re.search(r'CIK=(\d+)', r.text)
        if cik_match:
            return cik_match.group(1).zfill(10)
        return None
    except Exception:
        return None

@st.cache_data(ttl=3600)
def get_red_flags(ticker):
    """Check EDGAR and OTC Markets for red flags"""
    flags = []
    try:
        # Check for recent 10-K on EDGAR
        r2 = requests.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK={ticker}&type=10-K&dateb=&owner=include&count=5&search_text=&action=getcompany&output=atom",
            headers=EDGAR_HEADERS, timeout=10
        )
        if "No matching" in r2.text or r2.text.count("<entry>") == 0:
            flags.append("⚠️ No 10-K filed")

        # Check for bankruptcy in recent 8-Ks
        r3 = requests.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK={ticker}&type=8-K&dateb=&owner=include&count=10&search_text=&action=getcompany&output=atom",
            headers=EDGAR_HEADERS, timeout=10
        )
        if "chapter 11" in r3.text.lower() or "bankruptcy" in r3.text.lower():
            flags.append("🔴 Bankruptcy in filings")

    except Exception:
        pass

    # Check OTC Markets for hidden officers
    try:
        r4 = requests.get(
            f"https://www.otcmarkets.com/filing/json/issuer/{ticker}/officers",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        if r4.status_code == 200:
            data = r4.json()
            officers = data.get("officers", [])
            if not officers:
                flags.append("🚨 No officers on OTC Markets")
    except Exception:
        pass

    # Check OTC Markets company profile for shell indicators
    try:
        r5 = requests.get(
            f"https://www.otcmarkets.com/filing/json/issuer/{ticker}/profile",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        if r5.status_code == 200:
            profile = r5.json()
            # Check for multiple name changes
            former_names = profile.get("formerNames", [])
            if len(former_names) >= 2:
                flags.append(f"⚠️ {len(former_names)} prior name changes")
            # Check state of incorporation
            state = profile.get("stateOfIncorporation", "")
            if state in ["NV", "WY"]:
                flags.append(f"⚠️ Incorporated in {state} (shell-friendly state)")
            # Check SIC mismatch indicators
            sic = str(profile.get("sicCode", ""))
            company_desc = profile.get("businessDescription", "") or ""
            if sic == "3944":
                flags.append("⚠️ SIC 3944 — Games/Toys (common shell mismatch)")
    except Exception:
        pass

    return flags

@st.cache_data(ttl=3600)
def get_management_names(ticker):
    """Pull officer names from EDGAR company facts"""
    try:
        # Search EDGAR for DEF 14A (proxy statement) which lists all officers
        r = requests.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=DEF+14A&dateb=&owner=include&count=5&output=atom",
            headers=EDGAR_HEADERS, timeout=10
        )
        if r.text.count("<entry>") > 0:
            return "✅ Proxy filed — officers disclosed"
        # Check 10-K
        r2 = requests.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=10-K&dateb=&owner=include&count=3&output=atom",
            headers=EDGAR_HEADERS, timeout=10
        )
        if r2.text.count("<entry>") > 0:
            return "✅ 10-K filed — check Item 10 for officers"
        return "🚨 No proxy or 10-K — management HIDDEN"
    except Exception:
        return "⬜ Could not verify"

@st.cache_data(ttl=3600)
def get_recent_filings(ticker, form_types=None):
    if form_types is None:
        form_types = ["8-K", "10-K"]
    try:
        r = requests.get(
            f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms={','.join(form_types)}&dateRange=custom&startdt=2023-01-01",
            headers=EDGAR_HEADERS, timeout=10
        )
        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        filings = []
        for hit in hits[:15]:
            src = hit.get("_source", {})
            if not src.get("entity_name"):
                names = src.get("display_names", [])
                if names:
                    src["entity_name"] = names[0].get("name", ticker) if isinstance(names[0], dict) else names[0]
            filings.append({
                "ticker":    ticker,
                "form":      src.get("form_type", ""),
                "date":      src.get("file_date", ""),
                "company":   src.get("entity_name", ticker),
                "title":     str(src.get("display_names", [""])[0]) if src.get("display_names") else "",
                "url":       f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type={src.get('form_type','8-K')}&dateb=&owner=include&count=10",
                "accession": str(src.get("file_num", "")),
            })
        return filings
    except Exception:
        return []

@st.cache_data(ttl=3600)
def search_edgar_by_keyword(keyword, form_type="8-K", start_date="2024-01-01"):
    try:
        r = requests.get(
            f"https://efts.sec.gov/LATEST/search-index?q=%22{keyword}%22&forms={form_type}&dateRange=custom&startdt={start_date}",
            headers=EDGAR_HEADERS, timeout=10
        )
        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        results = []
        for hit in hits[:20]:
            src = hit.get("_source", {})
            results.append({
                "company":  src.get("entity_name", ""),
                "form":     src.get("form_type", ""),
                "date":     src.get("file_date", ""),
                "excerpt":  src.get("period_of_report", ""),
                "url":      f"https://efts.sec.gov/LATEST/search-index?q=%22{keyword}%22&forms={form_type}",
            })
        return results
    except Exception:
        return []

@st.cache_data(ttl=3600)
def search_edgar_full(query, form_type="8-K", start_date="2024-01-01"):
    """Use EDGAR full-text search"""
    try:
        encoded = requests.utils.quote(query)
        url = f"https://efts.sec.gov/LATEST/search-index?q=%22{encoded}%22&forms={form_type}&dateRange=custom&startdt={start_date}"
        r = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        for hit in hits:
            src = hit.get("_source", {})
            if not src.get("entity_name"):
                names = src.get("display_names", [])
                if names:
                    src["entity_name"] = names[0].get("name", "Unknown") if isinstance(names[0], dict) else names[0]
            if not src.get("file_date"):
                src["file_date"] = src.get("period_of_report", "")
            hit["_source"] = src
        return hits
    except Exception:
        return []

# ─── Market Data Functions ────────────────────────────────────────────────────
@st.cache_data(ttl=900)
def get_stock_data(ticker):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="3mo")
        info = t.fast_info
        if hist.empty:
            return None
        close = hist["Close"].iloc[-1]
        prev  = hist["Close"].iloc[-2] if len(hist) > 1 else close
        vol   = hist["Volume"].iloc[-1]
        avg_vol = hist["Volume"].rolling(20).mean().iloc[-1]
        vol_spike = (vol / avg_vol) if avg_vol > 0 else 1.0
        pct = ((close - prev) / prev) * 100 if prev > 0 else 0
        return {
            "price":     round(close, 4),
            "change":    round(pct, 2),
            "volume":    int(vol),
            "avg_vol":   int(avg_vol) if avg_vol else 0,
            "vol_spike": round(vol_spike, 2),
            "hist":      hist,
        }
    except Exception:
        return None

def calculate_rsi(prices, period=14):
    delta    = prices.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs  = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_signal(hist):
    if hist is None or len(hist) < 21:
        return "⬜ Insufficient data", None
    closes = hist["Close"]
    ma5  = closes.rolling(5).mean().iloc[-1]
    ma20 = closes.rolling(20).mean().iloc[-1]
    rsi  = calculate_rsi(closes).iloc[-1]
    if rsi < 35:
        return "🔵 Oversold — watch entry", round(rsi, 1)
    elif rsi > 65:
        return "🟡 Overbought", round(rsi, 1)
    elif ma5 > ma20:
        return "🟢 Momentum up", round(rsi, 1)
    else:
        return "🔴 Momentum down", round(rsi, 1)

# ─── Litigation keyword classifier ───────────────────────────────────────────
BANKRUPTCY_KW  = ["chapter 11", "bankruptcy", "reorganization plan", "debtor in possession", "automatic stay"]
LITIGATION_KW  = ["patent infringement", "class action", "asbestos", "lawsuit", "complaint filed", "litigation"]
SETTLEMENT_KW  = ["settlement", "resolved", "dismissed", "verdict", "judgment entered"]

def classify_filing(text):
    text = text.lower()
    tags = []
    if any(k in text for k in BANKRUPTCY_KW):  tags.append("BANKRUPTCY")
    if any(k in text for k in LITIGATION_KW):  tags.append("LITIGATION")
    if any(k in text for k in SETTLEMENT_KW):  tags.append("SETTLEMENT")
    return tags

# ─── News feeds ───────────────────────────────────────────────────────────────
NEWS_FEEDS = [
    {"name": "Reuters Business",  "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "AP Business",       "url": "https://feeds.apnews.com/rss/apf-business"},
    {"name": "PR Newswire",       "url": "https://www.prnewswire.com/rss/news-releases-list.rss"},
    {"name": "Business Wire",     "url": "https://feed.businesswire.com/rss/home/?rss=G1"},
]

@st.cache_data(ttl=1800)
def fetch_news_for_watchlist(watchlist):
    articles = []
    keywords = [t.lower() for t in watchlist]
    for feed in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries[:30]:
                title   = getattr(entry, "title", "")
                summary = getattr(entry, "summary", "")
                link    = getattr(entry, "link", "#")
                pub     = getattr(entry, "published", "")
                text    = (title + " " + summary).lower()
                matched = [k for k in keywords if k in text]
                if matched or any(w in text for w in ["bankruptcy", "settlement", "patent", "reorganization", "otc", "pink sheet"]):
                    articles.append({
                        "source":  feed["name"],
                        "title":   title,
                        "summary": summary[:250] + "..." if len(summary) > 250 else summary,
                        "link":    link,
                        "pub":     pub,
                        "matched": matched,
                    })
        except Exception:
            continue
    return articles

# ─── Header ───────────────────────────────────────────────────────────────────
st.markdown("# 💰 Penny Stock Tracker")
col_ts, col_ref = st.columns([3, 1])
with col_ts:
    st.caption(f"Last loaded: {datetime.now().strftime('%B %d, %Y  %I:%M %p ET')} · Data delayed ~15 min · Not investment advice")
with col_ref:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔍 Scanner", "📋 Watchlist", "📄 SEC Filings", "⚖️ Litigation Watch", "📰 News"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SCANNER
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### 🔍 EDGAR-Driven Opportunity Scanner")
    st.caption(
        "Searches SEC EDGAR filings for bankruptcy, litigation, and settlement keywords — "
        "finding the story before the price moves. Add promising tickers to your watchlist."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        scan_type = st.selectbox("Scan type", [
            "Bankruptcy filings (Chapter 11)",
            "Patent litigation",
            "Asbestos litigation",
            "Class action filings",
            "Settlement announcements",
            "Reorganization plan filed",
        ])
    with col2:
        scan_form = st.selectbox("Filing type", [
            "8-K — Material events (bankruptcy, settlement, CEO change)",
            "10-K — Annual report (business description, management bios)",
            "10-Q — Quarterly report (cash burn, financial trend)",
        ])
        scan_form_code = scan_form.split(" ")[0]  # Extract just 8-K, 10-K, or 10-Q
    with col3:
        this_year = datetime.now().year
        scan_start = st.selectbox("Since", [
            f"{this_year}-01-01",
            f"{this_year-1}-06-01",
            f"{this_year-1}-01-01",
            f"{this_year-2}-01-01",
        ])

    SCAN_QUERIES = {
        "Bankruptcy filings (Chapter 11)":  "chapter 11 bankruptcy",
        "Patent litigation":                "patent infringement complaint",
        "Asbestos litigation":              "asbestos liability",
        "Class action filings":             "class action complaint",
        "Settlement announcements":         "settlement agreement resolved",
        "Reorganization plan filed":        "plan of reorganization",
    }

    if st.button("🔍 Run Scan", type="primary", use_container_width=True):
        query = SCAN_QUERIES[scan_type]
        with st.spinner(f"Scanning EDGAR for '{query}'..."):
            hits = search_edgar_full(query, form_type=scan_form_code, start_date=scan_start)

        if hits:
            st.success(f"Found {len(hits)} filings matching '{scan_type}'")
            for hit in hits:
                src = hit.get("_source", {})
                company = src.get("entity_name", "Unknown")
                date    = src.get("file_date", "")
                form    = src.get("form_type", scan_form_code)
                period  = src.get("period_of_report", "")

                # Look up ticker from CIK
                cik = src.get("entity_id", "")
                ticker_display = ""
                price_display  = ""

                # First try parenthetical ticker in name
                ticker_match = re.search(r'\(([A-Z]{1,5})\)', company)
                if ticker_match:
                    possible_ticker = ticker_match.group(1)
                elif cik:
                    possible_ticker, _ = get_ticker_from_cik(str(int(cik)))
                else:
                    possible_ticker = ""

                if possible_ticker:
                    price_data = get_stock_data(possible_ticker)
                    if price_data:
                        color = "#00c853" if price_data["change"] >= 0 else "#ff5252"
                        arrow = "▲" if price_data["change"] >= 0 else "▼"
                        ticker_display = f"<span style='background:#2a2a00;color:#ffd600;padding:2px 8px;border-radius:4px;font-weight:700'>{possible_ticker}</span>"
                        price_display  = f"<span style='color:{color};font-weight:700;margin-left:8px'>${price_data['price']:.4f} {arrow}{abs(price_data['change']):.2f}%</span>"
                    else:
                        ticker_display = f"<span style='background:#2a2a00;color:#ffd600;padding:2px 8px;border-radius:4px;font-weight:700'>{possible_ticker}</span>"
                        price_display  = "<span style='color:#888;margin-left:8px'>No price data — may be delisted</span>"

                tags = classify_filing(scan_type.lower())
                tag_html = ""
                for tag in tags:
                    css = {"BANKRUPTCY": "tag-bk", "LITIGATION": "tag-lit", "SETTLEMENT": "tag-settle"}.get(tag, "tag-volume")
                    tag_html += f"<span class='tag {css}'>{tag}</span>"

                st.markdown(f"""
<div class='scanner-card'>
  <div style='display:flex;justify-content:space-between;align-items:flex-start'>
    <div>
      <span style='font-size:1.1em;font-weight:700;color:#fff'>{company.split("(CIK")[0].strip()}</span>
      <a href='https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=10' target='_blank' style='color:#666;font-size:0.8em;margin-left:8px'>CIK {cik} →</a>
      <span style='color:#888;font-size:0.8em;margin-left:10px'>{form} · {date}</span>
    </div>
    <div>{tag_html}</div>
  </div>
  <div style='margin-top:4px'>{ticker_display}{price_display}</div>
  <div style='font-size:0.82em;color:#aaa;margin-top:4px'>Period: {period}</div>
  <div style='font-size:0.82em;margin-top:6px;display:flex;gap:16px'>
    <a href='https://www.otcmarkets.com/search#/{company.split("(CIK")[0].strip().split()[0]}' target='_blank' style='color:#ffd600;text-decoration:none'>🔍 OTC Markets Search →</a>
    <a href='https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=10' target='_blank' style='color:#4a9eff;text-decoration:none'>📄 EDGAR Filings →</a>
  </div>
</div>
""", unsafe_allow_html=True)
</div>
""", unsafe_allow_html=True)
        else:
            st.info("No results found. Try broadening the date range or changing the scan type.")

    st.divider()
    st.markdown("**💡 How to use the scanner:**")
    st.markdown(
        "Run a bankruptcy scan → find companies in Chapter 11 → look up their ticker on "
        "[OTC Markets](https://www.otcmarkets.com) → read the 10-K for underlying asset value → "
        "add to watchlist if the core business is sound. That's the pattern that worked on TPMS and Dow."
    )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — WATCHLIST
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 📋 Watchlist")

    # Add/remove tickers
    col_add, col_remove = st.columns([2, 1])
    with col_add:
        new_ticker = st.text_input("Add ticker", placeholder="e.g. CENN, SNDL", key="add_input").upper().strip()
        if st.button("➕ Add to Watchlist") and new_ticker:
            tickers = [t.strip() for t in new_ticker.split(",")]
            for t in tickers:
                if t and t not in st.session_state.watchlist:
                    # Price check before adding
                    data = get_stock_data(t)
                    if data and data["price"] > 5.0:
                        st.warning(f"⚠️ {t} is trading at ${data['price']:.2f} — over the $5 penny stock threshold. Add anyway?")
                        if st.button(f"Add {t} anyway", key=f"force_add_{t}"):
                            st.session_state.watchlist.append(t)
                            st.rerun()
                    else:
                        st.session_state.watchlist.append(t)
            st.rerun()
    with col_remove:
        if st.session_state.watchlist:
            to_remove = st.selectbox("Remove ticker", ["—"] + st.session_state.watchlist)
            if st.button("➖ Remove") and to_remove != "—":
                st.session_state.watchlist.remove(to_remove)
                st.rerun()

    # Price filter toggle
    price_filter = st.toggle("💲 Show only stocks under $5", value=True)
    if price_filter:
        st.caption("Hiding tickers trading over $5. Toggle off to see all watchlist entries.")

    # OTC Screener — stocks under $5
    st.divider()
    st.markdown("#### 📋 OTC Stocks Under $5 — Live Screener")
    st.caption("Pulls current OTC/Pink Sheet stocks trading under $5. Click any ticker to add to your watchlist.")

    screen_col1, screen_col2, screen_col3 = st.columns(3)
    with screen_col1:
        max_price = st.slider("Max price ($)", 0.01, 5.00, 1.00, step=0.25)
    with screen_col2:
        min_volume = st.selectbox("Min daily volume", ["Any", "10,000+", "50,000+", "100,000+", "500,000+"])
    with screen_col3:
        screen_btn = st.button("🔍 Screen Now", use_container_width=True, type="primary")

    VOL_MAP = {"Any": 0, "10,000+": 10000, "50,000+": 50000, "100,000+": 100000, "500,000+": 500000}

    if screen_btn:
        min_vol_val = VOL_MAP[min_volume]
        with st.spinner("Scanning OTC markets..."):
            try:
                # Use OTC Markets API for screener
                url = (
                    f"https://www.otcmarkets.com/research/stock-screener/api?"
                    f"market=Pink,Expert,Venture&"
                    f"maxPrice={max_price}&"
                    f"minVolume={min_vol_val}&"
                    f"sortBy=dollarVolume&sortOrder=desc&"
                    f"pageSize=50&pageNum=1"
                )
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    stocks = data.get("stocks", []) or data.get("data", []) or []
                    if stocks:
                        st.success(f"Found {len(stocks)} stocks under ${max_price:.2f}")
                        screen_rows = []
                        for s in stocks[:50]:
                            ticker  = s.get("symbol", s.get("ticker", ""))
                            name    = s.get("companyName", s.get("name", ""))
                            price   = s.get("lastSale", s.get("price", 0))
                            chg     = s.get("percentChange", s.get("change", 0))
                            vol     = s.get("volume", s.get("totalVolume", 0))
                            market  = s.get("market", s.get("marketName", ""))
                            if ticker:
                                screen_rows.append({
                                    "Ticker":  ticker,
                                    "Company": name,
                                    "Price":   f"${price:.4f}" if price else "—",
                                    "Day %":   f"{chg:+.2f}%" if chg else "—",
                                    "Volume":  f"{int(vol):,}" if vol else "—",
                                    "Market":  market,
                                    "Add":     f"➕ {ticker}",
                                })

                        if screen_rows:
                            screen_df = pd.DataFrame(screen_rows)
                            st.dataframe(screen_df, use_container_width=True, hide_index=True)
                            st.caption("Copy any ticker above and paste it into the **Add ticker** box at the top to add it to your watchlist.")
                        else:
                            st.info("No stocks returned. Try adjusting the filters.")
                    else:
                        raise ValueError("Empty response")
                else:
                    raise ValueError(f"Status {r.status_code}")

            except Exception:
                # Fallback — direct OTC Markets link with filters pre-set
                st.info("Live screener unavailable — OTC Markets restricts direct API access. Use the link below to screen on their site:")
                vol_param = min_vol_val if min_vol_val > 0 else ""
                st.markdown(f"""
<div style='background:#1e2130;border-radius:8px;padding:14px 16px'>
  <div style='margin-bottom:8px'>
    <a href='https://www.otcmarkets.com/research/stock-screener?market=Pink,Expert,Venture&maxPrice={max_price}&minVolume={vol_param}&sortBy=dollarVolume&sortOrder=desc' 
       target='_blank' style='color:#ffd600;font-weight:700;font-size:1.05em'>
       🔍 Open OTC Markets Screener — Under ${max_price:.2f} →
    </a>
  </div>
  <div style='color:#aaa;font-size:0.85em'>
    The screener will open with your price/volume filters pre-set. Find a ticker you like, 
    copy it, and paste it into the <strong>Add ticker</strong> box above.
  </div>
</div>
""", unsafe_allow_html=True)

    st.divider()

    # Teaching Mode Toggle — prominent
    st.markdown("""
<div style='background:#1a1a2e;border:1px solid #7c4dff;border-radius:8px;padding:10px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px'>
  <span style='font-size:1.3em'>🎓</span>
  <span style='color:#ccc;font-size:0.9em'><strong style='color:#7c4dff'>Teaching Mode</strong> — toggle on to explain every column in plain English. Great for learning with kids or friends new to investing.</span>
</div>
""", unsafe_allow_html=True)
    teach = st.toggle("🎓 Teaching Mode — explain everything", value=False)

    if teach:
        st.markdown("""
<div style='background:#1a1a2e;border-left:4px solid #7c4dff;border-radius:8px;padding:16px;margin-bottom:12px'>
  <div style='font-weight:700;color:#7c4dff;font-size:1.05em;margin-bottom:8px'>🎓 Welcome to the Stock Market</div>
  <div style='color:#ccc;font-size:0.875em;line-height:1.9'>
    <strong>What is a stock?</strong> When you buy a stock, you own a tiny piece of a company. If the company does well, your piece becomes worth more. If it does poorly, it's worth less.<br><br>
    <strong>What is a penny stock?</strong> A stock that trades for under $5 — usually from small or struggling companies. They're cheap to buy but risky. You can buy 1,000 shares of a $0.003 stock for just $3. That same $3 buys you less than 1 share of Apple.<br><br>
    <strong>Why are they risky?</strong> Small companies can fail completely. Your investment can go to zero. But if the company recovers or gets bought, it can multiply many times over. High risk, high reward.
  </div>
</div>
""", unsafe_allow_html=True)

    if not st.session_state.watchlist:
        st.info("Watchlist is empty. Add tickers above or use the Scanner tab to find candidates.")
    else:
        rows = []
        for ticker in st.session_state.watchlist:
            data = get_stock_data(ticker)
            flags = get_red_flags(ticker)
            mgmt  = get_management_names(ticker)
            flag_str = " ".join(flags) if flags else "✅ None detected"
            if data:
                # Apply $5 filter
                if price_filter and data["price"] > 5.0:
                    continue
                sig, rsi = get_signal(data["hist"])
                vol_flag = "🔥" if data["vol_spike"] >= 2.0 else ""
                rows.append({
                    "Ticker":      ticker,
                    "Price":       f"${data['price']:.4f}",
                    "Day %":       f"{data['change']:+.2f}%",
                    "Volume":      f"{data['volume']:,}",
                    "Vol Spike":   f"{data['vol_spike']:.1f}x {vol_flag}",
                    "RSI":         rsi if rsi else "—",
                    "Signal":      sig,
                    "Red Flags":   "🚩 MANUALLY FLAGGED" if st.session_state.manual_flags.get(ticker) else flag_str,
                    "Management":  mgmt,
                    "My Notes":    st.session_state.notes.get(ticker, ""),
                    "Research":    f"https://www.otcmarkets.com/stock/{ticker}/company-info",
                })
            else:
                rows.append({
                    "Ticker":     ticker,
                    "Price":      "—", "Day %": "—", "Volume": "—",
                    "Vol Spike":  "—", "RSI": "—", "Signal": "⬜ No data",
                    "Red Flags":  "🚩 MANUALLY FLAGGED" if st.session_state.manual_flags.get(ticker) else flag_str,
                    "Management": mgmt,
                    "My Notes":   st.session_state.notes.get(ticker, ""),
                    "Research":   f"https://www.otcmarkets.com/stock/{ticker}/company-info",
                })

        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Research": st.column_config.LinkColumn(
                    "OTC Profile",
                    display_text="🔍 Research",
                ),
                "Red Flags": st.column_config.TextColumn(
                    "Red Flags",
                    width="medium",
                ),
                "Management": st.column_config.TextColumn(
                    "Management",
                    width="large",
                ),
                "My Notes": st.column_config.TextColumn(
                    "My Notes",
                    width="large",
                ),
            }
        )

        # Quick flag buttons — one per ticker
        st.divider()
        st.markdown("**⚡ Quick Flag — click to toggle red flag on any ticker:**")
        flag_cols = st.columns(len(st.session_state.watchlist))
        for col, ticker in zip(flag_cols, st.session_state.watchlist):
            with col:
                is_flagged = st.session_state.manual_flags.get(ticker, False)
                btn_label = f"🚩 {ticker}" if is_flagged else f"✅ {ticker}"
                btn_color = "primary" if is_flagged else "secondary"
                if st.button(btn_label, key=f"qflag_{ticker}", use_container_width=True, type=btn_color):
                    st.session_state.manual_flags[ticker] = not is_flagged
                    st.rerun()

        # Notes editor
        st.divider()
        st.markdown("#### 📝 My Research Notes")
        st.caption("Add your own observations per ticker. Use the Quick Flag buttons above to flag/unflag instantly.")
        note_ticker = st.selectbox("Select ticker", st.session_state.watchlist, key="note_select")

        note_text = st.text_area(
            "Research note",
            value=st.session_state.notes.get(note_ticker, ""),
            placeholder="e.g. 3 name changes, no officers on OTC Markets, NY incorporation — classic shell pattern. Avoid.",
            height=80,
            key=f"note_input_{note_ticker}"
        )

        if st.button("💾 Save Note", use_container_width=False):
            st.session_state.notes[note_ticker] = note_text
            st.success(f"Note saved for {note_ticker}")
            st.rerun()

        if teach:
            st.markdown("""
<div style='background:#1a1a2e;border-left:4px solid #7c4dff;border-radius:8px;padding:16px;margin-top:12px'>
  <div style='font-weight:700;color:#7c4dff;margin-bottom:10px'>🎓 What do these columns mean?</div>
  <div style='color:#ccc;font-size:0.875em;line-height:2.0'>
    <strong>Price</strong> — What one share costs right now. At $0.003, a dollar buys 333 shares. At $4.35, a dollar buys less than 1 share.<br>
    <strong>Day %</strong> — How much the price changed today. +50% means it went up a lot. -50% means it lost half its value in one day. Penny stocks move fast.<br>
    <strong>Volume</strong> — How many shares were traded today. Low volume means few people are interested. High volume means something is happening.<br>
    <strong>Vol Spike 🔥</strong> — When today's trading is 2x or more than normal. The fire emoji means unusual activity — someone big may be buying or selling.<br>
    <strong>RSI</strong> — A number from 0-100. Under 35 means the stock may be oversold (could bounce back). Over 65 means it may be overbought (could drop). Around 50 is neutral.<br>
    <strong>Signal</strong> — A simple buy/hold indicator based on recent price trends. Not a guarantee — just a starting point for discussion.<br>
    <strong>Red Flags ⚠️</strong> — Things that look suspicious. No 10-K means the company isn't filing required reports. That's like a student not turning in homework — something is wrong.<br>
    <strong>Management 🚨</strong> — Are the company's leaders publicly identified? Hiding names is a serious warning sign. Honest companies disclose who runs them.<br>
    <strong>🔍 Research</strong> — Click this to read everything about the company on OTC Markets. Always research before buying anything.
  </div>
</div>
""", unsafe_allow_html=True)

            st.markdown("""
<div style='background:#1a2a1a;border-left:4px solid #00c853;border-radius:8px;padding:16px;margin-top:12px'>
  <div style='font-weight:700;color:#00c853;margin-bottom:8px'>🎓 The $500 Learning Portfolio</div>
  <div style='color:#ccc;font-size:0.875em;line-height:1.9'>
    <strong>Rule 1 — Never invest more than you can afford to lose completely.</strong> With penny stocks, assume the worst.<br>
    <strong>Rule 2 — Read before you buy.</strong> Click 🔍 Research on every stock. Read what the company actually does.<br>
    <strong>Rule 3 — Red flags mean walk away.</strong> Hidden management and no filings = skip it, no matter how cheap.<br>
    <strong>Rule 4 — Spread your risk.</strong> Don't put $500 in one stock. Try $100 in 5 different ones.<br>
    <strong>Rule 5 — Watch and wait.</strong> Check the app daily. Watch how news, volume, and price connect.<br>
    <strong>Rule 6 — Write down why you bought it.</strong> Then when it goes up or down, you can learn from your own reasoning.<br><br>
    The goal isn't to get rich. The goal is to understand how markets work — and that lesson is worth far more than $500.
  </div>
</div>
""", unsafe_allow_html=True)

        st.divider()
        st.markdown("""
<div style='background:#1e2130;border-radius:8px;padding:14px 16px;margin-bottom:8px'>
  <div style='font-weight:700;color:#ffd600;margin-bottom:6px'>🚨 Shell Company Red Flag Checklist</div>
  <div style='color:#ccc;font-size:0.875em;line-height:1.8'>
    <strong>Nevada/Wyoming incorporation</strong> + multiple name changes = highest risk pattern<br>
    <strong>No 10-K filed</strong> = management hiding from disclosure requirements<br>
    <strong>No proxy statement (DEF 14A)</strong> = officer names not publicly disclosed<br>
    <strong>Same officers across multiple failed OTC companies</strong> = serial promoters<br>
    <strong>High salary + share issuance to insiders</strong> before bankruptcy = cash-out pattern<br>
    Always search officer names on SEC EDGAR to see their full history across companies
  </div>
</div>
""", unsafe_allow_html=True)

        st.divider()
        st.markdown("### 📈 Price Chart")
        chart_ticker = st.selectbox("Select ticker for chart", st.session_state.watchlist)
        period_choice = st.radio("Period", ["1mo", "3mo", "6mo", "1y"], horizontal=True, index=1)

        hist = get_stock_data(chart_ticker)
        if hist and hist["hist"] is not None:
            h = hist["hist"]
            if period_choice != "3mo":
                t = yf.Ticker(chart_ticker)
                h = t.history(period=period_choice)

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.75, 0.25], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(
                x=h.index, open=h["Open"], high=h["High"],
                low=h["Low"], close=h["Close"], name=chart_ticker,
                increasing_line_color="#00c853", decreasing_line_color="#ff5252",
            ), row=1, col=1)
            if len(h) >= 5:
                fig.add_trace(go.Scatter(x=h.index, y=h["Close"].rolling(5).mean(),
                    line=dict(color="#4a9eff", width=1.5), name="5-day MA"), row=1, col=1)
            if len(h) >= 20:
                fig.add_trace(go.Scatter(x=h.index, y=h["Close"].rolling(20).mean(),
                    line=dict(color="#ff9800", width=1.5), name="20-day MA"), row=1, col=1)
            colors = ["#00c853" if c >= o else "#ff5252" for c, o in zip(h["Close"], h["Open"])]
            fig.add_trace(go.Bar(x=h.index, y=h["Volume"],
                marker_color=colors, name="Volume", opacity=0.6), row=2, col=1)
            fig.update_layout(height=480, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                font=dict(color="#ddd"), xaxis_rangeslider_visible=False,
                margin=dict(l=40, r=20, t=20, b=20))
            fig.update_xaxes(gridcolor="#222")
            fig.update_yaxes(gridcolor="#222")
            st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SEC FILINGS
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 📄 SEC Filings per Ticker")
    st.caption("Pulls recent 8-K and 10-K filings from EDGAR. 8-Ks are material events — bankruptcy, settlements, litigation. 10-Ks have management bios and full business description.")

    if not st.session_state.watchlist:
        st.info("Add tickers to your watchlist first.")
    else:
        filing_ticker = st.selectbox("Select ticker", st.session_state.watchlist, key="filing_select")
        col_8k, col_10k = st.columns(2)

        with col_8k:
            st.markdown("**Recent 8-K filings (material events)**")
            with st.spinner("Loading 8-K filings..."):
                filings_8k = get_recent_filings(filing_ticker, ["8-K"])
            if filings_8k:
                for f in filings_8k[:10]:
                    tags = classify_filing(f.get("title", "") + " " + f.get("accession", ""))
                    tag_html = ""
                    css_class = "filing-card"
                    for tag in tags:
                        t_css = {"BANKRUPTCY": "tag-bk", "LITIGATION": "tag-lit", "SETTLEMENT": "tag-settle"}.get(tag, "tag-volume")
                        tag_html += f"<span class='tag {t_css}'>{tag}</span>"
                        if tag == "BANKRUPTCY": css_class += " filing-bk"
                        if tag == "LITIGATION": css_class += " filing-lit"
                        if tag == "SETTLEMENT": css_class += " filing-settle"
                    st.markdown(f"""
<div class='{css_class}'>
  <div style='font-size:0.75em;color:#888'>{f['form']} · {f['date']}</div>
  <div style='font-weight:600;color:#ddd;margin:3px 0'>{f['company']}</div>
  <div>{tag_html}</div>
  <div style='font-size:0.8em;color:#666;margin-top:3px'>
    <a href='https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={filing_ticker}&type=8-K&dateb=&owner=include&count=20' 
       target='_blank' style='color:#4a9eff'>View on EDGAR →</a>
  </div>
</div>
""", unsafe_allow_html=True)
            else:
                st.info("No 8-K filings found. Try searching EDGAR directly.")
                st.markdown(f"[Search EDGAR for {filing_ticker} →](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={filing_ticker}&type=8-K&dateb=&owner=include&count=20)")

        with col_10k:
            st.markdown("**Annual Reports (10-K) — management bios & business description**")
            with st.spinner("Loading 10-K filings..."):
                filings_10k = get_recent_filings(filing_ticker, ["10-K"])
            if filings_10k:
                for f in filings_10k[:5]:
                    st.markdown(f"""
<div class='filing-card'>
  <div style='font-size:0.75em;color:#888'>{f['form']} · {f['date']}</div>
  <div style='font-weight:600;color:#ddd;margin:3px 0'>{f['company']}</div>
  <div style='font-size:0.8em;margin-top:3px'>
    <a href='https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={filing_ticker}&type=10-K&dateb=&owner=include&count=10' 
       target='_blank' style='color:#4a9eff'>View on EDGAR →</a>
  </div>
</div>
""", unsafe_allow_html=True)
            else:
                st.info("No 10-K filings found.")
                st.markdown(f"[Search EDGAR for {filing_ticker} →](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={filing_ticker}&type=10-K&dateb=&owner=include&count=10)")

    st.divider()
    st.markdown("**📖 Reading guide — what to look for:**")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
**In the 8-K:**
- Item 1.01 — Material agreement (settlement?)
- Item 1.03 — Bankruptcy or receivership filed
- Item 8.01 — Other material events (litigation outcome)
- Item 9.01 — Financial exhibits
""")
    with col_b:
        st.markdown("""
**In the 10-K:**
- Item 1 — Business description (core asset intact?)
- Item 1A — Risk factors (how bad is the litigation?)
- Item 3 — Legal proceedings (full litigation list)
- Item 10 — Directors & management bios
""")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — LITIGATION WATCH
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### ⚖️ Litigation Watch")
    st.caption(
        "Scans EDGAR for active litigation that could be a catalyst — patent wins, asbestos settlements, "
        "class action resolutions. These are the events that move depressed stocks."
    )

    lit_col1, lit_col2 = st.columns(2)
    with lit_col1:
        lit_type = st.selectbox("Litigation type", [
            "Patent infringement — plaintiff win",
            "Patent infringement — settlement",
            "Asbestos — settlement or resolution",
            "Class action — settlement",
            "Bankruptcy — reorganization plan approved",
            "All litigation events",
        ])
    with lit_col2:
        lit_start = st.selectbox("Since", ["2025-01-01", "2024-06-01", "2024-01-01"], key="lit_start")

    LIT_QUERIES = {
        "Patent infringement — plaintiff win":        "patent infringement judgment plaintiff",
        "Patent infringement — settlement":           "patent infringement settlement agreement",
        "Asbestos — settlement or resolution":        "asbestos settlement resolved",
        "Class action — settlement":                  "class action settlement approved",
        "Bankruptcy — reorganization plan approved":  "plan of reorganization confirmed",
        "All litigation events":                      "litigation settlement judgment",
    }

    if st.button("⚖️ Search Litigation Filings", type="primary", use_container_width=True):
        query = LIT_QUERIES[lit_type]
        with st.spinner(f"Searching EDGAR for litigation events..."):
            hits = search_edgar_full(query, form_type="8-K", start_date=lit_start)

        if hits:
            st.success(f"Found {len(hits)} relevant filings")
            for hit in hits:
                src = hit.get("_source", {})
                company = src.get("entity_name", "Unknown")
                date    = src.get("file_date", "")
                period  = src.get("period_of_report", "")

                is_settlement = any(k in lit_type.lower() for k in ["settlement", "approved", "win"])
                card_color = "#00c853" if is_settlement else "#ff5252"
                tag_label  = "SETTLEMENT" if is_settlement else "LITIGATION"
                tag_css    = "tag-settle" if is_settlement else "tag-lit"

                st.markdown(f"""
<div class='filing-card' style='border-left-color:{card_color}'>
  <div style='display:flex;justify-content:space-between'>
    <div>
      <span style='font-weight:700;color:#fff'>{company}</span>
      <span style='color:#888;font-size:0.8em;margin-left:8px'>8-K · {date}</span>
    </div>
    <span class='tag {tag_css}'>{tag_label}</span>
  </div>
  <div style='font-size:0.82em;color:#aaa;margin-top:4px'>Period: {period}</div>
  <div style='font-size:0.82em;margin-top:6px;display:flex;gap:16px'>
    <a href='https://www.otcmarkets.com/research/stock-screener/api?market=Pink&search={requests.utils.quote(company.split("(")[0].strip())}' target='_blank' style='color:#ffd600;text-decoration:none'>🔍 Search OTC Markets →</a>
    <a href='https://efts.sec.gov/LATEST/search-index?q=%22{requests.utils.quote(query)}%22&forms=8-K&dateRange=custom&startdt={lit_start}' target='_blank' style='color:#4a9eff;text-decoration:none'>📄 EDGAR Results →</a>
  </div>
</div>
""", unsafe_allow_html=True)
        else:
            st.info("No results found. Try a broader date range.")

    st.divider()
    st.markdown("### 🔗 Direct EDGAR Full-Text Search")
    st.caption("Enter your own search term to query all SEC filings directly.")
    custom_query = st.text_input("Custom EDGAR search", placeholder="e.g. TPMS patent tire pressure")
    if st.button("Search EDGAR →") and custom_query:
        edgar_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{requests.utils.quote(custom_query)}%22&forms=8-K,10-K"
        st.markdown(f"[Open EDGAR search for '{custom_query}' →]({edgar_url})")

    st.markdown("""
<div style='background:#1e2130;border-radius:8px;padding:16px;margin-top:12px'>
  <div style='font-weight:700;color:#ffd600;margin-bottom:8px'>📘 The Pattern That Works</div>
  <div style='color:#ccc;font-size:0.875em;line-height:1.8'>
    <strong>Step 1</strong> — Find a company in bankruptcy whose core IP or business is intact<br>
    <strong>Step 2</strong> — Read the 10-K: is management capable? Is the product real?<br>
    <strong>Step 3</strong> — Check the litigation: is the liability the ONLY problem?<br>
    <strong>Step 4</strong> — Buy shares at pennies when the market prices it as worthless<br>
    <strong>Step 5</strong> — Wait for reorganization plan approval or settlement<br>
    <strong>Step 6</strong> — The market reprices — you exit
  </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — NEWS
# ══════════════════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 📰 News Feed")
    st.caption("Headlines matching your watchlist tickers plus OTC/penny stock market news.")

    with st.spinner("Loading news..."):
        articles = fetch_news_for_watchlist(st.session_state.watchlist)

    if articles:
        st.caption(f"{len(articles)} relevant articles found.")
        for art in articles:
            matched_str = ", ".join([t.upper() for t in art["matched"]]) if art["matched"] else ""
            match_html  = f"<span class='tag tag-volume'>{matched_str}</span>" if matched_str else ""
            st.markdown(f"""
<div class='filing-card'>
  <div style='font-size:0.75em;color:#888'>{art['source']} · {art['pub'][:25] if art['pub'] else ''} {match_html}</div>
  <div style='font-weight:600;margin:4px 0'>
    <a href='{art['link']}' target='_blank' style='color:#4a9eff;text-decoration:none'>{art['title']}</a>
  </div>
  <div style='font-size:0.85em;color:#bbb'>{art['summary']}</div>
</div>
""", unsafe_allow_html=True)
    else:
        st.info("No matching news articles right now. Try refreshing or add more tickers to your watchlist.")

# ─── Footer ───────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "⚠️ This tool displays publicly available market data and SEC filing information only. "
    "OTC and penny stocks carry substantial risk including total loss of investment. "
    "This is not investment advice. All investment decisions are yours alone."
)
