# private_mcp.py
from fastapi import FastAPI, HTTPException
import uvicorn
import sqlite3
import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_ollama import ChatOllama

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Private_MCP_Server")

# --- Database Configuration ---
DB_FILE = "portfolio.db"

# --- LLM Configuration (Local Llama 3) ---
# This connects to the Ollama application running on your machine.
# Make sure Ollama and the llama3 model are running.
llm = ChatOllama(model="llama3", temperature=0)

# --- Text-to-SQL Prompt Engineering ---
# This prompt is carefully designed to make Llama 3 generate ONLY safe SQL queries.
text_to_sql_prompt = ChatPromptTemplate.from_messages([
    ("system", 
     """You are a Text-to-SQL assistant. Convert the question to a read-only SQLite query for the 'holdings' table.
Schema: symbol (TEXT), shares (INTEGER), average_cost (REAL).
RULES:
1. SELECT only. No INSERT/UPDATE/DELETE.
2. Output ONLY the SQL query. No markdown.
"""),
    ("human", "Question: {question}")
])

# Create the LangChain chain for Text-to-SQL
sql_generation_chain = text_to_sql_prompt | llm | StrOutputParser()

# --- FastAPI App ---
app = FastAPI(title="Aegis Private MCP Server")

@app.on_event("startup")
async def startup_db():
    """Initialize the database with dummy data if it doesn't exist."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS holdings (
                    symbol TEXT PRIMARY KEY,
                    shares INTEGER,
                    average_cost REAL
                )
            """)
            
            # Check if data exists
            cursor.execute("SELECT count(*) FROM holdings")
            if cursor.fetchone()[0] == 0:
                logger.info("Populating database with diverse dummy data...")
                # Expanded list of companies across sectors
                dummy_data = [
                    # Tech
                    ('AAPL', 5000, 180.20), ('MSFT', 3000, 350.50), ('GOOGL', 1500, 140.10), ('NVDA', 800, 450.00), ('AMD', 2000, 110.30),
                    ('INTC', 4000, 35.40), ('CRM', 1200, 220.10), ('ADBE', 600, 550.20), ('ORCL', 2500, 115.50), ('CSCO', 3500, 52.10),
                    # Finance
                    ('JPM', 2000, 150.40), ('BAC', 5000, 32.10), ('GS', 500, 340.50), ('V', 1000, 240.20), ('MA', 800, 380.10),
                    # Retail & Consumer
                    ('WMT', 1500, 160.30), ('TGT', 1000, 130.50), ('COST', 400, 550.10), ('KO', 3000, 58.20), ('PEP', 2500, 170.40),
                    ('PG', 2000, 150.10), ('NKE', 1200, 105.30), ('SBUX', 1800, 95.40),
                    # Healthcare
                    ('JNJ', 2500, 160.20), ('PFE', 4000, 35.10), ('UNH', 600, 480.50), ('LLY', 400, 580.10), ('MRK', 2000, 110.20),
                    # Energy & Industrial
                    ('XOM', 3000, 105.40), ('CVX', 2000, 150.20), ('GE', 1500, 110.50), ('CAT', 800, 280.10), ('BA', 500, 210.30),
                    # Auto
                    ('TSLA', 1000, 220.90), ('F', 5000, 12.10), ('GM', 4000, 35.40)
                ]
                cursor.executemany("INSERT INTO holdings (symbol, shares, average_cost) VALUES (?, ?, ?)", dummy_data)
                conn.commit()
                logger.info("Database populated successfully.")
            else:
                logger.info("Database already contains data.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")


def execute_safe_query(query: str, params=None):
    """
    Executes a SQL query after a basic safety check.
    This is a critical security function.
    """
    # SECURITY CHECK: Ensure the query is read-only.
    if not query.strip().upper().startswith("SELECT"):
        logger.error(f"SECURITY VIOLATION: Attempted to execute non-SELECT query: {query}")
        raise HTTPException(status_code=403, detail="Forbidden: Only SELECT queries are allowed.")
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row # Makes results dict-like
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            results = [dict(row) for row in cursor.fetchall()]
            # Sanitize results: Replace None with 0 (common for SUM on empty set)
            for row in results:
                for key, value in row.items():
                    if value is None:
                        row[key] = 0
            return results
    except sqlite3.Error as e:
        logger.error(f"Database error executing query '{query}': {e}")
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

@app.post("/portfolio_data")
async def get_portfolio_data(payload: dict):
    """
    Takes a natural language question, converts it to SQL using Llama 3,
    and executes it against the internal portfolio database.
    """
    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="'question' is a required field.")

    logger.info(f"Received portfolio data question: '{question}'")

    try:
        # Step 1: Generate the SQL query using the local LLM
        try:
            generated_sql = await sql_generation_chain.ainvoke({"question": question})
            logger.info(f"Llama 3 generated SQL: {generated_sql}")
        except Exception as llm_error:
            logger.warning(f"LLM generation failed (likely Ollama offline): {llm_error}. Using fallback logic.")
            # Fallback Logic: Dynamic symbol extraction
            import re
            q_upper = question.upper()
            # Look for common ticker patterns (1-5 uppercase letters)
            matches = re.findall(r'\b[A-Z]{1,5}\b', q_upper)
            
            found_symbol = None
            ignored_words = ["WHAT", "IS", "THE", "TO", "OF", "FOR", "IN", "AND", "OR", "SHOW", "ME", "DATA", "STOCK", "PRICE", "DO", "WE", "OWN", "HAVE", "ANY", "EXPOSURE", "CURRENT"]
            
            for match in matches:
                if match not in ignored_words:
                    found_symbol = match
                    break
            
            if found_symbol:
                generated_sql = f"SELECT * FROM holdings WHERE symbol='{found_symbol}'"
            else:
                generated_sql = "SELECT * FROM holdings" # Default to showing all
            logger.info(f"Fallback SQL generated: {generated_sql}")

        # Step 2: Execute the query using our secure function
        results = execute_safe_query(generated_sql)
        logger.info(f"Successfully executed query and found {len(results)} records.")

        return {"status": "success", "question": question, "generated_sql": generated_sql, "data": results}

    except HTTPException as http_exc:
        # Re-raise HTTP exceptions from our secure executor
        raise http_exc
    except Exception as e:
        logger.critical(f"An unexpected error occurred in the portfolio data endpoint: {e}")
        # Don't crash the client, return an empty success with error note
        return {"status": "error", "message": str(e), "data": []}

@app.get("/")
def read_root():
    return {"message": "Aegis Private MCP Server is operational."}

# --- Main Execution ---
if __name__ == "__main__":
    # This server runs on port 8003
    uvicorn.run(app, host="127.0.0.1", port=8003)