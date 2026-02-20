import os
import time
import uuid
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Optional
from queue import PriorityQueue

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import requests
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    Float,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import psutil
import json
from sqlalchemy import event, text

load_dotenv()

# --- CONFIGURATION ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
AGENT_MODEL = os.getenv("AGENT_MODEL", "llama3.1:latest")
DB_PATH = os.getenv("TRACE_DB_PATH", "/app/data/traceability.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SEC", "600"))

logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Orchestrator")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
AGENT_ROLE = os.getenv("AGENT_ROLE", "both")  # master, worker, both

# --- DATABASE SETUP ---
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
# Add busy_timeout to handle concurrent write contention (5s)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 5})
Base = declarative_base()


class LLMTrace(Base):
    __tablename__ = "llm_traces"
    id = Column(String, primary_key=True)
    sprint_id = Column(String)
    agent_name = Column(String)
    worker_id = Column(String)  # Track which worker did the job
    execution_node = Column(String)  # Track the host/container
    priority = Column(Integer)
    prompt = Column(Text)
    response = Column(Text)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    status = Column(String)
    duration_ms = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)


class LLMJobRecord(Base):
    __tablename__ = "llm_jobs"
    id = Column(String, primary_key=True)
    sprint_id = Column(String)
    agent_name = Column(String)
    priority = Column(Integer)
    prompt = Column(Text)
    params = Column(Text)  # JSON string
    status = Column(
        String, default="PENDING"
    )  # PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED
    worker_id = Column(String, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GlobalLock(Base):
    __tablename__ = "global_locks"
    resource = Column(String, primary_key=True)  # e.g. "ollama_gpu"
    worker_id = Column(String)
    job_id = Column(String)
    acquired_at = Column(DateTime, default=datetime.utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id = Column(String, primary_key=True)
    hostname = Column(String)
    last_seen = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


# --- GLOBAL METRICS ---
token_counters = {"prompt": 0, "completion": 0, "start_time": time.time()}


# --- QUEUE SYSTEM ---
class LLMJobRequest(BaseModel):
    agent_name: str
    sprint_id: str
    priority: int  # 1: Security, 2: TeamLead, 3: Dev, 4: Tester
    prompt: str
    params: Optional[dict] = {}


class LLMJobCompletion(BaseModel):
    result: str
    metrics: dict


class JobQueue:
    def __init__(self):
        # We still keep in-memory for fast signaling, but source of truth is DB
        self.active_job = None
        self.results = {}

    def submit(self, job: LLMJobRequest):
        job_id = str(uuid.uuid4())
        db = SessionLocal()
        db_job = LLMJobRecord(
            id=job_id,
            sprint_id=job.sprint_id,
            agent_name=job.agent_name,
            priority=job.priority,
            prompt=job.prompt,
            params=json.dumps(job.params or {}),
            status="PENDING",
        )
        db.add(db_job)
        db.commit()
        db.close()
        self.results[job_id] = {"status": "PENDING", "result": None}
        return job_id

    def get_status(self, job_id: str):
        # Prefer DB status if not in memory
        if job_id in self.results:
            return self.results[job_id]

        db = SessionLocal()
        job = db.query(LLMJobRecord).filter(LLMJobRecord.id == job_id).first()
        db.close()
        if job:
            return {"status": job.status}
        return None

    def cancel(self, job_id: str):
        db = SessionLocal()
        job = db.query(LLMJobRecord).filter(LLMJobRecord.id == job_id).first()
        if job:
            job.status = "CANCELLED"
            db.commit()
        db.close()
        if job_id in self.results:
            self.results[job_id]["status"] = "CANCELLED"
        return True


project_queue = JobQueue()

# --- API ---
app = FastAPI(title="AI Software Factory Orchestrator")


@app.get("/health")
def health():
    return {"status": "ok", "ollama": OLLAMA_URL}


@app.post("/llm/submit")
def submit_llm_job(job: LLMJobRequest):
    job_id = project_queue.submit(job)
    return {"job_id": job_id, "status": "QUEUED"}


@app.post("/jobs/pull")
def pull_job(worker_id: str, hostname: str):
    db = SessionLocal()
    # Atomic pull: Find highest priority PENDING job and mark as PROCESSING
    # SQLite BEGIN IMMEDIATE ensures we have a reserved lock before reading
    db.execute(text("BEGIN IMMEDIATE"))
    try:
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
            project_queue.results[job.id] = {"status": "PROCESSING", "result": None}
            db.commit()
            job_data = {
                "id": job.id,
                "agent_name": job.agent_name,
                "sprint_id": job.sprint_id,
                "prompt": job.prompt,
                "params": json.loads(job.params),
                "priority": job.priority,
            }
            return job_data
        db.rollback()
    except Exception as e:
        db.rollback()
        logger.error(f"Pull error: {e}")
    finally:
        db.close()
    return None


@app.post("/jobs/heartbeat")
def worker_heartbeat(worker_id: str, hostname: str):
    db = SessionLocal()
    hb = (
        db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
    )
    if not hb:
        hb = WorkerHeartbeat(worker_id=worker_id, hostname=hostname)
        db.add(hb)
    hb.last_seen = datetime.utcnow()
    db.commit()
    db.close()
    return {"status": "ok"}


@app.post("/jobs/complete/{job_id}")
def complete_job(job_id: str, data: LLMJobCompletion, worker_id: str):
    db = SessionLocal()
    job = db.query(LLMJobRecord).filter(LLMJobRecord.id == job_id).first()
    if job:
        result = data.result
        metrics = data.metrics
        job.status = "COMPLETED"
        # Persist Trace
        trace = LLMTrace(
            id=job_id,
            sprint_id=job.sprint_id,
            agent_name=job.agent_name,
            worker_id=worker_id,
            execution_node=metrics.get("hostname", "unknown"),
            priority=job.priority,
            prompt=job.prompt,
            response=result,
            prompt_tokens=metrics.get("prompt_tokens", 0),
            completion_tokens=metrics.get("completion_tokens", 0),
            total_tokens=metrics.get("prompt_tokens", 0)
            + metrics.get("completion_tokens", 0),
            status="SUCCESS",
            duration_ms=metrics.get("duration_ms", 0),
        )
        db.add(trace)
        db.commit()

        # Update memory status for API
        project_queue.results[job_id] = {
            "status": "COMPLETED",
            "result": result,
            "metrics": metrics,
        }
    db.close()
    return {"status": "ok"}


@app.post("/llm/lock/acquire")
def acquire_lock(worker_id: str, job_id: str):
    db = SessionLocal()
    try:
        # Atomic lock using SQLite primary key constraint
        db.execute(
            text(
                "INSERT INTO global_locks (resource, worker_id, job_id, acquired_at) VALUES ('ollama_gpu', :wid, :jid, :at)"
            ),
            {"wid": worker_id, "jid": job_id, "at": datetime.utcnow()},
        )
        db.commit()
        return {"status": "LOCKED"}
    except Exception:
        # Check if it's already locked by this worker (re-entrant-ish but simple)
        lock = db.query(GlobalLock).filter(GlobalLock.resource == "ollama_gpu").first()
        if lock and lock.worker_id == worker_id:
            return {"status": "LOCKED"}
        return HTTPException(status_code=423, detail="GPU Busy")
    finally:
        db.close()


@app.post("/llm/lock/release")
def release_lock(worker_id: str):
    db = SessionLocal()
    db.query(GlobalLock).filter(
        GlobalLock.resource == "ollama_gpu", GlobalLock.worker_id == worker_id
    ).delete()
    db.commit()
    db.close()
    return {"status": "RELEASED"}


@app.get("/llm/status/{job_id}")
def get_job_status(job_id: str):
    status = project_queue.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@app.delete("/llm/cancel/{job_id}")
def cancel_job(job_id: str):
    success = project_queue.cancel(job_id)
    return {"status": "CANCELLED" if success else "NOT_FOUND"}


@app.get("/sprints")
def list_sprints():
    db = SessionLocal()
    # Unique sprint IDs from traces and jobs
    sprints_jobs = [r[0] for r in db.query(LLMJobRecord.sprint_id).distinct().all()]
    sprints_traces = [r[0] for r in db.query(LLMTrace.sprint_id).distinct().all()]
    db.close()
    return {"sprints": list(set(sprints_jobs + sprints_traces))}


@app.get("/system/status")
def system_status():
    process = psutil.Process(os.getpid())
    db = SessionLocal()
    pending = db.query(LLMJobRecord).filter(LLMJobRecord.status == "PENDING").count()
    processing = (
        db.query(LLMJobRecord).filter(LLMJobRecord.status == "PROCESSING").count()
    )
    db.close()
    return {
        "queue_depth": pending,
        "active_jobs": processing,
        "memory_rss_mb": process.memory_info().rss / 1024 / 1024,
        "database": DB_PATH,
    }


@app.get("/traces/{sprint_id}")
def get_sprint_traces(sprint_id: str):
    db = SessionLocal()
    traces = (
        db.query(LLMTrace)
        .filter(LLMTrace.sprint_id == sprint_id)
        .order_by(LLMTrace.timestamp.desc())
        .all()
    )
    db.close()
    return {
        "traces": [
            {
                "id": t.id,
                "agent": t.agent_name,
                "status": t.status,
                "duration_ms": t.duration_ms,
                "timestamp": t.timestamp.isoformat(),
            }
            for t in traces
        ]
    }


@app.get("/jobs/{sprint_id}")
def get_sprint_jobs(sprint_id: str):
    db = SessionLocal()
    jobs = db.query(LLMJobRecord).filter(LLMJobRecord.sprint_id == sprint_id).all()
    db.close()
    return {
        "jobs": [
            {
                "id": j.id,
                "agent": j.agent_name,
                "status": j.status,
                "priority": j.priority,
                "created_at": j.created_at.isoformat(),
            }
            for j in jobs
        ]
    }


@app.get("/metrics")
def get_metrics():
    process = psutil.Process(os.getpid())
    uptime = time.time() - token_counters["start_time"]

    db = SessionLocal()
    # Priority Distribution
    dist = {}
    pending_jobs = (
        db.query(LLMJobRecord.priority).filter(LLMJobRecord.status == "PENDING").all()
    )
    for (p,) in pending_jobs:
        dist[p] = dist.get(p, 0) + 1

    # Tokens from traces
    from sqlalchemy import func

    total_tokens_row = db.query(func.sum(LLMTrace.total_tokens)).first()
    total_tokens = total_tokens_row[0] or 0
    db.close()

    return {
        "queue": {"depth": len(pending_jobs), "priority_distribution": dist},
        "performance": {
            "total_tokens": total_tokens,
            "token_rate_per_min": (total_tokens / (uptime / 60)) if uptime > 0 else 0,
            "uptime_sec": uptime,
        },
        "system": {
            "memory_rss_mb": process.memory_info().rss / 1024 / 1024,
            "cpu_percent": process.cpu_percent(),
        },
    }


# --- STARTUP LOGIC ---
MASTER_STARTUP_TIME = datetime.utcnow()


def master_startup_cleanup():
    """Reset any jobs stuck in PROCESSING from a previous crash."""
    logger.info("Running Master Startup Cleanup...")
    db = SessionLocal()
    try:
        orphaned_jobs = (
            db.query(LLMJobRecord).filter(LLMJobRecord.status == "PROCESSING").all()
        )
        grace_boundary = MASTER_STARTUP_TIME - timedelta(seconds=30)
        for job in orphaned_jobs:
            # Race Condition Mitigation:
            # 1. Check if the worker is active in heartbeats
            is_active = (
                db.query(WorkerHeartbeat)
                .filter(WorkerHeartbeat.worker_id == job.worker_id)
                .first()
            )

            # 2. Grace Period: Only reset if locked_at is before master startup - 30s
            if not is_active or (job.locked_at and job.locked_at < grace_boundary):
                logger.info(
                    f"Resetting orphaned job {job.id} (Worker {job.worker_id} stale or outside grace period)"
                )
                job.status = "PENDING"
                job.worker_id = None
        db.commit()
    except Exception as e:
        logger.error(f"Startup cleanup error: {e}")
    finally:
        db.close()


# --- WATCHDOG ---
def watchdog_loop():
    logger.info("Starting Orchestrator Watchdog...")
    while True:
        try:
            db = SessionLocal()
            now = datetime.utcnow()

            # 1. Release Stale Leases (Jobs stuck in PROCESSING without heartbeat)
            # Find jobs where worker hasn't reported heartbeat recently
            timeout_limit = now - timedelta(seconds=60)
            stale_workers = (
                db.query(WorkerHeartbeat)
                .filter(WorkerHeartbeat.last_seen < timeout_limit)
                .all()
            )

            for sw in stale_workers:
                logger.warning(f"Worker {sw.worker_id} is stale. Releasing jobs...")
                stale_jobs = (
                    db.query(LLMJobRecord)
                    .filter(
                        LLMJobRecord.worker_id == sw.worker_id,
                        LLMJobRecord.status == "PROCESSING",
                    )
                    .all()
                )
                for sj in stale_jobs:
                    logger.info(f"Returning job {sj.id} to PENDING")
                    sj.status = "PENDING"
                    sj.worker_id = None

                # Also release potential Ollama lock
                db.query(GlobalLock).filter(
                    GlobalLock.worker_id == sw.worker_id
                ).delete()
                db.delete(sw)

            # 2. Release Stale Global Locks
            abs_timeout = now - timedelta(seconds=(LLM_TIMEOUT + 60))
            stale_locks = db.query(GlobalLock).all()
            for lock in stale_locks:
                hb = (
                    db.query(WorkerHeartbeat)
                    .filter(WorkerHeartbeat.worker_id == lock.worker_id)
                    .first()
                )
                if not hb:
                    logger.warning(
                        f"Releasing lock for missing worker {lock.worker_id}"
                    )
                    db.delete(lock)
                elif lock.acquired_at < abs_timeout:
                    logger.warning(
                        f"Releasing absolute timeout lock for worker {lock.worker_id}"
                    )
                    db.delete(lock)

            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Watchdog error: {e}")
        time.sleep(10)


# --- BACKGROUND WORKER ---
def llm_worker():
    worker_id = f"local-worker-{uuid.uuid4().hex[:8]}"
    hostname = os.getenv("HOSTNAME", "localhost")
    logger.info(f"Starting Local Distributed Worker {worker_id}...")

    while True:
        try:
            # 1. Heartbeat
            requests.post(
                f"{ORCHESTRATOR_URL}/jobs/heartbeat?worker_id={worker_id}&hostname={hostname}"
            )

            # 2. Pull Job
            res = requests.post(
                f"{ORCHESTRATOR_URL}/jobs/pull?worker_id={worker_id}&hostname={hostname}"
            )
            if res.status_code != 200 or not res.json():
                time.sleep(2)
                continue

            job_data = res.json()
            job_id = job_data["id"]

            # 3. Determinism for Replay
            options = job_data["params"]
            if "[REPLAY]" in job_data["prompt"]:
                logger.info(
                    f"REPLAY detected for {job_id}. Forcing deterministic params."
                )
                options.update({"temperature": 0.0, "seed": 42, "top_p": 1.0})

            # 4. Acquire Global Lock
            lock_res = requests.post(
                f"{ORCHESTRATOR_URL}/llm/lock/acquire?worker_id={worker_id}&job_id={job_id}"
            )
            if lock_res.status_code != 200:
                # GPU Busy, wait a bit and retry pulling later (job is still in PROCESSING for us)
                # In a real app, we might want to release the job if we can't get the lock for a long time
                time.sleep(1)
                continue

            # 5. Execute
            process = psutil.Process(os.getpid())
            mem_before = process.memory_info().rss / 1024 / 1024
            logger.info(
                f"Worker {worker_id} starting job {job_id}. Memory: {mem_before:.1f}MB"
            )

            start_time = time.time()
            try:
                response = requests.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": AGENT_MODEL,
                        "prompt": job_data["prompt"],
                        "stream": False,
                        "options": options,
                    },
                    timeout=LLM_TIMEOUT,
                )
                response.raise_for_status()
                res_json = response.json()

                mem_after = process.memory_info().rss / 1024 / 1024
                logger.info(
                    f"Worker {worker_id} finished job {job_id}. Memory: {mem_after:.1f}MB (Growth: {mem_after - mem_before:.1f}MB)"
                )

                # 6. Complete
                metrics = {
                    "hostname": hostname,
                    "prompt_tokens": res_json.get("prompt_eval_count", 0),
                    "completion_tokens": res_json.get("eval_count", 0),
                    "duration_ms": (time.time() - start_time) * 1000,
                    "memory_growth_mb": mem_after - mem_before,
                }
                requests.post(
                    f"{ORCHESTRATOR_URL}/jobs/complete/{job_id}?worker_id={worker_id}",
                    json={"result": res_json["response"], "metrics": metrics},
                ).raise_for_status()

            except Exception as e:
                logger.error(f"Execution failed for {job_id}: {e}")
                # Mark as FAILED in DB if possible (though we might have no network)
                try:
                    requests.post(
                        f"{ORCHESTRATOR_URL}/jobs/complete/{job_id}?worker_id={worker_id}",
                        json={
                            "result": f"Error: {str(e)}",
                            "metrics": {"status": "FAILED"},
                        },
                    )
                except:
                    pass
            finally:
                # 7. Release Lock
                try:
                    requests.post(
                        f"{ORCHESTRATOR_URL}/llm/lock/release?worker_id={worker_id}"
                    ).raise_for_status()
                except Exception as le:
                    logger.error(f"Failed to release lock: {le}")

        except Exception as e:
            logger.error(f"Worker {worker_id} loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    # Start threads based on role
    if AGENT_ROLE in ["master", "both"]:
        logger.info("Running as MASTER (API + Watchdog)")
        master_startup_cleanup()
        threading.Thread(target=watchdog_loop, daemon=True).start()

    if AGENT_ROLE in ["worker", "both"]:
        logger.info("Running as WORKER")
        threading.Thread(target=llm_worker, daemon=True).start()

    if AGENT_ROLE in ["master", "both"]:
        import uvicorn

        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        # Just keep the worker thread alive
        while True:
            time.sleep(1)
