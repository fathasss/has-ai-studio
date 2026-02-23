import os
import re
import time
import uuid
import logging
import threading
import json
import asyncio
import pynvml
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
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
    event,
    text,
    func,
)
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.orm import declarative_base as legacy_declarative_base
from dotenv import load_dotenv
import psutil
import socketio

load_dotenv()

# --- CONFIGURATION ENGINE ---
CONFIG_PATH = "data/config.json"
DEFAULT_CONFIG = {
    "AGENT_MODEL": os.getenv("AGENT_MODEL", "llama3.1:latest"),
    "TEAMLEAD_MODEL": os.getenv("TEAMLEAD_MODEL", "llama3.1:latest"),
    "OLLAMA_URL": os.getenv("OLLAMA_URL", "http://has-ai-ollama:11434"),
    "LLM_PROVIDER": "ollama",
    "LLM_API_KEY": "",
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except:
        return DEFAULT_CONFIG


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f)

def load_prompt(filename: str, key: str, fallback: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get(key, fallback)
    except Exception as e:
        logger.warning(f"Could not load prompt {key} from {filename}: {e}")
        return fallback

runtime_config = load_config()

OLLAMA_URL = runtime_config["OLLAMA_URL"]
AGENT_MODEL = runtime_config["AGENT_MODEL"]
TEAMLEAD_MODEL = runtime_config.get("TEAMLEAD_MODEL", AGENT_MODEL)
DB_PATH = os.getenv("TRACE_DB_PATH", "data/traceability.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SEC", "600"))

logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Orchestrator")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://has-ai-orchestrator:8000")
AGENT_ROLE = os.getenv("AGENT_ROLE", "both")

# --- DATABASE SETUP ---
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 5})


class Base(DeclarativeBase):
    pass


class LLMTrace(Base):
    __tablename__ = "llm_traces"
    id = Column(String, primary_key=True)
    sprint_id = Column(String)
    agent_name = Column(String)
    worker_id = Column(String)
    execution_node = Column(String)
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
    params = Column(Text)
    status = Column(String, default="PENDING")
    worker_id = Column(String, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GlobalLock(Base):
    __tablename__ = "global_locks"
    resource = Column(String, primary_key=True)
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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- UTILS ---
def extract_files(text: str, project_dir: str):
    pattern = r"### FILE:\s*([^\n\r\*` ]+)(.*?)(?=### FILE:|$)"
    matches = re.finditer(pattern, text, re.DOTALL)
    created_files = []
    for match in matches:
        raw_path = match.group(1).strip()
        content = match.group(2).strip()
        code_block_match = re.search(r"```(?:\w+)?\s*(.*?)\s*```", content, re.DOTALL)
        if code_block_match:
            content = code_block_match.group(1)
        rel_path = raw_path.replace("\\", "/").lstrip("/")
        if ".." in rel_path:
            continue
        full_path = os.path.join(project_dir, rel_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            created_files.append(rel_path)
            logger.info(f"Extracted: {full_path}")
        except Exception as e:
            logger.error(f"Extract failed {raw_path}: {e}")
    return created_files


def safe_json_loads(text: str):
    if not text:
        return None
    text = text.strip()
    
    # Try direct parse
    try:
        return json.loads(text)
    except:
        pass
        
    # Helper to clean up common LLM JSON errors
    def clean_json_str(s):
        # Remove trailing commas before closing braces/brackets
        s = re.sub(r',\s*\}', '}', s)
        s = re.sub(r',\s*\]', ']', s)
        return s

    # Try extracting markdown blocks
    json_blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    for block in json_blocks:
        try:
            return json.loads(clean_json_str(block.strip()))
        except:
            pass

    # Try finding any JSON-like object
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(clean_json_str(match.group(1).strip()))
        except:
            pass
            
    # Absolute fallback: if everything fails, at least regex out the project_name
    fallback = {}
    pmatch = re.search(r'"project_name"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
    if pmatch:
        fallback["project_name"] = pmatch.group(1)
    
    return fallback if fallback else None


token_counters = {"prompt": 0, "completion": 0, "start_time": time.time()}


class LLMJobRequest(BaseModel):
    agent_name: str
    sprint_id: str
    priority: int
    prompt: str
    params: Optional[dict] = {}

class ChatRequest(BaseModel):
    history: list
    params: Optional[dict] = {}

class ExecuteRequest(BaseModel):
    sprint_id: str
    plan: dict
    history: list

class LLMJobCompletion(BaseModel):
    result: str
    metrics: dict


class JobQueue:
    def __init__(self):
        self.results = {}

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
                    params=json.dumps(job.params or {}),
                    status="PENDING",
                )
            )
            db.commit()
            return job_id
        except Exception as e:
            db.rollback()
            logger.error(f"Submit error: {e}")
            raise e
        finally:
            db.close()


project_queue = JobQueue()

# --- API ---
app = FastAPI(title="HAS-AI-TEAM")
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
sio_app = socketio.ASGIApp(sio, app)


@app.get("/")
async def root():
    return {"message": "HAS-AI-TEAM Orchestrator API", "status": "running"}


@app.get("/config")
async def get_config():
    return load_config()


@app.post("/config")
async def update_config(new_cfg: dict):
    global runtime_config, OLLAMA_URL, AGENT_MODEL, TEAMLEAD_MODEL
    curr = load_config()
    curr.update(new_cfg)
    save_config(curr)
    runtime_config = curr
    OLLAMA_URL = curr["OLLAMA_URL"]
    AGENT_MODEL = curr["AGENT_MODEL"]
    TEAMLEAD_MODEL = curr.get("TEAMLEAD_MODEL", AGENT_MODEL)
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "ollama": OLLAMA_URL}


