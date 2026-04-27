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


# ═══════════════════════════════════════════════════════════════════
# YENİ: task_to_prompt — eski ve yeni JSON schema'yı birden destekler
# Eski schema: {"task": "[TARGET FILE]: ...\n[LOGIC]: ..."}
# Yeni schema: {"target_file": "...", "description": "...", "dependencies": [], "acceptance_criteria": []}
# ═══════════════════════════════════════════════════════════════════
# metrics_loop stays here...


async def metrics_loop(sio):
    config.logger.info("Metrics loop started.")
    while True:
        try:
            cpu_val  = psutil.cpu_percent()
            ram_val  = psutil.virtual_memory().percent
            disk_val = psutil.disk_usage('/').percent
            gpu_val  = _get_gpu_utilization()

            proc = psutil.Process(os.getpid())
            uptime_sec = int(time.time() - proc.create_time())

            agent_states = {}
            tokens_min   = 0

            db = SessionLocal()
            try:
                timeout = datetime.utcnow() - timedelta(seconds=60)
                active_workers = db.query(WorkerHeartbeat).filter(
                    WorkerHeartbeat.last_seen > timeout
                ).count()

                if active_workers > 0:
                    roles = ["TeamLead", "Frontend", "Backend", "Tester", "Security", "DevOps"]
                    for r in roles:
                        agent_states[r] = "AVAIL"

                    active_jobs = db.query(LLMJobRecord).filter(
                        LLMJobRecord.status == "PROCESSING"
                    ).all()
                    for job in active_jobs:
                        for r in agent_states.keys():
                            if job.agent_name.lower() == r.lower():
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

                sent_speed = (net_io.bytes_sent - metrics_loop.last_net_io.bytes_sent) / dt
                recv_speed = (net_io.bytes_recv - metrics_loop.last_net_io.bytes_recv) / dt

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
    while True:
        db = SessionLocal()
        try:
            timeout = datetime.utcnow() - timedelta(seconds=60)
            db.query(WorkerHeartbeat).filter(WorkerHeartbeat.last_seen < timeout).delete()
            expired_locks = db.query(GlobalLock).filter(
                ~GlobalLock.worker_id.in_(db.query(WorkerHeartbeat.worker_id))
            ).all()
            for lock in expired_locks:
                db.query(LLMJobRecord).filter(LLMJobRecord.id == lock.job_id).update(
                    {"status": "PENDING", "worker_id": None}
                )
                db.delete(lock)
            db.commit()
        except Exception as e:
            config.logger.error(f"Watchdog err: {e}")
        finally:
            db.close()
        time.sleep(30)


