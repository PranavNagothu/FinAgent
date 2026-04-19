from typing import Optional, List, Dict, Any, Tuple
"""
features/weekly_digest.py — Automated Weekly Market Digest
Background scheduler generates weekly briefings from watchlist data.
"""
import streamlit as st
import json
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("WeeklyDigest")

DIGESTS_DIR = "digests"
Path(DIGESTS_DIR).mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Digest generation pipeline
# ---------------------------------------------------------------------------
def _generate_digest_data() -> dict:
    """Gather watchlist data, news, and generate the digest."""
    from features.utils import fetch_stock_data, run_tavily_search, call_gemini, load_watchlist

    watchlist = load_watchlist()
    if not watchlist:
        return {"error": "Watchlist is empty. Add tickers to your watchlist first."}

    ticker_summaries = []
    winners = []
    losers = []

    for ticker in watchlist:
        try:
            data = fetch_stock_data(ticker, "1W")
            ts = data.get("data", {})
            sorted_times = sorted(ts.keys())
            if len(sorted_times) >= 2:
                first_close = float(ts[sorted_times[0]].get("4. close", 0))
                last_close = float(ts[sorted_times[-1]].get("4. close", 0))
                pct_change = ((last_close - first_close) / first_close * 100) if first_close > 0 else 0

                volumes = [int(ts[t].get("5. volume", 0)) for t in sorted_times]
                avg_vol = sum(volumes) / len(volumes) if volumes else 0
                latest_vol = volumes[-1] if volumes else 0
                vol_anomaly = (latest_vol / avg_vol - 1) * 100 if avg_vol > 0 else 0

                summary = {
                    "ticker": ticker,
                    "weekly_change_pct": round(pct_change, 2),
                    "latest_close": round(last_close, 2),
                    "volume_anomaly_pct": round(vol_anomaly, 1),
                }
                ticker_summaries.append(summary)

                if pct_change > 0:
                    winners.append(summary)
                else:
                    losers.append(summary)
        except Exception as e:
            logger.warning(f"Failed to fetch data for {ticker}: {e}")
            ticker_summaries.append({"ticker": ticker, "error": str(e)})

    winners.sort(key=lambda x: x.get("weekly_change_pct", 0), reverse=True)
    losers.sort(key=lambda x: x.get("weekly_change_pct", 0))

    # Fetch macro news
    try:
        macro_result = run_tavily_search("major financial market news this week economy stocks")
        macro_articles = []
        for qr in macro_result.get("data", []):
            for r in qr.get("results", []):
                macro_articles.append(f"- {r.get('title', '')}: {r.get('content', '')[:150]}")
        macro_news = "\n".join(macro_articles[:6])
    except Exception:
        macro_news = "Macro news unavailable."

    # Generate narrative with Gemini
    prompt = f"""You are a senior market analyst writing a Weekly Market Briefing for {datetime.now().strftime('%B %d, %Y')}.

WATCHLIST PERFORMANCE THIS WEEK:
{json.dumps(ticker_summaries, indent=2)}

BIGGEST WINNERS: {json.dumps(winners[:3], indent=2)}
BIGGEST LOSERS: {json.dumps(losers[:3], indent=2)}

MACRO NEWS:
{macro_news}

Write a professional 500-700 word "Weekly Market Briefing" that covers:
1. **Market Overview** - Overall sentiment and key moves
2. **Watchlist Highlights** - Winners and losers with context
3. **Volume Alerts** - Any unusual volume activity
4. **Macro Landscape** - Key economic developments
5. **Week Ahead** - What to watch for next week

Use a professional but accessible tone. Include specific numbers and percentages.
Do NOT use placeholders — use the actual data provided."""

    narrative = call_gemini(prompt, "You are a chief market strategist at a major financial institution.")

    return {
        "date": datetime.now().isoformat(),
        "date_display": datetime.now().strftime("%B %d, %Y"),
        "watchlist": watchlist,
        "ticker_summaries": ticker_summaries,
        "winners": winners[:3],
        "losers": losers[:3],
        "macro_news": macro_news,
        "narrative": narrative,
    }


