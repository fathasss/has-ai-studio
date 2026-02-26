from fastapi import APIRouter, Body
from ..config import runtime_config, save_config, logger

router = APIRouter(tags=["Config"])

@router.get("/config")
def get_runtime_config():
    return runtime_config

@router.post("/config")
def update_config(config: dict = Body(...)):
    global runtime_config
    try:
        # Update runtime_config dict in place or replace it
        for k, v in config.items():
            runtime_config[k] = v
        
        # Persist to data/config.json
        save_config(runtime_config)
        
        # We might need to refresh individual variables in config.py 
        # but for now, simple persistence is a good start.
        logger.info(f"Configuration updated: {runtime_config}")
        return {"status": "ok", "config": runtime_config}
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        return {"status": "error", "message": str(e)}
