"""
features/portfolio_analyzer.py — Personal Portfolio Document Analyzer
Upload CSV/PDF brokerage statements, get AI-driven portfolio insights.
"""
import streamlit as st
import pandas as pd
import json
import logging
import io
from datetime import datetime

logger = logging.getLogger("PortfolioAnalyzer")

# ---------------------------------------------------------------------------
# Sector mapping for common tickers (fallback)
# ---------------------------------------------------------------------------
SECTOR_MAP = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "NVDA": "Technology", "META": "Technology", "JPM": "Financials",
    "V": "Financials", "JNJ": "Healthcare", "WMT": "Consumer Staples",
    "PG": "Consumer Staples", "UNH": "Healthcare", "HD": "Consumer Discretionary",
    "DIS": "Communication Services", "BAC": "Financials", "XOM": "Energy",
    "KO": "Consumer Staples", "PFE": "Healthcare", "NFLX": "Communication Services",
    "INTC": "Technology", "AMD": "Technology", "CRM": "Technology",
    "MA": "Financials", "BA": "Industrials", "CAT": "Industrials",
}

# ---------------------------------------------------------------------------
# CSV parsers for common brokerage formats
# ---------------------------------------------------------------------------
COLUMN_ALIASES = {
    "ticker": ["ticker", "symbol", "stock", "instrument", "security"],
    "shares": ["shares", "quantity", "qty", "units", "amount", "open_quantity", "net_quantity", "quantity_available"],
    "avg_cost": ["avg_cost", "average_cost", "cost_basis", "avg_price",
                 "average_price", "purchase_price", "cost_per_share", "buy_average"],
    "current_price": ["current_price", "market_price", "price", "last_price",
                      "current_value_per_share", "mark"],
    "description": ["description", "action", "activity", "type", "transaction", "details"]
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame | None:
    """Try to map brokerage-specific columns to standard names."""
    col_lower = {c: str(c).lower().strip().replace(" ", "_").replace(".", "") for c in df.columns}
    df = df.rename(columns=col_lower)

    # Custom handling for Zerodha P&L format
    if "open_quantity" in df.columns and "open_value" in df.columns:
        df["open_quantity"] = pd.to_numeric(df["open_quantity"], errors="coerce").fillna(0)
        # Keep non-zero positions (handle negative quantities for short/accounting entries)
        df = df[df["open_quantity"] != 0].copy()
        df["shares"] = df["open_quantity"].abs()
        
        df["open_value"] = pd.to_numeric(df["open_value"], errors="coerce").fillna(0).abs()
        df["avg_cost"] = df["open_value"] / df["shares"]


    mapping = {}
    for standard, aliases in COLUMN_ALIASES.items():
        if standard in df.columns:
            continue  # Already mapped via custom logic above
        for alias in aliases:
            if alias in df.columns:
                mapping[alias] = standard
                break

    if "ticker" not in df.columns and "ticker" not in mapping.values():
        return None

    df = df.rename(columns=mapping)
    
    # Flag to check if this is an activity log (has tickers/instruments but no shares)
    is_activity_log = "shares" not in df.columns

    # Keep only mapped + extra columns
    available = [c for c in ["ticker", "shares", "avg_cost", "current_price", "description"] if c in df.columns]
    if len(available) < 2:
        return None
        
    df = df[available].copy()
    
    if is_activity_log:
        df["shares"] = 1.0 # Default to 1 so the analyzer can still fetch prices and analyze the asset
        if "avg_cost" not in df.columns:
            df["avg_cost"] = 0.0
        # Drop duplicate transactions so we just get a unique list of assets traded
        df = df.drop_duplicates(subset=["ticker"]).copy()
    
    # Ensure numeric columns are forced to float to prevent missing data errors
    for col in ["shares", "avg_cost", "current_price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            
    # Final filter: remove rows with 0 shares (closed positions)
    if "shares" in df.columns:
        df = df[df["shares"] > 0]
        
    # Cleanup empty tickers which might be generated from summary rows
    df = df[df["ticker"].notna()]
    df = df[df["ticker"].astype(str).str.strip() != ""]
        
    if df.empty:
        return None
        
    return df


def _find_header_and_normalize(df: pd.DataFrame) -> pd.DataFrame | None:
    """Find the actual table header (skipping metadata rows at top) and normalize."""
    import streamlit as st
    st.write("DEBUG: Raw DataFrame Head:", df.head())
    
    target_keywords = set()
    for aliases in COLUMN_ALIASES.values():
        target_keywords.update(aliases)
        
    header_idx = -1
    max_matches = 0
    
    # Search the first 50 rows for the row with the most matching target columns
    for idx, row in df.head(50).iterrows():
        # Clean up cell text for comparison
        row_vals = [str(val).lower().strip().replace(" ", "_").replace(".", "") for val in row.values]
        matches = sum(1 for val in row_vals if val in target_keywords)
        
        if matches > max_matches:
            max_matches = matches
            header_idx = idx

    # If we found a row with at least 2 matching columns (e.g. Symbol and Quantity)
    if header_idx != -1 and max_matches >= 2:
        df.columns = [str(c).strip() for c in df.iloc[header_idx].values]
        df = df.iloc[header_idx + 1:].reset_index(drop=True)
    elif header_idx == -1:
        # Fallback if we didn't search with header=None or couldn't find matches
        pass

    return _normalize_columns(df)


def _parse_csv(uploaded_file) -> pd.DataFrame | None:
    """Parse uploaded CSV and normalize columns, skipping metadata at top."""
    try:
        content = uploaded_file.getvalue()
        with open("debug_raw_file.csv", "wb") as f:
            f.write(content)
        df = pd.read_csv(io.BytesIO(content), header=None)
        return _find_header_and_normalize(df)
    except Exception as e:
        logger.error(f"CSV parse error: {e}")
        return None


def _parse_excel(uploaded_file) -> pd.DataFrame | None:
    """Parse uploaded Excel and normalize columns, skipping metadata at top."""
    try:
        content = uploaded_file.getvalue()
        with open("debug_raw_file.xlsx", "wb") as f:
            f.write(content)
        df = pd.read_excel(io.BytesIO(content), header=None)
        return _find_header_and_normalize(df)
    except Exception as e:
        logger.error(f"Excel parse error: {e}")
        return None
def _parse_pdf(uploaded_file) -> pd.DataFrame | None:
    """Extract holdings from a PDF brokerage statement.
    
    Strategy:
    1. Try pdfplumber table extraction first (structured PDFs)
    2. Fall back to Gemini AI extraction from raw text (any format)
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed")
        return None

    # --- Stage 1: Try structured table extraction ---
    full_text = ""
    try:
        text_rows = []
        uploaded_file.seek(0)
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                        
                    # Clean up rows
                    cleaned_table = []
                    for row in table:
                        if row and any(row):
                            cleaned_table.append([str(c).strip() if c else "" for c in row])
                            
                    if len(cleaned_table) > 1:
                        # Test this specific table
                        df = pd.DataFrame(cleaned_table[1:], columns=cleaned_table[0])
                        result = _normalize_columns(df)
                        if result is not None and not result.empty:
                            return result  # We found a valid holdings table!
                            
        # If we loop through all tables and find nothing valid
        logger.info("PDF table extraction yielded no valid holdings. Falling back to AI.")
    except Exception as e:
        logger.warning(f"PDF table extraction failed, falling back to AI: {e}")
        # Try to get raw text anyway if it wasn't extracted
        if not full_text:
            try:
                uploaded_file.seek(0)
                with pdfplumber.open(uploaded_file) as pdf:
                    full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            except Exception:
                return None

    # --- Stage 2: AI-powered extraction from raw text ---
    if not full_text or len(full_text.strip()) < 20:
        return None

    try:
        from features.utils import call_gemini
        import re

        # Truncate to avoid token limits
        text_chunk = full_text[:8000]

        prompt = f"""You are a senior financial analyst and data extraction expert. Extract the final, current stock/ETF equity holdings from this brokerage statement text.

DOCUMENT TEXT:
---
{text_chunk}
---

Extract ALL current investment holdings you can find. 
CRITICAL RULES FOR EXTRACTION:
1. **Holdings Snapshots:** Look first for a "Positions", "Holdings", or "Asset Allocation" summary table showing current shares owned.
2. **Transaction Ledgers (Acorns/etc):** If the document ONLY lists "Securities Bought" and "Securities Sold" without a final summary table, you MUST calculate the net holdings yourself.
   - For each ticker, sum the shares Bought and subtract the shares Sold.
   - If the net shares are > 0.0001, include it as a current holding.
   - To estimate `avg_cost`, take the total $ Amount Bought divided by total Shares Bought.
3. **Valid Assets:** Include stocks, equity ETFs, and bond ETFs (like AGG, ISTB, BND). Do not include raw cash/MMFs.
4. **Data Formatting:**
   - ticker: The standard ticker symbol (e.g., AAPL, VOO, AGG, IXUS). Do not use full names, ONLY the 1-5 letter ticker.
   - shares: Number of shares currently held (as a plain number, no commas).
   - avg_cost: Average cost per share (as a plain number, no $ sign). If unknown, use 0.

Return ONLY a valid JSON array. If you find NO absolute current holdings (or if net shares = 0), return an empty array: []
Example format:
[
    {{"ticker": "VOO", "shares": 1.55, "avg_cost": 415.25}},
    {{"ticker": "AGG", "shares": 3.2, "avg_cost": 98.10}}
]

Return ONLY the JSON array, no markdown formatting or explanation."""

        raw = call_gemini(prompt, "You are a precise financial document parser. Extract data accurately.")

        # Parse JSON from response
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if json_match:
            holdings_list = json.loads(json_match.group(0))
            if holdings_list:
                df = pd.DataFrame(holdings_list)
                # Clean up columns
                for col in ["ticker", "shares", "avg_cost"]:
                    if col not in df.columns:
                        df[col] = 0 if col != "ticker" else "UNKNOWN"
                df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)
                df["avg_cost"] = pd.to_numeric(df["avg_cost"], errors="coerce").fillna(0)
                df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
                # Filter out invalid rows
                df = df[df["ticker"].str.len() > 0]
                df = df[df["ticker"] != "UNKNOWN"]
                df = df[df["shares"] > 0]
                if not df.empty:
                    logger.info(f"AI extracted {len(df)} holdings from PDF")
                    return df
    except Exception as e:
        logger.error(f"AI PDF extraction failed: {e}")

    return None


# ---------------------------------------------------------------------------
# Analysis logic
# ---------------------------------------------------------------------------
def _enrich_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    """Fetch current prices and compute P&L metrics."""
    from features.utils import fetch_stock_data

    if "shares" in holdings.columns:
        holdings["shares"] = pd.to_numeric(holdings["shares"], errors="coerce").fillna(0)
    if "avg_cost" in holdings.columns:
        holdings["avg_cost"] = pd.to_numeric(holdings["avg_cost"], errors="coerce").fillna(0)

    current_prices = []
    for _, row in holdings.iterrows():
        ticker = str(row.get("ticker", "")).upper().strip()
        if "current_price" in holdings.columns and pd.notna(row.get("current_price")):
            current_prices.append(float(row["current_price"]))
            continue
        try:
            data = fetch_stock_data(ticker, "INTRADAY")
            ts = data.get("data", {})
            sorted_times = sorted(ts.keys())
            if sorted_times:
                current_prices.append(float(ts[sorted_times[-1]]["4. close"]))
            else:
                current_prices.append(0.0)
        except Exception:
            current_prices.append(0.0)

    holdings["current_price"] = current_prices
    if "shares" in holdings.columns and "avg_cost" in holdings.columns:
        holdings["market_value"] = holdings["shares"] * holdings["current_price"]
        holdings["cost_basis_total"] = holdings["shares"] * holdings["avg_cost"]
        holdings["unrealized_pnl"] = holdings["market_value"] - holdings["cost_basis_total"]
        holdings["pnl_pct"] = ((holdings["unrealized_pnl"] / holdings["cost_basis_total"]) * 100).round(2)
        total_value = holdings["market_value"].sum()
        holdings["weight_pct"] = ((holdings["market_value"] / total_value) * 100).round(2) if total_value > 0 else 0
    else:
        holdings["market_value"] = 0
        holdings["weight_pct"] = 0
        holdings["unrealized_pnl"] = 0
        holdings["pnl_pct"] = 0

    # Assign base sectors
    holdings["sector"] = holdings["ticker"].apply(
        lambda t: SECTOR_MAP.get(str(t).upper(), "Other")
    )

    # Dynamically resolve "Other" sectors via AI
    unknown_tickers = holdings[holdings["sector"] == "Other"]["ticker"].unique().tolist()
    if unknown_tickers:
        try:
            from features.utils import call_gemini
            import json
            import re
            
            prompt = f"""Categorize these stock tickers into their standard GICS sectors (e.g., Technology, Financials, Energy, Consumer Staples, Healthcare, Utilities, Basic Materials, etc.). 
If they are international or Indian stocks, classify them correctly based on their real-world industry.
Return ONLY a valid JSON dictionary mapping the ticker to its sector string.
Example: {{"AAPL": "Technology", "COALINDIA": "Energy"}}
Tickers to classify: {unknown_tickers}"""
            
            response = call_gemini(prompt, "You are a financial data categorizer. Return only JSON.")
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                sector_updates = json.loads(json_match.group(0))
                holdings["sector"] = holdings.apply(
                    lambda row: sector_updates.get(row["ticker"], row["sector"]) if row["sector"] == "Other" else row["sector"],
                    axis=1
                )
        except Exception as e:
            logger.warning(f"Failed to dynamically fetch sectors: {e}")

    return holdings


def _generate_ai_analysis(holdings: pd.DataFrame) -> dict:
    """Run Gemini to generate portfolio health narrative + recommendations."""
    from features.utils import call_gemini

    summary = holdings.to_string(index=False)
    total_value = holdings["market_value"].sum()
    total_pnl = holdings.get("unrealized_pnl", pd.Series([0])).sum()
    over_concentrated = holdings[holdings["weight_pct"] > 20]["ticker"].tolist() if "weight_pct" in holdings.columns else []

    prompt = f"""You are a certified financial planner analyzing a personal portfolio.

Portfolio Summary:
{summary}

Total Portfolio Value: ${total_value:,.2f}
Total Unrealized P&L: ${total_pnl:,.2f}
Over-concentrated positions (>20% weight): {over_concentrated if over_concentrated else 'None'}

Provide:
1. **Portfolio Health Narrative** (2-3 paragraphs): Overall assessment, diversification quality, risk level
2. **Rebalancing Recommendations** (numbered list of 3-5 specific actions)
3. **Risk Flags** (any issues to address urgently)

Be specific with ticker names and percentages. Be actionable."""

    narrative = call_gemini(prompt, "You are a senior portfolio advisor at a wealth management firm.")
    return {"narrative": narrative, "over_concentrated": over_concentrated}


# ---------------------------------------------------------------------------
# Streamlit page renderer
# ---------------------------------------------------------------------------
def render_portfolio_analyzer():
    st.markdown("## 💼 Portfolio Document Analyzer")
    st.caption("Upload your brokerage CSV or PDF statement to get AI-driven portfolio insights, "
               "sector allocation, and personalized rebalancing recommendations.")

    uploaded = st.file_uploader(
        "Upload Brokerage Statement",
        type=["csv", "pdf", "xlsx", "xls"],
        help="Supported: Robinhood, Schwab, Fidelity CSV/Excel exports, or any PDF with holdings tables.",
        key="pa_upload",
    )

    if uploaded is not None:
        # Parse based on file type
        if uploaded.name.lower().endswith(".csv"):
            holdings = _parse_csv(uploaded)
        elif uploaded.name.lower().endswith((".xlsx", ".xls")):
            holdings = _parse_excel(uploaded)
        else:
            holdings = _parse_pdf(uploaded)

        if holdings is None or holdings.empty:
            st.warning("⚠️ Could not parse holdings from this file. "
                       "Please ensure your CSV has columns like: ticker/symbol, shares/quantity, avg_cost/cost_basis.")
            st.info("**Supported column names:** ticker, symbol, shares, quantity, avg_cost, cost_basis, current_price, instrument, description")
            st.write("DEBUG: I tried to parse it but `holdings` returned empty. Is Streamlit running the latest code?")
            return

        st.success(f"✅ Parsed {len(holdings)} holdings from **{uploaded.name}**")
        st.write("DEBUG: Successfully parsed holdings DataFrame:", holdings)

        with st.status("📊 Analyzing portfolio...", expanded=True) as status:
            status.write("💰 Fetching current prices...")
            holdings = _enrich_holdings(holdings)
            status.write("🤖 Running AI analysis...")
            ai_result = _generate_ai_analysis(holdings)
            status.update(label="✅ Analysis Complete!", state="complete", expanded=False)

        st.session_state["pa_holdings"] = holdings
        st.session_state["pa_ai"] = ai_result

    # Display results
    holdings = st.session_state.get("pa_holdings")
    ai_result = st.session_state.get("pa_ai")

    if holdings is not None and not holdings.empty:
        st.markdown("### 📋 Holdings Overview")

        # Color-coded holdings table
        def _color_pnl(val):
            if isinstance(val, (int, float)):
                color = "#10b981" if val >= 0 else "#ef4444"
                return f"color: {color}; font-weight: 600"
            return ""

        display_cols = [c for c in ["ticker", "shares", "avg_cost", "current_price",
                                     "market_value", "unrealized_pnl", "pnl_pct",
                                     "weight_pct", "sector"] if c in holdings.columns]
        styled = holdings[display_cols].style.applymap(
            _color_pnl, subset=[c for c in ["unrealized_pnl", "pnl_pct"] if c in display_cols]
        ).format({
            c: "${:,.2f}" for c in ["avg_cost", "current_price", "market_value",
                                     "unrealized_pnl"] if c in display_cols
        } | {c: "{:.1f}%" for c in ["pnl_pct", "weight_pct"] if c in display_cols})

        st.dataframe(styled, use_container_width=True, hide_index=True)

        # Sector allocation pie chart
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 🥧 Sector Allocation")
            if "sector" in holdings.columns and "market_value" in holdings.columns:
                import plotly.express as px
                sector_data = holdings.groupby("sector")["market_value"].sum().reset_index()
                fig = px.pie(sector_data, values="market_value", names="sector",
                             template="plotly_dark",
                             color_discrete_sequence=px.colors.qualitative.Set2)
                fig.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.markdown("### 📊 Position Weights")
            if "weight_pct" in holdings.columns:
                import plotly.express as px
                fig = px.bar(holdings.sort_values("weight_pct", ascending=True),
                             x="weight_pct", y="ticker", orientation="h",
                             template="plotly_dark",
                             labels={"weight_pct": "Weight (%)", "ticker": ""},
                             color="weight_pct",
                             color_continuous_scale="Viridis")
                # Add 20% concentration line
                fig.add_vline(x=20, line_dash="dash", line_color="#ef4444",
                              annotation_text="20% threshold", annotation_position="top")
                st.plotly_chart(fig, use_container_width=True)

        # AI narrative
        if ai_result:
            st.markdown(f"""
            <div class="report-section" style="border-left: 3px solid #8b5cf6; margin-top: 2rem;">
                <h4 style="color: #a78bfa;">🤖 AI Portfolio Health Assessment</h4>
                <div class="alert-body" style="font-size: 1.05rem;">
                    {ai_result.get("narrative", "")}
                </div>
            </div>
            """, unsafe_allow_html=True)

            if ai_result.get("over_concentrated"):
                st.markdown(f"""
                <div class="alert-card alert-market" style="margin-top: 1rem;">
                    <div class="alert-header">
                        <span>⚠️ Concentration Alert</span>
                    </div>
                    <div class="alert-body">
                        **Over-concentrated positions detected:** {', '.join(ai_result['over_concentrated'])} (> 20% portfolio weight)
                    </div>
                </div>
                """, unsafe_allow_html=True)

        # PDF export
        st.markdown("---")
        if st.button("📥 Download Analysis as PDF", key="pa_pdf"):
            from features.utils import export_to_pdf
            sections = [
                {"title": "Portfolio Summary", "body": holdings.to_string(index=False)},
                {"title": "AI Health Assessment", "body": ai_result.get("narrative", "") if ai_result else ""},
            ]
            pdf_bytes = export_to_pdf(sections, "portfolio_analysis.pdf")
            st.download_button(
                label="⬇️ Download PDF",
                data=pdf_bytes,
                file_name="Portfolio_Analysis.pdf",
                mime="application/pdf",
                key="pa_pdf_dl",
            )
