from fastapi import APIRouter, HTTPException
import httpx
from .. import config

router = APIRouter(tags=["Ollama"])

@router.get("/ollama/models")
async def list_models():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{config.OLLAMA_URL}/api/tags")
            if resp.status_code != 200:
                return {"models": []}
            
            data = resp.json()
            model_names = [m["name"] for m in data.get("models", [])]
            return {"models": model_names}
    except Exception as e:
        config.logger.error(f"Failed to fetch Ollama models: {e}")
        return {"models": []}

@router.post("/ollama/pull")
async def pull_model(req: dict):
    model_name = req.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="Model name required")
    
    try:
        # We use a long timeout for pulls
        async with httpx.AsyncClient(timeout=1200.0) as client:
            resp = await client.post(
                f"{config.OLLAMA_URL}/api/pull",
                json={"name": model_name, "stream": False}
            )
            if resp.status_code == 200:
                return {"status": "ok", "message": f"Model {model_name} pulled successfully"}
            else:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except Exception as e:
        config.logger.error(f"Failed to pull model {model_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
