import os
import time
import json
import uuid
import logging
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
    safe_json_loads, log_project_exception, extract_files
)
from ..prompts import load_prompt

worker_id = str(uuid.uuid4())
START_TIME = time.time()

async def metrics_loop(sio):
    """
    Periodic task to gather system and performance metrics and emit via Socket.io
    """
    config.logger.info("Metrics loop started.")
    while True:
        try:
            # Resource usage
            try:
                pynvml.nvmlInit()
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                gpu_val = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
                pynvml.nvmlShutdown()
            except:
                gpu_val = 0

            cpu_val = psutil.cpu_percent()
            ram_val = psutil.virtual_memory().percent
            disk_val = psutil.disk_usage('/').percent
            
            # Process-based uptime
            proc = psutil.Process(os.getpid())
            uptime_sec = int(time.time() - proc.create_time())

            # Agent States & Token Rate Logic
            agent_states = {}
            tokens_min = 0
            db = SessionLocal()
            try:
                # Check for active workers in last 60s
                timeout = datetime.utcnow() - timedelta(seconds=60)
                active_workers = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.last_seen > timeout).count()
                
                if active_workers > 0:
                    roles = ["TeamLead", "Frontend", "Backend", "Tester", "Security", "DevOps"]
                    for r in roles:
                        agent_states[r] = "AVAIL"
                    
                    active_jobs = db.query(LLMJobRecord).filter(LLMJobRecord.status == "PROCESSING").all()
                    for job in active_jobs:
                        if job.agent_name in agent_states:
                            agent_states[job.agent_name] = "WORKING"

                # Calculate Tokens/min (last 1 minute for better reactivity)
                timeout_stats = datetime.utcnow() - timedelta(minutes=1)
                recent_traces = db.query(LLMTrace).filter(LLMTrace.timestamp > timeout_stats).all()
                total_chars = sum(len(t.response or "") + len(t.prompt or "") for t in recent_traces)
                tokens_min = int(total_chars / 4)

            except Exception as e:
                config.logger.error(f"DB metrics query error: {e}")
            finally:
                db.close()

            # Network metrics
            try:
                net_io = psutil.net_io_counters()
                if not hasattr(metrics_loop, "last_net_io"):
                    metrics_loop.last_net_io = net_io
                    metrics_loop.last_net_time = time.time()
                
                now = time.time()
                dt = now - metrics_loop.last_net_time
                if dt <= 0: dt = 0.001
                
                sent_speed = (net_io.bytes_sent - metrics_loop.last_net_io.bytes_sent) / dt
                recv_speed = (net_io.bytes_recv - metrics_loop.last_net_io.bytes_recv) / dt
                
                metrics_loop.last_net_io = net_io
                metrics_loop.last_net_time = now
            except Exception as e:
                config.logger.error(f"Network metrics error: {e}")
                sent_speed, recv_speed = 0, 0

            metrics = {
                "cpu": cpu_val,
                "ram": ram_val,
                "gpu": gpu_val,
                "disk": disk_val,
                "net_sent": sent_speed,
                "net_recv": recv_speed,
                "uptime": uptime_sec,
                "tokens_min": tokens_min,
                "agent_states": agent_states,
                "timestamp": datetime.now().isoformat()
            }
            
            # Use root namespace explicitly just in case
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
            for l in expired_locks:
                db.query(LLMJobRecord).filter(LLMJobRecord.id == l.job_id).update({"status": "PENDING", "worker_id": None})
                db.delete(l)
            db.commit()
        except Exception as e:
            config.logger.error(f"Watchdog err: {e}")
        finally:
            db.close()
        time.sleep(30)
        
