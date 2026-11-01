import uuid
import json
import copy
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from ..database import get_db
from ..models import LLMJobRecord, LLMTrace, ChatMessageRecord
from ..schemas import ExecuteRequest
from .. import config
from ..services.job_service import internal_submit_job
from ..utils import map_role, task_to_prompt, safe_json_loads
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
    if role == "DevOps":     return 1
    if role == "Database":   return 2
    if role == "Backend":    return 3
    if role == "Frontend":   return 4
    if role == "Security":   return 5
    if role == "Tester":     return 6
    if role == "Documenter": return 7
    return 3


def _inject_missing_roles(tasks: list) -> list:
    """
    Ensures DevOps, Security, and Tester are present in the task list.
    DÜZELTME 7: Var olan rolleri kontrol ederek duplicate eklemeyi önler.
    """
    existing_roles = {map_role(t.get("role", "")) for t in tasks}

    if "DevOps" not in existing_roles:
        tasks.insert(0, copy.deepcopy(_FALLBACK_DEVOPS_TASK))
    if "Security" not in existing_roles:
        tasks.append(copy.deepcopy(_FALLBACK_SECURITY_TASK))
    if "Tester" not in existing_roles:
        tasks.append(copy.deepcopy(_FALLBACK_TESTER_TASK))

    return tasks


@router.post("/sprint/execute")
async def execute_sprint(req: ExecuteRequest, db: Session = Depends(get_db)):
    sid  = req.sprint_id
    plan = req.plan

    # DÜZELTME 5: None guard — plan yoksa erken dön
    if not plan or "tasks" not in plan or not isinstance(plan["tasks"], list):
        raise HTTPException(status_code=400, detail="Plan must contain a 'tasks' array.")

    tasks = list(plan["tasks"])
    if not tasks:
        raise HTTPException(status_code=400, detail="Plan 'tasks' array cannot be empty.")

    # DÜZELTME 2 & 7: Duplicate role injection önlendi.
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
        duration_ms    = 0.0,
    ))
    db.commit()

        # 1. Generate project-driven markdown phases and project-based agent memory upfront
    target_dir = f"apps/{sid}" if sid else "workspace"
    structured_phases = []
    try:
        from ..services.phase_service import PhaseService
        from ..services.memory_service import MemoryService
        structured_phases = PhaseService.generate_project_phases(sid, plan, target_dir)
        MemoryService.init_project_memory(sid, plan, target_dir)
    except Exception as e:
        config.logger.warning(f"Could not initialize phase/memory files: {e}")

    # 2. Phased Execution: Projenin 1. Fazındaki görevleri (çoklu ajan dahil) kuyruğa ekle
    initial_tasks = []
    p1 = structured_phases[0] if structured_phases else None
    if p1 and p1.get("tasks"):
        initial_tasks = p1["tasks"]
    else:
        # Fallback: plan içindeki ilk görevler
        devops_tasks   = [t for t in tasks if map_role(t.get("role", "")) == "DevOps"]
        database_tasks = [t for t in tasks if map_role(t.get("role", "")) == "Database"]
        initial_tasks = devops_tasks or database_tasks or tasks

    queued_jobs = []
    for t in initial_tasks:
        role     = map_role(t.get("role", ""))
        priority = _get_priority(role)
        prompt   = task_to_prompt(t)
        job_id   = await internal_submit_job(role, sid, priority, prompt)
        queued_jobs.append(role)
        await sio.emit("job_update", {
            "job_id":     job_id,
            "status":     "PENDING",
            "sprint_id":  sid,
            "agent":      role,
            "agent_name": role,
        })

    await sio.emit("job_update", {
        "job_id":    "system",
        "status":    "STARTED",
        "sprint_id": sid,
        "queued":    queued_jobs,
    })

    # TeamLead initial phase kickoff message in chat and tracking stream
    proj_display_name = plan.get('project_name', sid)
    phase_lines = []
    if structured_phases:
        for p in structured_phases:
            agents_str = ", ".join(f"@{a}" for a in p.get("participating_agents", []))
            badge = "[⚡ ÇALIŞIYOR]" if p.get("phase_id") == 1 else "[⏳ BEKLİYOR]"
            phase_lines.append(f"- **Faz {p['phase_id']}: {p['name']}** ({agents_str}) {badge}")
    else:
        phase_lines = [
            "- **Faz 1: Çekirdek Altyapı & Veri Katmanı** (@DevOps, @Database) [⚡ ÇALIŞIYOR]",
            "- **Faz 2: İş Mantığı & Web Arayüzü** (@Backend, @Frontend) [⏳ BEKLİYOR]",
            "- **Faz 3: Güvenlik, Sentetik Testler & Teslimat** (@Security, @Tester, @Documenter) [⏳ BEKLİYOR]"
        ]

    phase_count = len(structured_phases) if structured_phases else 3
    first_phase_name = structured_phases[0]['name'] if structured_phases else 'Altyapı & Veri Mimarisi'
    msg_parts = [
        "🎯 **Proje Geliştirme Süreci Aktifleştirildi!**",
        f"TeamLead olarak `{proj_display_name}` projesini iş ve kabiliyet odaklı {phase_count} dinamik fazda takip ediyorum:",
        "\n".join(phase_lines),
        f"🚀 *1. Faz ({first_phase_name}) başladı. Ajanlar koordineli çalışmaktadır.*"
    ]
    kickoff_msg = "\n\n".join(msg_parts)
    try:
        db.add(ChatMessageRecord(sprint_id=sid, role="TeamLead", content=kickoff_msg))
        db.commit()
        await sio.emit("new_chat_message", {"sprint_id": sid, "role": "TeamLead", "content": kickoff_msg})
        
        p1_name = structured_phases[0]['name'] if structured_phases else "Çekirdek Altyapı & Veritabanı"
        p1_agent = structured_phases[0]['participating_agents'][0] if (structured_phases and structured_phases[0].get('participating_agents')) else "DevOps"
        p1_agents_str = ", ".join(f"@{a}" for a in (structured_phases[0]['participating_agents'] if structured_phases else ["DevOps", "Database"]))
        await sio.emit("phase_update", {
            "sprint_id": sid,
            "phase_number": 1,
            "phase_name": p1_name,
            "agent": p1_agent,
            "status": "IN_PROGRESS",
            "message": f"Faz 1 ({p1_name}) başlatıldı. Görevli Ajanlar: {p1_agents_str}"
        })
    except Exception as e:
        config.logger.warning(f"Could not persist kickoff chat message: {e}")

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