def _save_digest(digest: dict):
    """Save digest to JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(DIGESTS_DIR, f"digest_{timestamp}.json")
    with open(filepath, "w") as f:
        json.dump(digest, f, indent=2)
    return filepath


def _load_all_digests() -> List[dict]:
    """Load all saved digests, sorted newest first."""
    digests = []
    if not os.path.exists(DIGESTS_DIR):
        return digests
    for fname in sorted(os.listdir(DIGESTS_DIR), reverse=True):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(DIGESTS_DIR, fname)) as f:
                    d = json.load(f)
                    d["_filename"] = fname
                    digests.append(d)
            except Exception:
                pass
    return digests


# ---------------------------------------------------------------------------
# Email delivery (optional)
# ---------------------------------------------------------------------------
def _send_email(recipient: str, digest: dict):
    """Send digest as HTML email via SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from dotenv import load_dotenv

    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    load_dotenv(dotenv_path=env_path, override=True)

    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not smtp_user or not smtp_pass:
        return False, "SMTP credentials not configured. Set SMTP_USER and SMTP_PASSWORD environment variables."

    try:
        html_body = f"""
        <html>
        <body style="background:#111; color:#fff; font-family:Arial,sans-serif; padding:20px;">
            <h1 style="color:#a78bfa;">📊 FinAgent Weekly Market Digest</h1>
            <h3>{digest.get('date_display', '')}</h3>
            <hr style="border-color:#333;">
            <div style="white-space:pre-wrap;">{digest.get('narrative', '')}</div>
            <hr style="border-color:#333;">
            <p style="color:#888; font-size:12px;">Generated by FinAgent Financial Intelligence</p>
        </body>
        </html>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"FinAgent Weekly Digest — {digest.get('date_display', '')}"
        msg["From"] = smtp_user
        msg["To"] = recipient
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipient, msg.as_string())
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------
_scheduler_started = False

def _start_scheduler():
    """Start APScheduler for weekly digests (Sunday 8 AM)."""
    global _scheduler_started
    if _scheduler_started:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        def _scheduled_job():
            try:
                digest = _generate_digest_data()
                if "error" not in digest:
                    _save_digest(digest)
                    logger.info("Scheduled weekly digest generated successfully.")
            except Exception as e:
                logger.error(f"Scheduled digest generation failed: {e}")

        scheduler = BackgroundScheduler()
        scheduler.add_job(_scheduled_job, "cron", day_of_week="sun", hour=8, minute=0)
        scheduler.start()
        _scheduler_started = True
        logger.info("Weekly digest scheduler started (Sunday 8:00 AM)")
    except Exception as e:
        logger.warning(f"Failed to start scheduler: {e}")


# ---------------------------------------------------------------------------
# Streamlit page renderer
# ---------------------------------------------------------------------------
def render_weekly_digest():
    st.markdown("## 📬 Weekly Market Digest")
    st.caption("Automated weekly intelligence briefings covering your watchlist performance, "
               "macro trends, and AI-generated market commentary. Auto-generates every Sunday at 8 AM.")

    # Start background scheduler
    _start_scheduler()

    # Controls
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        if st.button("🔄 Regenerate Now", use_container_width=True, key="wd_regen"):
            with st.status("📊 Generating fresh digest...", expanded=True) as status:
                status.write("📡 Fetching watchlist data...")
                status.write("📰 Scanning macro environment...")
                status.write("✍️ Writing market briefing...")
                digest = _generate_digest_data()
                if "error" in digest:
                    status.update(label="⚠️ Error", state="error")
                    st.error(digest["error"])
                    return
                filepath = _save_digest(digest)
                st.session_state["wd_current"] = digest
                status.update(label="✅ Digest Generated!", state="complete", expanded=False)
                st.rerun()

    # Email settings
    with col2:
        email = st.text_input("📧 Email:", placeholder="your@email.com", key="wd_email", label_visibility="collapsed")
    with col3:
        if st.button("📤 Send Email", key="wd_send", use_container_width=True):
            current = st.session_state.get("wd_current")
            if current and email:
                ok, msg = _send_email(email, current)
                if ok:
                    st.success(msg)
                else:
                    st.error(f"Email failed: {msg}")
            else:
                st.warning("Generate a digest first, then enter your email.")

    st.markdown("---")

    # Archive selector
    all_digests = _load_all_digests()

    if all_digests:
        digest_options = {d.get("date_display", d.get("_filename", "Unknown")): i for i, d in enumerate(all_digests)}
        selected = st.selectbox(
            "📚 Browse Archive:",
            options=list(digest_options.keys()),
            key="wd_archive",
        )
        if selected:
            idx = digest_options[selected]
            st.session_state["wd_current"] = all_digests[idx]

    # Display current digest
    current = st.session_state.get("wd_current")
    if not current and all_digests:
        current = all_digests[0]  # Show latest
        st.session_state["wd_current"] = current

    if current:
        st.markdown(f"### 📅 {current.get('date_display', 'Unknown Date')}")

        # Quick stats
        summaries = current.get("ticker_summaries", [])
        winners = current.get("winners", [])
        losers = current.get("losers", [])

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📈 Watchlist Tickers", len(summaries))
        with col2:
            best = winners[0] if winners else {}
            st.metric("🏆 Best Performer",
                      best.get("ticker", "N/A"),
                      f"{best.get('weekly_change_pct', 0):+.2f}%" if best else None)
        with col3:
            worst = losers[0] if losers else {}
            st.metric("📉 Worst Performer",
                      worst.get("ticker", "N/A"),
                      f"{worst.get('weekly_change_pct', 0):+.2f}%" if worst else None)

        # Performance table
        if summaries:
            import pandas as pd
            df = pd.DataFrame([s for s in summaries if "error" not in s])
            if not df.empty:
                with st.expander("📊 Watchlist Performance Table", expanded=True):
                    st.dataframe(df, use_container_width=True, hide_index=True)

        # Narrative
        st.markdown("---")
        st.markdown("### 📝 Market Briefing")
        
        # Escape dollar signs so Streamlit doesn't render the paragraph as a LaTeX math equation
        safe_narrative = current.get("narrative", "No narrative available.").replace("$", r"\$")
        st.markdown(safe_narrative)

        # PDF Export
        st.markdown("---")
        if st.button("📥 Download Digest as PDF", key="wd_pdf"):
            from features.utils import export_to_pdf
            sections = [
                {"title": f"Weekly Digest — {current.get('date_display', '')}", "body": ""},
                {"title": "Market Briefing", "body": current.get("narrative", "")},
                {"title": "Watchlist Data", "body": json.dumps(summaries, indent=2)},
            ]
            pdf_bytes = export_to_pdf(sections, "weekly_digest.pdf")
            st.download_button("⬇️ Download PDF", data=pdf_bytes,
                               file_name=f"Weekly_Digest_{current.get('date_display', 'report').replace(' ', '_')}.pdf",
                               mime="application/pdf", key="wd_pdf_dl")
    else:
        st.info("📭 No digests yet. Click **Regenerate Now** to create your first weekly digest.")
