# agents/tool_calling_agents.py (Corrected with longer timeout)
import httpx
import logging

# --- Configuration ---
import os
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://127.0.0.1:8000/route_agent_request")

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ToolCallingAgents")

class BaseAgent:
    """A base class for agents that call tools via the MCP Gateway."""
    def __init__(self):
        # A reasonable default timeout for fast, external APIs
        self.client = httpx.Client(timeout=30.0)

    def call_mcp_gateway(self, target_service: str, payload: dict) -> dict:
        """A standardized method to make a request to the MCP Gateway."""
        request_body = { "target_service": target_service, "payload": payload }
        try:
            logger.info(f"Agent calling MCP Gateway for service '{target_service}' with payload: {payload}")
            response = self.client.post(MCP_GATEWAY_URL, json=request_body)
            response.raise_for_status()
            logger.info(f"Received successful response from MCP Gateway for '{target_service}'.")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Error response {e.response.status_code} from MCP Gateway: {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to MCP Gateway at {MCP_GATEWAY_URL}: {e}")
            raise

class WebResearchAgent(BaseAgent):
    """An agent specialized in performing web research using Tavily."""
    def research(self, queries: list[str], search_depth: str = "basic") -> dict:
        payload = { "queries": queries, "search_depth": search_depth }
        return self.call_mcp_gateway("tavily_research", payload)

class MarketDataAgent(BaseAgent):
    """An agent specialized in fetching financial market data."""
    def get_market_data(self, symbol: str, time_range: str = "DAILY") -> dict:
        payload = { "symbol": symbol, "time_range": time_range }
        return self.call_mcp_gateway("alpha_vantage_market_data", payload)

    def get_company_overview(self, symbol: str) -> dict:
        """Fetch company fundamentals (Revenue, EPS, P/E, Market Cap, etc.) - FREE tier."""
        payload = { "symbol": symbol }
        return self.call_mcp_gateway("alpha_vantage_overview", payload)

    def get_global_quote(self, symbol: str) -> dict:
        """Fetch real-time price quote (price, change, volume) - FREE tier."""
        payload = { "symbol": symbol }
        return self.call_mcp_gateway("alpha_vantage_quote", payload)

class InternalPortfolioAgent(BaseAgent):
    """An agent specialized in securely querying the internal portfolio database."""

    # --- THIS IS THE FIX ---
    def __init__(self):
        # Override the default client with one that has a longer timeout
        # because local LLM calls can be slow.
        super().__init__()
        self.client = httpx.Client(timeout=180.0) # Give it 180 seconds

    def query_portfolio(self, question: str) -> dict:
        payload = { "question": question }
        return self.call_mcp_gateway("internal_portfolio_data", payload)

# --- Example Usage (for testing this file directly) ---
if __name__ == '__main__':
    print("--- Testing Agents ---")
    
    # Make sure all your MCP servers and the gateway are running.
    
    # 1. Test the Web Research Agent
    print("\n[1] Testing Web Research Agent...")
    try:
        web_agent = WebResearchAgent()
        research_results = web_agent.research(queries=["What is the current market sentiment on NVIDIA?"])
        print("Web Research Result:", research_results['status'])
    except Exception as e:
        print("Web Research Agent failed:", e)

    # 2. Test the Market Data Agent
    print("\n[2] Testing Market Data Agent...")
    try:
        market_agent = MarketDataAgent()
        market_results = market_agent.get_intraday_data(symbol="TSLA", interval="15min")
        print("Market Data Result:", market_results['status'])
    except Exception as e:
        print("Market Data Agent failed:", e)

    # 3. Test the Internal Portfolio Agent
    print("\n[3] Testing Internal Portfolio Agent...")
    try:
        portfolio_agent = InternalPortfolioAgent()
        portfolio_results = portfolio_agent.query_portfolio(question="How many shares of AAPL do we own?")
        print("Portfolio Query Result:", portfolio_results['status'])
    except Exception as e:
        print("Internal Portfolio Agent failed:", e)