# ---------------------------------------------------------------------------
# TeamLead Phased Pipeline Tracking & Execution Breakdown
# ---------------------------------------------------------------------------

class PhaseUpdateRequest(BaseModel):
    sprint_id: str
    phase_number: int
    phase_name: str
    agent: str
    status: str
    message: str


DEFAULT_PROJECT_MILESTONES = [
    {
        "phase_id": 1,
        "key": "infra_database",
        "name": "Altyapı & Veritabanı Mimarisi",
        "role": "DevOps",
        "participating_agents": ["DevOps", "Database"],
        "icon": "🏗️",
        "color": "#14b8a6",
        "description": "Kapsayıcı ortamı, paket bağımlılıkları, veritabanı şeması ve modelleri",
        "default_deliverables": ["Dockerfile", "docker-compose.yml", "schema.sql", "models.py"],
    },
    {
        "phase_id": 2,
        "key": "core_business_ui",
        "name": "İş Mantığı Servisleri & Web Arayüzü",
        "role": "Backend",
        "participating_agents": ["Backend", "Frontend"],
        "icon": "⚡",
        "color": "#10b981",
        "description": "REST API servisleri ile responsive kullanıcı arayüzünün eşzamanlı entegre geliştirilmesi",
        "default_deliverables": ["main.py", "routers/", "services/", "index.html", "src/"],
    },
    {
        "phase_id": 3,
        "key": "security_testing_delivery",
        "name": "Güvenlik, Sentetik Testler & Teslimat",
        "role": "Security",
        "participating_agents": ["Security", "Tester", "Documenter", "TeamLead"],
        "icon": "🚀",
        "color": "#f59e0b",
        "description": "OWASP güvenlik denetimi, otomatik birim ve sentetik testler, kapsamlı dokümantasyon",
        "default_deliverables": ["security_audit.md", "tests/test_main.py", "README.md", "API_DOCS.md"],
    },
]


