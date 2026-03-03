from fastapi import APIRouter, HTTPException, Depends
import os
import psutil
from datetime import datetime
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import LLMJobRecord, LLMTrace, ProjectException
from ..config import logger, OLLAMA_URL, AGENT_MODEL
import httpx
from .ollama import is_model_installed

router = APIRouter(tags=["System"])

# Define base directory relative to this file to robustify path handling
# core/routers/system.py -> core/routers -> core -> root
# Specifically, we want the root that contains 'apps' and 'workspace'
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
APPS_DIR = os.path.join(BASE_DIR, "apps")
WORK_DIR = os.path.join(BASE_DIR, "workspace")

logger.info(f"System router initialized. BASE_DIR: {BASE_DIR}")
logger.info(f"APPS_DIR: {APPS_DIR} (Exists: {os.path.exists(APPS_DIR)})")
logger.info(f"WORK_DIR: {WORK_DIR} (Exists: {os.path.exists(WORK_DIR)})")

@router.get("/system/status")
async def get_system_status(db: Session = Depends(get_db)):
    process = psutil.Process(os.getpid())
    pending = db.query(LLMJobRecord).filter(LLMJobRecord.status == "PENDING").count()
    processing = db.query(LLMJobRecord).filter(LLMJobRecord.status == "PROCESSING").count()
    
    # Check model status
    installed = await is_model_installed(AGENT_MODEL)
    
    return {
        "queue_depth": pending,
        "active_jobs": processing,
        "memory_rss_mb": process.memory_info().rss / 1024 / 1024,
        "model_id": AGENT_MODEL,
        "model_status": "INSTALLED" if installed else "MISSING"
    }

@router.get("/projects")
@router.get("/sprints")
def list_projects(db: Session = Depends(get_db)):
    fs_projs = []
    if os.path.exists(APPS_DIR):
        fs_projs = [d for d in os.listdir(APPS_DIR) if os.path.isdir(os.path.join(APPS_DIR, d))]
    
    # Also get sprint IDs from database to include projects in setup/pending state
    db_sprints = db.query(LLMTrace.sprint_id).filter(LLMTrace.sprint_id != None).distinct().all()
    db_jobs = db.query(LLMJobRecord.sprint_id).filter(LLMJobRecord.sprint_id != None).distinct().all()
    
    all_sprints = set(fs_projs)
    for s in db_sprints:
        if s[0]: all_sprints.add(s[0])
    for s in db_jobs:
        if s[0]: all_sprints.add(s[0])
        
    projs = sorted(list(all_sprints), reverse=True)
    return {"projects": projs, "sprints": projs}

@router.get("/projects/{pname}/files")
def list_files(pname: str):
    project_dir = os.path.join(APPS_DIR, pname)
    if not os.path.exists(project_dir):
        logger.warning(f"Project directory not found: {project_dir}")
        raise HTTPException(status_code=404)
    file_tree = []
    for root, _, files in os.walk(project_dir):
        for name in files:
            file_tree.append(os.path.relpath(os.path.join(root, name), project_dir).replace("\\", "/"))
    return {"files": sorted(file_tree)}

@router.get("/projects/{pname}/file")
def get_file_content(pname: str, path: str):
    full_path = os.path.join(APPS_DIR, pname, path)
    if not os.path.exists(full_path):
        logger.warning(f"File not found: {full_path}")
        raise HTTPException(status_code=404, detail="File not found")
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
    if not os.path.exists(WORK_DIR):
        logger.warning(f"Workspace directory not found: {WORK_DIR}")
        return {"sessions": []}
    logger.info(f"Scanning for report sessions in: {WORK_DIR}")
    sessions = [d for d in os.listdir(WORK_DIR) if os.path.isdir(os.path.join(WORK_DIR, d))]
    return {"sessions": sorted(sessions, reverse=True)}

@router.get("/reports/{sid}/files")
def list_session_reports(sid: str):
    session_dir = os.path.join(WORK_DIR, sid)
    if not os.path.exists(session_dir):
        logger.warning(f"Session directory not found: {session_dir}")
        raise HTTPException(status_code=404, detail="Session not found")
    
    all_files = []
    for root, _, files in os.walk(session_dir):
        for f in files:
            if f.endswith(".md"):
                rel_path = os.path.relpath(os.path.join(root, f), session_dir)
                all_files.append(rel_path.replace("\\", "/"))
                
    return {"files": sorted(all_files)}

@router.get("/reports/{sid}/content")
def get_report_content(sid: str, filename: str):
    full_path = os.path.join(WORK_DIR, sid, filename)
    if not os.path.exists(full_path):
        logger.warning(f"Report file not found: {full_path}")
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/reports/debug")
def debug_reports():
    """Debug endpoint to verify what the backend sees in the workspace."""
    results = {
        "BASE_DIR": BASE_DIR,
        "WORK_DIR": WORK_DIR,
        "WORK_DIR_EXISTS": os.path.exists(WORK_DIR),
        "CWD": os.getcwd(),
        "listing": []
    }
    
    if os.path.exists(WORK_DIR):
        for root, dirs, files in os.walk(WORK_DIR):
            results["listing"].append({
                "root": root,
                "dirs": dirs,
                "files": files
            })
    return results
