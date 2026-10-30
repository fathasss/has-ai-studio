import os
import re
import time
import json
import uuid
import threading
import asyncio
import httpx
import requests
import psutil
import pynvml
from datetime import datetime, timedelta
from sqlalchemy import func
from .. import config
from ..database import SessionLocal
from ..models import (
    LLMJobRecord, LLMTrace, GlobalLock, WorkerHeartbeat
)
from ..utils import (
    safe_json_loads, log_project_exception, extract_files,
    get_project_context, map_role, task_to_prompt
)
from ..prompts import load_prompt

worker_id = str(uuid.uuid4())
START_TIME = time.time()

_GPU_AVAILABLE = False
_GPU_HANDLE = None
try:
    pynvml.nvmlInit()
    _GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    _GPU_AVAILABLE = True
    config.logger.info("GPU monitoring initialized.")
except Exception:
    config.logger.info("No GPU found or pynvml unavailable. GPU metrics will be 0.")


def _get_gpu_utilization() -> int:
    if _GPU_AVAILABLE and _GPU_HANDLE:
        try:
            return pynvml.nvmlDeviceGetUtilizationRates(_GPU_HANDLE).gpu
        except Exception:
            pass
    return 0


async def metrics_loop(sio):
    config.logger.info("Metrics loop started.")
    disk_root = os.path.abspath(os.sep)
    while True:
        try:
            cpu_val  = psutil.cpu_percent()
            ram_val  = psutil.virtual_memory().percent
            disk_val = psutil.disk_usage(disk_root).percent
            gpu_val  = _get_gpu_utilization()

            proc = psutil.Process(os.getpid())
            uptime_sec = int(time.time() - proc.create_time())

            agent_states = {}
            tokens_min   = 0

            db = SessionLocal()
            try:
                timeout = datetime.utcnow() - timedelta(seconds=90)
                active_workers = db.query(WorkerHeartbeat).filter(
                    WorkerHeartbeat.last_seen > timeout
                ).count()

                if active_workers > 0:
                    roles = ["TeamLead", "Frontend", "Backend", "Database", "Documenter", "Tester", "Security", "DevOps"]
                    for r in roles:
                        agent_states[r] = "AVAIL"

                    active_jobs = db.query(LLMJobRecord).filter(
                        LLMJobRecord.status == "PROCESSING"
                    ).all()
                    for job in active_jobs:
                        for r in agent_states.keys():
                            if (job.agent_name or "").lower() == r.lower():
                                agent_states[r] = "WORKING"

                timeout_stats = datetime.utcnow() - timedelta(minutes=1)
                recent_traces = db.query(LLMTrace).filter(
                    LLMTrace.timestamp > timeout_stats
                ).all()
                total_chars = sum(
                    len(t.response or "") + len(t.prompt or "")
                    for t in recent_traces
                )
                tokens_min = int(total_chars / 4)

            except Exception as e:
                config.logger.error(f"DB metrics query error: {e}")
            finally:
                db.close()

            try:
                net_io = psutil.net_io_counters()
                if not hasattr(metrics_loop, "last_net_io"):
                    metrics_loop.last_net_io   = net_io
                    metrics_loop.last_net_time = time.time()

                now = time.time()
                dt  = max(now - metrics_loop.last_net_time, 0.001)

                sent_speed = max(0.0, (net_io.bytes_sent - metrics_loop.last_net_io.bytes_sent) / dt)
                recv_speed = max(0.0, (net_io.bytes_recv - metrics_loop.last_net_io.bytes_recv) / dt)

                metrics_loop.last_net_io   = net_io
                metrics_loop.last_net_time = now
            except Exception as e:
                config.logger.error(f"Network metrics error: {e}")
                sent_speed, recv_speed = 0, 0

            metrics = {
                "cpu": cpu_val, "ram": ram_val, "gpu": gpu_val, "disk": disk_val,
                "net_sent": sent_speed, "net_recv": recv_speed,
                "uptime": uptime_sec, "tokens_min": tokens_min,
                "agent_states": agent_states,
                "timestamp": datetime.now().isoformat()
            }
            await sio.emit("system_update", metrics, namespace="/")

        except Exception as outer_e:
            config.logger.error(f"CRITICAL in metrics_loop: {outer_e}")

        await asyncio.sleep(2)


