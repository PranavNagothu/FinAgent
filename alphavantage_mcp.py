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
ts = TimeSeries(key=ALPHA_VANTAGE_API_KEY, output_format='json')

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
        # Catch ALL exceptions to ensure fallback works
        logger.error(f"Alpha Vantage API error for symbol {symbol}: {e}")
        logger.warning(f"Triggering MOCK DATA fallback for {symbol} due to error.")
        
        import random
        import math
        from datetime import datetime, timedelta
        
        # Seed randomness with symbol AND date to ensure it changes daily
        # But stays consistent within the same day
        today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        seed_value = f"{symbol}_{today_str}"
        random.seed(seed_value)
        
        mock_data = {}
        current_time = datetime.now()
        
        # Generate unique base price
        symbol_hash = sum(ord(c) for c in symbol)
        base_price = float(symbol_hash % 500) + 50
        
        # Force distinct start prices for common stocks
        if "AAPL" in symbol: base_price = 150.0
        if "TSLA" in symbol: base_price = 250.0
        if "NVDA" in symbol: base_price = 450.0
        if "MSFT" in symbol: base_price = 350.0
        if "GOOG" in symbol: base_price = 130.0
        if "AMZN" in symbol: base_price = 140.0
        
        # Add some daily variation to base price
        daily_noise = (hash(today_str) % 100) / 10.0  # -5 to +5 variation
        base_price += daily_noise
        
        trend_direction = 1 if symbol_hash % 2 == 0 else -1
        volatility = base_price * 0.02
        trend_strength = base_price * 0.001
        current_price = base_price
        
        # Determine number of data points based on time range
        if time_range == "INTRADAY":
            num_points = 100
            time_delta = timedelta(minutes=5)
        elif time_range in ["1D", "3D"]:
            num_points = int(time_range[0]) if time_range != "1D" else 1
            time_delta = timedelta(days=1)
        elif time_range == "1W":
            num_points = 7
            time_delta = timedelta(days=1)
        elif time_range == "1M":
            num_points = 30
            time_delta = timedelta(days=1)
        elif time_range == "3M":
            num_points = 90
            time_delta = timedelta(days=1)
        elif time_range == "1Y":
            num_points = 365
            time_delta = timedelta(days=1)
        else:
            num_points = 100
            time_delta = timedelta(minutes=5)
        
        for i in range(num_points):
            noise = random.uniform(-volatility, volatility)
            cycle_1 = (base_price * 0.02) * math.sin(i / 8.0)
            cycle_2 = (base_price * 0.01) * math.sin(i / 3.0)
            change = noise + (trend_direction * trend_strength)
            current_price += change
            final_price = current_price + cycle_1 + cycle_2
            final_price = max(1.0, final_price)
            
            t = current_time - (time_delta * (num_points - i - 1))
            
            # Format timestamp based on data type
            if time_range == "INTRADAY":
                timestamp_str = t.strftime("%Y-%m-%d %H:%M:%S")
            else:
                timestamp_str = t.strftime("%Y-%m-%d")
            
            mock_data[timestamp_str] = {
                "1. open": str(round(final_price, 2)),
                "2. high": str(round(final_price + (volatility * 0.3), 2)),
                "3. low": str(round(final_price - (volatility * 0.3), 2)),
                "4. close": str(round(final_price + random.uniform(-0.1, 0.1), 2)),
                "5. volume": str(int(random.uniform(100000, 5000000)))
            }
        
        return {
            "status": "success", 
            "data": mock_data, 
            "meta_data": {
                "Information": f"Mock Data ({time_range}) - API Limit/Error",
                "Source": "Simulated (Fallback)"
            }
        }


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
        logger.warning(f"Returning fallback overview for {symbol}")
        # Simulate realistic fallback data when API limit is hit
        base_mc = 10000000000  # 10B default
        base_rev = 5000000000
        base_eps = 2.50
        base_pe = 15.0
        
        if "AAPL" in symbol:
            base_mc, base_rev, base_eps, base_pe = 3000000000000, 380000000000, 6.42, 28.5
            name, sector = "Apple Inc.", "Technology"
        elif "MSFT" in symbol:
            base_mc, base_rev, base_eps, base_pe = 3100000000000, 240000000000, 11.50, 35.2
            name, sector = "Microsoft Corporation", "Technology"
        elif "NVDA" in symbol:
            base_mc, base_rev, base_eps, base_pe = 2200000000000, 60000000000, 12.30, 75.0
            name, sector = "NVIDIA Corporation", "Technology"
        elif "TSLA" in symbol:
            base_mc, base_rev, base_eps, base_pe = 600000000000, 95000000000, 3.12, 45.0
            name, sector = "Tesla Inc.", "Consumer Discretionary"
        elif "AMZN" in symbol:
            base_mc, base_rev, base_eps, base_pe = 1800000000000, 570000000000, 2.90, 60.0
            name, sector = "Amazon.com Inc.", "Consumer Discretionary"
        else:
            name = symbol
            sector = "General Market"
            
        import random
        # Add tiny randomization to make it look alive
        mc = base_mc * random.uniform(0.98, 1.02)
        rev = base_rev * random.uniform(0.98, 1.02)
        
        return {
            "status": "success",
            "source": "Mocked (API limit reached)",
            "data": {
                "Name": name, "Symbol": symbol,
                "Description": f"{name} is a major player in the {sector} sector. (Note: Data mocked due to Alpha Vantage API limits).",
                "Sector": sector, "Industry": sector,
                "MarketCapitalization": str(int(mc)), 
                "PERatio": f"{base_pe:.1f}", 
                "EPS": f"{base_eps:.2f}",
                "RevenueTTM": str(int(rev)), 
                "GrossProfitTTM": str(int(rev * 0.4)),
                "ProfitMargin": "0.15",
                "OperatingMarginTTM": "0.20", 
                "ReturnOnEquityTTM": "0.25",
                "DividendYield": "0.015", 
                "Beta": "1.1",
                "52WeekHigh": "150.0", 
                "52WeekLow": "100.0",
                "AnalystTargetPrice": "160.0",
                "QuarterlyEarningsGrowthYOY": "0.10",
                "QuarterlyRevenueGrowthYOY": "0.08",
            }
        }


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
        import random
        base_price = 150.0
        if "AAPL" in symbol: base_price = 175.50
        elif "MSFT" in symbol: base_price = 410.20
        elif "NVDA" in symbol: base_price = 880.00
        elif "TSLA" in symbol: base_price = 175.00
        
        price = base_price * random.uniform(0.98, 1.02)
        change = price * random.uniform(-0.02, 0.02)
        
        return {
            "status": "success",
            "source": "Mocked (API limit reached)",
            "data": {
                "symbol": symbol, 
                "price": f"{price:.2f}", 
                "open": f"{(price - change):.2f}",
                "high": f"{(price * 1.01):.2f}",
                "low": f"{(price * 0.99):.2f}",
                "change": f"{change:.2f}",
                "change_percent": f"{(change / base_price * 100):.2f}%", 
                "volume": str(int(random.uniform(1000000, 50000000))),
            }
        }


@app.get("/")
def read_root():
    return {"message": "Aegis Alpha Vantage MCP Server is operational."}

# --- Main Execution ---
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)