# Agentic QA

An autonomous website-testing SaaS you run **locally**. It uses **Claude Opus 4.8**
to drive a real **Playwright** browser and test any website end-to-end — like a human
QA engineer — then records structured findings and a report.

- **Backend:** FastAPI (Python) + Anthropic SDK + Playwright + SQLAlchemy
- **Frontend:** React (Vite, JavaScript)
- **Database:** PostgreSQL
- **No Docker.** Everything runs directly on your machine.

```
agentic-qa/
├── backend/     FastAPI app + agent loop + Playwright tools
└── frontend/    React dashboard
```

## Prerequisites

You already have these installed:
- Python 3.10+
- Node.js 18+
- PostgreSQL (running locally)

You also need an **Anthropic API key**: https://console.anthropic.com/

---

## 1. Create the database

In a terminal (PowerShell), create the database once:

```powershell
psql -U postgres -c "CREATE DATABASE agentic_qa;"
```

(If `psql` isn't on your PATH, use pgAdmin to create a database named `agentic_qa`.)

---

## 2. Start the backend

```powershell
cd C:\Users\user\agentic-qa\backend

python -m venv venv
venv\Scripts\Activate.ps1

pip install -r requirements.txt
playwright install chromium

copy .env.example .env
# → open .env and paste your ANTHROPIC_API_KEY (and adjust DATABASE_URL if needed)

uvicorn app.main:app --reload --port 8000
```

Backend is live at http://localhost:8000 (health check: http://localhost:8000/api/health).
Tables are created automatically on first start.

> **PowerShell note:** if `Activate.ps1` is blocked, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal first.

---

## 3. Start the frontend (new terminal)

```powershell
cd C:\Users\user\agentic-qa\frontend

npm install
npm run dev
```

Open http://localhost:5173

---

## 4. Use it

1. Enter a target URL (defaults to `https://automationexercise.com/`, a safe practice site).
2. Optionally set goals, max steps, and auth.
3. Click **Run test**. Select the run to watch it work across five tabs:
   **Findings**, **Activity** (agent step log), **Live Preview** (the headless
   browser streamed frame-by-frame), **Summary** (final report), and
   **Total Cost** (token usage and an approximate USD cost).

The agent navigates, clicks, fills forms, checks console/network errors, tests
responsive layouts, and records each defect as a finding with severity, repro
steps, and evidence.

`max_steps` bounds the number of individual steps (tool calls + narration
messages) — the same units shown in the Activity tab.

---

## How it works

```
React UI  ──POST /api/runs──▶  FastAPI  ──spawns thread──▶  Agent loop
   ▲                                                          │
   │  polls /runs, /findings, /steps                          │ tool calls
   │                                                          ▼
Postgres  ◀── findings / steps / summary ──  Opus 4.8  ⇄  Playwright (Chromium)
```

The agent loop (`backend/app/agent/runner.py`) sends the goal + tool definitions
to Opus, executes each tool call against a Playwright browser
(`browser_tools.py`), feeds results back, and repeats until the model finishes.
Findings and step logs are written to Postgres so the UI can show live progress.

## Notes & safety

- The agent uses fake test data and avoids destructive actions, but only test
  sites you own or are authorized to test.
- Passwords you enter are kept **in memory only** for the duration of a run —
  they are never written to the database.
- Set `QA_HEADLESS=false` in `.env` to watch the browser work in real time.
- Each run costs Anthropic API tokens (large snapshots → non-trivial). Start with
  a modest `max_steps` while testing.

## Next steps (extend it)

- HTML/PDF report export per run
- Playwright tracing + video capture
- More auth types (OAuth/SSO via stored session, 2FA via TOTP)
- Multi-user accounts, a job queue, and scheduled runs
