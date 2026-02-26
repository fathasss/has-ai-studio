import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Float
from .database import Base

class LLMTrace(Base):
    __tablename__ = "llm_traces"
    id = Column(String, primary_key=True)
    job_id = Column(String, nullable=True)
    sprint_id = Column(String)
    agent_name = Column(String)
    worker_id = Column(String)
    execution_node = Column(String)
    priority = Column(Integer)
    prompt = Column(Text)
    response = Column(Text)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    status = Column(String)
    duration_ms = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

class LLMJobRecord(Base):
    __tablename__ = "llm_jobs"
    id = Column(String, primary_key=True)
    sprint_id = Column(String)
    agent_name = Column(String)
    priority = Column(Integer)
    prompt = Column(Text)
    params = Column(Text)
    status = Column(String, default="PENDING")
    worker_id = Column(String, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class GlobalLock(Base):
    __tablename__ = "global_locks"
    resource = Column(String, primary_key=True)
    worker_id = Column(String)
    job_id = Column(String)
    acquired_at = Column(DateTime, default=datetime.utcnow)

class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id = Column(String, primary_key=True)
    hostname = Column(String)
    last_seen = Column(DateTime, default=datetime.utcnow)

class ChatMessageRecord(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sprint_id = Column(String, index=True)
    role = Column(String)
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

class ProjectException(Base):
    __tablename__ = "project_exceptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sprint_id = Column(String, index=True)
    source = Column(String)
    command = Column(String, nullable=True)
    error_message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
