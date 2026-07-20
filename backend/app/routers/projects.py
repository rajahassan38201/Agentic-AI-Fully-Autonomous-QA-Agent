"""REST API for projects: the applications under test."""
import threading
import uuid
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crypto, schemas
from ..agent.runner import LIVE_FRAMES, RUN_SECRETS, STOP_REQUESTS, run_test_job
from ..config import ALLOWED_MODELS, MODEL as DEFAULT_MODEL
from ..database import SessionLocal
from ..models import Project, RecordedStep, TestRun

router = APIRouter(prefix="/api")

ACTIVE_STATUSES = ("pending", "running")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _resolve_model(model: str | None) -> str:
    """Use the requested model if we support it, else the configured default."""
    return model if model in ALLOWED_MODELS else DEFAULT_MODEL


def _with_run_info(db: Session, projects: Iterable[Project]) -> list[dict]:
    """Attach each project's latest run status and run count for the table view."""
    projects = list(projects)
    if not projects:
        return []

    ids = [p.id for p in projects]
    runs = (
        db.query(TestRun.project_id, TestRun.id, TestRun.status, TestRun.created_at)
        .filter(TestRun.project_id.in_(ids))
        .order_by(TestRun.created_at.desc())
        .all()
    )

    latest: dict[str, tuple] = {}
    counts: dict[str, int] = {}
    for project_id, run_id, status, created_at in runs:
        counts[project_id] = counts.get(project_id, 0) + 1
        # Rows arrive newest-first, so the first one seen per project is latest.
        latest.setdefault(project_id, (run_id, status, created_at))

    out = []
    for p in projects:
        run_id, status, created_at = latest.get(p.id, (None, None, None))
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "target_url": p.target_url,
                "goals": p.goals,
                "max_steps": p.max_steps,
                "model": p.model,
                "auth_type": p.auth_type,
                "username": p.username,
                "login_instructions": p.login_instructions,
                "has_password": bool(p.password_encrypted),
                "has_secret_key": bool(p.secret_key_encrypted),
                "last_run_id": run_id,
                "last_run_status": status,
                "last_run_at": created_at,
                "runs_count": counts.get(p.id, 0),
                "total_cost_saved": p.total_cost_saved or 0.0,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
        )
    return out


def _one(db: Session, project: Project) -> dict:
    return _with_run_info(db, [project])[0]


def _encrypt_or_400(value: str | None) -> str | None:
    """Encrypt a credential, turning a missing key into a clear API error."""
    try:
        return crypto.encrypt(value)
    except crypto.SecretKeyMissing as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/projects", response_model=list[schemas.ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return _with_run_info(db, projects)


