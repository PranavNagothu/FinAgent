import os
import sys
import pandas as pd
import ast
from dotenv import load_dotenv
from typing import TypedDict, List, Dict, Any

from langgraph.graph import StateGraph, END

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.tool_calling_agents import WebResearchAgent, MarketDataAgent, InternalPortfolioAgent
from agents.data_analysis_agent import DataAnalysisAgent
from features.utils import call_gemini

# --- Configuration ---
load_dotenv()

# --- Initialize workers (Stateless) ---
web_agent = WebResearchAgent()
market_agent = MarketDataAgent()
portfolio_agent = InternalPortfolioAgent()

# --- Define the Enhanced State ---
class AgentState(TypedDict):
    task: str
    symbol: str
    web_research_results: str
    market_data_results: str
    portfolio_data_results: str
    scan_intent: str # "DOWNWARD", "UPWARD", "ALL", or None
    # --- NEW FIELDS FOR ANALYSIS ---
    analysis_dataframe: pd.DataFrame
    analysis_results: Dict[str, Any]
    final_report: str
    # Debug fields
    debug_market_data_raw: Any
    debug_dataframe_head: Any
    debug_analysis_results_full: Any

def get_orchestrator(llm_provider="gemini", api_key=None):
    """
    Factory function to create the orchestrator graph with a specific LLM.
    """
    
    # 2. Initialize Data Analyzer (Now uses global call_gemini fallback)
    data_analyzer = DataAnalysisAgent()

    # 3. Define Nodes

    # 3. Define Nodes (Closure captures 'llm' and 'data_analyzer')

    def extract_symbol_step(state: AgentState):
        print("--- 🔬 Symbol & Time Range Extraction ---")
        prompt = f"""
        Analyze the user's request: "{state['task']}"
        
        Extract TWO things:
        1. Stock symbol or scan intent
        2. Time range (if mentioned)
        
        RULES:
        - If request mentions a SPECIFIC company → Extract symbol
        - If request mentions time period → Extract time range
        - ONLY set scan_intent for "top gainers", "losers", "scan market"
        
        Response Format: JSON ONLY.
        {{
            "symbol": "TICKER" or null,
            "scan_intent": "DOWNWARD" | "UPWARD" | "ALL" or null,
            "time_range": "INTRADAY" | "1D" | "3D" | "1W" | "1M" | "3M" | "1Y" or null
        }}
        
        Time Range Examples:
        - "today", "now", "current", "recent" → "INTRADAY"
        - "yesterday", "1 day back" → "1D"
        - "3 days back", "last 3 days" → "3D"
        - "last week", "1 week", "7 days" → "1W"
        - "last month", "1 month", "30 days" → "1M"
        - "3 months", "quarter" → "3M"
        - "1 year", "12 months" → "1Y"
        
        Full Examples:
        - "Analyze Tesla" → {{"symbol": "TSLA", "scan_intent": null, "time_range": null}}
        - "3 days back stocks of Tesla" → {{"symbol": "TSLA", "scan_intent": null, "time_range": "3D"}}
        - "Last week AAPL performance" → {{"symbol": "AAPL", "scan_intent": null, "time_range": "1W"}}
        - "1 month trend for NVDA" → {{"symbol": "NVDA", "scan_intent": null, "time_range": "1M"}}
        - "Recent analysis of Tesla" → {{"symbol": "TSLA", "scan_intent": null, "time_range": "INTRADAY"}}
        - "Show me top gainers" → {{"symbol": null, "scan_intent": "UPWARD", "time_range": null}}
        
        CRITICAL: Default to null for time_range if not explicitly mentioned!
        """
        raw_response = call_gemini(prompt).strip()
        
        symbol = None
        scan_intent = None
        time_range = None
        
        try:
            import json
            import re
            # Find JSON in response
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                symbol = data.get("symbol")
                scan_intent = data.get("scan_intent")
                time_range = data.get("time_range")
            else:
                print(f"   WARNING: No JSON found in extraction response: {raw_response}")
                # Fallback to simple cleaning
                clean_resp = raw_response.strip().upper()
                if "SCAN" in clean_resp or "GAINERS" in clean_resp or "LOSERS" in clean_resp:
                    scan_intent = "ALL"
                elif len(clean_resp) <= 5 and clean_resp.isalpha():
                    symbol = clean_resp
        except Exception as e:
            print(f"   Error parsing symbol extraction: {e}")
        
        if symbol: symbol = symbol.upper().replace("$", "")
        
        # Default time_range to 1M if null (INTRADAY is premium-only, 1M uses free DAILY endpoint)
        if time_range is None:
            time_range = "1M"
        
        print(f"   Raw LLM Response: {raw_response}")
        print(f"   Extracted Symbol: {symbol}")
        print(f"   Scan Intent: {scan_intent}")
        print(f"   Time Range: {time_range}")
        
        return {"symbol": symbol, "scan_intent": scan_intent, "time_range": time_range}

    def web_research_step(state: AgentState):
        print("--- 🔎 Web Research ---")
        if state.get("scan_intent"):
            return {"web_research_results": "Market Scan initiated. Web research skipped for individual stock."}
        results = web_agent.research(queries=[state['task']])
        return {"web_research_results": results}

    def market_data_step(state: AgentState):
        print("--- 📊 Market Data Retrieval ---")
        
        # Handle scan intent
        if state.get("scan_intent"):
            print(f"   Scan Intent Detected: {state['scan_intent']}")
            
            # Load watchlist
            import json
            watchlist_path = "watchlist.json"
            if not os.path.exists(watchlist_path):
                return {"market_data_results": {"error": "Watchlist not found. Please add symbols to your watchlist."}}
            
            with open(watchlist_path, 'r') as f:
                watchlist = json.load(f)
            
            scan_results = []
            scan_intent = state['scan_intent']
            
            for sym in watchlist:
                try:
                    # Use GLOBAL_QUOTE for real-time price (free tier)
                    quote = market_agent.get_global_quote(symbol=sym)
                    quote_data = quote.get("data", {})
                    price = float(quote_data.get("price", 0))
                    change_pct_str = quote_data.get("change_percent", "0%").replace("%", "")
                    pct_change = float(change_pct_str) if change_pct_str else 0
                    
                    if scan_intent == "UPWARD" and pct_change > 0:
                        scan_results.append({"symbol": sym, "price": price, "change": pct_change})
                    elif scan_intent == "DOWNWARD" and pct_change < 0:
                        scan_results.append({"symbol": sym, "price": price, "change": pct_change})
                    elif scan_intent == "ALL":
                        scan_results.append({"symbol": sym, "price": price, "change": pct_change})
                except Exception as e:
                    print(f"   ⚠️ Error scanning {sym}: {e}")
            
            # Sort by change
            scan_results.sort(key=lambda x: x['change'], reverse=True)
            return {"market_data_results": {"scan_results": scan_results}}
        
        # Single symbol analysis
        if not state.get("symbol"):
            return {"market_data_results": "Skipped."}
        
        symbol = state["symbol"]
        combined_data = {"symbol": symbol}
        
        # 1. Get REAL current price via GLOBAL_QUOTE (free tier)
        try:
            import time
            quote = market_agent.get_global_quote(symbol=symbol)
            combined_data["quote"] = quote.get("data", {})
            combined_data["quote_source"] = quote.get("source", "Unknown")
            print(f"   ✅ Real-time quote: ${combined_data['quote'].get('price', 'N/A')}")
            time.sleep(1)  # Respect rate limit (1 req/sec)
        except Exception as e:
            print(f"   ⚠️ Quote fetch failed: {e}")
            combined_data["quote"] = {}
        
        # 2. Get REAL fundamentals via OVERVIEW (free tier)
        try:
            overview = market_agent.get_company_overview(symbol=symbol)
            combined_data["overview"] = overview.get("data", {})
            combined_data["overview_source"] = overview.get("source", "Unknown")
            print(f"   ✅ Company: {combined_data['overview'].get('Name', symbol)}, P/E: {combined_data['overview'].get('PERatio', 'N/A')}")
            import time
            time.sleep(1)  # Respect rate limit
        except Exception as e:
            print(f"   ⚠️ Overview fetch failed: {e}")
            combined_data["overview"] = {}
        
        # 3. Get historical data via DAILY (free tier) for trend analysis
        try:
            time_range = state.get("time_range", "1M")
            # Map INTRADAY to 1M for free tier compatibility
            if time_range == "INTRADAY":
                time_range = "1M"
            print(f"   Fetching DAILY data for {symbol} (time_range={time_range})")
            results = market_agent.get_market_data(symbol=symbol, time_range=time_range)
            combined_data["daily_data"] = results
            source = results.get("meta_data", {}).get("Source", "Unknown")
            data_points = len(results.get("data", {}))
            print(f"   ✅ Daily data: {data_points} data points (Source: {source})")
        except Exception as e:
            print(f"   ⚠️ Daily data fetch failed: {e}")
            combined_data["daily_data"] = {}
        
        return {"market_data_results": combined_data, "debug_market_data_raw": combined_data}

    def portfolio_data_step(state: AgentState):
        print("--- 💼 Internal Portfolio Data ---")
        if state.get("scan_intent"):
             return {"portfolio_data_results": "Market Scan initiated. Portfolio context skipped."}
             
        if not state.get("symbol"):
            return {"portfolio_data_results": "Skipped: No symbol provided."}
        
        try:
            results = portfolio_agent.query_portfolio(question=f"What is the current exposure to {state['symbol']}?")
            return {"portfolio_data_results": results}
        except Exception as e:
            print(f"   ⚠️ Portfolio data fetch failed (Private MCP may be down): {e}")
            return {"portfolio_data_results": f"Portfolio data unavailable (service error). Analysis continues without internal portfolio context."}

    def transform_data_step(state: AgentState):
        print("--- 🔀 Transforming Data for Analysis ---")
        if state.get("scan_intent"):
            return {"analysis_dataframe": pd.DataFrame()} # Skip transformation for scan
            
        market_data = state.get("market_data_results")
        
        if not isinstance(market_data, dict):
            print("   Skipping transformation: No valid market data received.")
            return {"analysis_dataframe": pd.DataFrame()}
        
        # Extract daily_data from the new combined format
        daily_data = market_data.get('daily_data', {})
        time_series_data = daily_data.get('data', {}) if isinstance(daily_data, dict) else {}
        
        if not time_series_data:
            print("   Skipping transformation: No daily time series data available.")
            return {"analysis_dataframe": pd.DataFrame()}
            
        try:
            df = pd.DataFrame.from_dict(time_series_data, orient='index')
            df.index = pd.to_datetime(df.index)
            df.index.name = "timestamp"
            df.rename(columns={
                '1. open': 'open', '2. high': 'high', '3. low': 'low',
                '4. close': 'close', '5. volume': 'volume'
            }, inplace=True)
            df = df.apply(pd.to_numeric).sort_index()
            
            print(f"   Successfully created DataFrame with shape {df.shape}")
            return {"analysis_dataframe": df, "debug_dataframe_head": df.head().to_dict()}
        except Exception as e:
            print(f"   CRITICAL ERROR during data transformation: {e}")
            return {"analysis_dataframe": pd.DataFrame()}

    def run_data_analysis_step(state: AgentState):
        print("--- 🔬 Running Deep-Dive Data Analysis ---")
        if state.get("scan_intent"):
            return {"analysis_results": {}} # Skip analysis for scan
            
        df = state.get("analysis_dataframe")
        if df is not None and not df.empty:
            analysis_results = data_analyzer.run_analysis(df)
            return {"analysis_results": analysis_results, "debug_analysis_results_full": analysis_results}
        else:
            print("   Skipping analysis: No data to analyze.")
            return {"analysis_results": {}}

    def synthesize_report_step(state: AgentState):
        print("--- 📝 Synthesizing Final Report ---")
        
        # Helper to truncate text to avoid Rate Limits
        def truncate(text, max_chars=3000):
            s = str(text)
            if len(s) > max_chars:
                return s[:max_chars] + "... (truncated)"
            return s

        # Check for Scan Results
        market_data_res = state.get("market_data_results", {})
        if isinstance(market_data_res, dict) and "scan_results" in market_data_res:
            scan_results = market_data_res["scan_results"]
            # Truncate scan results if necessary (though usually small)
            scan_results_str = truncate(scan_results, 4000)
            
            report_prompt = f"""
            You are a senior financial analyst. The user requested a market scan: "{state['task']}".
            
            Scan Results (from Watchlist):
            {scan_results_str}
            
            Generate a "Market Scan Report".
            1. Summary: Briefly explain the criteria and the overall market status based on these results.
            2. Results Table: Create a markdown table with columns: Symbol | Price | % Change.
            3. Conclusion: Highlight the most significant movers.
            """
            final_report = call_gemini(report_prompt)
            return {"final_report": final_report}

        analysis_insights = state.get("analysis_results", {}).get("insights", "Not available.")
        
        # Truncate inputs for the main report
        web_data = truncate(state.get('web_research_results', 'Not available.'), 3000)
        portfolio_data = truncate(state.get('portfolio_data_results', 'Not available.'), 2000)
        
        # Extract rich data from combined market results
        market_data_raw = state.get("market_data_results", {})
        data_sources = []
        
        # Build rich market context from the new format
        quote_data = {}
        overview_data = {}
        if isinstance(market_data_raw, dict):
            quote_data = market_data_raw.get("quote", {})
            overview_data = market_data_raw.get("overview", {})
            
            if market_data_raw.get("quote_source"):
                data_sources.append(f"Price: {market_data_raw['quote_source']}")
            if market_data_raw.get("overview_source"):
                data_sources.append(f"Fundamentals: {market_data_raw['overview_source']}")
            daily = market_data_raw.get("daily_data", {})
            if isinstance(daily, dict):
                src = daily.get("meta_data", {}).get("Source", "")
                if src:
                    data_sources.append(f"Historical: {src}")
        
        data_source = " | ".join(data_sources) if data_sources else "Unknown"
        
        # Build a structured market data section
        market_context = f"""
--- REAL-TIME PRICE (GLOBAL_QUOTE) ---
Current Price: ${quote_data.get('price', 'N/A')}
Change: {quote_data.get('change', 'N/A')} ({quote_data.get('change_percent', 'N/A')})
Open: ${quote_data.get('open', 'N/A')}
High: ${quote_data.get('high', 'N/A')}
Low: ${quote_data.get('low', 'N/A')}
Volume: {quote_data.get('volume', 'N/A')}
Previous Close: ${quote_data.get('previous_close', 'N/A')}

--- COMPANY FUNDAMENTALS (OVERVIEW) ---
Company: {overview_data.get('Name', 'N/A')}
Sector: {overview_data.get('Sector', 'N/A')} | Industry: {overview_data.get('Industry', 'N/A')}
Market Cap: ${overview_data.get('MarketCapitalization', 'N/A')}
Revenue (TTM): ${overview_data.get('RevenueTTM', 'N/A')}
EPS: ${overview_data.get('EPS', 'N/A')}
P/E Ratio: {overview_data.get('PERatio', 'N/A')}
Forward P/E: {overview_data.get('ForwardPE', 'N/A')}
Profit Margin: {overview_data.get('ProfitMargin', 'N/A')}
Operating Margin: {overview_data.get('OperatingMarginTTM', 'N/A')}
Return on Equity: {overview_data.get('ReturnOnEquityTTM', 'N/A')}
Beta: {overview_data.get('Beta', 'N/A')}
52-Week High: ${overview_data.get('52WeekHigh', 'N/A')}
52-Week Low: ${overview_data.get('52WeekLow', 'N/A')}
Dividend Yield: {overview_data.get('DividendYield', 'N/A')}
Analyst Target: ${overview_data.get('AnalystTargetPrice', 'N/A')}
Quarterly Earnings Growth: {overview_data.get('QuarterlyEarningsGrowthYOY', 'N/A')}
Quarterly Revenue Growth: {overview_data.get('QuarterlyRevenueGrowthYOY', 'N/A')}
"""
        
        report_prompt = f"""
        You are a senior financial analyst writing a comprehensive "Alpha Report".
        Your task is to synthesize all available information into a structured, cited report.
        USE THE REAL FINANCIAL NUMBERS PROVIDED — do NOT say data is unavailable if numbers are given.

        Original User Task: {state['task']}
        Target Symbol: {state.get('symbol', 'Unknown')}
        Data Source: {data_source}
        ---
        Available Information:
        - Web Intelligence: {web_data}
        - Market Data & Fundamentals: {market_context}
        - Deep-Dive Data Analysis Insights: {analysis_insights}
        - Internal Portfolio Context: {portfolio_data}
        ---

        CRITICAL INSTRUCTIONS:
        1. First, evaluate the "Available Information".
           - If the Target Symbol is 'Unknown' OR if the Web Intelligence and Market Data contain no meaningful information:
             You MUST respond with: "I am not sure about this company as I could not find sufficient data."
             Do NOT generate the rest of the report.

        2. Otherwise, generate the "Alpha Report" with the following sections:
        
        > [!NOTE]
        > **Data Source**: {data_source}

        ## 1. Executive Summary
        A 2-3 sentence overview of the key findings and current situation.

        ## 2. Internal Context
        Detail the firm's current exposure:
        - IF the firm has shares > 0: Present as a markdown table:
          | Symbol | Shares | Avg Cost | Current Value |
          |--------|--------|----------|---------------|
        - IF the firm has 0 shares: State: "The firm has no current exposure to {state.get('symbol')}."

        ## 3. Market Data
        ALWAYS present as a markdown table:
        | Metric | Value | Implication |
        |--------|-------|-------------|
        | Current Price | $XXX.XX | +/-X.X% vs. open |
        | 5-Day Trend | Upward/Downward/Flat | Brief note |
        | Volume | X.XXM | Above/Below average |

        ## 4. Real-Time Intelligence
        ### News
        - **[Headline]** - [Brief summary] `[Source: URL]`
        - **[Headline]** - [Brief summary] `[Source: URL]`

        ### Filings (if any)
        - **[Filing Type]** - [Brief description] `[Source: URL]`

        ## 5. Sentiment Analysis
        **Overall Sentiment:** Bullish / Bearish / Neutral

        **Evidence:**
        - [Specific fact from news/data supporting this sentiment]
        - [Another supporting fact]

        ## 6. Synthesis & Recommendations
        Combine all information to provide actionable insights. Focus on:
        - Key risks and opportunities
        - Recommended actions (if any)
        - Items to monitor

        FORMATTING RULES:
        - Use markdown headers (##, ###)
        - Include URLs in backticks: `[Source: example.com]`
        - Use tables for structured data
        - Be concise but comprehensive
        """
        final_report = call_gemini(report_prompt)
        return {"final_report": final_report}

    # 4. Build the Graph
    workflow = StateGraph(AgentState)

    workflow.add_node("extract_symbol", extract_symbol_step)
    workflow.add_node("web_researcher", web_research_step)
    workflow.add_node("market_data_analyst", market_data_step)
    workflow.add_node("portfolio_data_fetcher", portfolio_data_step)
    workflow.add_node("transform_data", transform_data_step)
    workflow.add_node("data_analyzer", run_data_analysis_step)
    workflow.add_node("report_synthesizer", synthesize_report_step)

    workflow.set_entry_point("extract_symbol")
    workflow.add_edge("extract_symbol", "web_researcher")
    workflow.add_edge("web_researcher", "market_data_analyst")
    workflow.add_edge("market_data_analyst", "portfolio_data_fetcher")
    workflow.add_edge("portfolio_data_fetcher", "transform_data")
    workflow.add_edge("transform_data", "data_analyzer")
    workflow.add_edge("data_analyzer", "report_synthesizer")
    workflow.add_edge("report_synthesizer", END)

    return workflow.compile()