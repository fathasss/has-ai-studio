from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import LLMJobRecord, LLMTrace
from ..schemas import ExecuteRequest
from .. import config
from ..services.job_service import internal_submit_job

router = APIRouter(tags=["Sprint"])

@router.post("/sprint/execute")
async def execute_sprint(req: ExecuteRequest, db: Session = Depends(get_db)):
    sid = req.sprint_id
    plan = req.plan
    
    # Validation & Injection
    if plan and "tasks" in plan:
        tasks = plan["tasks"]
        from ..utils import map_role
        roles = [map_role(t.get("role", "")) for t in tasks]
        
        if "DevOps" not in roles:
            setup_cmds = plan.get("setup_commands", [])
            setup_str = "\n".join(setup_cmds) if setup_cmds else "Initialize project."
            tasks.insert(0, {"role": "DevOps", "phase": "Setup", "task": f"Initialize project skeleton: {setup_str}"})
        if "Security" not in roles:
            tasks.append({"role": "Security", "phase": "Audit", "task": "Security check."})
        if "Tester" not in roles:
            tasks.append({"role": "Tester", "phase": "Testing", "task": "Functional tests."})
    
    # Create Synthetic Trace for Project Name Discovery
    import uuid
    import json
    db.add(
        LLMTrace(
            id=str(uuid.uuid4()),
            sprint_id=sid,
            agent_name="TeamLead",
            worker_id="orchestrator",
            execution_node="orchestrator",
            priority=1,
            prompt="Generated from UI Preview",
            response=f"```json\n{json.dumps(plan, indent=2, ensure_ascii=False)}\n```",
            status="SUCCESS"
        )
    )
    db.commit()
    
    # Queue Jobs
    queued_jobs = []
    for t in plan.get("tasks", []):
        from ..utils import map_role
        role = map_role(t.get("role", ""))
        priority = 1 if role == "DevOps" else (3 if role in ["Tester", "Security"] else 2)
        await internal_submit_job(role, sid, priority, t.get("task", ""))
        queued_jobs.append(role)
        
    from ..app_instance import sio
    await sio.emit("job_update", {"job_id": "system", "status": "COMPLETED", "sprint_id": sid})
    
    return {"status": "ok", "queued": queued_jobs}

@router.get("/traces/{sprint_id}")
async def get_sprint_traces(sprint_id: str, db: Session = Depends(get_db)):
    traces = db.query(LLMTrace).filter(LLMTrace.sprint_id == sprint_id).order_by(LLMTrace.timestamp.asc()).all()
    return traces
