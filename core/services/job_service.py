import uuid
import json
import time
import asyncio
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from .. import config
from ..database import SessionLocal
from ..models import LLMJobRecord, LLMTrace, GlobalLock, WorkerHeartbeat
from ..utils import map_role, safe_json_loads, extract_files, install_dependencies, execute_setup_commands
from ..schemas import LLMJobRequest

class JobQueueService:
    def submit(self, job: LLMJobRequest):
        job_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(
                LLMJobRecord(
                    id=job_id,
                    sprint_id=job.sprint_id,
                    agent_name=job.agent_name,
                    priority=job.priority,
                    prompt=job.prompt,
                    params=json.dumps(job.params or {}, ensure_ascii=False),
                    status="PENDING",
                )
            )
            db.commit()
            return job_id
        except Exception as e:
            db.rollback()
            config.logger.error(f"Submit error: {e}")
            raise e
        finally:
            db.close()

job_queue_service = JobQueueService()

async def internal_submit_job(agent_name: str, sprint_id: str, priority: int, prompt: str, params: dict = None):
    agent_name = map_role(agent_name)
    job = LLMJobRequest(
        agent_name=agent_name,
        sprint_id=sprint_id,
        priority=priority,
        prompt=prompt,
        params=params or {}
    )
    job_id = job_queue_service.submit(job)
    return job_id
