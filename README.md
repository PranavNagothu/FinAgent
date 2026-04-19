---
title: Sentinel AI Financial Intelligence
emoji: 🛡️
colorFrom: gray
colorTo: indigo
sdk: streamlit
sdk_version: 1.29.0
app_file: app.py
pinned: false
license: mit
---

# Sentinel AI - Financial Intelligence Platform

Transform raw market data into actionable business insights with the power of AI. Analyze stocks, news, and portfolios automatically using intelligent agents.

## Features

- 🧠 **Intelligent Analysis**: AI automatically understands market structures and generates insights
- 📊 **Smart Visualizations**: Creates appropriate charts and graphs with interactive visualizations
- 🎯 **Actionable Recommendations**: Get specific, measurable recommendations based on data-driven insights
- 🚨 **Live Wire**: Real-time market alerts and trending information

## Technology Stack

- **Frontend**: Streamlit
- **AI/ML**: Google Gemini, LangGraph
- **Data Sources**: Alpha Vantage, Tavily Search
- **Architecture**: Multi-agent system with orchestrated workflows

## Configuration

Before running, you need to set up the following secrets in Hugging Face Spaces settings:

```toml
GOOGLE_API_KEY = "your-google-api-key"
ALPHA_VANTAGE_API_KEY = "your-alpha-vantage-key"
TAVILY_API_KEY = "your-tavily-api-key"
```

## Local Development

```bash
pip install -r requirements.txt
streamlit run app.py
```

## License

MIT License - See LICENSE file for details
