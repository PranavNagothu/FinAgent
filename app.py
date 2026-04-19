import streamlit as st
import sys
import os
import httpx
import pandas as pd
import json
import time
from datetime import datetime
import base64
import subprocess

# --- Path Setup ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

# --- Configuration ---
WATCHLIST_FILE = "watchlist.json"
ALERTS_FILE = "alerts.json"

# --- Page Configuration ---
st.set_page_config(
    page_title="Sentinel - AI Financial Intelligence",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS ---
def load_css(file_name):
    with open(file_name) as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

load_css("style.css")

# --- Auto-Start Backend Services ---
# --- Auto-Start Backend Services ---
# --- Auto-Start Backend Services ---
@st.cache_resource
def start_background_services():
    # Managed by main.py in production
    pass

# Trigger startup (cached, runs once per container)
start_background_services()

# --- Helper Functions ---
@st.cache_data(ttl=60)
def check_server_status():
    # All services are mounted as sub-apps under the gateway on port 8000
    urls = {
        "Gateway": "http://127.0.0.1:8000/",
        "Tavily": "http://127.0.0.1:8000/tavily/",
        "Alpha Vantage": "http://127.0.0.1:8000/alphavantage/",
        "Private DB": "http://127.0.0.1:8000/private/",
    }
    statuses = {}
    with httpx.Client(timeout=3.0) as client:
        for name, url in urls.items():
            try:
                response = client.get(url)
                statuses[name] = "✅ Online" if response.status_code == 200 else "⚠️ Error"
            except: statuses[name] = "❌ Offline"
    return statuses

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE): return []
    try:
        with open(WATCHLIST_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, 'w') as f: json.dump(watchlist, f)

