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
    """Update worker heartbeat. Cleanup is handled by the System watchdog or llm.py stale lock cleaner."""
    hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
    if not hb:
        hb = WorkerHeartbeat(worker_id=worker_id, hostname=hostname)
        db.add(hb)
    hb.last_seen = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.get("/jobs/{sprint_id}")
async def get_sprint_jobs(sprint_id: str, db: Session = Depends(get_db)):
    """List all jobs associated with a specific sprint. Used by the Dashboard UI."""
    jobs = db.query(LLMJobRecord).filter(LLMJobRecord.sprint_id == sprint_id).all()
    return {"status": "ok", "jobs": jobs}
