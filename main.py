import subprocess
import sys
import os
import time
import signal

def cleanup(signum, frame):
    print("Stopping services...")
    # Add cleanup logic here if needed
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def main():
    print("🚀 Starting Sentinel Monolith...")
    
    # 1. Start the MCP Gateway (which now includes all microservices)
    # running on port 8000
    gateway_cmd = [sys.executable, "mcp_gateway.py"]
    gateway_process = subprocess.Popen(gateway_cmd, cwd=os.getcwd())
    print(f"✅ Gateway started (PID: {gateway_process.pid})")
    
    # 2. Start the Monitor (runs in background loop)
    # Using the same interpreter
    monitor_cmd = [sys.executable, "monitor.py"]
    monitor_process = subprocess.Popen(monitor_cmd, cwd=os.getcwd())
    print(f"✅ Monitor started (PID: {monitor_process.pid})")

    # Give backend a moment to initialize
    time.sleep(5)
    
    # 3. Start Streamlit (Frontend)
    # This commands blocks until Streamlit exits
    print("✅ Starting Streamlit on port 7860...")
    streamlit_cmd = [
        "streamlit", "run", "app.py",
        "--server.port", "7860",
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
        "--browser.serverAddress", "0.0.0.0",
        "--server.enableCORS", "false",
        "--server.enableXsrfProtection", "false"
    ]
    
    # We use subprocess.run for the foreground process
    subprocess.run(streamlit_cmd, check=False)
    
    # Cleanup when streamlit exits
    gateway_process.terminate()
    monitor_process.terminate()

if __name__ == "__main__":
    main()