def watchdog_loop():
    """Cleans up dead workers whose background heartbeat stopped for >90s."""
    while True:
        db = SessionLocal()
        try:
            timeout = datetime.utcnow() - timedelta(seconds=90)
            db.query(WorkerHeartbeat).filter(WorkerHeartbeat.last_seen < timeout).delete(synchronize_session="fetch")
            expired_locks = db.query(GlobalLock).filter(
                ~GlobalLock.worker_id.in_(db.query(WorkerHeartbeat.worker_id))
            ).all()
            for lock in expired_locks:
                config.logger.warning(f"Watchdog releasing orphaned lock for dead worker '{lock.worker_id}' (job={lock.job_id})")
                db.query(LLMJobRecord).filter(
                    LLMJobRecord.id == lock.job_id,
                    LLMJobRecord.status == "PROCESSING",
                ).update(
                    {"status": "PENDING", "worker_id": None, "locked_at": None},
                    synchronize_session="fetch",
                )
                db.delete(lock)

            # Auto-prune office gossip traces older than 24h to keep SQLite DB fast and compact
            trace_retention = datetime.utcnow() - timedelta(hours=24)
            db.query(LLMTrace).filter(
                LLMTrace.sprint_id == "idle",
                LLMTrace.timestamp < trace_retention
            ).delete(synchronize_session=False)

            db.commit()
        except Exception as e:
            db.rollback()
            config.logger.error(f"Watchdog err: {e}")
        finally:
            db.close()
        time.sleep(30)


def _heartbeat_loop(hostname: str):
    """
    Dedicated daemon thread sending worker heartbeats every 15s.
    Runs independently of blocking LLM inference calls (up to 600s+),
    preventing false watchdog lock eviction and UI 'DOWN' flickers.
    """
    while True:
        try:
            requests.post(
                f"{config.ORCHESTRATOR_URL}/jobs/heartbeat",
                params={"worker_id": worker_id, "hostname": hostname},
                timeout=5,
            )
        except Exception as e:
            config.logger.debug(f"Heartbeat API error: {e}")
        time.sleep(15)


def _sync_worker_config():
    """
    Synchronizes active node/model/provider settings from the Orchestrator
    (with disk fallback) before each job so Settings UI updates apply immediately.
    """
    try:
        resp = requests.get(f"{config.ORCHESTRATOR_URL}/config", timeout=3)
        if resp.status_code == 200:
            cfg = resp.json()
            if isinstance(cfg, dict) and "NODES" in cfg:
                config.refresh_runtime_config(cfg)
                return
    except Exception:
        pass
    config.reload_runtime_config()


def _report_exception(sprint_id: str, source: str, command: str, error_message: str):
    """Reports exception via Orchestrator API (for live Socket.IO emit + shared DB) with local DB fallback."""
    if not sprint_id:
        return
    try:
        resp = requests.post(
            f"{config.ORCHESTRATOR_URL}/exceptions",
            json={
                "sprint_id": sprint_id,
                "source": source,
                "command": command,
                "error_message": error_message,
            },
            timeout=5,
        )
        if resp.status_code == 200:
            return
    except Exception:
        pass
    log_project_exception(sprint_id, source, command, error_message)


def generate_agent_report(agent: str, sid: str, jid: str, prompt: str, resp: str, duration: float):
    if not sid:
        return

    workspace_dir = os.path.join("workspace", sid, agent)
    os.makedirs(workspace_dir, exist_ok=True)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(workspace_dir, f"report_{timestamp}.md")

    handover_match = re.search(
        r"### TECHNICAL_HANDOVER:\s*(.*?)(?=\n### FILE:|\n\[TARGET FILE\]:|\n### RESULT:|\n### STATUS:|$)",
        resp, re.DOTALL | re.IGNORECASE
    )
    handover_notes = handover_match.group(1).strip() if handover_match else ""
    snippet = resp[:500].replace("```", "~~~")

    report_content = f"""# Agent Activity Report
- **Sprint ID**: {sid}
- **Job ID**: {jid}
- **Agent**: {agent}
- **Timestamp**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- **Duration**: {duration:.2f}ms

## Task Description
{prompt}

## Technical Handover Notes
{handover_notes if handover_notes else "*No detailed handover notes provided by agent.*"}

## Results Summary
The agent {agent} has completed the assigned task.

### Technical Response Snippet
{snippet}...

---
*Report generated automatically by HAS AI Software Studio.*
"""
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        config.logger.info(f"Report generated: {report_path}")
    except Exception as e:
        config.logger.error(f"Failed to generate report for {agent}: {e}")


