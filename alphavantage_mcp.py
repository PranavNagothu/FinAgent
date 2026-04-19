# alphavantage_mcp.py (Corrected for Free Tier)
from fastapi import FastAPI, HTTPException
import uvicorn
import os
from dotenv import load_dotenv
from alpha_vantage.timeseries import TimeSeries
import logging

# --- Configuration ---
load_dotenv()

# --- Logging Setup (MUST be before we use logger) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AlphaVantage_MCP_Server")

# --- Get API Key ---
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

# Fallback: Try to read from Streamlit secrets file (for cloud deployment)
if not ALPHA_VANTAGE_API_KEY:
    try:
        import toml
        secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            secrets = toml.load(secrets_path)
            ALPHA_VANTAGE_API_KEY = secrets.get("ALPHA_VANTAGE_API_KEY")
            logger.info("Loaded ALPHA_VANTAGE_API_KEY from .streamlit/secrets.toml")
    except Exception as e:
        logger.warning(f"Could not load from secrets.toml: {e}")

if not ALPHA_VANTAGE_API_KEY:
    logger.warning("ALPHA_VANTAGE_API_KEY not found in environment. Market data features will fail.")
else:
    logger.info(f"ALPHA_VANTAGE_API_KEY found: {ALPHA_VANTAGE_API_KEY[:4]}...")

# --- FastAPI App & Alpha Vantage Client ---
app = FastAPI(title="Aegis Alpha Vantage MCP Server")
ts = TimeSeries(key=ALPHA_VANTAGE_API_KEY, output_format='json') if ALPHA_VANTAGE_API_KEY else None

@app.post("/market_data")
async def get_market_data(payload: dict):
    """
    Fetches market data using the Alpha Vantage API.
    Supports both intraday and daily data based on time_range.
    Expects a payload like:
    {
        "symbol": "NVDA",
        "time_range": "INTRADAY" | "1D" | "3D" | "1W" | "1M" | "3M" | "1Y"
    }
    """
    symbol = payload.get("symbol")
    time_range = payload.get("time_range", "INTRADAY")

    if not symbol:
        logger.error("Validation Error: 'symbol' is required.")
        raise HTTPException(status_code=400, detail="'symbol' is required.")

    logger.info(f"Received market data request for symbol: {symbol}, time_range: {time_range}")

    try:
        if not ts:
            raise ValueError("No Alpha Vantage API key configured — using mock data.")
        # Route to appropriate API based on time range
        if time_range == "INTRADAY":
            # Intraday data (last 4-6 hours, 5-min intervals)
            data, meta_data = ts.get_intraday(symbol=symbol, interval="5min", outputsize='compact')
            logger.info(f"Successfully retrieved intraday data for {symbol}")
            meta_data["Source"] = "Real API (Alpha Vantage)"
        else:
            # Daily data for historical ranges
            data, meta_data = ts.get_daily(symbol=symbol, outputsize='full')
            logger.info(f"Successfully retrieved daily data for {symbol}")
            
            # Filter data based on time range
            data = filter_data_by_time_range(data, time_range)
            logger.info(f"Filtered to {len(data)} data points for time_range={time_range}")
            meta_data["Source"] = "Real API (Alpha Vantage)"
        
        return {"status": "success", "data": data, "meta_data": meta_data}

    except Exception as e:
        logger.error(f"Alpha Vantage market data error for {symbol}: {e}")
        raise HTTPException(status_code=502, detail=f"Alpha Vantage API error: {str(e)}")



def filter_data_by_time_range(data: dict, time_range: str) -> dict:
    """Filter daily data to the specified time range."""
    from datetime import datetime, timedelta
    
    # Map time ranges to days
    range_map = {
        "1D": 1,
        "3D": 3,
        "1W": 7,
        "1M": 30,
        "3M": 90,
        "1Y": 365
    }
    
    days = range_map.get(time_range, 30)
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Filter data
    filtered = {}
    for timestamp_str, values in data.items():
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d")
            if timestamp >= cutoff_date:
                filtered[timestamp_str] = values
        except:
            # If parsing fails, include the data point
            filtered[timestamp_str] = values
    
    return filtered
        

