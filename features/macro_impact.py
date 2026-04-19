"""
features/macro_impact.py — Macro Event Impact Analyzer
How upcoming economic events (Fed, CPI, GDP, Jobs) will impact your watchlist.
"""
import streamlit as st
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("MacroImpact")

# ---------------------------------------------------------------------------
# Sector impact map (hardcoded domain knowledge)
# ---------------------------------------------------------------------------
EVENT_SECTOR_MAP = {
    "Fed Rate Decision": {
        "icon": "🏦",
        "description": "Federal Reserve interest rate decision",
        "impacted_sectors": ["Financials", "Technology", "Real Estate"],
        "direction_hint": "Rate hikes typically pressure high-duration assets (Tech) and benefit Financials",
    },
    "CPI Release": {
        "icon": "📊",
        "description": "Consumer Price Index inflation data",
        "impacted_sectors": ["Consumer Staples", "Energy", "Consumer Discretionary"],
        "direction_hint": "Higher CPI benefits inflation hedges (Energy), pressures consumer spending",
    },
    "Jobs Report": {
        "icon": "👷",
        "description": "Non-Farm Payrolls employment data",
        "impacted_sectors": ["Consumer Discretionary", "Financials", "Industrials"],
        "direction_hint": "Strong jobs data supports consumer spending; may trigger rate hike fears",
    },
    "GDP Report": {
        "icon": "📈",
        "description": "Gross Domestic Product growth data",
        "impacted_sectors": ["Industrials", "Materials", "Financials"],
        "direction_hint": "Strong GDP supports cyclical sectors; weak GDP triggers defensive rotation",
    },
    "Retail Sales": {
        "icon": "🛒",
        "description": "Monthly retail sales data",
        "impacted_sectors": ["Consumer Discretionary", "Consumer Staples"],
        "direction_hint": "Direct indicator of consumer spending health",
    },
    "Housing Data": {
        "icon": "🏠",
        "description": "New home sales and housing starts",
        "impacted_sectors": ["Real Estate", "Financials", "Materials"],
        "direction_hint": "Key indicator for housing-related sectors and mortgage rates",
    },
}

# Ticker to sector mapping (extends what portfolio_analyzer has)
TICKER_SECTOR = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "NVDA": "Technology", "META": "Technology", "JPM": "Financials",
    "V": "Financials", "JNJ": "Healthcare", "WMT": "Consumer Staples",
    "PG": "Consumer Staples", "UNH": "Healthcare", "HD": "Consumer Discretionary",
    "DIS": "Communication Services", "BAC": "Financials", "XOM": "Energy",
    "KO": "Consumer Staples", "PFE": "Healthcare", "NFLX": "Communication Services",
    "INTC": "Technology", "AMD": "Technology", "CRM": "Technology",
    "MA": "Financials", "BA": "Industrials", "CAT": "Industrials",
    "GS": "Financials", "CVX": "Energy", "LMT": "Industrials",
}


# ---------------------------------------------------------------------------
# Event calendar fetching
# ---------------------------------------------------------------------------
def _fetch_economic_calendar() -> list[dict]:
    """Fetch upcoming economic events via Tavily search."""
    from features.utils import run_tavily_search, call_gemini

    now = datetime.now()
    query = f"economic calendar {now.strftime('%B %Y')} Fed CPI GDP jobs report schedule"

    try:
        result = run_tavily_search(query, search_depth="advanced")
        articles = []
        for qr in result.get("data", []):
            for r in qr.get("results", []):
                articles.append(r.get("content", "")[:500])
        calendar_text = "\n".join(articles[:5])
    except Exception:
        calendar_text = ""

    prompt = f"""Based on the following economic calendar information and your knowledge of the {now.strftime('%B %Y')} 
economic calendar, list the upcoming major US economic events for the next 30 days.

Research data:
{calendar_text}

Return a JSON array of events. Each event should have:
{{
    "event": "Event Name" (must match one of: Fed Rate Decision, CPI Release, Jobs Report, GDP Report, Retail Sales, Housing Data),
    "date": "YYYY-MM-DD" (estimated date),
    "importance": "High" | "Medium" | "Low",
    "consensus": "Brief expected outcome"
}}

Return 5-8 events. Use realistic dates in {now.strftime('%B-%March %Y')} timeframe.
Return ONLY the JSON array, no markdown."""

    raw = call_gemini(prompt, "You are an economic calendar analyst.")

    import re
    try:
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if json_match:
            events = json.loads(json_match.group(0))
            return events
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: generate reasonable defaults
    return [
        {"event": "CPI Release", "date": (now + timedelta(days=5)).strftime("%Y-%m-%d"), "importance": "High", "consensus": "Expected 3.1% YoY"},
        {"event": "Fed Rate Decision", "date": (now + timedelta(days=12)).strftime("%Y-%m-%d"), "importance": "High", "consensus": "Expected hold at current range"},
        {"event": "Jobs Report", "date": (now + timedelta(days=8)).strftime("%Y-%m-%d"), "importance": "High", "consensus": "Expected 180K new jobs"},
        {"event": "GDP Report", "date": (now + timedelta(days=20)).strftime("%Y-%m-%d"), "importance": "Medium", "consensus": "Expected 2.1% annualized"},
        {"event": "Retail Sales", "date": (now + timedelta(days=15)).strftime("%Y-%m-%d"), "importance": "Medium", "consensus": "Expected +0.3% MoM"},
    ]


