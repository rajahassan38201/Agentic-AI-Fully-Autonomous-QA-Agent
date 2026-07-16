# Backend — Agentic QA

FastAPI service that runs the Claude Opus 4.8 + Playwright agent loop.

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env   # then edit ANTHROPIC_API_KEY / APP_SECRET_KEY / DATABASE_URL
uvicorn app.main:app --reload --port 8000
```

## Layout

```
app/
├── main.py              FastAPI app, CORS, startup init_db()
├── config.py            env-based settings (.env)
├── crypto.py            encrypt/decrypt project credentials at rest
├── database.py          SQLAlchemy engine/session + create tables
├── models.py            Project, TestRun, Finding, Step
├── schemas.py           Pydantic request/response models
├── routers/
│   ├── projects.py      REST API (project CRUD + start a run)
│   └── runs.py          REST API (run status, findings, steps, video)
└── agent/
    ├── prompts.py       QA system prompt
    ├── browser_tools.py Playwright session + tool schemas for Claude
    └── runner.py        the agent loop (runs in a worker thread)
```

## API

Runs are started from a project, never with raw credentials in the request.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects` | List projects with their latest run status |
| POST | `/api/projects` | Create a project (credentials encrypted at rest) |
| GET | `/api/projects/{id}` | One project |
| PUT | `/api/projects/{id}` | Update; blank credential fields keep stored values |
| DELETE | `/api/projects/{id}` | Delete a project and cascade its runs |
| GET | `/api/projects/{id}/runs` | The project's run (at most one) |
| POST | `/api/projects/{id}/runs` | Start a run, discarding the previous one; 409 if one is already active |
| GET | `/api/runs` | List recent runs across all projects |
| GET | `/api/runs/{id}` | Run status + summary |
| POST | `/api/runs/{id}/stop` | Ask a run to stop and save cleanly |
| DELETE | `/api/runs/{id}` | Delete a single run |
| GET | `/api/runs/{id}/findings` | Findings for a run |
| GET | `/api/runs/{id}/steps?after=N` | Step log (incremental) |
| GET | `/api/runs/{id}/preview` | Latest live browser frame (JPEG), 204 if none |
| GET | `/api/runs/{id}/video` | Recorded session (.webm), 204 if none |
| GET | `/api/health` | Health check |

A project keeps only its most recent run: starting a new one deletes the
previous run and cascades to its findings, steps, and recording.

A run reaches a terminal status (`completed` / `failed` / `stopped`) only after
its session video has been stored, so a terminal status always means every
artifact for that run is retrievable.

## Configuration (.env)

| Var | Default | Notes |
|-----|---------|-------|
| `ANTHROPIC_API_KEY` | — | required |
| `APP_SECRET_KEY` | — | required to save credentials; encrypts them at rest |
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/agentic_qa` | |
| `QA_MODEL` | `claude-opus-4-8` | |
| `QA_EFFORT` | `high` | low / medium / high / xhigh / max |
| `QA_HEADLESS` | `true` | `false` to watch the browser |
