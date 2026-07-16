"""Application configuration.

All settings are read from environment variables (loaded from a local .env file).
Nothing here is secret in the repo — put real values in backend/.env.
"""
import os
from datetime import date, datetime, timezone

from dotenv import load_dotenv

# Load backend/.env before anything else reads the environment.
load_dotenv()

# --- Secrets ---
# Key used to encrypt project credentials at rest (see app/crypto.py). Any
# passphrase works; it is stretched to a Fernet key. Changing it makes existing
# stored credentials unreadable.
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "")

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Opus 4.8 is the strongest agentic model. Override with QA_MODEL if needed.
MODEL = os.getenv("QA_MODEL", "claude-opus-4-8")
# Reasoning effort for the agent loop: low | medium | high | xhigh | max
EFFORT = os.getenv("QA_EFFORT", "high")

# Models the user may pick per-run from the UI. Any value outside this list is
# rejected by the API layer and falls back to MODEL.
ALLOWED_MODELS = [
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-haiku-4-5",
]


# --- Pricing (USD per 1M tokens) ---
# Used to give an approximate cost for a run from its token usage. Cache-write is
# ~1.25x input and cache-read ~0.1x input; we derive those from the base rates.
def _rates(inp: float, out: float) -> dict:
    return {
        "input": inp,
        "output": out,
        "cache_write": round(inp * 1.25, 4),
        "cache_read": round(inp * 0.10, 4),
    }


PRICING = {
    "claude-opus-4-8": _rates(5.0, 25.0),
    "claude-opus-4-7": _rates(5.0, 25.0),
    "claude-opus-4-6": _rates(5.0, 25.0),
    "claude-sonnet-5": _rates(3.0, 15.0),
    "claude-sonnet-4-6": _rates(3.0, 15.0),
    "claude-haiku-4-5": _rates(1.0, 5.0),
    "claude-fable-5": _rates(10.0, 50.0),
}


# Promotional rates that expire, mapped to the date they are last valid. After
# that date the list price in PRICING applies again with no code change needed.
INTRO_PRICING = {
    # Sonnet 5 introductory pricing; list price is $3/$15.
    "claude-sonnet-5": (date(2026, 8, 31), _rates(2.0, 10.0)),
}


def pricing_for(model, on=None) -> dict:
    """Rates for `model`, honouring introductory pricing while it is still live."""
    intro = INTRO_PRICING.get(model)
    if intro is not None:
        last_valid_day, intro_rates = intro
        if (on or datetime.now(timezone.utc).date()) <= last_valid_day:
            return intro_rates
    return PRICING.get(model) or PRICING.get(MODEL) or _rates(5.0, 25.0)


def estimate_cost(model, input_tokens=0, output_tokens=0, cache_read=0, cache_write=0) -> float:
    """Approximate USD cost for a run given its accumulated token usage."""
    p = pricing_for(model)
    cost = (
        (input_tokens or 0) / 1_000_000 * p["input"]
        + (output_tokens or 0) / 1_000_000 * p["output"]
        + (cache_read or 0) / 1_000_000 * p["cache_read"]
        + (cache_write or 0) / 1_000_000 * p["cache_write"]
    )
    return round(cost, 6)

# --- Database ---
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:1234@localhost:5432/agentic_qa",
)

# --- Browser ---
# Run Chromium headless by default. Set QA_HEADLESS=false to watch it work.
HEADLESS = os.getenv("QA_HEADLESS", "true").strip().lower() != "false"

# CORS origins for the local React dev server.
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]
