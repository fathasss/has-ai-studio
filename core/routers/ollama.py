from fastapi import APIRouter, HTTPException, BackgroundTasks
import httpx
import asyncio
import json
from .. import config
from ..app_instance import sio

router = APIRouter(tags=["Ollama"])

@router.get("/ollama/models")
async def list_models(url: str = None, provider: str = None, api_key: str = None):
    try:
        config.logger.info(f"Ollama Model List Request: url='{url}', provider='{provider}', api_key_set={'Yes' if api_key else 'No'}")
        
        # Use provided params or fallback to global config
        target_url = url or config.OLLAMA_URL
        target_provider = provider or config.LLM_PROVIDER
        target_api_key = api_key or config.LLM_API_KEY
        
        config.logger.info(f"Resolution: Using URL='{target_url}' for model discovery")

        headers = {}
        if target_provider == "ollama-cloud" and target_api_key:
            headers["Authorization"] = f"Bearer {target_api_key}"
            
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{target_url}/api/tags", headers=headers)
            if resp.status_code != 200:
                config.logger.warning(f"Failed to fetch models from {target_url}: {resp.status_code}")
                return {"models": []}
            
            data = resp.json()
            model_names = [m["name"] for m in data.get("models", [])]
            config.logger.info(f"Fetched {len(model_names)} models from {target_url}")
            return {"models": model_names}
    except Exception as e:
        config.logger.error(f"Failed to fetch Ollama models: {e}")
        return {"models": []}

async def pull_stream_worker(model_name: str, target_url: str, provider: str, api_key: str):
    config.logger.info(f"Background Pull Started: model='{model_name}', target='{target_url}'")
    try:
        headers = {}
        if provider == "ollama-cloud" and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            
        async with httpx.AsyncClient(timeout=1800.0) as client:
            async with client.stream(
                "POST", 
                f"{target_url}/api/pull", 
                headers=headers,
                json={"name": model_name, "stream": True}
            ) as response:
                if response.status_code != 200:
                    config.logger.error(f"Ollama pull stream failed initiation: {response.status_code}")
                    await sio.emit("model_pull_progress", {
                        "model": model_name, 
                        "status": "error", 
                        "message": f"Ollama HTTP {response.status_code}"
                    })
                    return

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        body = json.loads(line)
                        if "error" in body:
                            config.logger.error(f"Ollama error in stream: {body['error']}")
                            await sio.emit("model_pull_progress", {
                                "model": model_name,
                                "status": "error",
                                "message": body["error"]
                            })
                            return

                        status = body.get("status", "")
                        completed = body.get("completed", 0)
                        total = body.get("total", 0)
                        progress = int((completed / total) * 100) if total > 0 else 0
                        
                        # Broadcast to all clients
                        await sio.emit("model_pull_progress", {
                            "model": model_name,
                            "status": status,
                            "completed": completed,
                            "total": total,
                            "progress": progress
                        })
                    except Exception as e:
                        config.logger.debug(f"Pull stream parse skip: {e}")

        config.logger.info(f"Pull successfully completed for '{model_name}'")
        await sio.emit("model_pull_progress", {
            "model": model_name,
            "status": "success",
            "progress": 100
        })
        
    except Exception as e:
        config.logger.error(f"Critical error in pull_stream_worker: {e}")
        await sio.emit("model_pull_progress", {
            "model": model_name,
            "status": "error",
            "message": f"Orchestrator Internal Error: {str(e)}"
        })

@router.post("/ollama/pull")
async def pull_model(req: dict, background_tasks: BackgroundTasks):
    model_name = req.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="Model name required")

    # Pass current active config to the background worker
    background_tasks.add_task(
        pull_stream_worker, 
        model_name, 
        config.OLLAMA_URL, 
        config.LLM_PROVIDER, 
        config.LLM_API_KEY
    )
    
    return {"status": "started", "message": f"Pulling {model_name} in background..."}
