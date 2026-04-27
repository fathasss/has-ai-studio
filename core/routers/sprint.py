import uuid
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import LLMJobRecord, LLMTrace
from ..schemas import ExecuteRequest
from .. import config
from ..services.job_service import internal_submit_job
from ..utils import map_role, task_to_prompt
from ..app_instance import sio

router = APIRouter(tags=["Sprint"])

# DÜZELTME 4: Zayıf injection task'ları Pydantic schema ile uyumlu
# ve anlamlı description içerecek şekilde yeniden yazıldı.
_FALLBACK_DEVOPS_TASK = {
    "role":       "DevOps",
    "phase":      "Setup",
    "file_action": "CREATE",
    "target_file": "requirements.txt",
    "description": (
        "Initialize the project skeleton in the current directory. "
        "Create the appropriate dependency manifest for the chosen stack "
        "(e.g., requirements.txt for Python, package.json for Node.js) with all required packages "
        "pinned to exact versions. Create Dockerfile with multi-stage build. Create .env.example "
        "with all required environment variables. Do not write application logic. "
        "Only install frameworks and tools that the project actually needs."
    ),
    "dependencies":        [],
    "acceptance_criteria": [
        "Dependency manifest exists and installs without errors",
        "Dockerfile builds successfully",
        ".env.example documents all required variables",
    ],
}

_FALLBACK_SECURITY_TASK = {
    "role":       "Security",
    "phase":      "Security",
    "file_action": "MODIFY",
    "target_file": "security_audit.md",
    "description": (
        "Conduct a full security audit of all backend and frontend code. "
        "Check for: SQL injection, XSS, CSRF, insecure secrets handling, "
        "missing input validation, exposed stack traces, missing rate limiting. "
        "Fix all critical and high severity issues directly in the source files. "
        "Output a summary report to security_audit.md."
    ),
    "dependencies":        [],
    "acceptance_criteria": [
        "No critical or high severity vulnerabilities remain",
        "security_audit.md exists and summarizes findings",
    ],
}

_FALLBACK_TESTER_TASK = {
    "role":       "Tester",
    "phase":      "Testing",
    "file_action": "CREATE",
    "target_file": "tests/test_main.py",
    "description": (
        "Write and run comprehensive tests for all implemented features. "
        "Cover: happy path, edge cases, error responses (400/404/500). "
        "Ensure no placeholders or unimplemented logic remain. "
        "If any test fails or placeholder is found, append "
        "'### RESULT: FAILED' on its own line at the end of your response."
    ),
    "dependencies":        [],
    "acceptance_criteria": [
        "All tests pass",
        "No TODO or placeholder code remains",
        "Test file is runnable with: pytest tests/test_main.py",
    ],
}


def _get_priority(role: str) -> int:
    if role == "DevOps":                    return 1
    if role in ["Frontend", "Backend"]:     return 2
    if role in ["Security", "Tester"]:      return 3
    return 2


def _inject_missing_roles(tasks: list) -> list:
    """
    Ensures DevOps, Security, and Tester are present in the task list.
    DÜZELTME 7: Var olan rolleri kontrol ederek duplicate eklemeyi önler.
    """
    existing_roles = {map_role(t.get("role", "")) for t in tasks}

    if "DevOps" not in existing_roles:
        tasks.insert(0, _FALLBACK_DEVOPS_TASK)
    if "Security" not in existing_roles:
        tasks.append(_FALLBACK_SECURITY_TASK)
    if "Tester" not in existing_roles:
        tasks.append(_FALLBACK_TESTER_TASK)

    return tasks


@router.post("/sprint/execute")
async def execute_sprint(req: ExecuteRequest, db: Session = Depends(get_db)):
    sid  = req.sprint_id
    plan = req.plan

    # DÜZELTME 5: None guard — plan yoksa erken dön
    if not plan or "tasks" not in plan:
        raise HTTPException(status_code=400, detail="Plan must contain a 'tasks' array.")

    tasks = plan["tasks"]

    # DÜZELTME 2 & 7: map_role tek yerde import edildi (dosya üstünde).
    # Duplicate role injection önlendi.
    tasks = _inject_missing_roles(tasks)
    plan["tasks"] = tasks

    # Synthetic TeamLead trace — worker'ın plan'ı parse edebilmesi için
    db.add(LLMTrace(
        id             = str(uuid.uuid4()),
        sprint_id      = sid,
        agent_name     = "TeamLead",
        worker_id      = "orchestrator",
        execution_node = "orchestrator",
        priority       = 1,
        prompt         = "Generated from UI Preview",
        response       = f"```json\n{json.dumps(plan, indent=2, ensure_ascii=False)}\n```",
        status         = "SUCCESS",
    ))
    db.commit()

    # Job'ları sıraya al
    queued_jobs = []
    for t in tasks:
        role     = map_role(t.get("role", ""))
        priority = _get_priority(role)

        # DÜZELTME 3: Yeni schema desteği — task_to_prompt() helper'ı kullan
        prompt = task_to_prompt(t)
        await internal_submit_job(role, sid, priority, prompt)
        queued_jobs.append(role)

    # DÜZELTME 1: COMPLETED eventi kaldırıldı.
    # Job'lar background worker'da işlendiği için sprint henüz bitmedi.
    # Frontend, bireysel job_update eventlerini dinleyerek ilerlemeyi takip eder.
    await sio.emit("job_update", {
        "job_id":    "system",
        "status":    "STARTED",
        "sprint_id": sid,
        "queued":    queued_jobs,
    })

    return {"status": "ok", "queued": queued_jobs}


@router.get("/traces/{sprint_id}")
async def get_sprint_traces(sprint_id: str, db: Session = Depends(get_db)):
    traces = (
        db.query(LLMTrace)
        .filter(LLMTrace.sprint_id == sprint_id)
        .order_by(LLMTrace.timestamp.asc())
        .all()
    )
    # DÜZELTME 6: ORM objeleri direkt JSON serialize edilemez.
    # jsonable_encoder ile dict'e çevir.
    return {"status": "ok", "traces": jsonable_encoder(traces)}