@router.get("/sprint/{sprint_id}/phases")
async def get_sprint_phases(sprint_id: str, db: Session = Depends(get_db)):
    target_dir = f"apps/{sprint_id}" if sprint_id else "workspace"
    
    # 1. Check if dynamic project-driven phases exist in markdown files
    try:
        from ..services.phase_service import PhaseService
        dyn_summary = PhaseService.get_phase_status_summary(sprint_id, target_dir, db)
        if dyn_summary and dyn_summary.get("phases"):
            tl_trace = (
                db.query(LLMTrace)
                .filter(LLMTrace.sprint_id == sprint_id, LLMTrace.agent_name == "TeamLead")
                .order_by(LLMTrace.timestamp.desc())
                .first()
            )
            plan = safe_json_loads(tl_trace.response) if (tl_trace and tl_trace.response) else {}
            project_name = plan.get("project_name", sprint_id) if isinstance(plan, dict) else sprint_id

            agent_colors = {
                "DevOps": "#f97316", "Database": "#14b8a6", "Backend": "#10b981",
                "Frontend": "#06b6d4", "Security": "#ef4444", "Tester": "#a855f7",
                "Documenter": "#38bdf8", "TeamLead": "#facc15"
            }
            agent_icons = {
                "DevOps": "🐳", "Database": "🗄️", "Backend": "⚙️",
                "Frontend": "🎨", "Security": "🛡️", "Tester": "🧪",
                "Documenter": "📚", "TeamLead": "👑"
            }

            for p in dyn_summary["phases"]:
                primary_role = p.get("role") or (p.get("participating_agents", ["TeamLead"])[0] if p.get("participating_agents") else "TeamLead")
                p["icon"] = agent_icons.get(primary_role, "📌")
                p["color"] = agent_colors.get(primary_role, "#facc15")
                p["description"] = p.get("goal") or "Proje faz hedefleri"

            cur_p = dyn_summary["current_phase"]
            active_p_obj = next((p for p in dyn_summary["phases"] if p["phase_id"] == cur_p), dyn_summary["phases"][0])
            active_agents = ", ".join(f"@{a}" for a in active_p_obj.get("participating_agents", []))
            tl_status = f"Faz {cur_p} ({active_p_obj['name']}) aktif — Görevli Ajanlar: {active_agents}."
            if dyn_summary["overall_progress"] >= 100:
                tl_status = "🎉 Tüm proje fazları başarıyla tamamlandı. Proje kodları, testleri ve dokümantasyonu teslim edildi!"

            return {
                "status": "ok",
                "sprint_id": sprint_id,
                "project_name": project_name,
                "current_phase": cur_p,
                "total_phases": dyn_summary["total_phases"],
                "completed_phases": dyn_summary["completed_phases"],
                "overall_progress": dyn_summary["overall_progress"],
                "teamlead_status": tl_status,
                "phases": dyn_summary["phases"],
                "is_dynamic": True
            }
    except Exception as e:
        config.logger.warning(f"Error reading dynamic phases: {e}")
    """
    Returns the real-time 7-phase execution breakdown and TeamLead tracking status
    for the specified sprint.
    """
    # 1. Fetch latest TeamLead plan trace
    tl_trace = (
        db.query(LLMTrace)
        .filter(LLMTrace.sprint_id == sprint_id, LLMTrace.agent_name == "TeamLead")
        .order_by(LLMTrace.timestamp.desc())
        .first()
    )
    plan = safe_json_loads(tl_trace.response) if (tl_trace and tl_trace.response) else {}
    tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
    project_name = plan.get("project_name", sprint_id) if isinstance(plan, dict) else sprint_id

    # 2. Query all jobs for this sprint
    all_jobs = db.query(LLMJobRecord).filter(LLMJobRecord.sprint_id == sprint_id).all()

    phases_output = []
    completed_phases = 0
    in_progress_phase_id = None
    failed_phase_id = None

    for spec in DEFAULT_PROJECT_MILESTONES:
        p_agents = spec.get("participating_agents", [spec["role"]])
        assigned_tasks = [t for t in tasks if map_role(t.get("role", "")) in p_agents]
        deliverables = [t.get("target_file") for t in assigned_tasks if t.get("target_file")]
        if not deliverables:
            deliverables = list(spec["default_deliverables"])

        # Match jobs for participating roles
        role_jobs = [j for j in all_jobs if map_role(j.agent_name or "") in p_agents]

        # Status determination
        if any(j.status in ("PROCESSING", "WORKING") for j in role_jobs):
            status = "IN_PROGRESS"
            in_progress_phase_id = spec["phase_id"]
        elif any(j.status == "FAILED" for j in role_jobs):
            status = "FAILED"
            failed_phase_id = spec["phase_id"]
        elif role_jobs and all(j.status in ("COMPLETED", "SUCCESS") for j in role_jobs):
            status = "COMPLETED"
            completed_phases += 1
        elif any(j.status == "PENDING" for j in role_jobs):
            status = "PENDING"
        else:
            status = "PENDING"

        phases_output.append({
            "phase_id": spec["phase_id"],
            "key": spec["key"],
            "name": spec["name"],
            "role": spec["role"],
            "participating_agents": p_agents,
            "icon": spec["icon"],
            "color": spec["color"],
            "description": spec["description"],
            "status": status,
            "deliverables": deliverables,
            "tasks_count": len(assigned_tasks),
            "tasks": assigned_tasks,
            "jobs_count": len(role_jobs),
        })

    # Sequential logic: compute current phase and overall progress
    total_phases = len(DEFAULT_PROJECT_MILESTONES)
    current_phase = in_progress_phase_id or failed_phase_id
    if not current_phase:
        if completed_phases >= total_phases:
            current_phase = total_phases
        else:
            for p in phases_output:
                if p["status"] != "COMPLETED":
                    current_phase = p["phase_id"]
                    if p["status"] == "PENDING" and p["phase_id"] == completed_phases + 1 and completed_phases > 0:
                        p["status"] = "IN_PROGRESS"
                    break
            if not current_phase:
                current_phase = 1

    overall_progress = int((completed_phases / max(total_phases, 1)) * 100)
    if completed_phases >= total_phases:
        overall_progress = 100

    teamlead_commentaries = {
        1: "DevOps ve Veritabanı uzmanları altyapı iskeletini ve veri modellerini hazırlıyor.",
        2: "Backend ve Frontend ekipleri REST API servislerini ve kullanıcı arayüzünü entegre inşa ediyor.",
        3: "Güvenlik denetimi, otomatik sentetik testler ve nihai dokümantasyon tamamlanıp teslim ediliyor.",
    }
    tl_status = teamlead_commentaries.get(current_phase, "Proje geliştirme fazları takip ediliyor.")
    if completed_phases >= total_phases:
        tl_status = "🎉 Tüm proje fazları başarıyla tamamlandı. Proje test edildi ve teslime hazır!"

    return {
        "status": "ok",
        "sprint_id": sprint_id,
        "project_name": project_name,
        "current_phase": current_phase,
        "total_phases": total_phases,
        "completed_phases": completed_phases,
        "overall_progress": overall_progress,
        "teamlead_status": tl_status,
        "phases": phases_output,
    }
