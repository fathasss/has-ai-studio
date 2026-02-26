import os
import threading
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from .app_instance import f_app, sio_app, sio
from .database import engine, Base
from .config import logger, AGENT_ROLE
from .routers import chat, llm, sprint, system, jobs
from .services import worker_service

# Include Routers
f_app.include_router(chat.router)
f_app.include_router(llm.router)
f_app.include_router(sprint.router)
f_app.include_router(system.router)
f_app.include_router(jobs.router)

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
