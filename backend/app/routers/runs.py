"""REST API for test runs.

Runs are always started from a project (see routers/projects.py), which is what
keeps credentials encrypted at rest. This module covers reading a run's
progress, results, and recordings, plus stopping and deleting it.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import schemas
from ..agent.runner import LIVE_FRAMES, RUN_SECRETS, STOP_REQUESTS
from ..database import SessionLocal
from ..models import Finding, Step, TestRun

router = APIRouter(prefix="/api")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
