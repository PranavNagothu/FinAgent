# Aegis Deployment Guide

This guide explains how to deploy the Aegis Financial Analyst Agent using Docker and Docker Compose.

## Prerequisites
- **Docker** and **Docker Compose** installed on your machine.
- An `.env` file with valid API keys (see `.env.example` or your existing `.env`).

## Deployment Steps

1.  **Build and Start Services**
    Run the following command in the project root directory:
    ```bash
    docker-compose up --build -d
    ```
    This will:
    - Build the Docker image for the application.
    - Create a network `aegis-net`.
    - Start all services (Gateway, Microservices, Monitor, Frontend) in detached mode.

2.  **Verify Deployment**
    - **Frontend**: Access the Streamlit UI at `http://localhost:8501`.
    - **Gateway**: `http://localhost:8000`
    - **Services**:
        - Tavily: `http://localhost:8001`
        - Alpha Vantage: `http://localhost:8002`
        - Portfolio: `http://localhost:8003`

3.  **View Logs**
    To see logs for all services:
    ```bash
    docker-compose logs -f
    ```
    To see logs for a specific service (e.g., frontend):
    ```bash
    docker-compose logs -f frontend
    ```

4.  **Stop Services**
    To stop and remove containers:
    ```bash
    docker-compose down
    ```

## Environment Variables
Ensure your `.env` file contains:

- `GOOGLE_API_KEY`
- `TAVILY_API_KEY`
- `ALPHA_VANTAGE_API_KEY`

Docker Compose automatically reads these from the `.env` file in the same directory.

## Alternative Deployment (No Docker)
If you cannot run Docker, use the local deployment script:
```bash
./deploy_local.sh
```
This runs all services in the background and saves logs to a `logs/` folder.

## Troubleshooting
- **"Cannot connect to the Docker daemon"**: This means Docker is not running. Open **Docker Desktop** on your Mac and wait for it to start (the whale icon in the menu bar should stop animating).
- **Port Conflicts**: Ensure ports 8000-8003 and 8501 are free.
- **Database Persistence**: The `portfolio.db` file is mounted as a volume, so your internal portfolio data persists across restarts.
