#!/bin/bash

# deploy_local.sh - "Poor Man's Deployment"
# Runs Aegis services in the background using nohup.
# Useful if Docker is not available or not working.

echo "🚀 Starting Aegis in Production Mode (Local)..."

# 1. Activate Virtual Environment
source venv/bin/activate

# 2. Kill existing processes on ports
echo "🧹 Cleaning up ports..."
lsof -ti:8000,8001,8002,8003,8501 | xargs kill -9 2>/dev/null

# 3. Create logs directory
mkdir -p logs

# 4. Start Services in Background
echo "Starting Gateway..."
nohup uvicorn mcp_gateway:app --host 0.0.0.0 --port 8000 > logs/gateway.log 2>&1 &
PID_GATEWAY=$!
echo "Gateway PID: $PID_GATEWAY"

echo "Starting Tavily Service..."
nohup uvicorn tavily_mcp:app --host 0.0.0.0 --port 8001 > logs/tavily.log 2>&1 &

echo "Starting Alpha Vantage Service..."
nohup uvicorn alphavantage_mcp:app --host 0.0.0.0 --port 8002 > logs/alphavantage.log 2>&1 &

echo "Starting Portfolio Service..."
nohup uvicorn private_mcp:app --host 0.0.0.0 --port 8003 > logs/portfolio.log 2>&1 &

echo "Starting Monitor..."
nohup python monitor.py > logs/monitor.log 2>&1 &

echo "Starting Frontend..."
nohup streamlit run app.py --server.port 8501 --server.address 0.0.0.0 > logs/frontend.log 2>&1 &

echo "✅ Deployment Complete!"
echo "---------------------------------------------------"
echo "🌐 Frontend: http://localhost:8501"
echo "📂 Logs are being written to the 'logs/' directory."
echo "🛑 To stop all services, run: pkill -f 'uvicorn|streamlit|monitor.py'"
echo "---------------------------------------------------"
