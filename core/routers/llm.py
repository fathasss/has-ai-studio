"""
LLM job queue router.

Provides endpoints for job submission, distributed lock management,
and execution trace recording with real-time WebSocket notifications.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..app_instance import sio
from ..config import logger
from ..database import get_db
from ..models import GlobalLock, LLMJobRecord, LLMTrace, ProjectException
from ..schemas import LLMJobRequest, LLMTraceSchema
from ..services.job_service import job_queue_service
from ..utils import map_role

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(tags=["LLM"])

LOCK_TIMEOUT_MINUTES = int(os.getenv("LOCK_TIMEOUT_MINUTES", "12"))
LOCK_RESOURCE_NAME = "llm_unit"


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class SubmitJobResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    agent_name: str
    sprint_id: str | None = None


class AcquireLockRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=100)


class AcquireLockResponse(BaseModel):
    job_id: str
    agent_name: str
    prompt: str
    sprint_id: str | None = None
    priority: int


class ReleaseLockRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=100)


class LockReleaseResponse(BaseModel):
    status: str
    locks_released: int
    jobs_reset: int


class TraceResponse(BaseModel):
    status: str
    job_status: str


class ProjectExceptionCreate(BaseModel):
    sprint_id: str
    source: str
    command: str | None = None
    error_message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def safe_emit(event: str, data: dict) -> None:
    """
    Emit a Socket.IO event, logging but never raising on failure.

    WebSocket failures must not break core job processing logic.
    """
    try:
        await sio.emit(event, data)
    except Exception as e:
        logger.warning(f"Socket.IO emit failed for '{event}': {e}")


async def _clear_stale_locks(db: Session) -> int:
    """
    Remove stale locks and reset their associated jobs to PENDING.

    Returns the number of stale locks cleared.
    """
    stale_cutoff = datetime.utcnow() - timedelta(minutes=LOCK_TIMEOUT_MINUTES)

    # Find stale locks before deleting (need job IDs for reset)
    stale_locks = db.query(GlobalLock).filter(
        GlobalLock.acquired_at < stale_cutoff
    ).all()

    if not stale_locks:
        return 0

    stale_worker_ids = {lock.worker_id for lock in stale_locks}
    stale_job_ids = {lock.job_id for lock in stale_locks if lock.job_id}

    # Fetch sprint_ids and agent_names for these jobs for frontend notification
    job_info: dict[str, tuple[str | None, str]] = {}
    if stale_job_ids:
        jobs = db.query(LLMJobRecord).filter(LLMJobRecord.id.in_(stale_job_ids)).all()
        job_info = {j.id: (j.sprint_id, j.agent_name) for j in jobs}

    # Delete stale locks
    db.query(GlobalLock).filter(
        GlobalLock.acquired_at < stale_cutoff
    ).delete(synchronize_session="fetch")

    # Reset orphaned PROCESSING jobs back to PENDING
    reset_count = 0
    if stale_job_ids:
        reset_count = db.query(LLMJobRecord).filter(
            LLMJobRecord.id.in_(stale_job_ids),
            LLMJobRecord.status == "PROCESSING",
        ).update(
            {"status": "PENDING", "worker_id": None, "locked_at": None},
            synchronize_session="fetch",
        )

    db.commit()  # Commit now so lock removal and status change are visible

    # Emit updates for reset jobs
    for jid in stale_job_ids:
        sprint_id, agent_name = job_info.get(jid, (None, ""))
        await safe_emit("job_update", {
            "job_id": jid,
            "status": "PENDING",
            "sprint_id": sprint_id,
            "agent": agent_name,
            "agent_name": agent_name,
        })

    logger.warning(
        f"Cleared {len(stale_locks)} stale lock(s), "
        f"reset {reset_count} orphaned job(s). "
        f"Workers: {stale_worker_ids}"
    )

    return len(stale_locks)


# ---------------------------------------------------------------------------
# Routes — Job Submission & Status
# ---------------------------------------------------------------------------

@router.post("/llm/submit", response_model=SubmitJobResponse)
async def submit_job(req: LLMJobRequest):
    """
    Submit a new LLM job to the processing queue.

    The job will be queued with PENDING status and picked up by
    the next available worker via the lock/acquire endpoint.
    """
    req.agent_name = map_role(req.agent_name)
    try:
        job_id = job_queue_service.submit(req)
    except Exception as e:
        logger.error(f"Job submission failed: {e}", exc_info=True)
        raise HTTPException(500, "Failed to submit job")

    await safe_emit("job_update", {
        "job_id": job_id,
        "status": "PENDING",
        "sprint_id": req.sprint_id,
        "agent": req.agent_name,
        "agent_name": req.agent_name,
    })

    return SubmitJobResponse(job_id=job_id)


@router.get("/llm/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """Retrieve the current status of a specific LLM job."""
    job = db.query(LLMJobRecord).filter(LLMJobRecord.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        agent_name=job.agent_name,
        sprint_id=job.sprint_id,
    )


# ---------------------------------------------------------------------------
# Routes — Lock Management
# ---------------------------------------------------------------------------

@router.post("/llm/lock/acquire", response_model=AcquireLockResponse)
async def acquire_lock(
    req: AcquireLockRequest,
    db: Session = Depends(get_db),
):
    """
    Atomically acquire the LLM processing lock and claim the next pending job.

    Returns 404 if no pending jobs exist.
    Returns 423 if the LLM unit is already locked by another worker.
    """
    try:
        # 1. Housekeeping — clear stale locks
        await _clear_stale_locks(db)

        # 2. Check for existing active lock
        existing_lock = db.query(GlobalLock).filter(
            GlobalLock.resource == LOCK_RESOURCE_NAME
        ).first()

        if existing_lock:
            raise HTTPException(
                status_code=423,
                detail=(
                    f"LLM unit locked by worker '{existing_lock.worker_id}' "
                    f"since {existing_lock.acquired_at.isoformat() if existing_lock.acquired_at else 'unknown'}"
                ),
            )

        # 3. Claim next pending job ordered by priority then FIFO creation time
        job = (
            db.query(LLMJobRecord)
            .filter(LLMJobRecord.status == "PENDING")
            .order_by(
                LLMJobRecord.priority.asc(),
                LLMJobRecord.created_at.asc(),
            )
            .first()
        )

        if not job:
            raise HTTPException(status_code=404, detail="No pending jobs")

        # 4. Create lock + update job in single transaction
        now = datetime.utcnow()
        db.add(GlobalLock(
            resource=LOCK_RESOURCE_NAME,
            worker_id=req.worker_id,
            job_id=job.id,
            acquired_at=now,
        ))

        job.status = "PROCESSING"
        job.worker_id = req.worker_id
        job.locked_at = now

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=423,
                detail="LLM unit was concurrently locked by another worker",
            )

        logger.info(
            f"Lock acquired: worker='{req.worker_id}', "
            f"job='{job.id}', agent='{job.agent_name}'"
        )

        await safe_emit("job_update", {
            "job_id": job.id,
            "status": "PROCESSING",
            "sprint_id": job.sprint_id,
            "agent": job.agent_name,
            "agent_name": job.agent_name,
        })

        return AcquireLockResponse(
            job_id=job.id,
            agent_name=job.agent_name,
            prompt=job.prompt,
            sprint_id=job.sprint_id,
            priority=job.priority,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Lock acquisition failed: {e}", exc_info=True)
        raise HTTPException(500, "Failed to acquire lock")


@router.post("/llm/lock/release", response_model=LockReleaseResponse)
async def release_lock(
    req: ReleaseLockRequest,
    db: Session = Depends(get_db),
):
    """
    Release the LLM processing lock for a specific worker.

    If the worker had a PROCESSING job that was not completed,
    it is reset to PENDING so another worker can pick it up.
    """
    try:
        # Delete lock(s) for this worker
        deleted = db.query(GlobalLock).filter(
            GlobalLock.worker_id == req.worker_id,
            GlobalLock.resource == LOCK_RESOURCE_NAME,
        ).delete(synchronize_session="fetch")

        if deleted == 0:
            raise HTTPException(
                404,
                f"No active lock found for worker '{req.worker_id}'",
            )

        # Find incomplete PROCESSING jobs owned by this worker before resetting
        incomplete_jobs = db.query(LLMJobRecord).filter(
            LLMJobRecord.worker_id == req.worker_id,
            LLMJobRecord.status == "PROCESSING",
        ).all()
        incomplete_info = [(j.id, j.sprint_id, j.agent_name) for j in incomplete_jobs]

        reset_count = db.query(LLMJobRecord).filter(
            LLMJobRecord.worker_id == req.worker_id,
            LLMJobRecord.status == "PROCESSING",
        ).update(
            {"status": "PENDING", "worker_id": None, "locked_at": None},
            synchronize_session="fetch",
        )

        db.commit()

        for jid, sid, aname in incomplete_info:
            await safe_emit("job_update", {
                "job_id": jid,
                "status": "PENDING",
                "sprint_id": sid,
                "agent": aname,
                "agent_name": aname,
            })

        if reset_count > 0:
            logger.warning(
                f"Worker '{req.worker_id}' released lock with "
                f"{reset_count} incomplete job(s) reset to PENDING"
            )
        else:
            logger.info(f"Lock released: worker='{req.worker_id}'")

        return LockReleaseResponse(
            status="ok",
            locks_released=deleted,
            jobs_reset=reset_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Lock release failed: {e}", exc_info=True)
        raise HTTPException(500, "Failed to release lock")


# ---------------------------------------------------------------------------
# Routes — Trace & Exception Recording
# ---------------------------------------------------------------------------

@router.post("/llm/trace", response_model=TraceResponse)
async def log_trace(
    trace: LLMTraceSchema,
    db: Session = Depends(get_db),
):
    """
    Record an LLM execution trace and finalize the associated job.

    - Validates that the referenced job exists and is in a valid state.
    - Sets job status based on trace outcome (success → COMPLETED, else → FAILED).
    - Releases the processing lock for the job.
    """
    try:
        # 1. Verify job exists and is in a processable state
        job = db.query(LLMJobRecord).filter(
            LLMJobRecord.id == trace.job_id
        ).first()

        if not job:
            raise HTTPException(404, f"Job '{trace.job_id}' not found")

        if job.status not in ("PROCESSING", "PENDING"):
            raise HTTPException(
                409,
                f"Job '{trace.job_id}' is in state '{job.status}', "
                f"cannot record trace (expected PROCESSING)",
            )

        # 2. Create trace record using model_dump for maintainability
        new_trace = LLMTrace(**trace.model_dump())
        db.add(new_trace)

        # 3. Determine final job status from trace outcome
        status_norm = trace.status.upper()
        final_status = "COMPLETED" if status_norm in ("SUCCESS", "COMPLETED") else "FAILED"
        job.status = final_status
        job.completed_at = datetime.utcnow()

        # 4. Release the lock (CRITICAL — prevents stuck locks)
        lock_deleted = db.query(GlobalLock).filter(
            GlobalLock.job_id == trace.job_id
        ).delete(synchronize_session="fetch")

        if lock_deleted == 0:
            logger.warning(
                f"No lock found for job '{trace.job_id}' during trace recording. "
                f"Lock may have been stale-cleared or manually released."
            )

        db.commit()

        logger.info(
            f"Trace recorded: job='{trace.job_id}', "
            f"status='{final_status}', "
            f"duration={trace.duration_ms}ms, "
            f"tokens={trace.total_tokens}"
        )

        await safe_emit("job_update", {
            "job_id": trace.job_id,
            "status": final_status,
            "sprint_id": trace.sprint_id,
            "agent": job.agent_name,
            "agent_name": job.agent_name,
        })

        return TraceResponse(status="ok", job_status=final_status)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Trace recording failed: {e}", exc_info=True)
        raise HTTPException(500, "Failed to record trace")


@router.post("/exceptions")
async def record_project_exception(
    req: ProjectExceptionCreate,
    db: Session = Depends(get_db),
):
    """Record a project exception from workers and notify UI clients via Socket.IO."""
    try:
        exc = ProjectException(
            sprint_id=req.sprint_id,
            source=req.source,
            command=req.command,
            error_message=req.error_message,
        )
        db.add(exc)
        db.commit()
        db.refresh(exc)
        await safe_emit("project_exception", {
            "id": exc.id,
            "sprint_id": exc.sprint_id,
            "source": exc.source,
            "command": exc.command,
            "error_message": exc.error_message,
            "timestamp": exc.timestamp.isoformat() if exc.timestamp else None,
        })
        return {"status": "ok", "id": exc.id}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to record exception: {e}")
        raise HTTPException(500, "Failed to record exception")


@router.post("/test/live-step")
async def record_live_test_step(req: dict):
    """Broadcasts a realtime test execution step to all connected UI clients via Socket.IO."""
    await safe_emit("test_live_step", req)
    return {"status": "ok"}

