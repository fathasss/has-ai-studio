"""
System management router.

Provides endpoints for system health, project/sprint listing,
file browsing, trace/exception viewing, and report management.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .. import config  # DÜZELTME 1: Modül olarak import — runtime değişikliklerini yakalar
from ..database import get_db
from ..models import LLMJobRecord, LLMTrace, ProjectException
from .ollama import is_model_installed

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------

router = APIRouter(tags=["System"])

# Directory resolution: core/routers/system.py → core/routers → core → project root
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
APPS_DIR = os.path.join(BASE_DIR, "apps")
WORK_DIR = os.path.join(BASE_DIR, "workspace")

DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"

# Security constants
RESOURCE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-. ]*$")
MAX_RESOURCE_NAME_LENGTH = 200
MAX_FILES_SCAN = 5000
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

TEXT_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".env",
    ".sh", ".bash", ".sql", ".xml", ".csv", ".ini", ".cfg",
    ".dockerfile", ".gitignore", ".editorconfig", ".lock",
})

TEXT_FILENAMES = frozenset({
    "dockerfile", "makefile", ".gitignore", ".dockerignore",
    ".env.example", ".env.local", "procfile",
})

REPORT_EXTENSIONS = frozenset({".md", ".html", ".json", ".txt", ".log"})

SKIP_DIRECTORIES = frozenset({
    "node_modules", "__pycache__", ".git", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
})

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class SystemStatusResponse(BaseModel):
    queue_depth: int
    active_jobs: int
    memory_rss_mb: float
    model_id: str
    model_status: str


class SprintListResponse(BaseModel):
    sprints: list[str]
    projects: list[str]  # backward compatibility alias


class FileListResponse(BaseModel):
    files: list[str]


class FileContentResponse(BaseModel):
    content: str
    path: str


class ExceptionListResponse(BaseModel):
    exceptions: list[dict]
    total: int
    page: int
    page_size: int
    has_next: bool


class TraceListResponse(BaseModel):
    traces: list[dict]
    total: int
    page: int
    page_size: int
    has_next: bool


class SessionListResponse(BaseModel):
    sessions: list[str]


class ReportFileListResponse(BaseModel):
    files: list[str]


class ReportContentResponse(BaseModel):
    content: str
    filename: str


# ---------------------------------------------------------------------------
# Security Helpers
# ---------------------------------------------------------------------------

def validate_resource_name(name: str, resource_type: str = "resource") -> str:
    """
    Validate a resource name contains only safe characters.

    Prevents path traversal via project names, session IDs, etc.
    Raises HTTPException(400) if invalid.
    """
    name = name.strip()
    if not name:
        raise HTTPException(400, f"{resource_type} name cannot be empty")
    if len(name) > MAX_RESOURCE_NAME_LENGTH:
        raise HTTPException(400, f"{resource_type} name too long (max {MAX_RESOURCE_NAME_LENGTH})")
    if ".." in name:
        raise HTTPException(400, f"Invalid {resource_type} name")
    if not RESOURCE_NAME_PATTERN.match(name):
        raise HTTPException(
            400,
            f"Invalid {resource_type} name: only letters, digits, '-', '_', '.', and spaces allowed",
        )
    return name


def safe_resolve_path(base_dir: str, *segments: str) -> str:
    """
    Safely resolve a path ensuring it stays within base_dir.

    Prevents path traversal attacks (e.g., ../../etc/passwd).
    Raises HTTPException(400) on traversal attempt.
    """
    for segment in segments:
        if not segment or not segment.strip():
            raise HTTPException(400, "Empty path segment")

    base = Path(base_dir).resolve()
    target = Path(os.path.join(base_dir, *segments)).resolve()

    try:
        target.relative_to(base)
    except ValueError:
        config.logger.warning(
            f"Path traversal blocked: segments={segments}, "
            f"resolved='{target}', base='{base}'"
        )
        raise HTTPException(400, "Invalid path")

    return str(target)


def read_text_file_safe(file_path: str) -> str:
    """
    Safely read a text file with type and size guards.

    Raises HTTPException(404) if not found.
    Raises HTTPException(413) if too large.
    Raises HTTPException(415) if binary/unsupported type.
    """
    if not os.path.isfile(file_path):
        raise HTTPException(404, "File not found")

    ext = os.path.splitext(file_path)[1].lower()
    basename = os.path.basename(file_path).lower()

    if ext not in TEXT_EXTENSIONS and basename not in TEXT_FILENAMES:
        raise HTTPException(415, f"Unsupported file type: '{ext or basename}'")

    file_size = os.path.getsize(file_path)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            413,
            f"File too large: {file_size / 1024 / 1024:.1f}MB "
            f"(max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB)",
        )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        raise HTTPException(415, "File is not valid UTF-8 text")
    except PermissionError:
        config.logger.error(f"Permission denied reading file: {file_path}")
        raise HTTPException(403, "Permission denied")
    except OSError as e:
        config.logger.error(f"OS error reading file {file_path}: {e}")
        raise HTTPException(500, "Failed to read file")


# ---------------------------------------------------------------------------
# Filesystem Helpers
# ---------------------------------------------------------------------------

def _scan_directory(
    directory: str,
    max_files: int = MAX_FILES_SCAN,
    extension_filter: frozenset[str] | None = None,
) -> list[str]:
    """
    Scan a directory tree and return sorted relative file paths.

    - Skips hidden directories and known-heavy directories.
    - Skips symlinks to prevent symlink-based traversal.
    - Enforces a maximum file count to prevent DoS on large directories.
    """
    files: list[str] = []

    for root, dirnames, filenames in os.walk(directory, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and d not in SKIP_DIRECTORIES
            and not os.path.islink(os.path.join(root, d))
        ]

        for name in filenames:
            full = os.path.join(root, name)

            if os.path.islink(full):
                continue

            if extension_filter:
                ext = os.path.splitext(name)[1].lower()
                if ext not in extension_filter:
                    continue

            rel = os.path.relpath(full, directory).replace("\\", "/")
            files.append(rel)

            if len(files) >= max_files:
                config.logger.warning(
                    f"File scan limit reached ({max_files}) for {directory}"
                )
                return sorted(files)

    return sorted(files)


def _model_to_dict(obj) -> dict:
    """Convert a SQLAlchemy model instance to a plain dictionary."""
    return {
        col.name: getattr(obj, col.name)
        for col in obj.__table__.columns
    }


def _ensure_directory(path: str, name: str) -> None:
    """Ensure a directory exists, creating it if necessary."""
    if not os.path.exists(path):
        config.logger.warning(f"{name} does not exist, creating: {path}")
        os.makedirs(path, exist_ok=True)


# ---------------------------------------------------------------------------
# Startup Initialization
# ---------------------------------------------------------------------------

def initialize() -> None:
    """Verify and create required directories. Called once at import time."""
    _ensure_directory(APPS_DIR, "APPS_DIR")
    _ensure_directory(WORK_DIR, "WORK_DIR")
    config.logger.info(f"System router initialized. BASE_DIR={BASE_DIR}")


initialize()


# ---------------------------------------------------------------------------
# Shared Business Logic
# ---------------------------------------------------------------------------

async def _get_sprints(db: Session) -> SprintListResponse:
    """
    DÜZELTME 2: Shared sprint listing logic extracted to avoid double DB
    session when /projects delegates to /sprints.
    """
    fs_sprints: set[str] = set()
    if os.path.exists(APPS_DIR):
        fs_sprints = {
            d for d in os.listdir(APPS_DIR)
            if os.path.isdir(os.path.join(APPS_DIR, d)) and not d.startswith(".") and d.lower() != "idle"
        }

    db_sprint_ids = (
        db.query(LLMTrace.sprint_id)
        .filter(LLMTrace.sprint_id.isnot(None), LLMTrace.sprint_id != "", func.lower(LLMTrace.sprint_id) != "idle")
        .union(
            db.query(LLMJobRecord.sprint_id)
            .filter(LLMJobRecord.sprint_id.isnot(None), LLMJobRecord.sprint_id != "", func.lower(LLMJobRecord.sprint_id) != "idle")
        )
        .distinct()
        .all()
    )

    all_sprints = {s for s in (fs_sprints | {row[0] for row in db_sprint_ids if row[0]}) if s and s.lower() != "idle"}
    sorted_sprints = sorted(all_sprints, reverse=True)

    return SprintListResponse(
        sprints=sorted_sprints,
        projects=sorted_sprints,
    )


# ---------------------------------------------------------------------------
# Routes — System
# ---------------------------------------------------------------------------

@router.get("/system/status", response_model=SystemStatusResponse)
async def get_system_status(db: Session = Depends(get_db)):
    """Get current system health: queue depth, active jobs, memory, model status."""
    process = psutil.Process(os.getpid())

    job_counts = db.query(
        func.count(case((LLMJobRecord.status == "PENDING", 1))).label("pending"),
        func.count(case((LLMJobRecord.status == "PROCESSING", 1))).label("processing"),
    ).one()

    # DÜZELTME 1: config.AGENT_MODEL — runtime refresh'i yansıtır
    installed = await is_model_installed(config.AGENT_MODEL)

    return SystemStatusResponse(
        queue_depth=job_counts.pending,
        active_jobs=job_counts.processing,
        memory_rss_mb=round(process.memory_info().rss / 1024 / 1024, 2),
        model_id=config.AGENT_MODEL,
        model_status="INSTALLED" if installed else "MISSING",
    )


# ---------------------------------------------------------------------------
# Routes — Projects / Sprints
# ---------------------------------------------------------------------------

@router.get("/sprints", response_model=SprintListResponse)
async def list_sprints(db: Session = Depends(get_db)):
    """List all known sprints from filesystem and database records."""
    return await _get_sprints(db)


@router.get("/projects", response_model=SprintListResponse, deprecated=True)
async def list_projects(db: Session = Depends(get_db)):
    """Alias for /sprints. Deprecated — use GET /sprints instead."""
    # DÜZELTME 2: Aynı db session paylaşılıyor — double session açılmıyor
    return await _get_sprints(db)


# ---------------------------------------------------------------------------
# Routes — Project Files
# ---------------------------------------------------------------------------

@router.get("/projects/{pname}/files", response_model=FileListResponse)
async def list_project_files(pname: str):
    """List all files in a project directory."""
    pname = validate_resource_name(pname, "project")
    project_dir = safe_resolve_path(APPS_DIR, pname)

    if not os.path.isdir(project_dir):
        raise HTTPException(404, "Project not found")

    file_tree = await asyncio.to_thread(_scan_directory, project_dir)
    return FileListResponse(files=file_tree)


@router.get("/projects/{pname}/file", response_model=FileContentResponse)
async def get_project_file_content(
    pname: str,
    path: str = Query(..., min_length=1, max_length=500, description="Relative file path within the project"),
):
    """Read the content of a specific file within a project. Only text files under 5MB."""
    pname = validate_resource_name(pname, "project")

    if ".." in path.split("/"):
        raise HTTPException(400, "Invalid file path")

    full_path = safe_resolve_path(APPS_DIR, pname, path)
    content = await asyncio.to_thread(read_text_file_safe, full_path)

    return FileContentResponse(content=content, path=path)


# ---------------------------------------------------------------------------
# Routes — Exceptions & Traces (Paginated)
# ---------------------------------------------------------------------------

@router.get("/exceptions", response_model=ExceptionListResponse)
async def get_exceptions(
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """List project exceptions with pagination, newest first."""
    total = db.query(func.count(ProjectException.id)).scalar() or 0
    offset = (page - 1) * page_size

    excs = (
        db.query(ProjectException)
        .order_by(ProjectException.timestamp.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return ExceptionListResponse(
        exceptions=[_model_to_dict(e) for e in excs],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.get("/traces", response_model=TraceListResponse)
async def get_all_traces(
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """List LLM traces with pagination, newest first."""
    total = db.query(func.count(LLMTrace.id)).scalar() or 0
    offset = (page - 1) * page_size

    traces = (
        db.query(LLMTrace)
        .order_by(LLMTrace.timestamp.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return TraceListResponse(
        traces=[_model_to_dict(t) for t in traces],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


# ---------------------------------------------------------------------------
# Routes — Reports
# ---------------------------------------------------------------------------

@router.get("/reports/sessions", response_model=SessionListResponse)
async def list_report_sessions():
    """List available report sessions from the workspace directory."""
    if not os.path.exists(WORK_DIR):
        config.logger.warning(f"Workspace directory not found: {WORK_DIR}")
        return SessionListResponse(sessions=[])

    sessions = await asyncio.to_thread(
        lambda: sorted(
            [
                d for d in os.listdir(WORK_DIR)
                if os.path.isdir(os.path.join(WORK_DIR, d)) and not d.startswith(".")
            ],
            reverse=True,
        )
    )
    return SessionListResponse(sessions=sessions)


@router.get("/reports/{sid}/files", response_model=ReportFileListResponse)
async def list_session_reports(sid: str):
    """List report files within a specific session directory."""
    sid = validate_resource_name(sid, "session")
    session_dir = safe_resolve_path(WORK_DIR, sid)

    if not os.path.isdir(session_dir):
        raise HTTPException(404, "Session not found")

    files = await asyncio.to_thread(
        _scan_directory, session_dir, MAX_FILES_SCAN, REPORT_EXTENSIONS
    )
    return ReportFileListResponse(files=files)


@router.get("/reports/{sid}/content", response_model=ReportContentResponse)
async def get_report_content(
    sid: str,
    filename: str = Query(..., min_length=1, max_length=500),
):
    """Read the content of a specific report file within a session."""
    sid = validate_resource_name(sid, "session")

    if ".." in filename.split("/"):
        raise HTTPException(400, "Invalid filename")

    full_path = safe_resolve_path(WORK_DIR, sid, filename)
    content = await asyncio.to_thread(read_text_file_safe, full_path)

    return ReportContentResponse(content=content, filename=filename)


# ---------------------------------------------------------------------------
# Routes — Debug (conditional)
# ---------------------------------------------------------------------------

@router.get("/reports/debug", include_in_schema=False)
async def debug_reports():
    """
    Debug endpoint for workspace inspection.
    Only available when DEBUG=true environment variable is set.
    Returns minimal, non-sensitive information.
    """
    if not DEBUG_MODE:
        raise HTTPException(404)

    session_count = 0
    if os.path.exists(WORK_DIR):
        session_count = len([
            d for d in os.listdir(WORK_DIR)
            if os.path.isdir(os.path.join(WORK_DIR, d))
        ])

    return {
        "work_dir_exists": os.path.exists(WORK_DIR),
        "apps_dir_exists": os.path.exists(APPS_DIR),
        "session_count":   session_count,
        "debug_mode":      True,
    }