def load_alerts():
    if not os.path.exists(ALERTS_FILE): return []
    try:
        with open(ALERTS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception:
        return ""

# --- Session State ---
if 'page' not in st.session_state:
    st.session_state.page = 'home'
if 'analysis_complete' not in st.session_state:
    st.session_state.analysis_complete = False
if 'final_state' not in st.session_state:
    st.session_state.final_state = None
if 'error_message' not in st.session_state:
    st.session_state.error_message = None

# --- UI Components ---

def render_sidebar():
    with st.sidebar:
        # Logo Area
        logo_base64 = get_base64_image("assets/logo.png")
        if logo_base64:
            st.markdown(f"""
            <div style="text-align: center; margin-bottom: 2rem;">
                <img src="data:image/png;base64,{logo_base64}" style="width: 80px; height: 80px; margin-bottom: 10px;">
                <h2 style="margin:0; font-size: 1.5rem;">SENTINEL</h2>
                <p style="color: var(--text-secondary); font-size: 0.8rem;">AI Financial Intelligence</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Navigation
        if st.button("🏠 Home", use_container_width=True):
            st.session_state.page = 'home'
            st.rerun()
        
        if st.button("⚡ Analysis Console", use_container_width=True):
            st.session_state.page = 'analysis'
            st.rerun()

        st.markdown("---")
        st.markdown("### 🧩 Add-On Features")

        if st.button("📄 Research Reports", use_container_width=True):
            st.session_state.page = 'research_report'
            st.rerun()

        if st.button("💼 Portfolio Analyzer", use_container_width=True):
            st.session_state.page = 'portfolio_analyzer'
            st.rerun()

        if st.button("🎙️ Earnings Sentiment", use_container_width=True):
            st.session_state.page = 'earnings_sentiment'
            st.rerun()

        if st.button("📬 Weekly Digest", use_container_width=True):
            st.session_state.page = 'weekly_digest'
            st.rerun()

        if st.button("🌍 Macro Impact", use_container_width=True):
            st.session_state.page = 'macro_impact'
            st.rerun()

        st.markdown("---")
        
        # Settings - Completely Redesigned
        st.markdown("### 🎯 Intelligence Configuration")
        
        # Analysis Depth
        st.select_slider(
            "Analysis Depth",
            options=["Quick Scan", "Standard", "Deep Dive", "Comprehensive"],
            value="Standard"
        )
        
        # Risk Profile
        st.selectbox(
            "Risk Tolerance",
            ["Conservative", "Moderate", "Aggressive", "Custom"],
            help="Adjusts recommendation thresholds"
        )
        
        # Time Horizon
        st.radio(
            "Investment Horizon",
            ["Short-term (< 1 year)", "Medium-term (1-5 years)", "Long-term (5+ years)"],
            index=1
        )
        
        # Market Sentiment Tracking
        st.toggle("Track Market Sentiment", value=True, help="Include social media and news sentiment analysis")
        
        st.markdown("---")
        
        # System Status
        with st.expander("📡 System Status", expanded=False):
            server_statuses = check_server_status()
            for name, status in server_statuses.items():
                dot_class = "status-ok" if status == "✅ Online" else "status-err"
                st.markdown(f"""
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <span style="font-size: 0.9rem;">{name}</span>
                    <div><span class="status-dot {dot_class}"></span><span style="font-size: 0.8rem; color: var(--text-secondary);">{status.split(' ')[1]}</span></div>
                </div>
                """, unsafe_allow_html=True)

        # Watchlist
        with st.expander("🛡️ Watchlist", expanded=False):
            watchlist = load_watchlist()
            new_symbol = st.text_input("Add Symbol:", placeholder="e.g. MSFT").upper()
            if st.button("Add"):
                if new_symbol and new_symbol not in watchlist:
                    watchlist.append(new_symbol)
                    save_watchlist(watchlist)
                    st.rerun()
            
            if watchlist:
                st.markdown("---")
                for symbol in watchlist:
                    col1, col2 = st.columns([3, 1])
                    col1.markdown(f"**{symbol}**")
                    if col2.button("❌", key=f"del_{symbol}"):
                        watchlist.remove(symbol)
                        save_watchlist(watchlist)
                        st.rerun()

def render_home():
    # Auto-refresh logic (Every 10s)
    if 'last_refresh_home' not in st.session_state:
        st.session_state.last_refresh_home = time.time()

    if time.time() - st.session_state.last_refresh_home > 10:
        st.session_state.last_refresh_home = time.time()
        st.rerun()

    # Hero Section with Logo
    logo_base64 = get_base64_image("assets/logo.png")
    
    if logo_base64:
        st.markdown(f"""
        <div class="hero-container">
            <div style="margin-bottom: 24px;">
                <span class="theme-pill">🌟 SENTINEL V2.0 BETA</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: center; gap: 24px; margin-bottom: 1.5rem;">
                <img src="data:image/png;base64,{logo_base64}" style="width: 85px; height: 85px; filter: drop-shadow(0 0 20px rgba(167, 139, 250, 0.4));">
                <h1 class="hero-title" style="margin: 0;">Sentinel AI<br>Financial Intelligence</h1>
            </div>
            <p class="hero-subtitle">
                Transform raw market data into actionable business insights with the power of ultra-fast AI.
                Analyze stocks, macro news, and private portfolios through autonomous agentic workflows.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Fallback without logo
        st.markdown("""
        <div class="hero-container">
            <div style="margin-bottom: 24px;">
                <span class="theme-pill">🌟 SENTINEL V2.0 BETA</span>
            </div>
            <h1 class="hero-title">Sentinel AI<br>Financial Intelligence</h1>
            <p class="hero-subtitle">
                Transform raw market data into actionable business insights with the power of ultra-fast AI.
                Analyze stocks, macro news, and private portfolios through autonomous agentic workflows.
            </p>
        </div>
        """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        if st.button("🚀 INITIATE ANALYSIS SEQUENCE", type="primary", use_container_width=True):
            st.session_state.page = 'analysis'
            st.rerun()

    # Feature Cards Base
    st.markdown("""
    <div style="margin-top: 4rem;">
        <h3 style="text-align: center; margin-bottom: 1rem; color: #fff;">Core Subsystems Active</h3>
        <div class="feature-grid">
            <div class="feature-card">
                <div class="feature-icon">🧠</div>
                <div class="feature-title">Agentic Reasoning</div>
                <div class="feature-desc">
                    Our AI automatically understands market structures, identifies patterns, and generates insights via LangChain without manual oversight.
                </div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">�</div>
                <div class="feature-title">Live Data Injection</div>
                <div class="feature-desc">
                    Direct real-time connections to Wall Street terminals, Alpha Vantage, and global news aggregators via blazing fast MCP microservices.
                </div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🛡️</div>
                <div class="feature-title">Private Execution</div>
                <div class="feature-desc">
                    Analyze completely private Brokerage statements directly on your local machine using encrypted LangGraph vector embeddings.
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- Live Wire on Home Page ---
    st.markdown("---")
    st.markdown("### 🚨 Live Wire Trending")
    
    alerts_container = st.container()
    alerts = load_alerts()
    if not alerts:
        alerts_container.caption("No active alerts in feed.")
    else:
        for alert in reversed(alerts[-10:]): # Show last 10 on home
            alert_type = alert.get("type", "INFO")
            css_class = "alert-market" if alert_type == "MARKET" else "alert-news" if alert_type == "NEWS" else ""
            icon = "📉" if alert_type == "MARKET" else "📰"
            timestamp = datetime.fromisoformat(alert.get("timestamp", datetime.now().isoformat())).strftime("%H:%M:%S")
            
            html = f"""
            <div class="alert-card {css_class}">
                <div class="alert-header">
                    <span>{icon} {alert.get("symbol")}</span>
                    <span>{timestamp}</span>
                </div>
                <div class="alert-body">
                    {alert.get("message")}
                </div>
            </div>
            """
            alerts_container.markdown(html, unsafe_allow_html=True)

    # Footer
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("""
    <div style="text-align: center; color: var(--text-secondary); font-size: 0.9rem;">
        Powered by <b>Google Gemini</b> • Built with <b>LangGraph</b> • Designed with <b>Streamlit</b>
    </div>
    """, unsafe_allow_html=True)

def render_analysis():
    st.markdown("## ⚡ Intelligence Directive")
    
    # Error Display
    if st.session_state.error_message:
        st.error(st.session_state.error_message)
        if st.button("Dismiss Error"):
            st.session_state.error_message = None
            st.rerun()

    col_main, col_alerts = st.columns([3, 1.2])

    with col_main:
        with st.form("research_form", clear_on_submit=False):
            task_input = st.text_area("Enter directive:", placeholder="e.g., Analyze the recent volatility for Tesla ($TSLA) and summarize news.", height=100)
            submitted = st.form_submit_button("EXECUTE ANALYSIS", use_container_width=True)

        if submitted and task_input:
            st.session_state.error_message = None
            server_statuses = check_server_status()
            all_online = all(s == "✅ Online" for s in server_statuses.values())
            
            if not all_online:
                st.error("SYSTEM HALTED: Core services offline. Check sidebar status.")
            else:
                with st.status("🚀 SENTINEL ORCHESTRATOR ENGAGED...", expanded=True) as status:
                    try:
                        from agents.orchestrator_v3 import get_orchestrator
                        # Use default provider or env var
                        orchestrator = get_orchestrator(llm_provider="gemini")
                        
                        final_state_result = {}
                        for event in orchestrator.stream({"task": task_input}):
                            agent_name = list(event.keys())[0]
                            state_update = list(event.values())[0]
                            final_state_result.update(state_update)
                            
                            status.write(f"🛡️ Agent Active: {agent_name}...")
                            
                        status.update(label="✅ Analysis Complete!", state="complete", expanded=False)
                        st.session_state.final_state = final_state_result
                        st.session_state.analysis_complete = True
                        st.rerun()
                    except Exception as e:
                        status.update(label="❌ System Failure", state="error")
                        st.session_state.error_message = f"RUNTIME ERROR: {e}"
                        st.rerun()

        if st.session_state.analysis_complete:
            final_state = st.session_state.final_state
            symbol = final_state.get('symbol', 'N/A') if final_state else 'N/A'
            
            st.markdown(f"### 📝 Report: {symbol}")
            
            # Executive Summary
            st.info(final_state.get("final_report", "No report generated."))
            
            # Deep-Dive Insights
            with st.expander("🔍 Deep-Dive Insights", expanded=True):
                insights = final_state.get("analysis_results", {}).get("insights")
                if insights: st.markdown(insights)
                else: st.warning("No deep-dive insights available.")
            
            # Charts
            with st.expander("📊 Market Telemetry"):
                charts = final_state.get("analysis_results", {}).get("charts", [])
                if charts:
                    for chart in charts:
                        st.plotly_chart(chart, use_container_width=True)
                else:
                    st.caption("No telemetry data available.")
            
            # Raw Data
            with st.expander("💾 Raw Intelligence Logs"):
                tab1, tab2, tab3 = st.tabs(["Web Intelligence", "Market Data", "Internal Portfolio"])
                with tab1: st.json(final_state.get('web_research_results', '{}'))
                with tab2: st.json(final_state.get('market_data_results', '{}'))
                with tab3: st.json(final_state.get('portfolio_data_results', '{}'))

            if st.button("🛡️ New Analysis"):
                st.session_state.analysis_complete = False
                st.session_state.final_state = None
                st.rerun()

    # Live Alerts Feed
    with col_alerts:
        st.markdown("### 🚨 Live Wire")
        alerts_container = st.container()
        
        # Auto-refresh logic
        if 'last_refresh' not in st.session_state:
            st.session_state.last_refresh = time.time()

        if time.time() - st.session_state.last_refresh > 10:
            st.session_state.last_refresh = time.time()
            st.rerun()

        alerts = load_alerts()
        if not alerts:
            alerts_container.caption("No active alerts in feed.")
        else:
            for alert in reversed(alerts[-20:]):
                alert_type = alert.get("type", "INFO")
                css_class = "alert-market" if alert_type == "MARKET" else "alert-news" if alert_type == "NEWS" else ""
                icon = "📉" if alert_type == "MARKET" else "📰"
                timestamp = datetime.fromisoformat(alert.get("timestamp", datetime.now().isoformat())).strftime("%H:%M:%S")
                
                html = f"""
                <div class="alert-card {css_class}">
                    <div class="alert-header">
                        <span>{icon} {alert.get("symbol")}</span>
                        <span>{timestamp}</span>
                    </div>
                    <div class="alert-body">
                        {alert.get("message")}
                    </div>
                </div>
                """
                alerts_container.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page Router — dispatches to the correct page based on session state
# ---------------------------------------------------------------------------
render_sidebar()

if st.session_state.page == 'home':
    render_home()
elif st.session_state.page == 'analysis':
    render_analysis()
elif st.session_state.page == 'research_report':
    from features.research_report import render_research_report
    render_research_report()
elif st.session_state.page == 'portfolio_analyzer':
    from features.portfolio_analyzer import render_portfolio_analyzer
    render_portfolio_analyzer()
elif st.session_state.page == 'earnings_sentiment':
    from features.earnings_sentiment import render_earnings_sentiment
    render_earnings_sentiment()
elif st.session_state.page == 'weekly_digest':
    from features.weekly_digest import render_weekly_digest
    render_weekly_digest()
elif st.session_state.page == 'macro_impact':
    from features.macro_impact import render_macro_impact
    render_macro_impact()
else:
    render_home()