@app.post("/llm/submit")
async def submit_llm_job(job: LLMJobRequest):
    try:
        job_id = project_queue.submit(job)
        await sio.emit(
            "job_update",
            {
                "job_id": job_id,
                "agent": job.agent_name,
                "status": "PENDING",
                "sprint_id": job.sprint_id,
            },
        )
        return {"job_id": job_id, "status": "QUEUED"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/teamlead")
async def chat_teamlead(req: ChatRequest):
    sys_content = load_prompt("teamlead.json", "TM_teamlead_chat", "Error: Prompt missing")
    sys_prompt = {"role": "system", "content": sys_content}
    messages = [sys_prompt] + req.history
    try:
        res = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": TEAMLEAD_MODEL,
                "messages": messages,
                "stream": False,
                "options": req.params
            },
            timeout=120
        ).json()
        return {"response": res.get("message", {}).get("content", "")}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/preview")
async def chat_preview(req: ChatRequest):
    # Same prompt used in the orchestrator worker for TeamLead plan generation
    sys = load_prompt("teamlead.json", "TM_teamlead_preview", "Error: Prompt missing")
    
    # We add this system message at the END to force it to output JSON for the preview
    formatted_history = "\n".join([f"[{m.get('role', '').upper()}]: {m.get('content', '')}" for m in req.history])
    final_prompt = f"{sys}\n\nGEÇMİŞ:\n{formatted_history}\n\nLÜTFEN SADECE JSON ÇIKTISI ÜRET."
    
    try:
        res = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": TEAMLEAD_MODEL,
                "prompt": final_prompt,
                "stream": False,
                "options": req.params
            },
            timeout=120
        ).json()
        return {"response": res.get("response", "")}
    except Exception as e:
        logger.error(f"Preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sprint/execute")
