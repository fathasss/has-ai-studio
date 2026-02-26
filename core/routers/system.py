from fastapi import APIRouter, HTTPException, Depends
import os
import psutil
from datetime import datetime
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import LLMJobRecord, LLMTrace, ProjectException
from ..config import logger, OLLAMA_URL
import httpx

router = APIRouter(prefix="/system", tags=["System"])

@router.get("/status")
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
def list_projects():
    apps_dir = "apps"
    if not os.path.exists(apps_dir): return {"projects": []}
    return {"projects": [d for d in os.listdir(apps_dir) if os.path.isdir(os.path.join(apps_dir, d))]}

@router.get("/projects/{pname}/files")
def list_files(pname: str):
    project_dir = os.path.join("apps", pname)
    if not os.path.exists(project_dir): raise HTTPException(status_code=404)
    file_tree = []
    for root, _, files in os.walk(project_dir):
        for name in files:
            file_tree.append(os.path.relpath(os.path.join(root, name), project_dir).replace("\\", "/"))
    return {"files": sorted(file_tree)}

@router.get("/exceptions")
def get_exceptions(db: Session = Depends(get_db)):
    excs = db.query(ProjectException).order_by(ProjectException.timestamp.desc()).limit(100).all()
    return {"exceptions": excs}

@router.get("/traces")
def get_all_traces(db: Session = Depends(get_db)):
    traces = db.query(LLMTrace).order_by(LLMTrace.timestamp.desc()).limit(100).all()
    return {"traces": traces}
