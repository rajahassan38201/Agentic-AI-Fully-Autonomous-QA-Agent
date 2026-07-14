# Backend — Agentic QA

FastAPI service that runs the Claude Opus 4.8 + Playwright agent loop.

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env   # then edit ANTHROPIC_API_KEY / DATABASE_URL
uvicorn app.main:app --reload --port 8000
```

## Layout

```
app/
├── main.py              FastAPI app, CORS, startup init_db()
├── config.py            env-based settings (.env)
├── database.py          SQLAlchemy engine/session + create tables
├── models.py            TestRun, Finding, Step
├── schemas.py           Pydantic request/response models
├── routers/runs.py      REST API (create/list/get runs, findings, steps)
└── agent/
    ├── prompts.py       QA system prompt
    ├── browser_tools.py Playwright session + tool schemas for Claude
    └── runner.py        the agent loop (runs in a worker thread)
```

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/runs` | Create + start a run |
| GET | `/api/runs` | List recent runs |
| GET | `/api/runs/{id}` | Run status + summary |
| GET | `/api/runs/{id}/findings` | Findings for a run |
| GET | `/api/runs/{id}/steps?after=N` | Step log (incremental) |
| GET | `/api/health` | Health check |

## Configuration (.env)

| Var | Default | Notes |
|-----|---------|-------|
| `ANTHROPIC_API_KEY` | — | required |
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/agentic_qa` | |
| `QA_MODEL` | `claude-opus-4-8` | |
| `QA_EFFORT` | `high` | low / medium / high / xhigh / max |
| `QA_HEADLESS` | `true` | `false` to watch the browser |
