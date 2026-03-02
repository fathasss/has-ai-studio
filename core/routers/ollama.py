from fastapi import APIRouter, HTTPException
import httpx
import asyncio
from .. import config

router = APIRouter(tags=["Ollama"])

@router.get("/ollama/models")
async def list_models():
    try:
        headers = {}
        if config.LLM_PROVIDER == "ollama-cloud" and config.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
            
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{config.OLLAMA_URL}/api/tags", headers=headers)
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
    from ..app_instance import sio
    import json
    
    model_name = req.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="Model name required")
    
    async def pull_stream():
        try:
            headers = {}
            if config.LLM_PROVIDER == "ollama-cloud" and config.LLM_API_KEY:
                headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
                
            async with httpx.AsyncClient(timeout=1200.0) as client:
                async with client.stream(
                    "POST", 
                    f"{config.OLLAMA_URL}/api/pull", 
                    headers=headers,
                    json={"name": model_name, "stream": True}
                ) as response:
                    if response.status_code != 200:
                        config.logger.error(f"Ollama pull failed: {response.status_code}")
                        await sio.emit("model_pull_progress", {
                            "model": model_name, 
                            "status": "error", 
                            "message": f"Ollama Error: {response.status_code}"
                        })
                        return

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            body = json.loads(line)
                            status = body.get("status", "")
                            completed = body.get("completed", 0)
                            total = body.get("total", 0)
                            
                            progress = 0
                            if total > 0:
                                progress = int((completed / total) * 100)
                            
                            # Emit progress via Socket.io
                            await sio.emit("model_pull_progress", {
                                "model": model_name,
                                "status": status,
                                "completed": completed,
                                "total": total,
                                "progress": progress
                            })
                        except Exception as e:
                            config.logger.error(f"Error parsing pull stream: {e}")

            await sio.emit("model_pull_progress", {
                "model": model_name,
                "status": "success",
                "progress": 100
            })
            
        except Exception as e:
            config.logger.error(f"Pull stream failed locally: {e}")
            await sio.emit("model_pull_progress", {
                "model": model_name,
                "status": "error",
                "message": str(e)
            })

    # Start the stream as a background task via asyncio check
    asyncio.create_task(pull_stream())
    
    return {"status": "started", "message": f"Pulling {model_name} in background..."}