@router.post("/projects", response_model=schemas.ProjectOut, status_code=201)
def create_project(body: schemas.ProjectCreate, db: Session = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Project name is required")
    if not body.target_url.strip():
        raise HTTPException(status_code=400, detail="Application URL is required")

    project = Project(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        target_url=body.target_url.strip(),
        goals=(body.goals or "").strip() or None,
        max_steps=body.max_steps,
        model=_resolve_model(body.model),
        auth_type=body.auth_type,
        username=body.username or None,
        login_instructions=body.login_instructions or None,
        password_encrypted=_encrypt_or_400(body.password),
        secret_key_encrypted=_encrypt_or_400(body.secret_key),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _one(db, project)


@router.get("/projects/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _one(db, project)


@router.put("/projects/{project_id}", response_model=schemas.ProjectOut)
def update_project(project_id: str, body: schemas.ProjectUpdate, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Project name is required")
    if not body.target_url.strip():
        raise HTTPException(status_code=400, detail="Application URL is required")

    project.name = body.name.strip()
    project.target_url = body.target_url.strip()
    project.goals = (body.goals or "").strip() or None
    project.max_steps = body.max_steps
    project.model = _resolve_model(body.model)
    project.auth_type = body.auth_type
    project.username = body.username or None
    project.login_instructions = body.login_instructions or None

    # A blank credential field means "leave what's stored alone", so editing a
    # project never forces the password to be retyped. Switching to an auth type
    # that doesn't use a credential clears it instead.
    if body.password:
        project.password_encrypted = _encrypt_or_400(body.password)
    if body.secret_key:
        project.secret_key_encrypted = _encrypt_or_400(body.secret_key)
    if project.auth_type == "none":
        project.username = None
        project.password_encrypted = None
        project.secret_key_encrypted = None
    elif project.auth_type != "mfa":
        project.secret_key_encrypted = None

    db.commit()
    db.refresh(project)
    return _one(db, project)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    """Delete a project and, via cascade, all of its runs, findings, and steps."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()


@router.get("/projects/{project_id}/runs", response_model=list[schemas.RunOut])
def list_project_runs(project_id: str, db: Session = Depends(get_db)):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return (
        db.query(TestRun)
        .filter(TestRun.project_id == project_id)
        .order_by(TestRun.created_at.desc())
        .all()
    )


@router.post("/projects/{project_id}/runs", response_model=schemas.RunOut, status_code=201)
def start_project_run(project_id: str, db: Session = Depends(get_db)):
    """Start a test run using the project's saved configuration.

    A project keeps only its most recent run: starting a new one discards the
    previous result, along with its findings, steps, and session recording. That
    keeps storage flat over time — each recording is multiple megabytes.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    active = (
        db.query(TestRun)
        .filter(TestRun.project_id == project_id, TestRun.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="This project already has a test running. Stop it before starting another.",
        )

    # No run is active here (the check above guarantees it), so nothing that is
    # still executing can be deleted out from under a worker thread.
    previous = db.query(TestRun).filter(TestRun.project_id == project_id).all()
    for old in previous:
        # ORM delete (not a bulk query) so findings and steps cascade with it.
        db.delete(old)
        LIVE_FRAMES.pop(old.id, None)
        STOP_REQUESTS.discard(old.id)
        RUN_SECRETS.pop(old.id, None)
    if previous:
        db.flush()

    run_id = str(uuid.uuid4())
    run = TestRun(
        id=run_id,
        project_id=project.id,
        target_url=project.target_url,
        goals=project.goals,
        status="pending",
        config={
            "max_steps": project.max_steps,
            "viewport_width": None,
            "viewport_height": None,
            "auth_type": project.auth_type,
            # Pin the model so cost stays accurate even if the project changes later.
            "model": project.model,
            "project_name": project.name,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Decrypt straight into the worker's in-memory secret store. Plaintext
    # credentials exist only here and in the agent thread — never on disk.
    RUN_SECRETS[run_id] = {
        "auth_type": project.auth_type,
        "username": project.username,
        "password": crypto.decrypt(project.password_encrypted),
        "secret_key": crypto.decrypt(project.secret_key_encrypted),
        "login_instructions": project.login_instructions,
    }

    threading.Thread(target=run_test_job, args=(run_id,), daemon=True).start()
    return run


def _latest_cassette_run(db: Session, project_id: str) -> TestRun | None:
    """Most recent run of this project that recorded a replayable cassette.

    Replay runs write no RecordedStep rows, so this naturally resolves to the last
    AI run — the one whose steps we want to re-execute for free.
    """
    return (
        db.query(TestRun)
        .join(RecordedStep, RecordedStep.run_id == TestRun.id)
        .filter(TestRun.project_id == project_id)
        .order_by(TestRun.created_at.desc())
        .first()
    )


@router.post("/projects/{project_id}/runs/replay", response_model=schemas.RunOut, status_code=201)
def replay_project_run(
    project_id: str,
    options: schemas.ReplayOptions = schemas.ReplayOptions(),
    db: Session = Depends(get_db),
):
    """Re-run the project's last recorded test from its cassette.

    Deterministic replay spends zero tokens; drifted steps are self-healed by the
    model only when ``options.ai_fallback`` is on, within a bounded budget. The
    source AI run is preserved (its cassette is the input); only prior replay runs
    are discarded to keep storage flat.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    active = (
        db.query(TestRun)
        .filter(TestRun.project_id == project_id, TestRun.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="This project already has a test running. Stop it before starting another.",
        )

    source = _latest_cassette_run(db, project_id)
    if source is None:
        raise HTTPException(
            status_code=400,
            detail="No recorded run to replay yet. Run a normal test first to record a cassette.",
        )

    # Discard previous replay runs only — never the source AI run whose cassette we
    # are about to replay.
    prior_replays = (
        db.query(TestRun)
        .filter(
            TestRun.project_id == project_id,
            TestRun.config["mode"].astext == "replay",
        )
        .all()
    )
    for old in prior_replays:
        db.delete(old)
        LIVE_FRAMES.pop(old.id, None)
        STOP_REQUESTS.discard(old.id)
        RUN_SECRETS.pop(old.id, None)
    if prior_replays:
        db.flush()

    run_id = str(uuid.uuid4())
    run = TestRun(
        id=run_id,
        project_id=project.id,
        target_url=project.target_url,
        goals=project.goals,
        status="pending",
        config={
            "mode": "replay",
            "source_run_id": source.id,
            "max_steps": project.max_steps,
            "viewport_width": None,
            "viewport_height": None,
            "auth_type": project.auth_type,
            "model": project.model,  # kept for schema parity; cost will be ~$0
            "project_name": project.name,
            # Phase 3 self-heal knobs from the UI.
            "ai_fallback": options.ai_fallback,
            "max_heal_steps": options.max_heal_steps,
            "max_heal_total_steps": options.max_heal_total_steps,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Replay may still need live secrets (MFA code regeneration, HTTP-basic auth).
    RUN_SECRETS[run_id] = {
        "auth_type": project.auth_type,
        "username": project.username,
        "password": crypto.decrypt(project.password_encrypted),
        "secret_key": crypto.decrypt(project.secret_key_encrypted),
        "login_instructions": project.login_instructions,
    }

    threading.Thread(target=run_test_job, args=(run_id,), daemon=True).start()
    return run
