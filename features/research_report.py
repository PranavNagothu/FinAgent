"""
features/research_report.py — AI-Generated Investment Research Reports
Uses LangGraph multi-agent pipeline: Fundamentals, News, Risk, Verdict agents.
Data from SEC EDGAR, Tavily, Alpha Vantage.
"""
import streamlit as st
import json
import re
import time
import requests
import logging
from typing import TypedDict, Dict, Any
from datetime import datetime
from functools import lru_cache

from langgraph.graph import StateGraph, END

logger = logging.getLogger("ResearchReport")

# ---------------------------------------------------------------------------
# SEC EDGAR — Dynamic CIK lookup (supports ALL US public companies)
# ---------------------------------------------------------------------------
SEC_HEADERS = {"User-Agent": "SentinelAI research@sentinel-ai.app", "Accept-Encoding": "gzip, deflate"}

_cik_cache: dict = {}  # in-memory cache: ticker -> CIK


def _get_cik_for_ticker(ticker: str) -> str | None:
    """Look up CIK number for any US public company ticker via SEC EDGAR."""
    global _cik_cache
    ticker = ticker.upper().strip()

    # Return from cache if available
    if ticker in _cik_cache:
        return _cik_cache[ticker]

    # Fetch the full SEC ticker→CIK mapping (cached after first call)
    if not _cik_cache:
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for entry in data.values():
                t = str(entry.get("ticker", "")).upper()
                cik = str(entry.get("cik_str", "")).zfill(10)
                _cik_cache[t] = cik
            logger.info(f"Loaded {len(_cik_cache)} ticker→CIK mappings from SEC EDGAR")
        except Exception as e:
            logger.error(f"Failed to fetch SEC ticker mappings: {e}")
            return None

    return _cik_cache.get(ticker)


# ---------------------------------------------------------------------------
# Smart ticker resolution (supports company names AND ticker symbols)
# ---------------------------------------------------------------------------
# Common company names → tickers (fast path)
_COMMON_NAMES = {
    "AMAZON": "AMZN", "APPLE": "AAPL", "GOOGLE": "GOOGL", "ALPHABET": "GOOGL",
    "MICROSOFT": "MSFT", "TESLA": "TSLA", "NVIDIA": "NVDA", "META": "META",
    "FACEBOOK": "META", "NETFLIX": "NFLX", "AMD": "AMD", "INTEL": "INTC",
    "DISNEY": "DIS", "WALMART": "WMT", "JPMORGAN": "JPM", "GOLDMAN": "GS",
    "BERKSHIRE": "BRK-B", "VISA": "V", "MASTERCARD": "MA", "PAYPAL": "PYPL",
    "UBER": "UBER", "AIRBNB": "ABNB", "SNOWFLAKE": "SNOW", "PALANTIR": "PLTR",
    "COINBASE": "COIN", "SPOTIFY": "SPOT", "SHOPIFY": "SHOP", "SALESFORCE": "CRM",
    "ORACLE": "ORCL", "IBM": "IBM", "CISCO": "CSCO", "ADOBE": "ADBE",
    "BOEING": "BA", "FORD": "F", "GM": "GM", "TOYOTA": "TM",
    "COCA-COLA": "KO", "COCACOLA": "KO", "PEPSI": "PEP", "NIKE": "NKE",
    "STARBUCKS": "SBUX", "MCDONALDS": "MCD", "PFIZER": "PFE", "JOHNSON": "JNJ",
    "EXXON": "XOM", "CHEVRON": "CVX", "COSTCO": "COST", "TARGET": "TGT",
    "BROADCOM": "AVGO", "QUALCOMM": "QCOM", "MICRON": "MU", "RIVIAN": "RIVN",
    "ROBINHOOD": "HOOD", "SOFI": "SOFI", "BLOCK": "SQ", "SQUARE": "SQ",
}

# Name-to-ticker cache from SEC EDGAR
_name_to_ticker_cache: dict = {}