@app.post("/company_overview")
async def get_company_overview(payload: dict):
    """
    Fetches company fundamentals from Alpha Vantage OVERVIEW endpoint.
    Returns: Revenue, EPS, P/E, Market Cap, Margins, Dividend Yield, etc.
    Expects: {"symbol": "AAPL"}
    """
    import requests as req

    symbol = payload.get("symbol")
    if not symbol:
        raise HTTPException(status_code=400, detail="'symbol' is required.")

    logger.info(f"Fetching company overview for {symbol}")

    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "OVERVIEW",
            "symbol": symbol,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }
        resp = req.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Check for error/empty response
        if "Symbol" not in data:
            raise ValueError(f"No overview data returned: {data.get('Note', data.get('Information', 'Unknown error'))}")

        logger.info(f"Successfully retrieved company overview for {symbol}")
        return {
            "status": "success",
            "source": "Alpha Vantage OVERVIEW",
            "data": {
                "Name": data.get("Name", symbol),
                "Symbol": data.get("Symbol", symbol),
                "Description": data.get("Description", ""),
                "Sector": data.get("Sector", ""),
                "Industry": data.get("Industry", ""),
                "MarketCapitalization": data.get("MarketCapitalization", "N/A"),
                "PERatio": data.get("PERatio", "N/A"),
                "EPS": data.get("EPS", "N/A"),
                "RevenuePerShareTTM": data.get("RevenuePerShareTTM", "N/A"),
                "RevenueTTM": data.get("RevenueTTM", "N/A"),
                "GrossProfitTTM": data.get("GrossProfitTTM", "N/A"),
                "ProfitMargin": data.get("ProfitMargin", "N/A"),
                "OperatingMarginTTM": data.get("OperatingMarginTTM", "N/A"),
                "ReturnOnEquityTTM": data.get("ReturnOnEquityTTM", "N/A"),
                "DividendPerShare": data.get("DividendPerShare", "N/A"),
                "DividendYield": data.get("DividendYield", "N/A"),
                "Beta": data.get("Beta", "N/A"),
                "52WeekHigh": data.get("52WeekHigh", "N/A"),
                "52WeekLow": data.get("52WeekLow", "N/A"),
                "50DayMovingAverage": data.get("50DayMovingAverage", "N/A"),
                "200DayMovingAverage": data.get("200DayMovingAverage", "N/A"),
                "SharesOutstanding": data.get("SharesOutstanding", "N/A"),
                "BookValue": data.get("BookValue", "N/A"),
                "PriceToBookRatio": data.get("PriceToBookRatio", "N/A"),
                "TrailingPE": data.get("TrailingPE", "N/A"),
                "ForwardPE": data.get("ForwardPE", "N/A"),
                "AnalystTargetPrice": data.get("AnalystTargetPrice", "N/A"),
                "AnalystRatingBuy": data.get("AnalystRatingBuy", "N/A"),
                "AnalystRatingHold": data.get("AnalystRatingHold", "N/A"),
                "AnalystRatingSell": data.get("AnalystRatingSell", "N/A"),
                "QuarterlyEarningsGrowthYOY": data.get("QuarterlyEarningsGrowthYOY", "N/A"),
                "QuarterlyRevenueGrowthYOY": data.get("QuarterlyRevenueGrowthYOY", "N/A"),
            }
        }

    except Exception as e:
        logger.error(f"Company overview error for {symbol}: {e}")
        raise HTTPException(status_code=502, detail=f"Alpha Vantage overview API error: {str(e)}")



@app.post("/global_quote")
async def get_global_quote(payload: dict):
    """
    Fetches real-time quote from Alpha Vantage GLOBAL_QUOTE endpoint.
    Returns: latest price, change, change%, volume, etc.
    Expects: {"symbol": "AAPL"}
    """
    import requests as req

    symbol = payload.get("symbol")
    if not symbol:
        raise HTTPException(status_code=400, detail="'symbol' is required.")

    logger.info(f"Fetching global quote for {symbol}")

    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }
        resp = req.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        quote = data.get("Global Quote", {})
        if not quote:
            raise ValueError(f"No quote data returned: {data.get('Note', 'Unknown error')}")

        logger.info(f"Successfully retrieved global quote for {symbol}")
        return {
            "status": "success",
            "source": "Alpha Vantage GLOBAL_QUOTE",
            "data": {
                "symbol": quote.get("01. symbol", symbol),
                "price": quote.get("05. price", "0"),
                "open": quote.get("02. open", "0"),
                "high": quote.get("03. high", "0"),
                "low": quote.get("04. low", "0"),
                "volume": quote.get("06. volume", "0"),
                "previous_close": quote.get("08. previous close", "0"),
                "change": quote.get("09. change", "0"),
                "change_percent": quote.get("10. change percent", "0%"),
            }
        }

    except Exception as e:
        logger.error(f"Global quote error for {symbol}: {e}")
        raise HTTPException(status_code=502, detail=f"Alpha Vantage quote API error: {str(e)}")



@app.get("/")
def read_root():
    return {"message": "Aegis Alpha Vantage MCP Server is operational."}

# --- Main Execution ---
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)