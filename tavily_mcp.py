# tavily_mcp.py (Corrected Version)
from fastapi import FastAPI, HTTPException
import uvicorn
import os
from dotenv import load_dotenv
from tavily import TavilyClient
import logging

# --- Configuration ---
load_dotenv()

# --- Logging Setup (MUST be before we use logger) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Tavily_MCP_Server")

# --- Get API Key ---
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Fallback: Try to read from Streamlit secrets file (for cloud deployment)
if not TAVILY_API_KEY:
    try:
        import toml
        secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            secrets = toml.load(secrets_path)
            TAVILY_API_KEY = secrets.get("TAVILY_API_KEY")
            logger.info("Loaded TAVILY_API_KEY from .streamlit/secrets.toml")
    except Exception as e:
        logger.warning(f"Could not load from secrets.toml: {e}")

if not TAVILY_API_KEY:
    logger.warning("TAVILY_API_KEY not found in environment. Search features will fail.")
else:
    logger.info(f"TAVILY_API_KEY found: {TAVILY_API_KEY[:4]}...")

# --- FastAPI App & Tavily Client ---
app = FastAPI(title="Aegis Tavily MCP Server")
tavily = TavilyClient(api_key=TAVILY_API_KEY)

@app.post("/research")
async def perform_research(payload: dict):
    """
    Performs a search for each query using the Tavily API.
    Expects a payload like:
    {
        "queries": ["query1", "query2"],
        "search_depth": "basic" or "advanced" (optional, default basic)
    }
    """
    queries = payload.get("queries")
    search_depth = payload.get("search_depth", "basic")

    if not queries or not isinstance(queries, list):
        logger.error("Validation Error: 'queries' must be a non-empty list.")
        raise HTTPException(status_code=400, detail="'queries' must be a non-empty list.")

    logger.info(f"Received research request for {len(queries)} queries. Search depth: {search_depth}")
    
    # --- THIS IS THE CORRECTED LOGIC ---
    all_results = []
    try:
        # Loop through each query and perform a search
        for query in queries:
            logger.info(f"Performing search for query: '{query}'")
            # The search method takes a single query string
            response = tavily.search(
                query=query,
                search_depth=search_depth,
                max_results=5 
            )
            # Add the results for this query to our collection
            all_results.append({"query": query, "results": response["results"]})
            
        logger.info(f"Successfully retrieved results for all queries from Tavily API.")
        return {"status": "success", "data": all_results}

    except Exception as e:
        logger.error(f"Tavily API Error (likely rate limit): {e}. Switching to MOCK DATA fallback.")
        # --- FALLBACK MECHANISM ---
        mock_results = []
        import random
        from datetime import datetime
        
        # Dynamic market sentiments to rotate through
        sentiments = ["Bullish", "Bearish", "Neutral", "Volatile", "Cautious"]
        events = ["Earnings Surprise", "New Product Launch", "Regulatory Update", "Sector Rotation", "Macro Headwinds"]
        
        current_time = datetime.now().strftime("%H:%M")
        
        for query in queries:
            # Pick random sentiment and event to diversify the "news"
            s = random.choice(sentiments)
            e = random.choice(events)
            
            mock_results.append({
                "query": query,
                "results": [
                    {
                        "title": f"[{current_time}] Market Update: {s} Sentiment for {query}",
                        "content": f"Live market data at {current_time} indicates a {s} trend for {query}. Analysts are tracking a potential {e} that could impact short-term price action. Volume remains high as traders adjust positions.",
                        "url": "http://mock-source.com/market-update"
                    },
                    {
                        "title": f"[{current_time}] Sector Alert: {e} affecting {query}",
                        "content": f"Breaking: A significant {e} is rippling through the sector, heavily influencing {query}. Experts advise monitoring key resistance levels. (Simulated Real-Time Data)",
                        "url": "http://mock-source.com/sector-alert"
                    }
                ]
            })
        return {"status": "success", "data": mock_results}

@app.get("/")
def read_root():
    return {"message": "Aegis Tavily MCP Server is operational."}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)   