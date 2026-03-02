from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
import json
from ..database import get_db
from ..models import LLMJobRecord, LLMTrace, GlobalLock
from ..schemas import LLMJobRequest, LLMJobCompletion, LLMTraceSchema
from .. import config
from ..app_instance import sio
from ..services.job_service import job_queue_service

router = APIRouter(tags=["LLM"])

@router.post("/llm/submit")
async def submit_job(req: LLMJobRequest):
    job_id = job_queue_service.submit(req)
    await sio.emit("job_update", {"job_id": job_id, "status": "PENDING", "sprint_id": req.sprint_id})
    return {"job_id": job_id}

@router.post("/llm/lock/acquire")
async def acquire_lock(worker_id: str, db: Session = Depends(get_db)):
    # Logic extracted from main.py for atomic lock acquisition
    job = db.query(LLMJobRecord).filter(LLMJobRecord.status == "PENDING").order_by(LLMJobRecord.priority.asc(), LLMJobRecord.created_at.asc()).first()
    if not job: raise HTTPException(status_code=404, detail="No pending jobs")
    
    # Clear stale locks (older than 10 mins)
    ten_mins_ago = datetime.utcnow() - timedelta(minutes=10)
    db.query(GlobalLock).filter(GlobalLock.acquired_at < ten_mins_ago).delete()

    # Check global lock
    existing_lock = db.query(GlobalLock).filter(GlobalLock.resource == "llm_unit").first()
    if existing_lock: raise HTTPException(status_code=423, detail="LLM unit locked")
    
    db.add(GlobalLock(resource="llm_unit", worker_id=worker_id, job_id=job.id))
    job.status = "PROCESSING"
    job.worker_id = worker_id
    job.locked_at = datetime.utcnow()
    db.commit()
    
    await sio.emit("job_update", {"job_id": job.id, "status": "PROCESSING", "sprint_id": job.sprint_id})
    return {"job_id": job.id, "agent_name": job.agent_name, "prompt": job.prompt, "sprint_id": job.sprint_id, "priority": job.priority}

@router.post("/llm/lock/release")
async def release_lock(worker_id: str, db: Session = Depends(get_db)):
    db.query(GlobalLock).filter(GlobalLock.worker_id == worker_id).delete()
    db.commit()
    return {"status": "ok"}

@router.post("/llm/trace")
async def log_trace(trace: LLMTraceSchema, db: Session = Depends(get_db)):
    from ..models import LLMTrace
    from ..app_instance import sio
    
    new_trace = LLMTrace(
        id=trace.id,
        job_id=trace.job_id,
        sprint_id=trace.sprint_id,
        agent_name=trace.agent_name,
        worker_id=trace.worker_id,
        execution_node=trace.execution_node,
        priority=trace.priority,
        prompt=trace.prompt,
        response=trace.response,
        status=trace.status,
        duration_ms=trace.duration_ms,
        project_name=trace.project_name,
        prompt_tokens=trace.prompt_tokens,
        completion_tokens=trace.completion_tokens,
        total_tokens=trace.total_tokens
    )
    db.add(new_trace)
    db.query(LLMJobRecord).filter(LLMJobRecord.id == trace.job_id).update({"status": "COMPLETED"})
    db.commit()
    
    await sio.emit("job_update", {"job_id": trace.job_id, "status": "COMPLETED", "sprint_id": trace.sprint_id})
    return {"status": "ok"}
