from pydantic import BaseModel
from typing import List, Optional

class LLMJobRequest(BaseModel):
    agent_name: str
    sprint_id: str
    priority: int
    prompt: str
    params: Optional[dict] = {}

class ChatRequest(BaseModel):
    history: list
    params: Optional[dict] = {}

class ExecuteRequest(BaseModel):
    sprint_id: str
    plan: dict
    history: Optional[list] = []

class LLMJobCompletion(BaseModel):
    result: str
    metrics: dict

class ChatMessageSchema(BaseModel):
    sprint_id: str
    role: str
    content: str

class LLMTraceSchema(BaseModel):
    id: str
    job_id: str
    sprint_id: str
    agent_name: str
    worker_id: str
    execution_node: str
    priority: int
    prompt: str
    response: str
    status: str
    duration_ms: float
    prompt_tokens: Optional[int] = 0
    completion_tokens: Optional[int] = 0
    total_tokens: Optional[int] = 0
