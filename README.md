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
# → open .env and set:
#     ANTHROPIC_API_KEY   your key
#     APP_SECRET_KEY      any long random string; encrypts saved credentials.
#                         Generate one with:
#                           python -c "import secrets; print(secrets.token_urlsafe(32))"
#     DATABASE_URL        adjust if your Postgres differs

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

The app has two screens:

- **Dashboard** — a static overview of platform health and recent agent activity.
  Nothing here is wired to live telemetry yet.
- **Projects** — the real workflow.

1. Go to **Projects** and click **Add Project**. Give it a name, the application
   URL, optional goals, a step budget, a model, and an authentication type.
2. Click **Run Test** on any row. The agent starts immediately and the row's
   status tracks it.
3. Use **View** (the eye icon) to open a project and inspect its latest run
   across five tabs: **Findings**, **Activity** (agent step log), **Live
   Preview** (the headless browser streamed frame-by-frame while running, and
   the recorded session afterwards), **Summary** (final report), and **Total
   Cost** (token usage and an approximate USD cost).
4. **Edit** changes a project's configuration; **Delete** removes it along with
   its run, findings, and recording.

Two things to know about runs:

- A project keeps **only its latest run**. Starting a new test discards the
  previous result and its recording, which keeps storage flat — each recording
  is several megabytes.
- A project can only have one test running at a time. Starting a second is
  rejected until the first finishes or is stopped.

The agent navigates, clicks, fills forms, checks console/network errors, tests
responsive layouts, and records each defect as a finding with severity, repro
steps, and evidence.

`max_steps` bounds the number of individual steps (tool calls + narration
messages) — the same units shown in the Activity tab.

---

## How it works

```
React UI ──POST /api/projects/{id}/runs──▶ FastAPI ──spawns thread──▶ Agent loop
   ▲                                          │                         │
   │  polls /runs, /findings, /steps          │ decrypts credentials    │ tool calls
   │                                          ▼                         ▼
Postgres ◀── findings / steps / summary ── in-memory secrets ──  Claude  ⇄  Playwright
```

A **project** stores the configuration; a **run** is one execution of it. Runs
are always started from a project, which is what keeps credentials encrypted at
rest — there is no endpoint that accepts a raw password.

The agent loop (`backend/app/agent/runner.py`) sends the goal + tool definitions
to Opus, executes each tool call against a Playwright browser
(`browser_tools.py`), feeds results back, and repeats until the model finishes.
Findings and step logs are written to Postgres so the UI can show live progress.

## Notes & safety

- The agent uses fake test data and avoids destructive actions, but only test
  sites you own or are authorized to test.
- A project's password and TOTP secret are **encrypted at rest** (Fernet, keyed
  by `APP_SECRET_KEY`) so a saved project can be re-run without retyping them.
  They are decrypted only in memory, at the moment a run starts, and the API
  never returns them — it reports only whether a credential is on file.
- Keep `APP_SECRET_KEY` stable and out of version control. Changing it leaves
  the projects intact but makes saved credentials unreadable, so they have to be
  re-entered.
- Set `QA_HEADLESS=false` in `.env` to watch the browser work in real time.
- Each run costs Anthropic API tokens (large snapshots → non-trivial). Start with
  a modest `max_steps` while testing.

## Next steps (extend it)

- Wire the Dashboard to real telemetry instead of static values
- Build the Settings screen and real sign-in (both are inert placeholders today)
- HTML/PDF report export per run
- Scheduled runs, and a job queue so runs survive a backend restart
- Multi-user accounts and per-user project ownership
Commit at 2026-08-06T10:19:52
Commit at 2026-08-06T11:30:43
Commit at 2026-08-07T09:24:26
Commit at 2026-08-07T15:54:01
Commit at 2026-08-08T11:01:00
Commit at 2026-08-08T12:03:34
Commit at 2026-08-08T14:13:51
Commit at 2026-08-09T12:48:59
Commit at 2026-08-09T16:25:21
Commit at 2026-08-10T10:11:25
Commit at 2026-08-10T11:41:13
Commit at 2026-08-11T11:10:15
Commit at 2026-08-11T11:29:36
Commit at 2026-08-11T12:50:30
Commit at 2026-08-12T12:14:57
Commit at 2026-08-12T17:44:38
Commit at 2026-08-13T11:44:03
Commit at 2026-08-13T14:44:13
Commit at 2026-08-13T15:39:52
Commit at 2026-08-14T09:49:13
Commit at 2026-08-14T14:44:27
Commit at 2026-08-15T16:08:18
Commit at 2026-08-15T17:07:19
