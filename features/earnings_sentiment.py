"""
features/earnings_sentiment.py — Earnings Call Sentiment Intelligence
Analyzes earnings call transcripts for sentiment, confidence, guidance tone.
"""
import streamlit as st
import json
import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("EarningsSentiment")


# ---------------------------------------------------------------------------
# Transcript fetching
# ---------------------------------------------------------------------------
def _fetch_transcript(ticker: str, quarter: int = None, year: int = None) -> str:
    """Fetch earnings call transcript via Tavily search."""
    from features.utils import run_tavily_search

    now = datetime.now()
    if not quarter:
        quarter = (now.month - 1) // 3 + 1
        # Last quarter
        if quarter == 1:
            quarter = 4
            year = (year or now.year) - 1
        else:
            quarter -= 1
    if not year:
        year = now.year

    query = f"{ticker} earnings call transcript Q{quarter} {year}"
    try:
        result = run_tavily_search(query, search_depth="advanced")
        texts = []
        for qr in result.get("data", []):
            for r in qr.get("results", []):
                texts.append(r.get("content", ""))
        return "\n\n".join(texts[:5]) if texts else ""
    except Exception as e:
        logger.error(f"Transcript fetch failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Sentiment analysis via Gemini
# ---------------------------------------------------------------------------
def _analyze_sentiment(ticker: str, transcript: str) -> dict:
    """Run Gemini to analyze sentiment of earnings call."""
    from features.utils import call_gemini

    prompt = f"""You are an expert sentiment analyst specializing in earnings.

Analyze the following text regarding the earnings call for {ticker}.
Note: The text may be the raw transcript OR market commentary/news about the call. 
Analyze whatever is provided to determine the sentiment, guidance, and key themes as accurately as possible.

---
{transcript[:6000]}
---

Provide your analysis as a VALID JSON object with this exact structure:
{{
    "management_sentiment": {{
        "score": <float from -1.0 to 1.0>,
        "label": "Positive" | "Neutral" | "Negative",
        "confidence_level": <int from 0-100>,
        "forward_guidance": "Optimistic" | "Cautious" | "Withdrawn",
        "key_quotes": ["quote1", "quote2"]
    }},
    "qa_sentiment": {{
        "score": <float from -1.0 to 1.0>,
        "label": "Positive" | "Neutral" | "Negative",
        "confidence_level": <int from 0-100>,
        "analyst_concerns": ["concern1", "concern2"]
    }},
    "key_themes": ["theme1", "theme2", "theme3", "theme4", "theme5"],
    "positive_words": ["word1", "word2", "word3", "word4", "word5", "word6", "word7", "word8"],
    "negative_words": ["word1", "word2", "word3", "word4", "word5", "word6", "word7", "word8"],
    "divergence_alerts": ["alert1 if any"],
    "between_the_lines": "A 2-3 paragraph analysis of what management is really communicating between the lines."
}}

Be precise with scores. Detect hedging language, overconfidence, and tone shifts.
Return ONLY the JSON, no markdown formatting."""

    raw = call_gemini(prompt, "You are a senior NLP analyst at a hedge fund specializing in earnings call analysis.")

    # Force JSON format cleanup if AI included markdown blocks
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        # Match from first { to last }
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Sentiment parse error: {e}")

    # Fallback structure
    return {
        "management_sentiment": {"score": 0, "label": "Neutral", "confidence_level": 50, "forward_guidance": "Cautious", "key_quotes": []},
        "qa_sentiment": {"score": 0, "label": "Neutral", "confidence_level": 50, "analyst_concerns": []},
        "key_themes": ["Unable to parse"],
        "positive_words": [], "negative_words": [],
        "divergence_alerts": [],
        "between_the_lines": raw,
    }


# ---------------------------------------------------------------------------
# Visualization helpers
# ---------------------------------------------------------------------------
def _render_gauge(score: float, label: str, title: str):
    """Render a Plotly gauge chart for sentiment score."""
    import plotly.graph_objects as go

    color = "#10b981" if score > 0.2 else "#ef4444" if score < -0.2 else "#f59e0b"
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=score,
        title={"text": title, "font": {"size": 16, "color": "white"}},
        number={"font": {"color": "white"}},
        gauge={
            "axis": {"range": [-1, 1], "tickcolor": "white"},
            "bar": {"color": color},
            "bgcolor": "#1e1e1e",
            "bordercolor": "#333",
            "steps": [
                {"range": [-1, -0.3], "color": "rgba(239,68,68,0.2)"},
                {"range": [-0.3, 0.3], "color": "rgba(245,158,11,0.2)"},
                {"range": [0.3, 1], "color": "rgba(16,185,129,0.2)"},
            ],
        },
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", font_color="white",
        height=250, margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def _render_wordcloud(words: list, title: str, colormap: str = "Greens"):
    """Generate a word cloud image from a list of words."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from wordcloud import WordCloud

    if not words:
        return None

    text = " ".join(words)
    wc = WordCloud(
        width=400, height=200, background_color="black",
        colormap=colormap, max_words=50, prefer_horizontal=0.7,
    ).generate(text)

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title(title, color="white", fontsize=12, pad=10)
    fig.patch.set_facecolor("black")
    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Streamlit page renderer
# ---------------------------------------------------------------------------
def render_earnings_sentiment():
    st.markdown("## 🎙️ Earnings Call Sentiment Intelligence")
    st.caption("Analyze earnings call transcripts for hidden sentiment signals, management confidence, "
               "and forward guidance shifts that predict future price moves.")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        ticker = st.text_input("Ticker Symbol:", placeholder="e.g. AAPL", key="es_ticker").upper().strip()
    with col2:
        quarter = st.selectbox("Quarter:", [None, 1, 2, 3, 4], format_func=lambda x: f"Q{x}" if x else "Auto-detect", key="es_q")
    with col3:
        year = st.number_input("Year:", min_value=2020, max_value=2026, value=datetime.now().year, key="es_year")

    analyze_btn = st.button("🔍 Analyze Earnings Call", use_container_width=True, key="es_analyze")

    if analyze_btn and ticker:
        with st.status("🎙️ Analyzing earnings call...", expanded=True) as status:
            status.write(f"📡 Searching for {ticker} Q{quarter or 'latest'} {year} transcript...")
            transcript = _fetch_transcript(ticker, quarter, year)

            if not transcript:
                status.update(label="⚠️ No transcript found", state="error")
                st.warning(f"Could not find earnings call transcript for {ticker}. "
                           "Try specifying a different quarter or year.")
                return

            status.write("🧠 Running deep sentiment analysis...")
            analysis = _analyze_sentiment(ticker, transcript)
            st.session_state["es_analysis"] = analysis
            st.session_state["es_display_ticker"] = ticker
            status.update(label="✅ Analysis Complete!", state="complete", expanded=False)

    # Display results
    analysis = st.session_state.get("es_analysis")
    if not analysis:
        return

    ticker_display = st.session_state.get("es_display_ticker", "")
    st.markdown(f"### 📊 Sentiment Analysis: **{ticker_display}**")

    mgmt = analysis.get("management_sentiment", {})
    qa = analysis.get("qa_sentiment", {})

    # Side-by-side gauges
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🎤 Management Prepared Remarks")
        fig = _render_gauge(mgmt.get("score", 0), mgmt.get("label", "N/A"), "Management Sentiment")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown(f"**Confidence Level:** {mgmt.get('confidence_level', 'N/A')}/100")
        st.markdown(f"**Forward Guidance:** {mgmt.get('forward_guidance', 'N/A')}")

        if mgmt.get("key_quotes"):
            st.markdown("**Key Quotes:**")
            for q in mgmt["key_quotes"]:
                st.markdown(f'> *"{q}"*')

    with col2:
        st.markdown("#### ❓ Q&A Session")
        fig = _render_gauge(qa.get("score", 0), qa.get("label", "N/A"), "Q&A Sentiment")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown(f"**Confidence Level:** {qa.get('confidence_level', 'N/A')}/100")

        if qa.get("analyst_concerns"):
            st.markdown("**Analyst Concerns:**")
            for c in qa["analyst_concerns"]:
                st.markdown(f"- ⚠️ {c}")

    # Key Themes
    st.markdown("---")
    st.markdown("#### 🏷️ Key Themes Mentioned")
    themes = analysis.get("key_themes", [])
    if themes:
        cols = st.columns(min(len(themes), 5))
        for i, theme in enumerate(themes[:5]):
            with cols[i % 5]:
                st.markdown(f"""
                <div style="background: #1e1e1e; border: 1px solid #333; border-radius: 8px;
                     padding: 12px; text-align: center; margin: 4px 0;">
                    <span style="font-size: 0.9rem; color: #a78bfa;">{theme}</span>
                </div>
                """, unsafe_allow_html=True)

    # Word Clouds
    col1, col2 = st.columns(2)
    with col1:
        fig = _render_wordcloud(analysis.get("positive_words", []), "Positive Language", "Greens")
        if fig:
            st.pyplot(fig)
    with col2:
        fig = _render_wordcloud(analysis.get("negative_words", []), "Negative / Hedging Language", "Reds")
        if fig:
            st.pyplot(fig)

    # Divergence Alerts
    alerts = analysis.get("divergence_alerts", [])
    if alerts:
        st.markdown("---")
        st.markdown("#### 🚨 Divergence Alerts")
        for alert in alerts:
            st.error(f"⚠️ {alert}")

    # Between the Lines
    st.markdown("---")
    with st.expander("🔮 What Management Is Really Saying", expanded=True):
        st.markdown(analysis.get("between_the_lines", "No analysis available."))

    # PDF Export
    st.markdown("---")
    if st.button("📥 Download Sentiment Report as PDF", key="es_pdf"):
        from features.utils import export_to_pdf
        sections = [
            {"title": f"Earnings Sentiment: {ticker_display}", "body": f"Management: {mgmt.get('label', 'N/A')} ({mgmt.get('score', 0):.2f})\nQ&A: {qa.get('label', 'N/A')} ({qa.get('score', 0):.2f})"},
            {"title": "Key Themes", "body": ", ".join(themes)},
            {"title": "Between the Lines", "body": analysis.get("between_the_lines", "")},
        ]
        pdf_bytes = export_to_pdf(sections, f"{ticker_display}_sentiment.pdf")
        st.download_button("⬇️ Download PDF", data=pdf_bytes,
                           file_name=f"{ticker_display}_Sentiment_Report.pdf",
                           mime="application/pdf", key="es_pdf_dl")