def _submit_job(agent_name: str, sid: str, priority: int, prompt: str) -> bool:
    try:
        resp = requests.post(
            f"{config.ORCHESTRATOR_URL}/llm/submit",
            json={"agent_name": agent_name, "sprint_id": sid, "priority": priority, "prompt": prompt},
            timeout=10
        )
        return resp.status_code == 200
    except Exception as e:
        config.logger.error(f"Failed to submit job for {agent_name}: {e}")
        return False


AGENT_PROMPT_MAP = {
    "DevOps":     ("devops",     "DV_devops_worker"),
    "Database":   ("database",   "DB_database_worker"),
    "Frontend":   ("frontend",   "FE_frontend_worker"),
    "Backend":    ("backend",    "BE_backend_worker"),
    "Tester":     ("tester",     "TT_tester_worker"),
    "Security":   ("security",   "SM_security_worker"),
    "Documenter": ("documenter", "DC_documenter_worker"),
    "TeamLead":   ("teamlead",   "TM_teamlead_worker"),
}


def llm_worker():
    import socket
    hostname = socket.gethostname()
    config.logger.info(f"Worker {worker_id} started on {hostname}")

    # Start non-blocking background heartbeat thread immediately
    threading.Thread(target=_heartbeat_loop, args=(hostname,), daemon=True).start()

    while True:
        try:
            try:
                acquire_resp = requests.post(
                    f"{config.ORCHESTRATOR_URL}/llm/lock/acquire",
                    json={"worker_id": worker_id},
                    timeout=10
                )
            except requests.exceptions.RequestException as net_err:
                config.logger.debug(f"Orchestrator not reachable at {config.ORCHESTRATOR_URL}: {net_err}")
                time.sleep(5)
                continue

            if acquire_resp.status_code != 200:
                time.sleep(3)
                continue

            # Sync latest runtime config (Active Node / Model / API Key)
            _sync_worker_config()

            job_data   = acquire_resp.json()
            jid        = job_data["job_id"]
            agent      = job_data["agent_name"]
            prompt     = job_data["prompt"]
            sid        = job_data["sprint_id"]
            target_dir = f"apps/{sid}" if sid else "workspace"

            model = config.TEAMLEAD_MODEL if agent == "TeamLead" else config.AGENT_MODEL
            config.logger.info(f"[{jid}] {agent} starting on {model} (provider={config.LLM_PROVIDER}) for {sid}")

            system_prompt = ""
            if agent in AGENT_PROMPT_MAP:
                folder, key = AGENT_PROMPT_MAP[agent]
                system_prompt = load_prompt(folder, key, "")

            project_context = get_project_context(target_dir, sid)
            context_header  = f"# PROJECT CONTEXT (MANDATORY READ)\n{project_context}\n\n"
            user_content = f"{context_header}TASK:\n{prompt}"

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_content})

            start_t           = time.time()
            resp_text         = ""
            llm_ok            = False
            prompt_tokens     = 0
            completion_tokens = 0
            total_tokens      = 0

            max_attempts = max(1, 1 + getattr(config, "LLM_MAX_RETRIES", 2))
            for attempt in range(1, max_attempts + 1):
                try:
                    headers = {}
                    provider = config.LLM_PROVIDER
                    num_ctx = getattr(config, "LLM_NUM_CTX", 8192)

                    if provider == "openai":
                        endpoint = config.build_openai_url(config.OLLAMA_URL, "/v1/chat/completions")
                        if config.LLM_API_KEY:
                            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
                        headers["Content-Type"] = "application/json"
                        payload = {
                            "model": model,
                            "messages": messages,
                            "stream": False,
                            "temperature": 0.2,
                        }
                    else:
                        endpoint = f"{config.OLLAMA_URL.rstrip('/')}/api/chat"
                        if provider == "ollama-cloud" and config.LLM_API_KEY:
                            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
                        payload = {
                            "model": model,
                            "messages": messages,
                            "stream": False,
                            "options": {
                                "num_ctx": num_ctx,
                                "temperature": 0.2,
                            },
                        }

                    with httpx.Client(timeout=config.LLM_TIMEOUT) as client:
                        llm_http_resp = client.post(endpoint, headers=headers, json=payload)

                        if llm_http_resp.status_code != 200:
                            resp_text = f"Error: LLM returned HTTP {llm_http_resp.status_code}: {llm_http_resp.text[:500]}"
                            config.logger.warning(f"[{jid}] Attempt {attempt}/{max_attempts} failed: {resp_text}")
                            if llm_http_resp.status_code >= 500 and attempt < max_attempts:
                                time.sleep(2 * attempt)
                                continue
                            break

                        data = llm_http_resp.json()
                        if provider == "openai":
                            choices = data.get("choices", [])
                            resp_text = choices[0].get("message", {}).get("content", "") if choices else ""
                            usage = data.get("usage") or {}
                            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
                            total_tokens = int(usage.get("total_tokens", 0) or (prompt_tokens + completion_tokens))
                        else:
                            resp_text = data.get("message", {}).get("content", "")
                            prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
                            completion_tokens = int(data.get("eval_count", 0) or 0)
                            total_tokens = prompt_tokens + completion_tokens

                        if not resp_text or not resp_text.strip():
                            resp_text = f"Error: LLM returned empty response. Provider={provider}, Model={model}"
                            config.logger.warning(f"[{jid}] Attempt {attempt}/{max_attempts}: {resp_text}")
                            if attempt < max_attempts:
                                time.sleep(2 * attempt)
                                continue
                            break

                        if total_tokens == 0:
                            prompt_tokens = int(len(user_content) / 4)
                            completion_tokens = int(len(resp_text) / 4)
                            total_tokens = prompt_tokens + completion_tokens

                        llm_ok = True
                        break

                except Exception as e:
                    resp_text = f"Error: {str(e)}"
                    config.logger.warning(f"[{jid}] Attempt {attempt}/{max_attempts} exception: {e}")
                    if attempt < max_attempts:
                        time.sleep(2 * attempt)
                        continue

            duration = (time.time() - start_t) * 1000
            trace_status = "SUCCESS" if llm_ok else "FAILED"
            trace_posted = False

            try:
                t_resp = requests.post(
                    f"{config.ORCHESTRATOR_URL}/llm/trace",
                    json={
                        "id": str(uuid.uuid4()),
                        "job_id": jid,
                        "sprint_id": sid or "",
                        "agent_name": agent,
                        "worker_id": worker_id,
                        "execution_node": hostname,
                        "priority": job_data.get("priority", 1),
                        "prompt": prompt,
                        "response": resp_text,
                        "status": trace_status,
                        "duration_ms": duration,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                        "project_name": sid,
                    },
                    timeout=10
                )
                trace_posted = t_resp.status_code == 200
            except Exception as e:
                config.logger.error(f"Failed to save trace for {jid}: {e}")

            # Only release lock explicitly if /llm/trace failed (since /llm/trace already releases it)
            if not trace_posted:
                try:
                    requests.post(
                        f"{config.ORCHESTRATOR_URL}/llm/lock/release",
                        json={"worker_id": worker_id},
                        timeout=5
                    )
                except Exception as e:
                    config.logger.error(f"Failed to fallback-release lock for {jid}: {e}")

            if not llm_ok:
                config.logger.error(f"[{jid}] {agent} job FAILED for {sid}: {resp_text}")
                _report_exception(sid, agent, f"LLM Inference ({model})", resp_text)
                continue

            if agent in AGENT_PROMPT_MAP:
                num_extracted = extract_files(resp_text, target_dir, sid, agent)
                config.logger.info(f"[{jid}] Extracted {num_extracted} files for {sid}")

            generate_agent_report(agent, sid, jid, prompt, resp_text, duration)
            handle_recursive_triggers(agent, resp_text, sid, target_dir)

        except Exception as e:
            config.logger.error(f"Worker Loop Error: {e}", exc_info=True)
            time.sleep(5)