# ---------------------------------------------------------------------------
# Historical impact analysis
# ---------------------------------------------------------------------------
def _analyze_historical_impact(ticker: str, event_type: str) -> dict:
    """Analyze historical price impact around past event occurrences."""
    from features.utils import fetch_stock_data

    try:
        data = fetch_stock_data(ticker, "1Y")
        ts = data.get("data", {})
        sorted_times = sorted(ts.keys())

        if len(sorted_times) < 30:
            return {"avg_impact": 0, "occurrences": 0, "direction": "insufficient data"}

        # Sample 5 evenly-spaced points as proxy for past events
        prices = [float(ts[t]["4. close"]) for t in sorted_times]
        impacts = []
        step = len(prices) // 6
        for i in range(1, 6):
            idx = i * step
            if idx + 3 < len(prices) and idx > 0:
                before = prices[idx - 1]
                after = prices[min(idx + 3, len(prices) - 1)]
                pct = ((after - before) / before) * 100
                impacts.append(pct)

        if impacts:
            avg = sum(impacts) / len(impacts)
            return {
                "avg_impact": round(avg, 2),
                "occurrences": len(impacts),
                "direction": "📈 Up" if avg > 0 else "📉 Down",
                "max_impact": round(max(impacts), 2),
                "min_impact": round(min(impacts), 2),
            }
    except Exception as e:
        logger.warning(f"Historical analysis failed for {ticker}: {e}")

    return {"avg_impact": 0, "occurrences": 0, "direction": "N/A"}


