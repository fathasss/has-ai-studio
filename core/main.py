import os
import threading
import asyncio
import time
from datetime import datetime, timedelta
from fastapi import Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from .app_instance import f_app, sio_app, sio
from .database import engine, Base, SessionLocal, get_db
from .models import LLMTrace
from .config import logger, AGENT_ROLE
from .routers import chat, llm, sprint, system, jobs, config, ollama
from .services import worker_service

# Include Routers
f_app.include_router(chat.router)
f_app.include_router(llm.router)
f_app.include_router(sprint.router)
f_app.include_router(system.router)
f_app.include_router(jobs.router)
f_app.include_router(config.router)
f_app.include_router(ollama.router)

@f_app.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    # Simple real-time metrics fetch for non-websocket clients
    timeout = datetime.utcnow() - timedelta(minutes=10)
    recent_traces = db.query(LLMTrace).filter(LLMTrace.timestamp > timeout).all()
    total_chars = sum(len(t.response or "") + len(t.prompt or "") for t in recent_traces)
    tokens_min = int((total_chars / 4) / 10)
    
    # Approx uptime
    uptime_sec = int(time.time() - worker_service.START_TIME)
    
    return {
        "performance": {
            "total_tokens": int(total_chars / 4),
            "token_rate_per_min": tokens_min,
            "uptime_sec": uptime_sec
        }
    }

# CORS configuration
f_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@f_app.on_event("startup")
async def startup_event():
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    
    logger.info(f"HAS-AI-TEAM Orchestrator starting with ROLE: {AGENT_ROLE}")
    
    if AGENT_ROLE in ["master", "both"]:
        logger.info("Initializing Master tasks (Watchdog, Metrics)...")
        threading.Thread(target=worker_service.watchdog_loop, daemon=True).start()
        asyncio.create_task(worker_service.metrics_loop(sio))
    
    if AGENT_ROLE in ["worker", "both"]:
        logger.info("Initializing Worker tasks (LLM Worker)...")
        threading.Thread(target=worker_service.llm_worker, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(sio_app, host="0.0.0.0", port=8000)