def _resolve_ticker(user_input: str) -> str:
    """Resolve user input (company name or ticker) to a valid ticker symbol."""
    global _name_to_ticker_cache
    cleaned = user_input.upper().strip()

    # 1. Check if it's already a valid short ticker (1-5 chars, all alpha)
    if len(cleaned) <= 5 and cleaned.replace("-", "").isalpha():
        # Verify it exists in SEC data (if cache is loaded)
        if _cik_cache and cleaned in _cik_cache:
            return cleaned
        # If cache is empty, trust the user
        if not _cik_cache:
            return cleaned

    # 2. Fast path: common names
    if cleaned in _COMMON_NAMES:
        logger.info(f"Resolved '{user_input}' → '{_COMMON_NAMES[cleaned]}' (common name)")
        return _COMMON_NAMES[cleaned]

    # 3. Check partial matches in common names
    for name, ticker in _COMMON_NAMES.items():
        if name in cleaned or cleaned in name:
            logger.info(f"Resolved '{user_input}' → '{ticker}' (partial match: {name})")
            return ticker

    # 4. Search SEC EDGAR company names (lazy load)
    if not _name_to_ticker_cache:
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for entry in data.values():
                name = str(entry.get("title", "")).upper()
                ticker = str(entry.get("ticker", "")).upper()
                _name_to_ticker_cache[name] = ticker
        except Exception as e:
            logger.warning(f"SEC name lookup failed: {e}")

    # Exact match on SEC company name
    if cleaned in _name_to_ticker_cache:
        resolved = _name_to_ticker_cache[cleaned]
        logger.info(f"Resolved '{user_input}' → '{resolved}' (SEC EDGAR exact)")
        return resolved

    # Partial match on SEC company name
    for name, ticker in _name_to_ticker_cache.items():
        if cleaned in name:
            logger.info(f"Resolved '{user_input}' → '{ticker}' (SEC EDGAR partial: {name})")
            return ticker

    # 5. Fallback: return as-is (user probably typed a valid ticker we don't have cached)
    logger.warning(f"Could not resolve '{user_input}' — using as-is")
    return cleaned


# ---------------------------------------------------------------------------
# SEC EDGAR filing fetcher
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------
class ReportState(TypedDict):
    ticker: str
    sec_data: Dict[str, Any]
    fundamentals_output: str
    news_output: str
    risk_output: str
    verdict_output: str
    final_report: Dict[str, str]