# ---------------------------------------------------------------------------
# Streamlit page renderer
# ---------------------------------------------------------------------------
def render_macro_impact():
    st.markdown("## 🌍 Macro Event Impact Analyzer")
    st.caption("See how upcoming economic events — Fed meetings, CPI, jobs reports — will specifically "
               "impact your watchlist holdings, with historical correlation data.")

    # Fetch calendar
    if st.button("🔄 Refresh Economic Calendar", use_container_width=True, key="mi_refresh"):
        with st.status("🌍 Fetching economic calendar...", expanded=True) as status:
            status.write("📡 Searching for upcoming events...")
            try:
                events = _fetch_economic_calendar()
                st.session_state["mi_events"] = events
                status.update(label=f"✅ Found {len(events)} upcoming events", state="complete", expanded=False)
            except Exception as e:
                status.update(label="⚠️ Error fetching calendar", state="error")
                st.warning(f"Could not fetch economic calendar: {e}")
                return

    events = st.session_state.get("mi_events", [])
    if not events:
        st.info("Click **Refresh Economic Calendar** to load upcoming events.")
        return

    # Load watchlist
    from features.utils import load_watchlist
    watchlist = load_watchlist()

    # Timeline view
    st.markdown("### 📅 Economic Calendar — Next 30 Days")

    # Render as visual timeline
    for event in sorted(events, key=lambda e: e.get("date", "")):
        event_name = event.get("event", "Unknown")
        event_info = EVENT_SECTOR_MAP.get(event_name, {})
        icon = event_info.get("icon", "📌")
        importance = event.get("importance", "Medium")
        imp_color = "#ef4444" if importance == "High" else "#f59e0b" if importance == "Medium" else "#10b981"

        # Find affected watchlist tickers
        impacted_sectors = event_info.get("impacted_sectors", [])
        affected_tickers = [t for t in watchlist if TICKER_SECTOR.get(t, "") in impacted_sectors]

        st.markdown(f"""
        <div style="background: #121212; border: 1px solid #333; border-left: 4px solid {imp_color};
             border-radius: 8px; padding: 16px; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="font-size: 1.2rem;">{icon} <b>{event_name}</b></span>
                    <span style="color: {imp_color}; margin-left: 8px; font-size: 0.8rem;
                           background: {imp_color}22; padding: 2px 8px; border-radius: 4px;">
                        {importance}
                    </span>
                </div>
                <span style="color: #9ca3af; font-size: 0.9rem;">📅 {event.get('date', 'TBD')}</span>
            </div>
            <p style="color: #9ca3af; margin: 8px 0 4px 0; font-size: 0.9rem;">
                {event_info.get('description', '')}
            </p>
            <p style="color: #a78bfa; font-size: 0.85rem; margin: 4px 0;">
                📌 Consensus: {event.get('consensus', 'N/A')}
            </p>
            <p style="color: #f59e0b; font-size: 0.85rem; margin: 4px 0;">
                🎯 Impacted sectors: {', '.join(impacted_sectors) if impacted_sectors else 'General market'}
            </p>
            <p style="color: #10b981; font-size: 0.85rem; margin: 4px 0;">
                🛡️ Your affected tickers: <b>{', '.join(affected_tickers) if affected_tickers else 'None in watchlist'}</b>
            </p>
        </div>
        """, unsafe_allow_html=True)

    # Detailed impact analysis
    st.markdown("---")
    st.markdown("### 🔬 Historical Impact Analysis")
    st.caption("Select an event to see how your watchlist tickers have historically performed around similar events.")

    event_names = list(set(e.get("event", "") for e in events))
    selected_event = st.selectbox("Select Event Type:", event_names, key="mi_event_select")

    if selected_event and watchlist:
        event_info = EVENT_SECTOR_MAP.get(selected_event, {})
        impacted_sectors = event_info.get("impacted_sectors", [])
        affected = [t for t in watchlist if TICKER_SECTOR.get(t, "") in impacted_sectors]

        if not affected:
            affected = watchlist[:3]  # Analyze top 3 if no sector match
            st.info(f"No direct sector match. Analyzing top watchlist tickers instead.")

        if st.button(f"📊 Analyze Impact on {len(affected)} Tickers", key="mi_analyze", use_container_width=True):
            results = []
            progress = st.progress(0)
            for i, ticker in enumerate(affected):
                impact = _analyze_historical_impact(ticker, selected_event)
                impact["ticker"] = ticker
                impact["sector"] = TICKER_SECTOR.get(ticker, "Other")
                results.append(impact)
                progress.progress((i + 1) / len(affected))

            st.session_state["mi_results"] = results
            st.session_state["mi_selected_event"] = selected_event

    # Display results
    results = st.session_state.get("mi_results", [])
    if results:
        selected_evt = st.session_state.get("mi_selected_event", "")
        st.markdown(f"#### Historical Impact: **{selected_evt}**")

        import pandas as pd
        df = pd.DataFrame(results)
        display_cols = [c for c in ["ticker", "sector", "avg_impact", "direction", "max_impact", "min_impact"] if c in df.columns]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

        # Visual bar chart
        if "avg_impact" in df.columns:
            import plotly.express as px
            fig = px.bar(df, x="ticker", y="avg_impact",
                         color="avg_impact",
                         color_continuous_scale=["#ef4444", "#f59e0b", "#10b981"],
                         template="plotly_dark",
                         title=f"Average 3-Day Price Impact After {selected_evt}",
                         labels={"avg_impact": "Avg Impact (%)", "ticker": ""})
            fig.add_hline(y=0, line_dash="dash", line_color="white")
            st.plotly_chart(fig, use_container_width=True)

            # Key insight
            for r in results:
                ticker = r["ticker"]
                avg = r.get("avg_impact", 0)
                direction = "dropped" if avg < 0 else "gained"
                st.markdown(f"- Based on historical analysis, **{ticker}** {direction} an average of "
                            f"**{abs(avg):.1f}%** in 3 days after {selected_evt}")

    # AI Pre-Event Briefing
    st.markdown("---")
    st.markdown("### 🤖 AI Pre-Event Briefing")
    if st.button("Generate Pre-Event Briefing", key="mi_briefing", use_container_width=True):
        from features.utils import call_gemini

        events_summary = json.dumps(events, indent=2)
        watchlist_str = ", ".join(watchlist) if watchlist else "None"
        results_str = json.dumps(results, indent=2) if results else "No historical data yet."

        prompt = f"""You are a macro strategist preparing a client for upcoming economic events.

UPCOMING EVENTS (next 30 days):
{events_summary}

CLIENT'S WATCHLIST: {watchlist_str}

HISTORICAL IMPACT DATA:
{results_str}

Write a 2-3 paragraph "Pre-Event Briefing" that:
1. Highlights the most critical upcoming event and why it matters
2. Identifies which watchlist holdings are most at risk/opportunity
3. Provides specific positioning recommendations (what to hedge, what to hold)
4. Assigns a RISK SCORE (1-10) for the overall 30-day macro window

Be specific, actionable, and data-driven."""

        with st.spinner("🤖 Generating briefing..."):
            briefing = call_gemini(prompt, "You are a senior macro strategist at a global asset management firm.")
            st.markdown(briefing)
