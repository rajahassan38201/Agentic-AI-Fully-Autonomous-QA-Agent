"""Application configuration.

All settings are read from environment variables (loaded from a local .env file).
Nothing here is secret in the repo — put real values in backend/.env.
"""
import os

from dotenv import load_dotenv

# Load backend/.env before anything else reads the environment.
load_dotenv()

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Opus 4.8 is the strongest agentic model. Override with QA_MODEL if needed.
MODEL = os.getenv("QA_MODEL", "claude-opus-4-8")
# Reasoning effort for the agent loop: low | medium | high | xhigh | max
EFFORT = os.getenv("QA_EFFORT", "high")

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