def _fetch_sec_filings(ticker: str) -> dict:
    """Fetch company filing metadata from SEC EDGAR (supports ALL tickers)."""
    cik = _get_cik_for_ticker(ticker.upper())
    if not cik:
        return {"error": f"CIK not found for {ticker}. SEC data unavailable."}
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        company_name = data.get("name", ticker)
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        descriptions = recent.get("primaryDocDescription", [])
        accession = recent.get("accessionNumber", [])
        # Get last 10-K and 10-Q
        filings_summary = []
        for i, form in enumerate(forms[:50]):
            if form in ("10-K", "10-Q", "8-K"):
                filings_summary.append({
                    "form": form,
                    "date": dates[i] if i < len(dates) else "N/A",
                    "description": descriptions[i] if i < len(descriptions) else "",
                    "accession": accession[i] if i < len(accession) else "",
                })
        return {"company_name": company_name, "filings": filings_summary[:10]}
    except Exception as e:
        logger.error(f"SEC EDGAR fetch failed: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Build the LangGraph pipeline
# ---------------------------------------------------------------------------
def _build_report_pipeline():
    from features.utils import call_gemini, run_tavily_search, fetch_stock_data, fetch_company_overview, fetch_global_quote

    def fundamentals_agent(state: ReportState):
        ticker = state["ticker"]
        sec = state.get("sec_data", {})

        # Fetch company fundamentals (Revenue, EPS, P/E, Margins, Market Cap)
        overview_data = {}
        try:
            overview_result = fetch_company_overview(ticker)
            overview_data = overview_result.get("data", {})
            overview_source = overview_result.get("source", "Unknown")
        except Exception as e:
            logger.warning(f"Company overview fetch failed: {e}")
            overview_source = "Unavailable"

        # Fetch real-time price quote
        quote_data = {}
        try:
            quote_result = fetch_global_quote(ticker)
            quote_data = quote_result.get("data", {})
        except Exception as e:
            logger.warning(f"Global quote fetch failed: {e}")

        # Build a rich data summary for the LLM
        financials_summary = f"""
Company: {overview_data.get('Name', ticker)} ({overview_data.get('Symbol', ticker)})
Sector: {overview_data.get('Sector', 'N/A')} | Industry: {overview_data.get('Industry', 'N/A')}
Description: {overview_data.get('Description', 'N/A')[:300]}

--- FINANCIAL METRICS (Source: {overview_source}) ---
Market Cap: ${overview_data.get('MarketCapitalization', 'N/A')}
Revenue (TTM): ${overview_data.get('RevenueTTM', 'N/A')}
Gross Profit (TTM): ${overview_data.get('GrossProfitTTM', 'N/A')}
EPS: ${overview_data.get('EPS', 'N/A')}
P/E Ratio: {overview_data.get('PERatio', 'N/A')}
Forward P/E: {overview_data.get('ForwardPE', 'N/A')}
Profit Margin: {overview_data.get('ProfitMargin', 'N/A')}
Operating Margin: {overview_data.get('OperatingMarginTTM', 'N/A')}
Return on Equity: {overview_data.get('ReturnOnEquityTTM', 'N/A')}
Revenue Per Share: ${overview_data.get('RevenuePerShareTTM', 'N/A')}
Book Value: ${overview_data.get('BookValue', 'N/A')}
Price to Book: {overview_data.get('PriceToBookRatio', 'N/A')}
Dividend Yield: {overview_data.get('DividendYield', 'N/A')}
Beta: {overview_data.get('Beta', 'N/A')}

--- GROWTH ---
Quarterly Earnings Growth (YoY): {overview_data.get('QuarterlyEarningsGrowthYOY', 'N/A')}
Quarterly Revenue Growth (YoY): {overview_data.get('QuarterlyRevenueGrowthYOY', 'N/A')}

--- PRICE DATA ---
Current Price: ${quote_data.get('price', 'N/A')}
Today's Change: {quote_data.get('change', 'N/A')} ({quote_data.get('change_percent', 'N/A')})
Today's Open: ${quote_data.get('open', 'N/A')}
Today's High: ${quote_data.get('high', 'N/A')}
Today's Low: ${quote_data.get('low', 'N/A')}
Volume: {quote_data.get('volume', 'N/A')}
Previous Close: ${quote_data.get('previous_close', 'N/A')}
52-Week High: ${overview_data.get('52WeekHigh', 'N/A')}
52-Week Low: ${overview_data.get('52WeekLow', 'N/A')}
50-Day MA: ${overview_data.get('50DayMovingAverage', 'N/A')}
200-Day MA: ${overview_data.get('200DayMovingAverage', 'N/A')}

--- ANALYST CONSENSUS ---
Target Price: ${overview_data.get('AnalystTargetPrice', 'N/A')}
Buy Ratings: {overview_data.get('AnalystRatingBuy', 'N/A')}
Hold Ratings: {overview_data.get('AnalystRatingHold', 'N/A')}
Sell Ratings: {overview_data.get('AnalystRatingSell', 'N/A')}
"""

        prompt = f"""You are a financial fundamentals analyst. Analyze {ticker}.

{financials_summary}

SEC Filings Summary: {json.dumps(sec.get('filings', [])[:5], indent=2)}

Based on ALL the data above, provide:
1. Business overview (2-3 sentences)
2. Key financial metrics analysis — use the ACTUAL numbers provided (Revenue, EPS, Margins, P/E, etc.)
3. Year-over-year growth assessment using the quarterly growth data
4. A markdown table of key metrics with their actual values
5. Valuation assessment (is it overvalued/undervalued based on P/E, P/B, analyst targets?)

Use the real numbers. Be specific and data-driven."""

        result = call_gemini(prompt, "You are a senior equity research analyst specializing in fundamental analysis.")
        return {"fundamentals_output": result}

    def news_agent(state: ReportState):
        ticker = state["ticker"]
        try:
            search_result = run_tavily_search(f"{ticker} stock news last 30 days analysis")
            articles = []
            for qr in search_result.get("data", []):
                for r in qr.get("results", []):
                    articles.append(f"- **{r.get('title', '')}**: {r.get('content', '')[:200]}...")
            news_text = "\n".join(articles[:8]) if articles else "No recent news found."
        except Exception:
            news_text = "News search unavailable."

        prompt = f"""Summarize the last 30 days of news for {ticker}:

{news_text}

Provide:
1. Overall news sentiment (Bullish/Bearish/Neutral)
2. Top 3-5 key headlines with brief explanations
3. Any catalysts or upcoming events mentioned
Be concise and factual."""
        result = call_gemini(prompt, "You are a financial news analyst summarizing market intelligence.")
        return {"news_output": result}

    def risk_agent(state: ReportState):
        ticker = state["ticker"]
        sec = state.get("sec_data", {})
        filings_text = json.dumps(sec.get("filings", []), indent=2)

        try:
            search_result = run_tavily_search(f"{ticker} 10-K risk factors annual report risks")
            risk_articles = []
            for qr in search_result.get("data", []):
                for r in qr.get("results", []):
                    risk_articles.append(r.get("content", "")[:300])
            risk_text = "\n".join(risk_articles[:5])
        except Exception:
            risk_text = "Risk search unavailable."

        prompt = f"""You are a risk analyst. Identify key risk factors for {ticker}.

SEC Filing History: {filings_text}
Risk-Related Research: {risk_text}

Provide:
1. Top 5 risk factors (ranked by severity)
2. Risk category for each (Operational, Financial, Regulatory, Market, Competitive)
3. Brief mitigation outlook for each
Format as a numbered list."""
        result = call_gemini(prompt, "You are a senior risk analyst at a major investment bank.")
        return {"risk_output": result}

    def verdict_agent(state: ReportState):
        prompt = f"""You are the lead analyst writing the final investment verdict for {state['ticker']}.

FUNDAMENTALS ANALYSIS:
{state.get('fundamentals_output', 'N/A')}

NEWS & SENTIMENT:
{state.get('news_output', 'N/A')}

RISK ASSESSMENT:
{state.get('risk_output', 'N/A')}

Based on ALL the above analysis, provide:
1. **Recommendation**: Buy / Hold / Sell (with conviction level: High/Medium/Low)
2. **Price Target**: Estimated 12-month price target with brief methodology
3. **Bull Case** (2-3 sentences)
4. **Bear Case** (2-3 sentences)
5. **Key Catalysts to Watch** (3-5 bullet points)

Be specific and data-driven. Reference specific findings from the analysis above."""
        result = call_gemini(prompt, "You are a senior investment strategist issuing a formal recommendation.")
        return {"verdict_output": result}

    def compile_report(state: ReportState):
        return {
            "final_report": {
                "executive_summary": f"Research report for **{state['ticker']}** generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}.",
                "fundamentals": state.get("fundamentals_output", ""),
                "news": state.get("news_output", ""),
                "risks": state.get("risk_output", ""),
                "verdict": state.get("verdict_output", ""),
            }
        }

    workflow = StateGraph(ReportState)
    workflow.add_node("fundamentals", fundamentals_agent)
    workflow.add_node("news", news_agent)
    workflow.add_node("risk", risk_agent)
    workflow.add_node("verdict", verdict_agent)
    workflow.add_node("compile", compile_report)

    workflow.set_entry_point("fundamentals")
    workflow.add_edge("fundamentals", "news")
    workflow.add_edge("news", "risk")
    workflow.add_edge("risk", "verdict")
    workflow.add_edge("verdict", "compile")
    workflow.add_edge("compile", END)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Cached report generation
# ---------------------------------------------------------------------------
@lru_cache(maxsize=128)
def generate_report(ticker: str) -> dict:
    # Resolve company names to ticker symbols
    resolved = _resolve_ticker(ticker)
    sec_data = _fetch_sec_filings(resolved)
    pipeline = _build_report_pipeline()
    result = pipeline.invoke({"ticker": resolved.upper(), "sec_data": sec_data})
    report = result.get("final_report", {})
    report["_resolved_ticker"] = resolved.upper()
    return report


# ---------------------------------------------------------------------------
# Streamlit page renderer
# ---------------------------------------------------------------------------
def render_research_report():
    st.markdown("## 🌳💰 AI-Generated Research Report")
    st.caption("Generate a comprehensive, multi-agent investment research report for any stock. "
               "Powered by SEC EDGAR, Tavily news search, Alpha Vantage, and Google Gemini.")

    col1, col2 = st.columns([3, 1])
    with col1:
        ticker = st.text_input("Enter Ticker or Company Name:", placeholder="e.g. AAPL, Tesla, Amazon, NVDA", key="rr_ticker").strip()
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        generate_btn = st.button("🔬 Generate Report", use_container_width=True, key="rr_generate")

    if generate_btn and ticker:
        with st.status("🚀 Multi-Agent Research Pipeline Active...", expanded=True) as status:
            status.write("📡 Fetching SEC filings...")
            time.sleep(0.5)
            status.write("🔬 FundamentalsAgent analyzing financials...")
            status.write("📰 NewsAgent scanning last 30 days...")
            status.write("⚠️ RiskAgent evaluating risk factors...")
            status.write("🎯 VerdictAgent synthesizing recommendation...")

            try:
                report = generate_report(ticker)
                resolved = report.get("_resolved_ticker", ticker.upper())
                st.session_state["rr_report"] = report
                st.session_state["rr_display_ticker"] = resolved
                if resolved != ticker.upper():
                    status.write(f"🔄 Resolved '{ticker}' → {resolved}")
                status.update(label=f"✅ Report Complete for {resolved}!", state="complete", expanded=False)
            except Exception as e:
                status.update(label="❌ Pipeline Error", state="error")
                st.error(f"Failed to generate report: {e}")
                return

    # Display report
    report = st.session_state.get("rr_report")
    if report:
        ticker_display = st.session_state.get("rr_display_ticker", "")
        st.markdown(f"### 🌳💰 Research Report: **{ticker_display}**")
        st.info(report.get("executive_summary", ""))

        st.subheader("📋 Business Overview & Financial Health")
        st.markdown(report.get('fundamentals', 'No data available.'))
        st.markdown("---")

        st.subheader("📰 Recent News & Sentiment")
        st.markdown(report.get('news', 'No data available.'))
        st.markdown("---")

        st.subheader("⚠️ Risk Factors")
        st.markdown(report.get('risks', 'No data available.'))
        st.markdown("---")

        st.subheader("🎯 Analyst Verdict & Price Target")
        st.markdown(report.get('verdict', 'No data available.'))

        # PDF Download
        st.markdown("---")
        if st.button("📥 Download as PDF", key="rr_pdf"):
            from features.utils import export_to_pdf
            sections = [
                {"title": "Executive Summary", "body": report.get("executive_summary", "")},
                {"title": "Business Overview & Financial Health", "body": report.get("fundamentals", "")},
                {"title": "Recent News & Sentiment", "body": report.get("news", "")},
                {"title": "Risk Factors", "body": report.get("risks", "")},
                {"title": "Analyst Verdict & Price Target", "body": report.get("verdict", "")},
            ]
            pdf_bytes = export_to_pdf(sections, f"{ticker_display}_report.pdf")
            st.download_button(
                label="⬇️ Download PDF",
                data=pdf_bytes,
                file_name=f"{ticker_display}_Research_Report.pdf",
                mime="application/pdf",
                key="rr_pdf_dl",
            )
