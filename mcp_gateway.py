from typing import Optional, List, Dict, Any, Tuple
# mcp_gateway.py
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import httpx
import logging
import os
import io
from dotenv import load_dotenv

load_dotenv()

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MCP_Gateway")

# --- Import Microservices for Consolidation ---
try:
    from tavily_mcp import app as tavily_app
    from alphavantage_mcp import app as alphavantage_app
    from private_mcp import app as private_app
    logger.info("Successfully imported microservices for consolidation.")
except ImportError as e:
    logger.critical(f"Failed to import microservices: {e}")
    raise

# --- Configuration (Updated for Monolithic Mode) ---
# Default to internal mounted paths on the same port (8002)
TAVILY_MCP_URL = os.getenv("TAVILY_MCP_URL", "http://127.0.0.1:8002/tavily/research")
ALPHAVANTAGE_MCP_URL = os.getenv("ALPHAVANTAGE_MCP_URL", "http://127.0.0.1:8002/alphavantage/market_data")
PRIVATE_MCP_URL = os.getenv("PRIVATE_MCP_URL", "http://127.0.0.1:8002/private/portfolio_data")

# --- FastAPI App ---
app = FastAPI(title="Aegis MCP Gateway (Monolith)")

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Mount Microservices ---
app.mount("/tavily", tavily_app)
app.mount("/alphavantage", alphavantage_app)
app.mount("/private", private_app)

client = httpx.AsyncClient()

@app.middleware("http")
async def audit_log_middleware(request: Request, call_next):
    # Skip logging for internal sub-app calls to reduce noise if needed, 
    # but strictly speaking this middleware triggers for the parent app.
    # Requests to mounted apps might bypass this or trigger it depending on path matching.
    logger.info(f"Request received: {request.method} {request.url}")
    response = await call_next(request)
    return response

# --- New REST Endpoints for Next.js ---
class ResearchRequest(BaseModel):
    ticker: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []

@app.post("/api/chat")
async def api_chat_orchestrator(request: ChatRequest):
    try:
        from features.utils import call_gemini
        from features.research_report import generate_report
        import re

        user_msg = request.message
        
        # 1. Routing Agent: Determine intent
        routing_prompt = f"""You are FinAgent's routing agent. The user said: "{user_msg}"
Determine if they want a deep research report on a specific stock ticker. 
If YES, reply ONLY with the stock ticker symbol (e.g. AAPL, TSLA, NVDA).
If NO (they are just asking a general question or chatting), reply ONLY with the word "CHAT".
"""
        intent = call_gemini(routing_prompt, "You are a precise routing system.").strip().upper()

        if intent != "CHAT" and len(intent) <= 5 and intent.isalpha():
            # Trigger Research Pipeline
            logger.info(f"Routing to Research Report Pipeline for: {intent}")
            report = generate_report(intent)
            
            # Format the JSON report beautifully into Markdown for the Chat UI
            reply = f"### 📊 FinAgent Analysis Sequence Complete: **{report.get('_resolved_ticker', intent)}**\n\n"
            reply += f"**Executive Summary**\n{report.get('executive_summary', '')}\n\n"
            reply += f"***\n**Fundamentals**\n{report.get('fundamentals', '')}\n\n"
            reply += f"***\n**Latest Intelligence**\n{report.get('news', '')}\n\n"
            reply += f"***\n**⚠️ Risk Assessment**\n{report.get('risks', '')}\n\n"
            reply += f"***\n**🎯 Final Verdict & Price Target**\n{report.get('verdict', '')}"
            return {"reply": reply}

        else:
            # 2. General Conversation Agent
            logger.info("Routing to General Chat Agent")
            chat_context = ""
            for msg in request.history[-5:]: # Keep last 5 messages for context
                chat_context += f"{msg.role.capitalize()}: {msg.content}\n"
            
            chat_prompt = f"""You are FinAgent, an elite AI financial intelligence operating system.
You are talking to a user through a sleek, neon 'Generative UI' terminal.
Keep your responses concise, sharp, and highly technical. Use markdown extensively.

Conversation History:
{chat_context}

User's new message:
{user_msg}
"""
            reply = call_gemini(chat_prompt, "You are FinAgent, an elite financial AI.")
            return {"reply": reply}

    except Exception as e:
        logger.error(f"Chat Orchestrator Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/research")
async def api_research_report(request: ResearchRequest):
    try:
        from features.research_report import generate_report
        report = generate_report(request.ticker)
        return {"status": "success", "data": report}
    except Exception as e:
        logger.error(f"Research Report Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/portfolio")
async def api_portfolio_analyzer(file: UploadFile = File(...)):
    try:
        from features.portfolio_analyzer import _parse_csv, _parse_excel, _parse_pdf, _enrich_holdings, _generate_ai_analysis
        content = await file.read()
        file_obj = io.BytesIO(content)
        file_obj.name = file.filename 

        if file.filename.lower().endswith('.csv'):
            holdings = _parse_csv(file_obj)
        elif file.filename.lower().endswith(('.xlsx', '.xls')):
            holdings = _parse_excel(file_obj)
        elif file.filename.lower().endswith('.pdf'):
            holdings = _parse_pdf(file_obj)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format.")

        if holdings is None or holdings.empty:
            raise HTTPException(status_code=400, detail="Could not parse holdings from the uploaded file.")
        
        enriched = _enrich_holdings(holdings)
        ai_result = _generate_ai_analysis(enriched)
        
        # Convert df to dict
        enriched_dict = enriched.to_dict(orient="records")
        return {
            "status": "success",
            "data": {
                "holdings": enriched_dict,
                "analysis": ai_result
            }
        }
    except Exception as e:
        logger.error(f"Portfolio Analyzer Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/route_agent_request")
async def route_agent_request(request_data: dict):
    target_service = request_data.get("target_service")
    payload = request_data.get("payload", {})
    
    logger.info(f"Routing request for target service: {target_service}")

    url_map = {
        "tavily_research": TAVILY_MCP_URL,
        "alpha_vantage_market_data": ALPHAVANTAGE_MCP_URL,
        "alpha_vantage_overview": os.getenv("AV_OVERVIEW_URL", "http://127.0.0.1:8002/alphavantage/company_overview"),
        "alpha_vantage_quote": os.getenv("AV_QUOTE_URL", "http://127.0.0.1:8002/alphavantage/global_quote"),
        "internal_portfolio_data": PRIVATE_MCP_URL,
    }

    target_url = url_map.get(target_service)

    if not target_url:
        logger.error(f"Invalid target service specified: {target_service}")
        raise HTTPException(status_code=400, detail=f"Invalid target service: {target_service}")

    try:
        # Self-referential call (Gateway -> Mounted App on same server)
        # We must ensure we don't block. HTTPX AsyncClient handles this well.
        response = await client.post(target_url, json=payload, timeout=180.0)
        response.raise_for_status()
        return JSONResponse(content=response.json(), status_code=response.status_code)

    except httpx.HTTPStatusError as e:
        logger.error(f"Error from microservice {target_service}: {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.json())
    except httpx.RequestError as e:
        logger.error(f"Could not connect to microservice {target_service}: {e}")
        raise HTTPException(status_code=503, detail=f"Service '{target_service}' is unavailable.")
    except Exception as e:
        logger.critical(f"An unexpected error occurred during routing: {e}")
        raise HTTPException(status_code=500, detail="Internal server error in MCP Gateway.")

@app.get("/")
def read_root():
    return {"message": "Aegis MCP Gateway (Monolithic) is operational."}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)

    