def handle_recursive_triggers(agent: str, resp: str, sid: str, target_dir: str):
    if not sid:
        return

    if agent == "TeamLead":
        if "### STATUS:" in resp.upper():
            try:
                requests.post(f"{config.ORCHESTRATOR_URL}/chat/history", json={
                    "sprint_id": sid, "role": "TeamLead", "content": resp
                }, timeout=5)
            except Exception as e:
                config.logger.error(f"Failed to post chat history: {e}")
            return

        plan = safe_json_loads(resp)
        if not plan or "tasks" not in plan or not plan["tasks"]:
            config.logger.error(f"CORRUPTED PLAN for {sid}: Agent {agent} produced invalid JSON or no tasks.")
            _report_exception(sid, "TeamLead", "Plan Orchestration", "TeamLead plan is corrupted or contains no tasks. Sprint aborted to prevent broken project.")
            return

        normalized_tasks = []
        for t in plan["tasks"]:
            raw_role = t.get("role", "")
            t["_mapped_role"] = map_role(raw_role)
            normalized_tasks.append(t)

        plan_roles = set(t["_mapped_role"] for t in normalized_tasks)
        config.logger.info(f"Plan roles for {sid}: {plan_roles}")

        devops_tasks   = [t for t in normalized_tasks if t["_mapped_role"] == "DevOps"]
        db_tasks       = [t for t in normalized_tasks if t["_mapped_role"] == "Database"]
        backend_tasks  = [t for t in normalized_tasks if t["_mapped_role"] == "Backend"]
        frontend_tasks = [t for t in normalized_tasks if t["_mapped_role"] == "Frontend"]

        if devops_tasks:
            config.logger.info(f"Phased Trigger: Starting Phase 1 (DevOps) with {len(devops_tasks)} task(s) for {sid}")
            for t in devops_tasks:
                _submit_job("DevOps", sid, 1, task_to_prompt(t))
        elif db_tasks:
            config.logger.info(f"Phased Trigger: Starting Phase 2 (Database) with {len(db_tasks)} task(s) for {sid}")
            for t in db_tasks:
                _submit_job("Database", sid, 2, task_to_prompt(t))
        elif backend_tasks:
            config.logger.info(f"Phased Trigger: Starting Phase 3 (Backend) with {len(backend_tasks)} task(s) for {sid}")
            for t in backend_tasks:
                _submit_job("Backend", sid, 3, task_to_prompt(t))
        elif frontend_tasks:
            config.logger.info(f"Phased Trigger: Starting Phase 4 (Frontend) with {len(frontend_tasks)} task(s) for {sid}")
            for t in frontend_tasks:
                _submit_job("Frontend", sid, 4, task_to_prompt(t))
        else:
            # Fix plan targeting Security, Tester, or Documenter directly
            for t in normalized_tasks:
                r = t["_mapped_role"]
                prio = 5 if r == "Security" else (6 if r == "Tester" else 7)
                _submit_job(r, sid, prio, task_to_prompt(t))

    if agent == "DevOps":
        db = SessionLocal()
        try:
            latest_plan_trace = db.query(LLMTrace).filter(
                LLMTrace.sprint_id == sid,
                LLMTrace.agent_name == "TeamLead"
            ).order_by(LLMTrace.timestamp.desc()).first()

            if not latest_plan_trace:
                return

            plan = safe_json_loads(latest_plan_trace.response)
            if not (plan and "tasks" in plan):
                return

            plan_cutoff = (latest_plan_trace.timestamp or datetime.utcnow()) - timedelta(seconds=2)

            plan_db_tasks       = [t for t in plan["tasks"] if map_role(t.get("role", "")) == "Database"]
            plan_backend_tasks  = [t for t in plan["tasks"] if map_role(t.get("role", "")) == "Backend"]
            plan_frontend_tasks = [t for t in plan["tasks"] if map_role(t.get("role", "")) == "Frontend"]

            active_devops = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                LLMJobRecord.agent_name == "DevOps",
                LLMJobRecord.status.in_(["PENDING", "PROCESSING"])
            ).count()

            if active_devops == 0:
                # 1. Sıradaki faz: Database
                if plan_db_tasks:
                    already_db = db.query(LLMJobRecord).filter(
                        LLMJobRecord.sprint_id == sid,
                        LLMJobRecord.created_at >= plan_cutoff,
                        func.lower(LLMJobRecord.agent_name) == "database"
                    ).count()
                    if already_db == 0:
                        config.logger.info(f"DevOps Complete for {sid}. Triggering Phase 2 (Database).")
                        for t in plan_db_tasks:
                            _submit_job("Database", sid, 2, task_to_prompt(t))
                        return

                # 2. Sıradaki faz: Backend
                if plan_backend_tasks:
                    already_be = db.query(LLMJobRecord).filter(
                        LLMJobRecord.sprint_id == sid,
                        LLMJobRecord.created_at >= plan_cutoff,
                        func.lower(LLMJobRecord.agent_name) == "backend"
                    ).count()
                    if already_be == 0:
                        config.logger.info(f"DevOps Complete for {sid}. Triggering Phase 3 (Backend).")
                        for t in plan_backend_tasks:
                            _submit_job("Backend", sid, 3, task_to_prompt(t))
                        return

                # 3. Sıradaki faz: Frontend (Sadece UI olan projelerde)
                if plan_frontend_tasks:
                    already_fe = db.query(LLMJobRecord).filter(
                        LLMJobRecord.sprint_id == sid,
                        LLMJobRecord.created_at >= plan_cutoff,
                        func.lower(LLMJobRecord.agent_name) == "frontend"
                    ).count()
                    if already_fe == 0:
                        config.logger.info(f"DevOps Complete for {sid}. Triggering Phase 4 (Frontend).")
                        for t in plan_frontend_tasks:
                            _submit_job("Frontend", sid, 4, task_to_prompt(t))
                        return

                # Hiç implementasyon görevi yoksa doğrudan QA'e geç
                config.logger.info(f"No further implementation tasks in plan for {sid}. Proceeding to QA.")
                _trigger_qa_phase(sid, plan, target_dir, db, plan_cutoff)
        finally:
            db.close()

    if agent == "Database":
        db = SessionLocal()
        try:
            latest_plan_trace = db.query(LLMTrace).filter(
                LLMTrace.sprint_id == sid,
                LLMTrace.agent_name == "TeamLead"
            ).order_by(LLMTrace.timestamp.desc()).first()

            if not latest_plan_trace:
                return

            plan = safe_json_loads(latest_plan_trace.response)
            if not (plan and "tasks" in plan):
                return

            plan_cutoff = (latest_plan_trace.timestamp or datetime.utcnow()) - timedelta(seconds=2)
            plan_backend_tasks  = [t for t in plan["tasks"] if map_role(t.get("role", "")) == "Backend"]
            plan_frontend_tasks = [t for t in plan["tasks"] if map_role(t.get("role", "")) == "Frontend"]

            active_db = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                LLMJobRecord.agent_name == "Database",
                LLMJobRecord.status.in_(["PENDING", "PROCESSING"])
            ).count()

            if active_db == 0:
                # Database bitti, sıradaki faz: Backend
                if plan_backend_tasks:
                    already_be = db.query(LLMJobRecord).filter(
                        LLMJobRecord.sprint_id == sid,
                        LLMJobRecord.created_at >= plan_cutoff,
                        func.lower(LLMJobRecord.agent_name) == "backend"
                    ).count()
                    if already_be == 0:
                        config.logger.info(f"Database Complete for {sid}. Triggering Phase 3 (Backend).")
                        for t in plan_backend_tasks:
                            _submit_job("Backend", sid, 3, task_to_prompt(t))
                        return

                # Backend yoksa ama Frontend varsa: Frontend
                if plan_frontend_tasks:
                    already_fe = db.query(LLMJobRecord).filter(
                        LLMJobRecord.sprint_id == sid,
                        LLMJobRecord.created_at >= plan_cutoff,
                        func.lower(LLMJobRecord.agent_name) == "frontend"
                    ).count()
                    if already_fe == 0:
                        config.logger.info(f"Database Complete for {sid}. Triggering Phase 4 (Frontend).")
                        for t in plan_frontend_tasks:
                            _submit_job("Frontend", sid, 4, task_to_prompt(t))
                        return

                # İkisi de yoksa QA fazına geç
                _trigger_qa_phase(sid, plan, target_dir, db, plan_cutoff)
        finally:
            db.close()

    if agent == "Backend":
        db = SessionLocal()
        try:
            latest_plan_trace = db.query(LLMTrace).filter(
                LLMTrace.sprint_id == sid,
                LLMTrace.agent_name == "TeamLead"
            ).order_by(LLMTrace.timestamp.desc()).first()

            if not latest_plan_trace:
                return

            plan = safe_json_loads(latest_plan_trace.response)
            if not (plan and "tasks" in plan):
                return

            plan_cutoff = (latest_plan_trace.timestamp or datetime.utcnow()) - timedelta(seconds=2)
            plan_frontend_tasks = [t for t in plan["tasks"] if map_role(t.get("role", "")) == "Frontend"]

            active_be = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                LLMJobRecord.agent_name == "Backend",
                LLMJobRecord.status.in_(["PENDING", "PROCESSING"])
            ).count()

            if active_be == 0:
                # Backend bitti! Sırada Frontend varsa, Backend handover verilerini alarak Frontend başlar.
                if plan_frontend_tasks:
                    already_fe = db.query(LLMJobRecord).filter(
                        LLMJobRecord.sprint_id == sid,
                        LLMJobRecord.created_at >= plan_cutoff,
                        func.lower(LLMJobRecord.agent_name) == "frontend"
                    ).count()
                    if already_fe == 0:
                        config.logger.info(f"Backend Phase Complete for {sid}. Sequentially triggering Phase 4 (Frontend).")
                        for t in plan_frontend_tasks:
                            _submit_job("Frontend", sid, 4, task_to_prompt(t))
                        return

                # Frontend yoksa (salt API/CLI/servis projesi) doğrudan QA fazına geç
                _trigger_qa_phase(sid, plan, target_dir, db, plan_cutoff)
        finally:
            db.close()

    if agent == "Frontend":
        db = SessionLocal()
        try:
            latest_plan_trace = db.query(LLMTrace).filter(
                LLMTrace.sprint_id == sid,
                LLMTrace.agent_name == "TeamLead"
            ).order_by(LLMTrace.timestamp.desc()).first()

            plan_cutoff = (
                (latest_plan_trace.timestamp - timedelta(seconds=2))
                if (latest_plan_trace and latest_plan_trace.timestamp)
                else datetime.min
            )

            # Tüm ön fazların (DevOps, Database, Backend, Frontend) işleri bitmiş mi kontrol et
            active_impl = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                LLMJobRecord.agent_name.in_(["DevOps", "Database", "Backend", "Frontend"]),
                LLMJobRecord.status.in_(["PENDING", "PROCESSING"])
            ).count()

            if active_impl == 0:
                plan_data = safe_json_loads(latest_plan_trace.response) if latest_plan_trace else None
                _trigger_qa_phase(sid, plan_data, target_dir, db, plan_cutoff)
        finally:
            db.close()

    if agent in ["Tester", "Security"]:
        has_failure = bool(re.search(r"###\s*RESULT:\s*FAILED", resp, re.IGNORECASE))

        if has_failure:
            _report_exception(sid, agent, "Quality/Security Verification", resp)
            db = SessionLocal()
            try:
                # If Security failed while Tester is still PENDING, cancel pending Tester job
                # so the fix cycle starts immediately instead of testing broken code.
                db.query(LLMJobRecord).filter(
                    LLMJobRecord.sprint_id == sid,
                    LLMJobRecord.agent_name == "Tester",
                    LLMJobRecord.status == "PENDING",
                ).delete(synchronize_session="fetch")
                db.commit()

                failed_count = db.query(LLMTrace).filter(
                    LLMTrace.sprint_id == sid,
                    LLMTrace.agent_name.in_(["Tester", "Security"]),
                    LLMTrace.response.like("%### RESULT: FAILED%")
                ).count()

                if failed_count <= 3:
                    config.logger.warning(
                        f"Loopback Triggered for {sid} (Attempt {failed_count}/3) by {agent}"
                    )
                    _submit_job("TeamLead", sid, 1,
                        f"BUGS/VULNERABILITIES DETECTED BY {agent.upper()}.\n"
                        f"Iteration: {failed_count}/3.\n"
                        f"### RESULT: FAILED\n\n"
                        f"Review the report below and output a new JSON plan to FIX these issues.\n"
                        f"Assign tasks only to the responsible agents.\n\nREPORT:\n{resp}")
                else:
                    config.logger.error(f"Max feedback cycles reached for {sid}.")
                    _submit_job("TeamLead", sid, 1,
                        f"HUMAN ASSISTANCE REQUIRED. 3 automated fix cycles failed.\n"
                        f"Summarize the major blockers and what help is needed.\n"
                        f"This is a FINAL REPORT for the human Product Owner.\n\nLAST REPORT:\n{resp}")
            finally:
                db.close()

        elif agent == "Tester":
            db = SessionLocal()
            try:
                latest_plan_trace = db.query(LLMTrace).filter(
                    LLMTrace.sprint_id == sid,
                    LLMTrace.agent_name == "TeamLead"
                ).order_by(LLMTrace.timestamp.desc()).first()
                plan = safe_json_loads(latest_plan_trace.response) if latest_plan_trace else None
                doc_tasks = [t for t in plan.get("tasks", []) if map_role(t.get("role", "")) == "Documenter"] if plan else []

                if doc_tasks:
                    config.logger.info(f"Tester passed. Triggering Phase 7 (Documenter) for {sid}.")
                    for t in doc_tasks:
                        _submit_job("Documenter", sid, 7, task_to_prompt(t))
                else:
                    _submit_job("TeamLead", sid, 8,
                        f"Project in {target_dir} passed QA. Generate completion message and README.md.")
            finally:
                db.close()

    if agent == "Documenter":
        config.logger.info(f"Documenter completed for {sid}. Triggering TeamLead completion.")
        _submit_job("TeamLead", sid, 8,
            f"Project in {target_dir} passed QA and full documentation is complete. Generate completion message and final README.md.")


