from typing import Optional, List, Dict, Any, Tuple
"""
features/utils.py — Shared utilities for all FinAgent add-on features.
Wraps existing MCP gateway calls, Gemini client, and PDF export.
"""
import os
import time
import json
import logging
import functools
import httpx
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
logger = logging.getLogger("FinAgentFeatures")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://127.0.0.1:8002/route_agent_request")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
AV_RATE_LIMIT_DELAY = 12  # seconds between Alpha Vantage calls (free tier)

_last_av_call = 0.0  # module-level timestamp for rate-limiting

# Load all LLM keys from secrets.toml if not in env
def _load_secrets():
    try:
        import toml as _toml
        _sp = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".streamlit", "secrets.toml")
        if os.path.exists(_sp):
            return _toml.load(_sp)
    except Exception:
        pass
    return {}

_secrets = _load_secrets()
def _get_key(name): return os.getenv(name, "") or _secrets.get(name, "")


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------
def retry_with_backoff(max_retries: int = 3, base_delay: float = 2.0):
    """Decorator: retries a function with exponential back-off."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    wait = base_delay * (2 ** attempt)
                    logger.warning(f"[retry {attempt+1}/{max_retries}] {fn.__name__} failed: {exc} — retrying in {wait:.1f}s")
                    time.sleep(wait)
            raise last_exc  # type: ignore
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# MCP Gateway helpers (mirrors tool_calling_agents.py pattern)
# ---------------------------------------------------------------------------
def _call_gateway(target_service: str, payload: dict, timeout: float = 60.0) -> dict:
    """Low-level POST to MCP Gateway."""
    body = {"target_service": target_service, "payload": payload}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(MCP_GATEWAY_URL, json=body)
        resp.raise_for_status()
        return resp.json()


@retry_with_backoff(max_retries=3)
def fetch_stock_data(ticker: str, time_range: str = "INTRADAY") -> dict:
    """Fetch stock data via the MCP gateway → Alpha Vantage microservice.
    Respects rate-limiting (12 s between calls).
    """
    global _last_av_call
    elapsed = time.time() - _last_av_call
    if elapsed < AV_RATE_LIMIT_DELAY:
        time.sleep(AV_RATE_LIMIT_DELAY - elapsed)
    result = _call_gateway("alpha_vantage_market_data", {"symbol": ticker, "time_range": time_range})
    _last_av_call = time.time()
    return result


@retry_with_backoff(max_retries=3)
def run_tavily_search(query: str, search_depth: str = "basic", max_results: int = 5) -> dict:
    """Run a web search via the MCP gateway → Tavily microservice."""
    return _call_gateway("tavily_research", {"queries": [query], "search_depth": search_depth})


@retry_with_backoff(max_retries=2)
def fetch_company_overview(ticker: str) -> dict:
    """Fetch company fundamentals (Revenue, EPS, P/E, Market Cap, Margins) via AV OVERVIEW."""
    return _call_gateway("alpha_vantage_overview", {"symbol": ticker}, timeout=20.0)


@retry_with_backoff(max_retries=2)
def fetch_global_quote(ticker: str) -> dict:
    """Fetch real-time price quote via AV GLOBAL_QUOTE."""
    return _call_gateway("alpha_vantage_quote", {"symbol": ticker}, timeout=15.0)


# ---------------------------------------------------------------------------
# Gemini LLM helper (with automatic model fallback for rate limits)
# ---------------------------------------------------------------------------
# Ordered fallback chain — tries newest/most capable first
_GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

def get_gemini_llm(temperature: float = 0.0, model: str = None):
    """Return a ChatGoogleGenerativeAI instance. Uses the specified model or the first in the chain."""
    api_key = GOOGLE_API_KEY
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set. Cannot call Gemini.")
    model_name = model or _GEMINI_MODELS[0]
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
        max_retries=2,
    )


def call_gemini(prompt: str, system_prompt: str = "") -> str:
    """LLM call with Groq-first strategy and Gemini fallback."""
    from langchain_core.messages import SystemMessage, HumanMessage
    import time as _time

    messages = []
    if system_prompt:
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
    else:
        messages = [HumanMessage(content=prompt)]

    # --- Load Groq key from secrets.toml or env ---
    groq_api_key = os.getenv("GROQ_API_KEY", "")
    if not groq_api_key:
        try:
            import toml as _toml
            _sp = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".streamlit", "secrets.toml")
            if os.path.exists(_sp):
                groq_api_key = _toml.load(_sp).get("GROQ_API_KEY", "")
        except Exception:
            pass

    # --- Try Groq FIRST (most reliable free tier) ---
    groq_api_key = _get_key("GROQ_API_KEY")
    if groq_api_key:
        try:
            from langchain_groq import ChatGroq
            groq_llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=groq_api_key, temperature=0.0, max_retries=2)
            result = groq_llm.invoke(messages).content.strip()
            logger.info("Groq (Llama-3 70B) responded successfully.")
            return result
        except Exception as e:
            logger.warning(f"Groq failed: {e}. Trying next...")

    # --- Try OpenRouter (free models: Gemma, Mistral, Qwen) ---
    openrouter_key = _get_key("OPENROUTER_API_KEY")
    if openrouter_key:
        _or_models = [
            "google/gemma-3-12b-it:free",
            "mistralai/mistral-7b-instruct:free",
            "google/gemma-2-9b-it:free",
            "qwen/qwen-2.5-7b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct:free",
        ]
        for or_model in _or_models:
            try:
                from langchain_openai import ChatOpenAI
                or_llm = ChatOpenAI(model=or_model, api_key=openrouter_key, base_url="https://openrouter.ai/api/v1", temperature=0.0, max_retries=1)
                result = or_llm.invoke(messages).content.strip()
                logger.info(f"OpenRouter ({or_model}) responded successfully.")
                return result
            except Exception as e:
                logger.warning(f"OpenRouter {or_model} failed: {str(e)[:60]}")
                continue

    # --- Try Mistral AI ---
    mistral_key = _get_key("MISTRAL_API_KEY")
    if mistral_key:
        try:
            from langchain_openai import ChatOpenAI
            mistral_llm = ChatOpenAI(
                model="mistral-small-latest",
                api_key=mistral_key,
                base_url="https://api.mistral.ai/v1",
                temperature=0.0,
                max_retries=2,
            )
            result = mistral_llm.invoke(messages).content.strip()
            logger.info("Mistral AI responded successfully.")
            return result
        except Exception as e:
            logger.warning(f"Mistral failed: {e}. Trying Gemini models...")

    # --- Gemini fallback chain ---
    last_error = None
    for model_name in _GEMINI_MODELS:
        try:
            llm = get_gemini_llm(model=model_name)
            result = llm.invoke(messages).content.strip()
            return result
        except Exception as e:
            error_str = str(e)
            last_error = e
            if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower() or "404" in error_str:
                logger.warning(f"Gemini {model_name} rate-limited, trying next...")
                _time.sleep(2)
                continue
            else:
                logger.warning(f"Gemini {model_name} error: {error_str[:60]}")
                continue

    # All Gemini models exhausted — try Groq (Llama-3) as fallback
    # Load from Streamlit secrets OR .env file
    groq_api_key = os.getenv("GROQ_API_KEY", "")
    if not groq_api_key:
        try:
            import toml as _toml
            _secrets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".streamlit", "secrets.toml")
            if os.path.exists(_secrets_path):
                _secrets = _toml.load(_secrets_path)
                groq_api_key = _secrets.get("GROQ_API_KEY", "")
        except Exception:
            pass

    if groq_api_key:
        logger.info("All Gemini models rate-limited. Falling back to Groq (Llama-3 70B)...")
        try:
            from langchain_groq import ChatGroq
            groq_llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                api_key=groq_api_key,
                temperature=0.0,
                max_retries=2
            )
            result = groq_llm.invoke(messages).content.strip()
            logger.info("Groq fallback succeeded.")
            return result
        except ImportError:
            logger.error("langchain_groq not installed.")
        except Exception as e:
            logger.error(f"Groq fallback also failed: {e}")

    # All models exhausted
    raise last_error


# ---------------------------------------------------------------------------
# PDF export (fpdf2)
# ---------------------------------------------------------------------------
def _sanitize_for_pdf(text: str) -> str:
    """Replace Unicode characters unsupported by Helvetica (latin-1) with safe equivalents."""
    import re
    replacements = {
        "\u2014": "--",   # em dash —
        "\u2013": "-",    # en dash –
        "\u2018": "'",    # left single quote '
        "\u2019": "'",    # right single quote '
        "\u201c": '"',    # left double quote "
        "\u201d": '"',    # right double quote "
        "\u2026": "...",  # ellipsis …
        "\u2022": "*",    # bullet •
        "\u2023": ">",    # triangle bullet ‣
        "\u2027": "-",    # hyphenation point ‧
        "\u00a0": " ",    # non-breaking space
        "\u200b": "",     # zero-width space
        "\u2032": "'",    # prime ′
        "\u2033": '"',    # double prime ″
        "\u2212": "-",    # minus sign −
        "\u00b7": "*",    # middle dot ·
        "\u25cf": "*",    # black circle ●
        "\u25cb": "o",    # white circle ○
        "\u2713": "[x]",  # check mark ✓
        "\u2717": "[ ]",  # cross mark ✗
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    # Remove markdown bold/italic asterisks (but keep list bullet asterisks at start of lines)
    text = re.sub(r'(?<!^)\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'(?<!^)\*(.*?)\*', r'\1', text)
    
    # Final fallback: strip any remaining non-latin-1 chars
    return text.encode("latin-1", errors="replace").decode("latin-1")


def export_to_pdf(sections: List[dict], filename: str = "report.pdf") -> bytes:
    """Generate a professional, Wall Street-grade PDF report with logo and styling.

    Each section dict:  {"title": "...", "body": "..."}
    Returns the PDF as bytes.
    """
    from fpdf import FPDF
    import re

    # --- Color palette ---
    NAVY = (43, 58, 103)        # #2B3A67
    GOLD = (197, 165, 90)       # #C5A55A
    DARK_TEXT = (30, 30, 30)
    LIGHT_GRAY = (230, 230, 235)
    MID_GRAY = (160, 160, 170)
    WHITE = (255, 255, 255)
    SECTION_BG = (240, 242, 248)

    # --- Custom PDF class with header/footer ---
    class FinAgentPDF(FPDF):
        def __init__(self):
            super().__init__()
            self.logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "sentinel_logo.png")

        def header(self):
            if self.page_no() == 1:
                return  # Skip header on title page
            # Logo
            if os.path.exists(self.logo_path):
                self.image(self.logo_path, 10, 6, 12)
            # Company name
            self.set_font("Times", "B", 9)
            self.set_text_color(*NAVY)
            self.set_xy(24, 8)
            self.cell(0, 5, "FINAGENT", align="L")
            self.set_font("Times", "", 7)
            self.set_text_color(*MID_GRAY)
            self.set_xy(24, 13)
            self.cell(0, 4, "Equity Research Division", align="L")
            # Right side: CONFIDENTIAL stamp
            self.set_font("Times", "B", 7)
            self.set_text_color(*GOLD)
            self.set_xy(-50, 10)
            self.cell(40, 5, "CONFIDENTIAL", align="R")
            # Divider line
            self.set_draw_color(*NAVY)
            self.set_line_width(0.5)
            self.line(10, 20, self.w - 10, 20)
            self.ln(16)

        def footer(self):
            self.set_y(-15)
            self.set_draw_color(*LIGHT_GRAY)
            self.set_line_width(0.3)
            self.line(10, self.get_y(), self.w - 10, self.get_y())
            self.ln(2)
            self.set_font("Times", "", 7)
            self.set_text_color(*MID_GRAY)
            self.cell(0, 5, "Generated by FinAgent | For Authorized Use Only", align="L")
            self.set_font("Times", "B", 7)
            self.cell(0, 5, f"Page {self.page_no()}", align="R")

    pdf = FinAgentPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ===== TITLE PAGE =====
    pdf.add_page()
    pdf.ln(30)

    # Logo centered
    if os.path.exists(pdf.logo_path):
        pdf.image(pdf.logo_path, (pdf.w - 40) / 2, pdf.get_y(), 40)
        pdf.ln(45)

    # Title
    pdf.set_font("Times", "B", 28)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 14, _sanitize_for_pdf("FINAGENT"), new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Times", "", 12)
    pdf.set_text_color(*GOLD)
    pdf.cell(0, 8, _sanitize_for_pdf("Equity Research Report"), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)

    # Gold accent line
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(1)
    pdf.line(70, pdf.get_y(), pdf.w - 70, pdf.get_y())
    pdf.ln(10)

    # Extract ticker from first section
    first_body = sections[0].get("body", "") if sections else ""
    ticker_match = re.search(r'\(([A-Z]{1,5})\)', first_body)
    ticker_display = ticker_match.group(1) if ticker_match else ""

    if ticker_display:
        pdf.set_font("Times", "B", 20)
        pdf.set_text_color(*DARK_TEXT)
        pdf.cell(0, 12, ticker_display, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(2)

    # Date
    from datetime import datetime
    pdf.set_font("Times", "", 10)
    pdf.set_text_color(*MID_GRAY)
    pdf.cell(0, 8, f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(15)

    # Disclaimer box
    pdf.set_fill_color(*SECTION_BG)
    pdf.rect(20, pdf.get_y(), pdf.w - 40, 18, style="F")
    pdf.set_font("Times", "I", 7)
    pdf.set_text_color(*MID_GRAY)
    pdf.set_xy(25, pdf.get_y() + 3)
    pdf.multi_cell(pdf.w - 50, 4,
        _sanitize_for_pdf("This report is generated by FinAgent using real-time market data from Alpha Vantage, "
        "SEC EDGAR filings, and AI-powered analysis. It is for informational purposes only and does not "
        "constitute financial advice. Past performance is not indicative of future results."))

    # ===== CONTENT PAGES =====

    def _render_markdown_line(line: str):
        """Render a single markdown line with professional formatting."""
        line = _sanitize_for_pdf(line)
        stripped = line.strip()

        if not stripped:
            pdf.ln(2)
            return

        # Headers
        if stripped.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Times", "B", 11)
            pdf.set_text_color(*NAVY)
            pdf.multi_cell(0, 6, stripped[4:])
            pdf.ln(1)
            return
        if stripped.startswith("## "):
            pdf.ln(3)
            pdf.set_font("Times", "B", 13)
            pdf.set_text_color(*NAVY)
            pdf.multi_cell(0, 7, stripped[3:])
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 40, pdf.get_y())
            pdf.ln(2)
            return
        if stripped.startswith("# "):
            pdf.ln(4)
            pdf.set_font("Times", "B", 15)
            pdf.set_text_color(*NAVY)
            pdf.multi_cell(0, 8, stripped[2:])
            pdf.set_draw_color(*NAVY)
            pdf.set_line_width(0.5)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(3)
            return

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            pdf.set_draw_color(*LIGHT_GRAY)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(3)
            return

        # Table rows
        if "|" in stripped and not stripped.startswith("|--"):
            # Skip separator lines like |---|---|
            if re.match(r'^[\|\-\:\s]+$', stripped):
                return
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if cells:
                col_width = (pdf.w - pdf.l_margin - pdf.r_margin) / max(len(cells), 1)
                is_header = any(c.startswith("**") or c in ("Metric", "Value", "Rank", "Risk Factor", "Implication") for c in cells)
                if is_header:
                    pdf.set_font("Times", "B", 8)
                    pdf.set_fill_color(*NAVY)
                    pdf.set_text_color(*WHITE)
                else:
                    pdf.set_font("Times", "", 8)
                    pdf.set_fill_color(*SECTION_BG)
                    pdf.set_text_color(*DARK_TEXT)
                for cell in cells:
                    cell = re.sub(r'\*\*(.*?)\*\*', r'\1', cell)  # strip bold
                    cell = cell[:50]  # truncate long cells
                    pdf.cell(col_width, 6, cell, border=1, fill=True)
                pdf.ln()
                return

        # Skip pure table separator lines
        if re.match(r'^[\|\-\:\s]+$', stripped):
            return

        # Bullet points
        if stripped.startswith(("- ", "* ")):
            prefix = stripped[:2]
            text = stripped[2:]
            # Handle bold text within bullets
            parts = re.split(r'(\*\*.*?\*\*)', text)
            pdf.set_text_color(*DARK_TEXT)
            pdf.cell(6)  # indent
            pdf.set_font("Times", "", 9)
            pdf.cell(4, 5, chr(8226).encode("latin-1", errors="replace").decode("latin-1"))  # bullet char
            # Build the full text (strip markdown bold markers)
            full_text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
            pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 12, 5, full_text)
            pdf.ln(1)
            return

        # Numbered lists
        num_match = re.match(r'^(\d+)\.\s+', stripped)
        if num_match:
            text = stripped[num_match.end():]
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
            pdf.set_font("Times", "", 9)
            pdf.set_text_color(*DARK_TEXT)
            pdf.cell(4)  # indent
            pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 6, 5, f"{num_match.group(1)}. {text}")
            pdf.ln(1)
            return

        # Regular text
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', stripped)
        pdf.set_font("Times", "", 9)
        pdf.set_text_color(*DARK_TEXT)
        pdf.multi_cell(0, 5, text)
        pdf.ln(1)

    for idx, sec in enumerate(sections):
        pdf.add_page()

        # Section header with colored left bar
        title = _sanitize_for_pdf(sec.get("title", ""))

        # Section number badge
        section_icons = {
            "Executive Summary": "01",
            "Business Overview": "02",
            "Recent News": "03",
            "Risk Factors": "04",
            "Analyst Verdict": "05",
        }
        badge_num = section_icons.get(title, f"{idx + 1:02d}")

        # Navy accent bar on the left
        y_start = pdf.get_y()
        pdf.set_fill_color(*NAVY)
        pdf.rect(pdf.l_margin, y_start, 3, 12, style="F")

        # Section number
        pdf.set_font("Times", "B", 8)
        pdf.set_text_color(*GOLD)
        pdf.set_xy(pdf.l_margin + 6, y_start)
        pdf.cell(10, 5, f"SECTION {badge_num}")

        pdf.set_font("Times", "B", 15)
        pdf.set_text_color(*NAVY)
        pdf.set_xy(pdf.l_margin + 6, y_start + 5)
        pdf.cell(0, 8, title)
        pdf.ln(8)

        # Gold underline
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(0.5)
        pdf.line(pdf.l_margin + 6, pdf.get_y(), pdf.l_margin + 80, pdf.get_y())
        pdf.ln(6)

        # Render body
        body = sec.get("body", "")
        for line in body.split("\n"):
            _render_markdown_line(line)
        pdf.ln(4)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Watchlist helper
# ---------------------------------------------------------------------------
WATCHLIST_FILE = "watchlist.json"

def load_watchlist() -> List[str]:
    if not os.path.exists(WATCHLIST_FILE):
        return []
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []
