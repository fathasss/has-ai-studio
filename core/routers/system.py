from fastapi import APIRouter, HTTPException, Depends
import os
import psutil
from datetime import datetime
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import LLMJobRecord, LLMTrace, ProjectException
from ..config import logger, OLLAMA_URL
import httpx

router = APIRouter(tags=["System"])

@router.get("/system/status")
def get_system_status(db: Session = Depends(get_db)):
    process = psutil.Process(os.getpid())
    pending = db.query(LLMJobRecord).filter(LLMJobRecord.status == "PENDING").count()
    processing = db.query(LLMJobRecord).filter(LLMJobRecord.status == "PROCESSING").count()
    return {
        "queue_depth": pending,
        "active_jobs": processing,
        "memory_rss_mb": process.memory_info().rss / 1024 / 1024,
    }

@router.get("/projects")
@router.get("/sprints")
def list_projects():
    apps_dir = "apps"
    if not os.path.exists(apps_dir): return {"projects": [], "sprints": []}
    projs = [d for d in os.listdir(apps_dir) if os.path.isdir(os.path.join(apps_dir, d))]
    return {"projects": projs, "sprints": projs}

@router.get("/projects/{pname}/files")
def list_files(pname: str):
    project_dir = os.path.join("apps", pname)
    if not os.path.exists(project_dir): raise HTTPException(status_code=404)
    file_tree = []
    for root, _, files in os.walk(project_dir):
        for name in files:
            file_tree.append(os.path.relpath(os.path.join(root, name), project_dir).replace("\\", "/"))
    return {"files": sorted(file_tree)}

@router.get("/projects/{pname}/file")
def get_file_content(pname: str, path: str):
    full_path = os.path.join("apps", pname, path)
    if not os.path.exists(full_path): raise HTTPException(status_code=404, detail="File not found")
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exceptions")
def get_exceptions(db: Session = Depends(get_db)):
    excs = db.query(ProjectException).order_by(ProjectException.timestamp.desc()).limit(100).all()
    return {"exceptions": excs}

@router.get("/traces")
def get_all_traces(db: Session = Depends(get_db)):
    traces = db.query(LLMTrace).order_by(LLMTrace.timestamp.desc()).limit(100).all()
    return {"traces": traces}

@router.get("/reports/sessions")
def list_report_sessions():
    work_dir = "workspace"
    if not os.path.exists(work_dir): return {"sessions": []}
    sessions = [d for d in os.listdir(work_dir) if os.path.isdir(os.path.join(work_dir, d))]
    return {"sessions": sorted(sessions, reverse=True)}

@router.get("/reports/{sid}/files")
def list_session_reports(sid: str):
    session_dir = os.path.join("workspace", sid)
    if not os.path.exists(session_dir): raise HTTPException(status_code=404, detail="Session not found")
    files = [f for f in os.listdir(session_dir) if f.endswith(".md")]
    return {"files": sorted(files)}

@router.get("/reports/{sid}/content")
def get_report_content(sid: str, filename: str):
    full_path = os.path.join("workspace", sid, filename)
    if not os.path.exists(full_path): raise HTTPException(status_code=404, detail="Report not found")
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