def generate_agent_report(agent: str, sid: str, jid: str, prompt: str, resp: str, duration: float):
    if not sid:
        return

    workspace_dir = os.path.join("workspace", sid, agent)
    os.makedirs(workspace_dir, exist_ok=True)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(workspace_dir, f"report_{timestamp}.md")

    handover_match = re.search(
        r"### TECHNICAL_HANDOVER:\s*(.*?)(?=\n### FILE:|\n\[TARGET FILE\]:|$)",
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
        requests.post(
            f"{config.ORCHESTRATOR_URL}/llm/submit",
            json={"agent_name": agent_name, "sprint_id": sid, "priority": priority, "prompt": prompt},
            timeout=5
        )
        return True
    except Exception as e:
        config.logger.error(f"Failed to submit job for {agent_name}: {e}")
        return False


def llm_worker():
    import socket
    hostname = socket.gethostname()
    config.logger.info(f"Worker {worker_id} started on {hostname}")

    AGENT_PROMPT_MAP = {
        "DevOps":    ("devops",    "DV_devops_worker"),
        "Frontend":  ("frontend",  "FE_frontend_worker"),
        "Backend":   ("backend",   "BE_backend_worker"),
        "Tester":    ("tester",    "TT_tester_worker"),
        "Security":  ("security",  "SM_security_worker"),
        "TeamLead":  ("teamlead",  "TM_teamlead_worker"),
    }

    while True:
        try:
            try:
                requests.post(
                    f"{config.ORCHESTRATOR_URL}/jobs/heartbeat"
                    f"?worker_id={worker_id}&hostname={hostname}",
                    timeout=5
                )
            except Exception as e:
                config.logger.error(f"Heartbeat API error: {e}")

            acquire_resp = requests.post(
                f"{config.ORCHESTRATOR_URL}/llm/lock/acquire",
                json={"worker_id": worker_id},
                timeout=5
            )
            if acquire_resp.status_code != 200:
                time.sleep(5)
                continue

            job_data   = acquire_resp.json()
            jid        = job_data["job_id"]
            agent      = job_data["agent_name"]
            prompt     = job_data["prompt"]
            sid        = job_data["sprint_id"]
            target_dir = f"apps/{sid}" if sid else "workspace"

            model = config.TEAMLEAD_MODEL if agent == "TeamLead" else config.AGENT_MODEL
            config.logger.info(f"[{jid}] {agent} starting on {model} for {sid}")

            system_prompt = ""
            if agent in AGENT_PROMPT_MAP:
                folder, key = AGENT_PROMPT_MAP[agent]
                system_prompt = load_prompt(folder, key, "")

            project_context = get_project_context(target_dir, sid)
            context_header  = f"# PROJECT CONTEXT (MANDATORY READ)\n{project_context}\n\n"
            user_content = f"{context_header}TASK:\n{prompt}"

            # DÜZELTME: /api/generate → /api/chat geçişi.
            # system_prompt ve user content ayrı mesajlar olarak gönderiliyor.
            # Bu sayede LLM rol ayrımını doğru yapıyor ve bağlamı kaybetmiyor.
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_content})

            start_t   = time.time()
            resp_text = ""
            try:
                headers = {}
                provider = config.LLM_PROVIDER

                # Provider'a göre endpoint ve payload seç
                if provider == "openai":
                    endpoint = f"{config.OLLAMA_URL}/v1/chat/completions"
                    if config.LLM_API_KEY:
                        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
                    headers["Content-Type"] = "application/json"
                    payload = {"model": model, "messages": messages, "stream": False}
                else:
                    endpoint = f"{config.OLLAMA_URL}/api/chat"
                    if provider == "ollama-cloud" and config.LLM_API_KEY:
                        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
                    payload = {"model": model, "messages": messages, "stream": False}

                with httpx.Client(timeout=config.LLM_TIMEOUT) as client:
                    llm_http_resp = client.post(endpoint, headers=headers, json=payload)

                    if llm_http_resp.status_code != 200:
                        resp_text = f"Error: LLM returned HTTP {llm_http_resp.status_code}: {llm_http_resp.text[:500]}"
                        config.logger.error(resp_text)
                    else:
                        data = llm_http_resp.json()
                        if provider == "openai":
                            choices = data.get("choices", [])
                            resp_text = choices[0].get("message", {}).get("content", "") if choices else ""
                        else:
                            resp_text = data.get("message", {}).get("content", "")

                        if not resp_text.strip():
                            resp_text = f"Error: LLM returned empty response. Provider={provider}, Model={model}"
                            config.logger.error(resp_text)
            except Exception as e:
                resp_text = f"Error: {str(e)}"

            duration = (time.time() - start_t) * 1000

            try:
                requests.post(
                    f"{config.ORCHESTRATOR_URL}/llm/trace",
                    json={
                        "id": str(uuid.uuid4()), "job_id": jid, "sprint_id": sid,
                        "agent_name": agent, "worker_id": worker_id,
                        "execution_node": hostname,
                        "priority": job_data.get("priority", 1),
                        "prompt": prompt, "response": resp_text,
                        "status": "COMPLETED", "duration_ms": duration
                    },
                    timeout=5
                )
            except Exception as e:
                config.logger.error(f"Failed to save trace for {jid}: {e}")

            try:
                requests.post(
                    f"{config.ORCHESTRATOR_URL}/llm/lock/release",
                    json={"worker_id": worker_id},
                    timeout=5
                )
            except Exception as e:
                config.logger.error(f"Failed to release lock for {jid}: {e}")

            if agent in AGENT_PROMPT_MAP:
                num_extracted = extract_files(resp_text, target_dir, sid, agent)
                config.logger.info(f"[{jid}] Extracted {num_extracted} files for {sid}")

            generate_agent_report(agent, sid, jid, prompt, resp_text, duration)
            handle_recursive_triggers(agent, resp_text, sid, target_dir)

        except Exception as e:
            config.logger.error(f"Worker Loop Error: {e}")
            time.sleep(5)


