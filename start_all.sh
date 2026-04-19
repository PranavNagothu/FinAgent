#!/bin/bash

# Function to kill all background processes on exit
cleanup() {
    echo "Stopping all services..."
    kill $(jobs -p) 2>/dev/null
    exit
}

# Trap SIGINT (Ctrl+C) and call cleanup
trap cleanup SIGINT

# Cleanup existing processes to prevent port conflicts
echo "🧹 Cleaning up existing processes..."
lsof -ti:8000,8001,8002,8003,7860 | xargs kill -9 2>/dev/null || true
pkill -f "uvicorn" || true
pkill -f "streamlit" || true
sleep 2

echo "🚀 Starting Aegis System..."

# Check if venv exists and activate it
if [ -d "venv" ]; then
    echo "🔌 Activating virtual environment..."
    source venv/bin/activate
else
    echo "⚠️  No virtual environment found. Running with system python..."
fi

# Start Microservices
echo "Starting MCP Gateway (Port 8000)..."
python mcp_gateway.py > mcp_gateway.log 2>&1 &

echo "Starting Tavily MCP (Port 8001)..."
python tavily_mcp.py > tavily_mcp.log 2>&1 &

echo "Starting Alpha Vantage MCP (Port 8002)..."
python alphavantage_mcp.py > alphavantage_mcp.log 2>&1 &

echo "Starting Private Portfolio MCP (Port 8003)..."
python private_mcp.py > private_mcp.log 2>&1 &

# Start Monitor
echo "Starting Proactive Monitor..."
python monitor.py > monitor.log 2>&1 &

# Wait a moment for services to spin up
sleep 3

# Start Streamlit App
echo "🛡️  Launching Sentinel Interface..."
streamlit run app.py --server.port 7860 > streamlit.log 2>&1