async def execute_sprint(req: ExecuteRequest):
    # This endpoint locks in the exact previewed JSON plan
    db = SessionLocal()
    try:
        # Create a synthetic trace representing TeamLead's final decision
        # so that extract_files can read the project_name deterministically
        db.add(
            LLMTrace(
                id=str(uuid.uuid4()),
                sprint_id=req.sprint_id,
                agent_name="TeamLead",
                worker_id="orchestrator",
                execution_node="orchestrator",
                priority=1,
                prompt="Generated from UI Preview",
                response=f"```json\n{json.dumps(req.plan, indent=2)}\n```",
                status="SUCCESS"
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Execute trace error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

    # Automatically queue Dev tasks from the exact plan
    queued_jobs = []
    if req.plan and "tasks" in req.plan:
        for t in req.plan["tasks"]:
            role = t.get("role")
            if role in ["Frontend", "Backend", "Tester", "Security"]:
                try:
                    priority = 3 if role in ["Tester", "Security"] else 2
                    res = requests.post(
                        f"{ORCHESTRATOR_URL}/llm/submit",
                        json={
                            "agent_name": role,
                            "sprint_id": req.sprint_id,
                            "priority": priority,
                            "prompt": t.get("task", ""),
                        },
                        timeout=5,
                    )
                    queued_jobs.append(role)
                except Exception as e:
                    logger.error(f"Execute submit error for {role}: {e}")

    await sio.emit("job_update", {"job_id": "system", "status": "COMPLETED", "sprint_id": req.sprint_id})
    return {"status": "ok", "queued": queued_jobs}

@app.post("/jobs/pull")
async def pull_job(worker_id: str, hostname: str):
    db = SessionLocal()
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        job = (
            db.query(LLMJobRecord)
            .filter(LLMJobRecord.status == "PENDING")
            .order_by(LLMJobRecord.priority.asc(), LLMJobRecord.created_at.asc())
            .first()
        )
        if job:
            job.status, job.worker_id, job.locked_at = (
                "PROCESSING",
                worker_id,
                datetime.utcnow(),
            )
            db.commit()
            await sio.emit(
                "job_update",
                {"job_id": job.id, "status": "PROCESSING", "sprint_id": job.sprint_id},
            )

            # Decide model
            target_model = (
                TEAMLEAD_MODEL if job.agent_name == "TeamLead" else AGENT_MODEL
            )

            return {
                "id": job.id,
                "agent_name": job.agent_name,
                "sprint_id": job.sprint_id,
                "prompt": job.prompt,
                "params": json.loads(job.params),
                "priority": job.priority,
                "model": target_model,
            }
        db.rollback()
    except Exception as e:
        db.rollback()
        logger.error(f"Pull error: {e}")
    finally:
        db.close()
    return None


@app.post("/jobs/heartbeat")
def worker_heartbeat(worker_id: str, hostname: str, db: Session = Depends(get_db)):
    hb = (
        db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
    )
    if not hb:
        hb = WorkerHeartbeat(worker_id=worker_id, hostname=hostname)
        db.add(hb)
    hb.last_seen = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@app.post("/jobs/complete/{job_id}")
async def complete_job(
    job_id: str, data: LLMJobCompletion, worker_id: str, db: Session = Depends(get_db)
):
    job = db.query(LLMJobRecord).filter(LLMJobRecord.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "COMPLETED"
    db.add(
        LLMTrace(
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
            total_tokens=data.metrics.get("prompt_tokens", 0)
            + data.metrics.get("completion_tokens", 0),
            status="SUCCESS",
            duration_ms=data.metrics.get("duration_ms", 0),
        )
    )
    token_counters["prompt"] += data.metrics.get("prompt_tokens", 0)
    token_counters["completion"] += data.metrics.get("completion_tokens", 0)
    db.commit()
    await sio.emit(
        "job_update",
        {"job_id": job_id, "status": "COMPLETED", "sprint_id": job.sprint_id},
    )
    await sio.emit("metric_update", {"tokens": token_counters})
    return {"status": "ok"}


@app.post("/llm/lock/acquire")
def acquire_lock(worker_id: str, job_id: str, db: Session = Depends(get_db)):
    try:
        db.execute(
            text(
                "INSERT INTO global_locks (resource, worker_id, job_id, acquired_at) VALUES ('ollama_gpu', :wid, :jid, :at)"
            ),
            {"wid": worker_id, "jid": job_id, "at": datetime.utcnow()},
        )
        db.commit()
        return {"status": "LOCKED"}
    except:
        lock = db.query(GlobalLock).filter(GlobalLock.resource == "ollama_gpu").first()
        if lock and lock.worker_id == worker_id:
            return {"status": "LOCKED"}
        raise HTTPException(status_code=423, detail="GPU Busy")


@app.post("/llm/lock/release")
def release_lock(worker_id: str, db: Session = Depends(get_db)):
    db.query(GlobalLock).filter(
        GlobalLock.resource == "ollama_gpu", GlobalLock.worker_id == worker_id
    ).delete()
    db.commit()
    return {"status": "RELEASED"}


@app.get("/sprints")
def list_sprints(db: Session = Depends(get_db)):
    s1 = db.query(LLMJobRecord.sprint_id).distinct().all()
    s2 = db.query(LLMTrace.sprint_id).distinct().all()
    return {"sprints": list(set([x[0] for x in s1] + [x[0] for x in s2]))}


@app.get("/system/status")
def get_system_status(db: Session = Depends(get_db)):
    process = psutil.Process(os.getpid())
    pending = db.query(LLMJobRecord).filter(LLMJobRecord.status == "PENDING").count()
    processing = (
        db.query(LLMJobRecord).filter(LLMJobRecord.status == "PROCESSING").count()
    )
    active_jobs = (
        db.query(LLMJobRecord)
        .filter(LLMJobRecord.status.in_(["PROCESSING", "PENDING"]))
        .all()
    )
    agent_states = {
        "TeamLead": "idle",
        "Frontend": "idle",
        "Backend": "idle",
        "Security": "idle",
        "Tester": "idle",
    }
    for job in active_jobs:
        st = "PROCESSING" if job.status == "PROCESSING" else "PENDING"
        if agent_states.get(job.agent_name) != "PROCESSING":
            agent_states[job.agent_name] = st
    return {
        "queue_depth": pending,
        "active_jobs": processing,
        "memory_rss_mb": process.memory_info().rss / 1024 / 1024,
        "agent_states": agent_states,
    }


@app.get("/ollama/models")
def get_ollama_models():
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        res.raise_for_status()
        data = res.json()
        models = [m.get("name") for m in data.get("models", [])]
        return {"models": models}
    except Exception as e:
        logger.error(f"Failed to fetch ollama models: {e}")
        return {"models": [], "error": str(e)}

class PullModelRequest(BaseModel):
    model: str

@app.post("/ollama/pull")
async def pull_ollama_model(req: PullModelRequest):
    try:
        # stream=False kullanarak bloklayıcı istek atıyoruz
        res = requests.post(
            f"{OLLAMA_URL}/api/pull", 
            json={"name": req.model, "stream": False},
            timeout=1200 # Büyük modeller için uzun timeout
        )
        res.raise_for_status()
        return {"status": "success", "message": f"Model {req.model} successfully pulled."}
    except Exception as e:
        logger.error(f"Failed to pull ollama model {req.model}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/traces/{sprint_id}")
def get_traces_by_sprint(sprint_id: str, db: Session = Depends(get_db)):
    traces = (
        db.query(LLMTrace)
        .filter(LLMTrace.sprint_id == sprint_id)
        .order_by(LLMTrace.timestamp.desc())
        .all()
    )
    return {
        "traces": [
            {
                "agent": t.agent_name,
                "status": t.status,
                "duration_ms": t.duration_ms,
                "timestamp": t.timestamp.isoformat(),
                "response": t.response,
            }
            for t in traces
        ]
    }

@app.get("/traces")
def get_global_traces(db: Session = Depends(get_db)):
    traces = (
        db.query(LLMTrace)
        .order_by(LLMTrace.timestamp.desc())
        .limit(50)
        .all()
    )
    return {
        "traces": [
            {
                "sprint_id": t.sprint_id,
                "agent": t.agent_name,
                "status": t.status,
                "duration_ms": t.duration_ms,
                "timestamp": t.timestamp.isoformat(),
                "response": t.response,
            }
            for t in traces
        ]
    }


@app.get("/jobs/{sprint_id}")
def get_jobs(sprint_id: str, db: Session = Depends(get_db)):
    jobs = db.query(LLMJobRecord).filter(LLMJobRecord.sprint_id == sprint_id).all()
    return {
        "jobs": [
            {"agent": j.agent_name, "status": j.status, "priority": j.priority}
            for j in jobs
        ]
    }


@app.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    uptime = time.time() - token_counters["start_time"]
    total_tokens = db.query(func.sum(LLMTrace.total_tokens)).first()[0] or 0
    return {
        "performance": {
            "total_tokens": total_tokens,
            "token_rate_per_min": (total_tokens / (uptime / 60)) if uptime > 0 else 0,
            "uptime_sec": uptime,
        }
    }


# --- LOOPS ---
def watchdog_loop():
    logger.info("Watchdog started.")
    while True:
        db = SessionLocal()
        try:
            limit = datetime.utcnow() - timedelta(seconds=60)
            stale_workers = (
                db.query(WorkerHeartbeat)
                .filter(WorkerHeartbeat.last_seen < limit)
                .all()
            )
            for sw in stale_workers:
                db.query(LLMJobRecord).filter(
                    LLMJobRecord.worker_id == sw.worker_id,
                    LLMJobRecord.status == "PROCESSING",
                ).update({"status": "PENDING", "worker_id": None})
                db.query(GlobalLock).filter(
                    GlobalLock.worker_id == sw.worker_id
                ).delete()
                db.delete(sw)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Watchdog error: {e}")
        finally:
            db.close()
        time.sleep(10)

def get_agent_states(db: Session):
    active_jobs = (
        db.query(LLMJobRecord)
        .filter(LLMJobRecord.status.in_(["PROCESSING", "PENDING"]))
        .all()
    )
    agent_states = {
        "TeamLead": "IDLE",
        "Frontend": "IDLE",
        "Backend": "IDLE",
        "Security": "IDLE",
        "Tester": "IDLE",
    }
    for job in active_jobs:
        st = "PROCESSING" if job.status == "PROCESSING" else "PENDING"
        if agent_states.get(job.agent_name) != "PROCESSING":
            agent_states[job.agent_name] = st
    return agent_states

async def metrics_loop():
    import asyncio
    logger.info("Metrics loop started.")
    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            
            db = SessionLocal()
            try:
                agent_states = get_agent_states(db)
            finally:
                db.close()
            
            try:
                pynvml.nvmlInit()
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu = util.gpu
                pynvml.nvmlShutdown()
            except Exception:
                gpu = 0
            
            payload = {
                "cpu": cpu,
                "ram": ram,
                "disk": disk,
                "gpu": gpu,
                "agent_states": agent_states
            }
            await sio.emit("system_update", payload)
        except Exception as e:
            logger.error(f"Metrics loop error: {e}")
        
        await asyncio.sleep(2)


def llm_worker():
    worker_id, hostname = f"worker-{uuid.uuid4().hex[:4]}", os.getenv(
        "HOSTNAME", "localhost"
    )
    logger.info(f"Worker {worker_id} started on {hostname}")
    while True:
        try:
            try:
                requests.post(
                    f"{ORCHESTRATOR_URL}/jobs/heartbeat?worker_id={worker_id}&hostname={hostname}",
                    timeout=5,
                )
            except requests.exceptions.ConnectionError:
                logger.info("Orchestrator not reachable yet, retrying...")
                time.sleep(5)
                continue

            res = requests.post(
                f"{ORCHESTRATOR_URL}/jobs/pull?worker_id={worker_id}&hostname={hostname}",
                timeout=5,
            )
            if res.status_code != 200 or not res.json():
                time.sleep(2)
                continue
            job = res.json()
            jid, agent, sid, model = (
                job["id"],
                job["agent_name"],
                job["sprint_id"],
                job["model"],
            )
            if (
                requests.post(
                    f"{ORCHESTRATOR_URL}/llm/lock/acquire?worker_id={worker_id}&job_id={jid}",
                    timeout=5,
                ).status_code
                != 200
            ):
                time.sleep(1)
                continue

            db = SessionLocal()
            try:
                prior = (
                    db.query(LLMTrace)
                    .filter(LLMTrace.sprint_id == sid, LLMTrace.status == "SUCCESS")
                    .all()
                )
            finally:
                db.close()

            ctx = "Prior Work:\n" + "\n".join(
                [f"{p.agent_name}: {p.response}" for p in prior]
            )
            sys = "Error: Prompt missing"
            if agent == "TeamLead":
                sys = load_prompt("teamlead.json", "TM_teamlead_worker", sys)
            elif agent == "Frontend":
                sys = load_prompt("frontend.json", "FE_frontend_worker", sys)
            elif agent == "Backend":
                sys = load_prompt("backend.json", "BE_backend_worker", sys)
            elif agent == "Security":
                sys = load_prompt("security.json", "SM_security_worker", sys)
            elif agent == "Tester":
                sys = load_prompt("tester.json", "TT_tester_worker", sys)

            start = time.time()
            ollama = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": f"{sys}\n{ctx}\nTask: {job['prompt']}",
                    "stream": False,
                    "options": job["params"],
                },
                timeout=LLM_TIMEOUT,
            ).json()
            resp = ollama.get("response", "")
            
            target_dir = f"apps/{sid}"
            db = SessionLocal()
            try:
                tl_trace = db.query(LLMTrace).filter(
                    LLMTrace.sprint_id == sid, 
                    LLMTrace.agent_name == "TeamLead"
                ).order_by(LLMTrace.timestamp.desc()).first()
                if tl_trace:
                    plan = safe_json_loads(tl_trace.response)
                    if plan and "project_name" in plan:
                        import string
                        safe_name = "".join(c for c in plan["project_name"] if c.isalnum() or c in (" ", "-", "_")).strip()
                        safe_name = safe_name.replace(" ", "-").lower()
                        if safe_name:
                            target_dir = f"apps/{safe_name}"
            finally:
                db.close()
                
            if agent != "TeamLead":
                extract_files(resp, target_dir)
            requests.post(
                f"{ORCHESTRATOR_URL}/jobs/complete/{jid}?worker_id={worker_id}",
                json={
                    "result": resp,
                    "metrics": {
                        "hostname": hostname,
                        "duration_ms": (time.time() - start) * 1000,
                        "prompt_tokens": ollama.get("prompt_eval_count", 0),
                        "completion_tokens": ollama.get("eval_count", 0),
                    },
                },
                timeout=10,
            )
            requests.post(
                f"{ORCHESTRATOR_URL}/llm/lock/release?worker_id={worker_id}", timeout=5
            )

            if agent == "TeamLead":
                plan = safe_json_loads(resp)
                if plan and "tasks" in plan:
                    for t in plan["tasks"]:
                        role = t.get("role")
                        if role in ["Frontend", "Backend"]:
                            requests.post(
                                f"{ORCHESTRATOR_URL}/llm/submit",
                                json={
                                    "agent_name": role,
                                    "sprint_id": sid,
                                    "priority": 2,
                                    "prompt": t.get("task", ""),
                                },
                                timeout=5,
                            )

            if agent in ["Frontend", "Backend"]:
                db = SessionLocal()
                try:
                    tot = (
                        db.query(LLMJobRecord)
                        .filter(
                            LLMJobRecord.sprint_id == sid,
                            func.lower(LLMJobRecord.agent_name).in_(
                                ["frontend", "backend"]
                            ),
                        )
                        .count()
                    )
                    done = (
                        db.query(LLMJobRecord)
                        .filter(
                            LLMJobRecord.sprint_id == sid,
                            func.lower(LLMJobRecord.agent_name).in_(
                                ["frontend", "backend"]
                            ),
                            LLMJobRecord.status == "COMPLETED",
                        )
                        .count()
                    )
                finally:
                    db.close()
                
                # Deterministic QA Trigger
                if tot > 0 and done == tot:
                    # Sadece Dev görevleri tamamsa QA kuyruğa girsin (tek seferlik tetiklenme)
                    # Check if already triggered
                    db = SessionLocal()
                    try:
                        qa_exists = db.query(LLMJobRecord).filter(
                            LLMJobRecord.sprint_id == sid,
                            LLMJobRecord.agent_name == "Tester"
                        ).first()
                    finally:
                        db.close()
                        
                    if not qa_exists:
                        # Queue Security
                        requests.post(
                            f"{ORCHESTRATOR_URL}/llm/submit",
                            json={
                                "agent_name": "Security",
                                "sprint_id": sid,
                                "priority": 3,
                                "prompt": f"Please review the code generated for project in {target_dir} and output security_audit.md.",
                            },
                            timeout=5,
                        )
                        # Queue Tester
                        requests.post(
                            f"{ORCHESTRATOR_URL}/llm/submit",
                            json={
                                "agent_name": "Tester",
                                "sprint_id": sid,
                                "priority": 4,
                                "prompt": f"Please thoroughly review and test the code generated in {target_dir}. Write unit tests to tests/test_main.py. If any issues or errors are found, you MUST append '### RESULT: FAILED' at the very end of your response.",
                            },
                            timeout=5,
                        )

            # Max Feedback Loop Logic
            if agent == "Tester" and "FAILED" in resp.upper():
                db = SessionLocal()
                try:
                    failed_count = (
                        db.query(LLMTrace)
                        .filter(
                            LLMTrace.sprint_id == sid,
                            LLMTrace.agent_name == "Tester",
                            LLMTrace.response.like("%FAILED%")
                        )
                        .count()
                    )
                finally:
                    db.close()
                logger.warning(f"Tester reported FAILED for {sid}. Previous failures: {failed_count - 1}")
                if failed_count <= 3:
                     # Re-submit TeamLead with bug fix instructions
                     requests.post(
                         f"{ORCHESTRATOR_URL}/llm/submit",
                         json={
                             "agent_name": "TeamLead",
                             "sprint_id": sid,
                             "priority": 1, # High Priority Fix
                             "prompt": f"BUGS DETECTED BY TESTER. Max Feedback Cycle: {failed_count}/3. \nReview the following tester report and output a new JSON plan to assign fixing tasks to Frontend/Backend ONLY.\n\nTESTER REPORT:\n{resp}\n\nOutput JSON ONLY.",
                         },
                         timeout=5,
                     )
                else:
                     logger.error(f"Max feedback cycle reached for {sid} (Count: {failed_count}). Aborting further auto-fixes.")
        except Exception as e:
            logger.error(f"Worker err: {e}")
            time.sleep(5)


@app.on_event("startup")
async def startup_event():
    if AGENT_ROLE in ["master", "both"]:
        logger.info("Starting Master background tasks...")
        threading.Thread(target=watchdog_loop, daemon=True).start()
        # Schedule metrics loop on the same event loop as FastAPI/SocketIO
        asyncio.create_task(metrics_loop())
    
    if AGENT_ROLE in ["worker", "both"]:
        logger.info("Starting Worker background thread...")
        threading.Thread(target=llm_worker, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(sio_app, host="0.0.0.0", port=8000)
