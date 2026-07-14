"""REST API for test runs."""
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import schemas
from ..config import ALLOWED_MODELS, MODEL as DEFAULT_MODEL
from ..agent.runner import LIVE_FRAMES, RUN_SECRETS, STOP_REQUESTS, run_test_job
from ..database import SessionLocal
from ..models import Finding, Step, TestRun
 
router = APIRouter(prefix="/api")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/runs", response_model=schemas.RunOut)
def create_run(body: schemas.RunCreate, db: Session = Depends(get_db)):
    if not body.target_url:
        raise HTTPException(status_code=400, detail="target_url is required")

    run_id = str(uuid.uuid4())
    # Use the user's chosen model if it's one we support, else fall back to default.
    model = body.model if body.model in ALLOWED_MODELS else DEFAULT_MODEL
    config = {
        "max_steps": max(1, min(body.max_steps, 5000)),
        "viewport_width": body.viewport_width,
        "viewport_height": body.viewport_height,
        "auth_type": body.auth_type,
        # Pin the model so cost stays accurate even if QA_MODEL changes later.
        "model": model,
    }
    run = TestRun(
        id=run_id,
        target_url=body.target_url,
        goals=body.goals,
        status="pending",
        config=config,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Secrets live in memory only, keyed by run id — never written to the DB.
    RUN_SECRETS[run_id] = {
        "auth_type": body.auth_type,
        "username": body.username,
        "password": body.password,
        "secret_key": body.secret_key,
        "login_instructions": body.login_instructions,
    }

    threading.Thread(target=run_test_job, args=(run_id,), daemon=True).start()
    return run


@router.get("/runs", response_model=list[schemas.RunOut])
def list_runs(db: Session = Depends(get_db)):
    return db.query(TestRun).order_by(TestRun.created_at.desc()).limit(50).all()


@router.get("/runs/{run_id}", response_model=schemas.RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs/{run_id}/stop", response_model=schemas.RunOut)
def stop_run(run_id: str, db: Session = Depends(get_db)):
    """Ask a running run to stop. The worker finishes cleanly and saves everything;
    this is not a failure. No-op if the run already finished."""
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("pending", "running"):
        STOP_REQUESTS.add(run_id)
    return run


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str, db: Session = Depends(get_db)):
    """Delete a run and, via cascade, all of its findings and steps."""
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    db.commit()
    # Drop any in-memory state for a run that may still be executing.
    RUN_SECRETS.pop(run_id, None)
    LIVE_FRAMES.pop(run_id, None)
    STOP_REQUESTS.discard(run_id)


@router.get("/runs/{run_id}/preview")
def get_preview(run_id: str):
    """Return the latest live browser frame as a JPEG, or 204 if none yet."""
    frame = LIVE_FRAMES.get(run_id)
    if not frame:
        return Response(status_code=204)
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/runs/{run_id}/video")
def get_video(run_id: str, db: Session = Depends(get_db)):
    """Return the full recorded session as a .webm video, or 204 if none."""
    run = db.get(TestRun, run_id)
    if run is None or not run.video:  # accessing .video lazily loads the blob
        return Response(status_code=204)
    return Response(content=run.video, media_type="video/webm")


@router.get("/runs/{run_id}/findings", response_model=list[schemas.FindingOut])
def get_findings(run_id: str, db: Session = Depends(get_db)):
    return (
        db.query(Finding)
        .filter(Finding.run_id == run_id)
        .order_by(Finding.created_at.asc())
        .all()
    )


@router.get("/runs/{run_id}/steps", response_model=list[schemas.StepOut])
def get_steps(run_id: str, after: int = -1, db: Session = Depends(get_db)):
    return (
        db.query(Step)
        .filter(Step.run_id == run_id, Step.index > after)
        .order_by(Step.index.asc())
        .all()
    )