def handle_recursive_triggers(agent: str, resp: str, sid: str, target_dir: str):

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
            log_project_exception(sid, "TeamLead", "Plan Orchestration", "TeamLead plan is corrupted or contains no tasks. Sprint aborted to prevent broken project.")
            return

        normalized_tasks = []
        for t in plan["tasks"]:
            raw_role = t.get("role", "")
            t["_mapped_role"] = map_role(raw_role)
            normalized_tasks.append(t)

        # Determine which roles are actually in the plan
        plan_roles = set(t["_mapped_role"] for t in normalized_tasks)
        config.logger.info(f"Plan roles for {sid}: {plan_roles}")

        devops_tasks = [t for t in normalized_tasks if t["_mapped_role"] == "DevOps"]

        if devops_tasks:
            config.logger.info(f"Phased Trigger: {len(devops_tasks)} DevOps tasks for {sid}")
            for t in devops_tasks:
                _submit_job("DevOps", sid, 1, task_to_prompt(t))
        else:
            # No DevOps phase — submit only implementation roles that ARE in the plan
            config.logger.info(f"Phased Trigger: No DevOps. Submitting Implementation tasks for {sid}")
            for t in normalized_tasks:
                if t["_mapped_role"] in ["Frontend", "Backend"]:
                    _submit_job(t["_mapped_role"], sid, 2, task_to_prompt(t))

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

            # Determine which implementation roles exist in the plan
            plan_impl_roles = set()
            for t in plan["tasks"]:
                mapped = map_role(t.get("role", ""))
                if mapped in ["Frontend", "Backend"]:
                    plan_impl_roles.add(mapped)

            pending_devops = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                LLMJobRecord.agent_name == "DevOps",
                LLMJobRecord.status != "COMPLETED"
            ).count()

            if pending_devops == 0:
                already_submitted = db.query(LLMJobRecord).filter(
                    LLMJobRecord.sprint_id == sid,
                    func.lower(LLMJobRecord.agent_name).in_([r.lower() for r in plan_impl_roles] if plan_impl_roles else ["__none__"])
                ).count()

                if already_submitted == 0 and plan_impl_roles:
                    config.logger.info(f"DevOps Phase Complete for {sid}. Triggering Implementation for roles: {plan_impl_roles}")
                    for t in plan["tasks"]:
                        mapped = map_role(t.get("role", ""))
                        if mapped in plan_impl_roles:
                            _submit_job(mapped, sid, 2, task_to_prompt(t))
                elif not plan_impl_roles:
                    # No Frontend/Backend in plan — skip straight to QA
                    config.logger.info(f"No implementation roles in plan for {sid}. Skipping to QA.")
                    _trigger_qa_phase(sid, plan, target_dir, db)
                else:
                    config.logger.info(f"Implementation jobs already submitted for {sid}, skipping.")
        finally:
            db.close()

    if agent in ["Frontend", "Backend"]:
        db = SessionLocal()
        try:
            # Get plan to know which implementation roles were expected
            latest_plan_trace = db.query(LLMTrace).filter(
                LLMTrace.sprint_id == sid,
                LLMTrace.agent_name == "TeamLead"
            ).order_by(LLMTrace.timestamp.desc()).first()

            plan_impl_roles = {"frontend", "backend"}  # default
            if latest_plan_trace:
                plan = safe_json_loads(latest_plan_trace.response)
                if plan and "tasks" in plan:
                    plan_impl_roles = set()
                    for t in plan["tasks"]:
                        mapped = map_role(t.get("role", ""))
                        if mapped in ["Frontend", "Backend"]:
                            plan_impl_roles.add(mapped.lower())

            tot = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                func.lower(LLMJobRecord.agent_name).in_(list(plan_impl_roles) if plan_impl_roles else ["__none__"])
            ).count()

            done = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                func.lower(LLMJobRecord.agent_name).in_(list(plan_impl_roles) if plan_impl_roles else ["__none__"]),
                LLMJobRecord.status == "COMPLETED"
            ).count()

            if tot > 0 and done >= tot:
                plan_data = None
                if latest_plan_trace:
                    plan_data = safe_json_loads(latest_plan_trace.response)
                _trigger_qa_phase(sid, plan_data, target_dir, db)
        finally:
            db.close()

    if agent in ["Tester", "Security"]:
        has_failure = bool(re.search(r"###\s*RESULT:\s*FAILED", resp, re.IGNORECASE))

        if has_failure:
            log_project_exception(sid, agent, "Quality/Security Verification", resp)
            db = SessionLocal()
            try:
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
                        f"Iteration: {failed_count}/3.\n\n"
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
            _submit_job("TeamLead", sid, 5,
                f"Project in {target_dir} passed QA. Generate completion message and README.md.")


def _trigger_qa_phase(sid: str, plan: dict, target_dir: str, db):
    """Triggers Security and Tester agents after all implementation is done."""
    active_qa = db.query(LLMJobRecord).filter(
        LLMJobRecord.sprint_id == sid,
        LLMJobRecord.agent_name.in_(["Tester", "Security", "TeamLead"]),
        LLMJobRecord.status.in_(["PENDING", "PROCESSING"])
    ).count()
    already_qa = db.query(LLMJobRecord).filter(
        LLMJobRecord.sprint_id == sid,
        LLMJobRecord.agent_name.in_(["Tester", "Security"]),
    ).count()

    if active_qa == 0 and already_qa == 0:
        config.logger.info(f"Triggering QA for {sid}")

        security_prompt = None
        tester_prompt   = None

        if plan and "tasks" in plan:
            for t in plan["tasks"]:
                mapped = map_role(t.get("role", ""))
                if mapped == "Security" and not security_prompt:
                    security_prompt = task_to_prompt(t)
                elif mapped == "Tester" and not tester_prompt:
                    tester_prompt = task_to_prompt(t)

        # Fallback
        if not security_prompt:
            security_prompt = (
                f"Please review the code generated for project in {target_dir} "
                f"and output security_audit.md."
            )
        if not tester_prompt:
            tester_prompt = (
                f"Please thoroughly review and test the code generated in {target_dir}. "
                f"Write unit tests to tests/test_main.py. "
                f"If any issues are found, append '### RESULT: FAILED' on its own line."
            )

        _submit_job("Security", sid, 3, security_prompt)
        _submit_job("Tester",   sid, 4, tester_prompt)