@router.post("/sprint/phase-update")
async def update_sprint_phase(req: PhaseUpdateRequest, db: Session = Depends(get_db)):
    """
    Receives phase progress events and broadcasts them to clients via Socket.IO
    while saving a TeamLead tracking message into chat history.
    """
    msg_content = f"📌 **[Faz Takibi] Faz {req.phase_number} ({req.phase_name})**: {req.message}"
    try:
        db.add(ChatMessageRecord(
            sprint_id=req.sprint_id,
            role="TeamLead",
            content=msg_content
        ))
        db.commit()
    except Exception as e:
        config.logger.warning(f"Could not save phase update to chat history: {e}")

    await sio.emit("phase_update", {
        "sprint_id": req.sprint_id,
        "phase_number": req.phase_number,
        "phase_name": req.phase_name,
        "agent": req.agent,
        "status": req.status,
        "message": req.message
    })
    await sio.emit("new_chat_message", {
        "sprint_id": req.sprint_id,
        "role": "TeamLead",
        "content": msg_content
    })
    return {"status": "ok"}


@router.get("/sprint/{sprint_id}/memory")
async def get_sprint_memory(sprint_id: str):
    """Returns the accumulated project memory and per-agent memories."""
    target_dir = f"apps/{sprint_id}" if sprint_id else "workspace"
    from ..services.memory_service import MemoryService
    return MemoryService.get_all_memory(sprint_id, target_dir)