def _trigger_qa_phase(sid: str, plan: dict, target_dir: str, db, plan_cutoff: datetime = None):
    """Triggers Security (priority 5) and Tester (priority 6) sequentially after implementation completes."""
    cutoff = plan_cutoff or datetime.min

    active_qa = db.query(LLMJobRecord).filter(
        LLMJobRecord.sprint_id == sid,
        LLMJobRecord.agent_name.in_(["Tester", "Security", "TeamLead", "Documenter"]),
        LLMJobRecord.status.in_(["PENDING", "PROCESSING"])
    ).count()

    # Scope 'already_qa' to the current TeamLead plan cycle so MODE 3 fix loops re-trigger QA cleanly!
    already_qa = db.query(LLMJobRecord).filter(
        LLMJobRecord.sprint_id == sid,
        LLMJobRecord.created_at >= cutoff,
        LLMJobRecord.agent_name.in_(["Tester", "Security"]),
    ).count()

    if active_qa == 0 and already_qa == 0:
        config.logger.info(f"Triggering QA phase for {sid}")

        security_prompt = None
        tester_prompt   = None

        if plan and "tasks" in plan:
            for t in plan["tasks"]:
                mapped = map_role(t.get("role", ""))
                if mapped == "Security" and not security_prompt:
                    security_prompt = task_to_prompt(t)
                elif mapped == "Tester" and not tester_prompt:
                    tester_prompt = task_to_prompt(t)

        if not security_prompt:
            security_prompt = (
                f"Please review the code generated for project in {target_dir}, "
                f"fix any critical/high vulnerabilities, and output security_audit.md."
            )
        if not tester_prompt:
            tester_prompt = (
                f"Please thoroughly review and test the code generated in {target_dir}. "
                f"Write unit tests to tests/test_main.py. "
                f"If any issues are found, append '### RESULT: FAILED' on its own line."
            )

        # Security priority 5, Tester priority 6 (Security runs first, hardens code, then Tester runs)
        _submit_job("Security", sid, 5, security_prompt)
        _submit_job("Tester",   sid, 6, tester_prompt)
