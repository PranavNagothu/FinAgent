# app_command_center.py
import streamlit as st
import sys
import os
import httpx
import time
import json
from datetime import datetime

# --- Path Setup ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))
from agents.orchestrator_v3 import SentinelOrchestratorV3

# --- Configuration ---
WATCHLIST_FILE = "watchlist.json"
ALERTS_FILE = "alerts.json"

# --- Page Configuration ---
st.set_page_config(
    page_title="Aegis Digital Briefing",
    page_icon="🛡️",
    layout="wide"
)

# --- Custom CSS for the Briefing Room Theme ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@600;700&family=Open+Sans:wght@400;600&display=swap');
    
    html, body, [class*="st-"] {
        font-family: 'Open Sans', sans-serif;
    }
    
    /* Main Headers */
    h1, h2, h3 {
        font-family: 'Source Serif 4', serif;
    }
    .main-header {
        font-size: 2.8rem;
        font-weight: 700;
        color: #1A202C;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        text-align: center;
        color: #718096;
        font-size: 1.1rem;
        margin-bottom: 2.5rem;
    }
    
    /* Card/Widget styling */
    .card {
        background-color: #FFFFFF;
        border-radius: 8px;
        padding: 25px;
        border: 1px solid #E2E8F0;
    }
    .metric-card {
        border-radius: 8px;
        padding: 1.5rem;
        text-align: center;
        border: 1px solid #E2E8F0;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #2D3748;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #A0AEC0;
        font-weight: 600;
    }

    /* Sidebar "Analyst Notes" */
    .sidebar .st-emotion-cache-16txtl3 {
        font-size: 1.2rem;
        font-weight: 600;
        color: #2D3748;
    }
    .note-entry {
        background-color: #F7FAFC;
        border-left: 4px solid #4299E1;
        padding: 1rem;
        border-radius: 4px;
        margin-bottom: 0.75rem;
    }
    .note-title { font-weight: 600; color: #2C5282; margin-bottom: 0.25rem; }
    .note-content { font-size: 0.85rem; color: #4A5568; }
    
    /* Alerts Styling */
    .alert-card {
        padding: 1rem;
        border-radius: 6px;
        margin-bottom: 0.8rem;
        border-left: 5px solid #CBD5E0;
        background-color: #F7FAFC;
    }
    .alert-market { border-left-color: #E53E3E; background-color: #FFF5F5; } /* Red for Market */
    .alert-news { border-left-color: #3182CE; background-color: #EBF8FF; } /* Blue for News */
    .alert-header { display: flex; justify-content: space-between; font-size: 0.85rem; color: #718096; margin-bottom: 0.5rem; }
    .alert-body { font-weight: 600; color: #2D3748; }

</style>
""", unsafe_allow_html=True)

# --- Helper Functions & State ---
@st.cache_data(ttl=60)
def check_server_status():
    urls = {"Gateway": "http://127.0.0.1:8000/", "Tavily": "http://127.0.0.1:8001/",
            "Alpha Vantage": "http://127.0.0.1:8002/", "Private DB": "http://127.0.0.1:8003/"}
    statuses = {}
    with httpx.Client(timeout=2.0) as client:
        for name, url in urls.items():
            try:
                response = client.get(url)
                statuses[name] = "✅ Online" if response.status_code == 200 else "⚠️ Error"
            except:
                statuses[name] = "❌ Offline"
    return statuses

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE): return []
    try:
        with open(WATCHLIST_FILE, 'r') as f: return json.load(f)
    except: return []

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, 'w') as f: json.dump(watchlist, f)

def load_alerts():
    if not os.path.exists(ALERTS_FILE): return []
    try:
        with open(ALERTS_FILE, 'r') as f: return json.load(f)
    except: return []

if 'final_state' not in st.session_state:
    st.session_state.final_state = None

# --- UI Rendering ---

# Header
st.markdown('<h1 class="main-header">Aegis Digital Briefing Room</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Automated Intelligence Reports for Modern Finance</p>', unsafe_allow_html=True)

# --- SIDEBAR: Watchlist & Notes ---
sidebar = st.sidebar
sidebar.title("🛡️ Command Center")

# 1. Watchlist Manager
sidebar.subheader("Active Watchlist")
watchlist = load_watchlist()
new_symbol = sidebar.text_input("Add Symbol:", placeholder="e.g. MSFT").upper()
if sidebar.button("Add to Watchlist"):
    if new_symbol and new_symbol not in watchlist:
        watchlist.append(new_symbol)
        save_watchlist(watchlist)
        st.rerun()

symbol_to_remove = sidebar.selectbox("Remove Symbol:", ["Select..."] + watchlist)
if symbol_to_remove != "Select..." and sidebar.button("Remove"):
    watchlist.remove(symbol_to_remove)
    save_watchlist(watchlist)
    st.rerun()

sidebar.markdown("---")

# 2. Analyst Notes
sidebar.title("👨‍💼 Analyst's Live Notes")
notes_placeholder = sidebar.empty()
notes_placeholder.info("Awaiting new directive...")

# --- MAIN CONTENT ---
main_col, alerts_col = st.columns([3, 1])

with main_col:
    # Main container for Research
    main_container = st.container(border=True)
    
    # Input Form
    with main_container:
        st.subheader("🚀 Launch On-Demand Analysis")
        with st.form("research_form"):
            task_input = st.text_input("", placeholder="Enter your directive, e.g., 'Analyze market reaction to the latest Apple ($AAPL) product launch'", label_visibility="collapsed")
            submitted = st.form_submit_button("Generate Briefing", use_container_width=True)

    # --- Main Logic ---
    if submitted and task_input:
        server_statuses = check_server_status()
        if not all(s == "✅ Online" for s in server_statuses.values()):
            main_container.error("Analysis cannot proceed. One or more backend services are offline. Please check the status.")
        else:
            # main_container.empty() # Don't clear, just show results below
            
            final_state_result = {}
            analyst_notes = []
            
            try:
                with st.spinner("Your AI Analyst is compiling the briefing... This may take a moment."):
                    for event in SentinelOrchestratorV3.stream({"task": task_input}):
                        node_name = list(event.keys())[0]
                        final_state_result.update(event[node_name])
                        
                        # --- Generate and Display Live Analyst Notes ---
                        note = ""
                        if node_name == "extract_symbol":
                            note = f"Identified target entity: **{event[node_name].get('symbol', 'N/A')}**"
                        elif node_name == "web_researcher":
                            note = "Sourced initial open-source intelligence from the web."
                        elif node_name == "market_data_analyst":
                            note = "Retrieved latest intraday market performance data."
                        elif node_name == "data_analyzer":
                            note = "Commenced deep-dive quantitative analysis of time-series data."
                        elif node_name == "report_synthesizer":
                            note = "Synthesizing all findings into the final executive briefing."
                        
                        if note:
                            analyst_notes.append(f'<div class="note-entry"><div class="note-title">{node_name.replace("_", " ").title()}</div><div class="note-content">{note}</div></div>')
                            notes_placeholder.markdown("".join(analyst_notes), unsafe_allow_html=True)
                            time.sleep(0.5)

                # --- Display the Final Briefing ---
                st.session_state.final_state = final_state_result
                final_state = st.session_state.final_state
                symbol = final_state.get("symbol", "N/A")

                # HEADLINE
                st.markdown(f"## Briefing: {symbol} - {datetime.now().strftime('%B %d, %Y')}")
                st.markdown("---")
                
                # KEY METRICS WIDGET
                st.subheader("Key Performance Indicators")
                df = final_state.get("analysis_results", {}).get("dataframe")
                if df is not None and not df.empty:
                    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                    with m_col1:
                        st.markdown(f'<div class="metric-card"><div class="metric-value">${df["close"].iloc[-1]:.2f}</div><div class="metric-label">Latest Close Price</div></div>', unsafe_allow_html=True)
                    with m_col2:
                        st.markdown(f'<div class="metric-card"><div class="metric-value">{df["volume"].sum()/1e6:.2f}M</div><div class="metric-label">Total Volume</div></div>', unsafe_allow_html=True)
                    with m_col3:
                        st.markdown(f'<div class="metric-card"><div class="metric-value">${df["high"].max():.2f}</div><div class="metric-label">Intraday High</div></div>', unsafe_allow_html=True)
                    with m_col4:
                        st.markdown(f'<div class="metric-card"><div class="metric-value">${df["low"].min():.2f}</div><div class="metric-label">Intraday Low</div></div>', unsafe_allow_html=True)
                else:
                    st.info("Quantitative market data was not applicable for this briefing.")
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                # MAIN BRIEFING (REPORT + CHARTS)
                brief_col1, brief_col2 = st.columns([7, 5]) # 70/50 split
                with brief_col1:
                    st.subheader("Executive Summary & Analysis")
                    report_html = final_state.get("final_report", "No report generated.").replace("\n", "<br>")
                    st.markdown(f'<div class="card" style="height: 100%;">{report_html}</div>', unsafe_allow_html=True)
                
                with brief_col2:
                    st.subheader("Visual Data Debrief")
                    charts = final_state.get("analysis_results", {}).get("charts", [])
                    if charts:
                        for chart in charts:
                            st.plotly_chart(chart, use_container_width=True)
                    else:
                        st.markdown('<div class="card" style="height: 100%;"><p>No visualizations were generated for this briefing.</p></div>', unsafe_allow_html=True)
                        
                # EVIDENCE LOG
                with st.expander("Show Evidence Log & Methodology"):
                    st.markdown("#### Open Source Intelligence (Web Research)")
                    st.json(final_state.get('web_research_results', '{}'))
                    st.markdown("#### Deep-Dive Analysis Insights")
                    st.text(final_state.get("analysis_results", {}).get("insights", "No insights."))

                if st.button("Start New Briefing"):
                    st.session_state.final_state = None
                    st.rerun()

            except Exception as e:
                st.error(f"An error occurred: {e}")

# --- LIVE ALERTS FEED ---
with alerts_col:
    st.subheader("🚨 Live Alerts")
    st.caption("Real-time monitoring feed")
    
    alerts_container = st.container(height=600)
    
    # Auto-refresh logic for alerts
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = time.time()

    # Refresh every 10 seconds
    if time.time() - st.session_state.last_refresh > 10:
        st.session_state.last_refresh = time.time()
        st.rerun()

    alerts = load_alerts()
    if not alerts:
        alerts_container.info("No active alerts.")
    else:
        for alert in alerts:
            alert_type = alert.get("type", "INFO")
            css_class = "alert-market" if alert_type == "MARKET" else "alert-news" if alert_type == "NEWS" else ""
            icon = "📉" if alert_type == "MARKET" else "📰"
            
            timestamp = datetime.fromisoformat(alert.get("timestamp", datetime.now().isoformat())).strftime("%H:%M")
            
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