def generate_agent_report(agent, sid, jid, prompt, resp, duration):
    """Generates a technical Markdown report in the workspace directory."""
    if not sid: return
    
    workspace_dir = os.path.join("workspace", sid)
    os.makedirs(workspace_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"{agent}-report_{timestamp}.md"
    report_path = os.path.join(workspace_dir, report_filename)
    
    report_content = f"""# Agent Activity Report
- **Sprint ID**: {sid}
- **Job ID**: {jid}
- **Agent**: {agent}
- **Timestamp**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- **Duration**: {duration:.2f}ms

## Task Description
{prompt}

## Results Summary
The agent {agent} has completed the assigned task. Technical details and code generation are summarized below.

### Technical Response Snippet
```markdown
{resp[:1000]}...
```

---
*Report generated automatically by HAS AI Software Studio.*
"""
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        config.logger.info(f"Report generated: {report_path}")
    except Exception as e:
        config.logger.error(f"Failed to generate report for {agent}: {e}")

def llm_worker():
    import socket
    hostname = socket.gethostname()
    config.logger.info(f"Worker {worker_id} started on {hostname}")
    
    while True:
        try:
            # Heartbeat via API instead of direct DB
            try:
                requests.post(f"{config.ORCHESTRATOR_URL}/jobs/heartbeat?worker_id={worker_id}&hostname={hostname}", timeout=5)
            except Exception as e:
                config.logger.error(f"Heartbeat API error: {e}")

            # Acquire Job
            resp = requests.post(f"{config.ORCHESTRATOR_URL}/llm/lock/acquire?worker_id={worker_id}", timeout=5)
            if resp.status_code != 200:
                time.sleep(5)
                continue
            
            job_data = resp.json()
            jid = job_data["job_id"]
            agent = job_data["agent_name"]
            prompt = job_data["prompt"]
            sid = job_data["sprint_id"]
            target_dir = f"apps/{sid}" if sid else "workspace"
            
            model = config.TEAMLEAD_MODEL if agent == "TeamLead" else config.AGENT_MODEL
            config.logger.info(f"[{jid}] {agent} starting on {model} for {sid}")

            # Load Role-specific System Prompt
            system_prompt = ""
            if agent == "DevOps": system_prompt = load_prompt("devops", "DV_devops_worker", "")
            elif agent == "Frontend": system_prompt = load_prompt("frontend", "FE_frontend_worker", "")
            elif agent == "Backend": system_prompt = load_prompt("backend", "BE_backend_worker", "")
            elif agent == "Tester": system_prompt = load_prompt("tester", "TT_tester_worker", "")
            elif agent == "Security": system_prompt = load_prompt("security", "SM_security_worker", "")
            elif agent == "TeamLead": system_prompt = load_prompt("teamlead", "TM_teamlead_worker", "")
            
            combined_prompt = f"{system_prompt}\n\nTASK:\n{prompt}" if system_prompt else prompt

            start_t = time.time()
            try:
                with httpx.Client(timeout=config.LLM_TIMEOUT) as client:
                    llm_resp = client.post(
                        f"{config.OLLAMA_URL}/api/generate",
                        json={"model": model, "prompt": combined_prompt, "stream": False}
                    )
                    llm_data = llm_resp.json()
                    resp_text = llm_data.get("response", "")
            except Exception as e:
                resp_text = f"Error: {str(e)}"

            duration = (time.time() - start_t) * 1000
            
            # Save Trace & Complete Job
            requests.post(
                f"{config.ORCHESTRATOR_URL}/llm/trace",
                json={
                    "id": str(uuid.uuid4()),
                    "job_id": jid,
                    "sprint_id": sid,
                    "agent_name": agent,
                    "worker_id": worker_id,
                    "execution_node": hostname,
                    "priority": job_data.get("priority", 1),
                    "prompt": prompt,
                    "response": resp_text,
                    "status": "COMPLETED",
                    "duration_ms": duration
                },
                timeout=5
            )
            
            requests.post(
                f"{config.ORCHESTRATOR_URL}/llm/lock/release?worker_id={worker_id}", timeout=5
            )

            # Post-Process: Files
            if agent in ["DevOps", "Frontend", "Backend", "Tester"]:
                extract_files(resp_text, target_dir, sid)

            # Generate Activity Report
            generate_agent_report(agent, sid, jid, prompt, resp_text, duration)

            # Recursive Trigger Logic
            handle_recursive_triggers(agent, resp_text, sid, target_dir)

        except Exception as e:
            config.logger.error(f"Worker Loop Error: {e}")
            time.sleep(5)

def handle_recursive_triggers(agent, resp, sid, target_dir):
    if agent == "TeamLead":
        plan = safe_json_loads(resp)
        if plan and "tasks" in plan:
            for t in plan["tasks"]:
                role = t.get("role")
                if role in ["Frontend", "Backend", "Tester", "Security", "DevOps"]:
                    requests.post(
                        f"{config.ORCHESTRATOR_URL}/llm/submit",
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
            tot = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                func.lower(LLMJobRecord.agent_name).in_(["frontend", "backend"])
            ).count()
            done = db.query(LLMJobRecord).filter(
                LLMJobRecord.sprint_id == sid,
                func.lower(LLMJobRecord.agent_name).in_(["frontend", "backend"]),
                LLMJobRecord.status == "COMPLETED"
            ).count()
            
            if tot > 0 and (done + 1) >= tot:
                active_qa = db.query(LLMJobRecord).filter(
                    LLMJobRecord.sprint_id == sid,
                    LLMJobRecord.agent_name.in_(["Tester", "Security", "TeamLead"]),
                    LLMJobRecord.status.in_(["PENDING", "PROCESSING"])
                ).count()
                
                if active_qa == 0:
                    config.logger.info(f"Triggering QA for {sid}")
                    requests.post(f"{config.ORCHESTRATOR_URL}/llm/submit", json={
                        "agent_name": "Security", "sprint_id": sid, "priority": 3,
                        "prompt": f"Please review the code generated for project in {target_dir} and output security_audit.md."
                    }, timeout=5)
                    requests.post(f"{config.ORCHESTRATOR_URL}/llm/submit", json={
                        "agent_name": "Tester", "sprint_id": sid, "priority": 4,
                        "prompt": f"Please thoroughly review and test the code generated in {target_dir}. Write unit tests to tests/test_main.py. If any issues or errors are found, you MUST append '### RESULT: FAILED' at the very end of your response."
                    }, timeout=5)
        finally:
            db.close()

    if agent == "Tester":
        if "FAILED" in resp.upper():
            log_project_exception(sid, "Tester", "QA Verification", resp)
            db = SessionLocal()
            try:
                failed_count = db.query(LLMTrace).filter(
                    LLMTrace.sprint_id == sid,
                    LLMTrace.agent_name == "Tester",
                    LLMTrace.response.like("%FAILED%")
                ).count()
                if failed_count <= 3:
                     requests.post(f"{config.ORCHESTRATOR_URL}/llm/submit", json={
                         "agent_name": "TeamLead", "sprint_id": sid, "priority": 1,
                         "prompt": f"BUGS DETECTED BY TESTER. Max Feedback Cycle: {failed_count}/3. \nReview report and output a new JSON plan for FIXES.\n\nREPORT:\n{resp}"
                     }, timeout=5)
            finally:
                db.close()
        else:
            requests.post(f"{config.ORCHESTRATOR_URL}/llm/submit", json={
                "agent_name": "TeamLead", "sprint_id": sid, "priority": 5,
                "prompt": f"Project in {target_dir} passed QA. Generate completion message and README.md."
            }, timeout=5)
