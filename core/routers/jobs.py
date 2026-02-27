from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import json
import uuid
from ..database import get_db, SessionLocal
from ..models import LLMJobRecord, LLMTrace, WorkerHeartbeat
from ..schemas import LLMJobCompletion, LLMJobRequest
from .. import config
from ..app_instance import sio

router = APIRouter(tags=["Jobs"])

@router.post("/jobs/heartbeat")
def worker_heartbeat(worker_id: str, hostname: str, db: Session = Depends(get_db)):
    hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
    if not hb:
        hb = WorkerHeartbeat(worker_id=worker_id, hostname=hostname)
        db.add(hb)
    hb.last_seen = datetime.utcnow()
    db.commit()
    return {"status": "ok"}

@router.post("/jobs/pull")
async def pull_job(worker_id: str, hostname: str, db: Session = Depends(get_db)):
    # Use immediate transaction for atomic pull if possible (SQLite style)
    job = (
        db.query(LLMJobRecord)
        .filter(LLMJobRecord.status == "PENDING")
        .order_by(LLMJobRecord.priority.asc(), LLMJobRecord.created_at.asc())
        .first()
    )
    if job:
        job.status = "PROCESSING"
        job.worker_id = worker_id
        job.locked_at = datetime.utcnow()
        db.commit()
        
        await sio.emit("job_update", {
            "job_id": job.id, 
            "status": "PROCESSING", 
            "sprint_id": job.sprint_id,
            "agent": job.agent_name,
            "agent_name": job.agent_name
        })
        
        target_model = config.TEAMLEAD_MODEL if job.agent_name == "TeamLead" else config.AGENT_MODEL
        return {
            "id": job.id,
            "agent_name": job.agent_name,
            "sprint_id": job.sprint_id,
            "prompt": job.prompt,
            "params": json.loads(job.params or "{}"),
            "priority": job.priority,
            "model": target_model,
        }
    return None

@router.post("/jobs/complete/{job_id}")
async def complete_job(job_id: str, data: LLMJobCompletion, worker_id: str, db: Session = Depends(get_db)):
    job = db.query(LLMJobRecord).filter(LLMJobRecord.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job.status = "COMPLETED"
    
    new_trace = LLMTrace(
        id=str(uuid.uuid4()),
        sprint_id=job.sprint_id,
        agent_name=job.agent_name,
        worker_id=worker_id,
        execution_node=data.metrics.get("hostname", "unknown"),
        priority=job.priority,
        prompt=job.prompt,
        response=data.result,
        prompt_tokens=data.metrics.get("prompt_tokens", 0),
        completion_tokens=data.metrics.get("completion_tokens", 0),
        total_tokens=data.metrics.get("prompt_tokens", 0) + data.metrics.get("completion_tokens", 0),
        status="SUCCESS",
        duration_ms=data.metrics.get("duration_ms", 0),
    )
    db.add(new_trace)
    db.commit()
    
    await sio.emit("job_update", {
        "job_id": job_id, 
        "status": "COMPLETED", 
        "sprint_id": job.sprint_id,
        "agent": job.agent_name,
        "agent_name": job.agent_name
    })
    return {"status": "ok"}

@router.get("/jobs/{sprint_id}")
async def get_sprint_jobs(sprint_id: str, db: Session = Depends(get_db)):
    jobs = db.query(LLMJobRecord).filter(LLMJobRecord.sprint_id == sprint_id).all()
    return {"status": "ok", "jobs": jobs}
