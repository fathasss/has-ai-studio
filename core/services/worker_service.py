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
from .live_tester import inspect_build_and_syntax, run_live_synthetic_user_tests
from .unified_llm import call_unified_llm_sync

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


def _get_priority(role: str) -> int:
    if role == "DevOps":     return 1
    if role == "Database":   return 2
    if role == "Backend":    return 3
    if role == "Frontend":   return 4
    if role == "Security":   return 5
    if role == "Tester":     return 6
    if role == "Documenter": return 7
    return 3


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

def _emit_phase_tracking(sprint_id: str, phase_number: int, phase_name: str, agent: str, status: str, message: str):
    """Notifies the Orchestrator and UI of phase progression with TeamLead tracking commentary."""
    if not sprint_id:
        return
    try:
        requests.post(
            f"{config.ORCHESTRATOR_URL}/sprint/phase-update",
            json={
                "sprint_id": sprint_id,
                "phase_number": phase_number,
                "phase_name": phase_name,
                "agent": agent,
                "status": status,
                "message": message
            },
            timeout=5
        )
    except Exception as e:
        config.logger.warning(f"Failed to post phase update: {e}")


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

            agent_cfg = config.get_agent_llm_config(agent, purpose="task")
            provider = agent_cfg["provider"]
            model = agent_cfg["model"]
            url = agent_cfg["url"]
            api_key = agent_cfg["apiKey"]
            config.logger.info(f"[{jid}] {agent} starting on {provider}:{model} for {sid}")

            system_prompt = ""
            if agent in AGENT_PROMPT_MAP:
                folder, key = AGENT_PROMPT_MAP[agent]
                system_prompt = load_prompt(folder, key, "")

            project_context = get_project_context(target_dir, sid, agent=agent)
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
                    resp_text, prompt_tokens, completion_tokens = call_unified_llm_sync(
                        provider=provider,
                        model=model,
                        messages=messages,
                        url=url,
                        api_key=api_key,
                        timeout=config.LLM_TIMEOUT,
                        allow_fallback=True
                    )
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
                    resp_text = f"Error: {e}"
                    config.logger.warning(f"[{jid}] Attempt {attempt}/{max_attempts} failed: {resp_text}")
                    if attempt < max_attempts:
                        time.sleep(2 * attempt)
                        continue
                    break

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
            try:
                extracted_files = re.findall(r"### FILE:\s*([^\n]+)", resp_text) + re.findall(r"\[TARGET FILE\]:\s*([^\n]+)", prompt)
                extracted_files = list(dict.fromkeys(f.strip() for f in extracted_files if f.strip()))
                from .phase_service import PhaseService
                from .memory_service import MemoryService
                PhaseService.record_agent_task_execution(sid, agent, target_dir, prompt, resp_text, extracted_files)
                MemoryService.update_agent_memory(sid, agent, target_dir, prompt, resp_text, extracted_files)
            except Exception as mem_err:
                config.logger.warning(f"Error updating phase/memory for {sid}: {mem_err}")
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

        from .phase_service import PhaseService
        structured_phases = PhaseService.generate_project_phases(sid, plan, target_dir)
        p1 = structured_phases[0] if structured_phases else None

        if p1 and p1.get("tasks"):
            p1_agents = ", ".join(f"@{a}" for a in p1.get("participating_agents", []))
            config.logger.info(f"Phased Trigger: Starting Phase 1 ({p1['name']}) with {len(p1['tasks'])} task(s) for {sid}. Agents: {p1_agents}")
            _emit_phase_tracking(
                sid, 1, p1["name"],
                p1["participating_agents"][0] if p1.get("participating_agents") else "TeamLead",
                "IN_PROGRESS",
                f"Faz 1 ({p1['name']}) başlatıldı. Görevli Ajanlar: {p1_agents}"
            )
            for t in p1["tasks"]:
                r = map_role(t.get("role", "Developer"))
                prio = _get_priority(r)
                _submit_job(r, sid, prio, task_to_prompt(t))
        else:
            # Fallback
            for t in normalized_tasks:
                r = t["_mapped_role"]
                prio = 5 if r == "Security" else (6 if r == "Tester" else 7)
                _submit_job(r, sid, prio, task_to_prompt(t))

    if agent in ["DevOps", "Database", "Backend", "Frontend"]:
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

            # Check if other agents in current milestone are still actively working
            active_impl = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                LLMJobRecord.agent_name.in_(["DevOps", "Database", "Backend", "Frontend"]),
                LLMJobRecord.status.in_(["PENDING", "PROCESSING"])
            ).count()

            if active_impl > 0:
                config.logger.info(f"Agent {agent} finished, but {active_impl} implementation job(s) still active for {sid}. Waiting.")
                return

            # All active implementation jobs for the current phase are done!
            from .phase_service import PhaseService
            summary = PhaseService.get_phase_status_summary(sid, target_dir, db)

            if summary and summary.get("phases"):
                phases = summary["phases"]
                next_phase = None
                for p in phases:
                    p_tasks = p.get("tasks", [])
                    if not p_tasks:
                        continue
                    # Check if jobs for this phase have been submitted yet
                    p_agents = p.get("participating_agents", [])
                    jobs_for_phase = db.query(LLMJobRecord).filter(
                        LLMJobRecord.sprint_id == sid,
                        LLMJobRecord.created_at >= plan_cutoff,
                        LLMJobRecord.agent_name.in_(p_agents)
                    ).all()

                    if len(jobs_for_phase) < len(p_tasks):
                        next_phase = p
                        break

                if next_phase:
                    p_num = next_phase["phase_id"]
                    p_name = next_phase["name"]
                    p_agents = next_phase.get("participating_agents", [])
                    p_agents_str = ", ".join(f"@{a}" for a in p_agents)
                    primary_agent = p_agents[0] if p_agents else "Backend"

                    config.logger.info(f"Phased Transition: Starting Phase {p_num} ({p_name}) for {sid}. Agents: {p_agents_str}")
                    _emit_phase_tracking(
                        sid, p_num, p_name, primary_agent, "IN_PROGRESS",
                        f"Faz {p_num} ({p_name}) başlatıldı. Görevli Ajanlar: {p_agents_str}"
                    )
                    for t in next_phase.get("tasks", []):
                        r = map_role(t.get("role", "Developer"))
                        prio = _get_priority(r)
                        _submit_job(r, sid, prio, task_to_prompt(t))
                    return

            # If all implementation phases are completed, run Gatekeeper and proceed to QA
            config.logger.info(f"All implementation phases completed for {sid}. Running Gatekeeper & QA.")
            inspection = inspect_build_and_syntax(target_dir, sid)
            if not inspection["is_valid"]:
                config.logger.warning(f"Build & Syntax Inspection FAILED for {sid}: {inspection['errors']}")
                _report_exception(sid, "DevOps", "Build/Syntax Gatekeeper", "\n".join(inspection["errors"]))
                _submit_job("TeamLead", sid, 1,
                    f"BUILD & SYNTAX INSPECTION FAILED for {sid}.\n"
                    f"### RESULT: FAILED\n\n"
                    f"Please assign fix tasks to repair these syntax/build errors before QA testing.\n\nREPORT:\n{inspection['report']}")
                return

            _trigger_qa_phase(sid, plan, target_dir, db, plan_cutoff)
        finally:
            db.close()

    if agent == "Tester":
        # Execute Real-time Synthetic User Journey & Ephemeral Server Tests!
        config.logger.info(f"Tester completed output. Executing Real-time User Journey & Server Tests for {sid} in {target_dir}...")
        live_res = run_live_synthetic_user_tests(target_dir, sid, config.ORCHESTRATOR_URL)
        if not live_res["passed"]:
            config.logger.warning(f"Realtime Synthetic User Tests FAILED for {sid}: {live_res.get('summary', '')}")
            resp += f"\n\n### REALTIME TEST RUNNER FAILURE:\n{live_res.get('summary', 'Live user journey tests failed.')}\n### RESULT: FAILED"

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
                    _emit_phase_tracking(sid, 7, "Teknik Dokümantasyon", "Documenter", "IN_PROGRESS", "Tüm güvenlik ve test kontrolleri başarıyla onaylandı! TeamLead 7. Fazı (Teknik Dokümantasyon ve README) başlattı.")
                    for t in doc_tasks:
                        _submit_job("Documenter", sid, 7, task_to_prompt(t))
                else:
                    _submit_job("TeamLead", sid, 8,
                        f"Project in {target_dir} passed QA. Generate completion message and README.md.")
            finally:
                db.close()

    if agent == "Documenter":
        config.logger.info(f"Documenter completed for {sid}. Triggering TeamLead completion.")
        total_p = 3
        try:
            from .phase_service import PhaseService
            psum = PhaseService.get_phase_status_summary(sid, target_dir)
            if psum and psum.get("total_phases"):
                total_p = psum["total_phases"]
        except Exception:
            pass
        _emit_phase_tracking(
            sid, total_p, "Proje Teslimatı & Canlıya Alım", "TeamLead", "COMPLETED",
            f"🎉 Tebrikler! Tüm geliştirme fazları (1-{total_p}) başarıyla tamamlandı. Proje mimarisi, kodları, testleri ve dokümantasyonu teslim edildi."
        )
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
        # Pre-QA Gatekeeper: DevOps & Build Syntax Inspection
        inspection = inspect_build_and_syntax(target_dir, sid)
        if not inspection["is_valid"]:
            config.logger.warning(f"Build & Syntax Inspection FAILED for {sid}: {inspection['errors']}")
            _report_exception(sid, "DevOps", "Build/Syntax Gatekeeper", "\n".join(inspection["errors"]))
            _submit_job("TeamLead", sid, 1,
                f"BUILD & SYNTAX INSPECTION FAILED for {sid}.\n"
                f"### RESULT: FAILED\n\n"
                f"Please assign fix tasks to repair these syntax/build errors before QA testing.\n\nREPORT:\n{inspection['report']}")
            return

        config.logger.info(f"Triggering QA phase for {sid}")
        total_p = 3
        try:
            from .phase_service import PhaseService
            psum = PhaseService.get_phase_status_summary(sid, target_dir)
            if psum and psum.get("total_phases"):
                total_p = psum["total_phases"]
        except Exception:
            pass
        _emit_phase_tracking(
            sid, total_p, "Güvenlik & Kalite Denetimi", "Security", "IN_PROGRESS",
            f"Tüm uygulama kod geliştirme fazları tamamlandı. Faz {total_p} (Güvenlik Denetimi & Sentetik Testler) süreci başlatıldı."
        )

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
