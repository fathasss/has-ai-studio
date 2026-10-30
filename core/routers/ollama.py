"""
Ollama & OpenAI-compatible model management router.

Provides endpoints for listing available models and pulling new models
from an Ollama instance with real-time progress via WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from enum import Enum
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .. import config
from ..app_instance import sio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

router = APIRouter(tags=["Ollama"])

ALLOWED_URL_SCHEMES = {"http", "https"}
MODEL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9:._\-/]*$")
PROGRESS_EMIT_INTERVAL = 0.5  # seconds — minimum gap between WS emissions


class OllamaTimeouts:
    """Centralized timeout configuration for Ollama HTTP calls."""
    QUICK_CHECK: float = 5.0
    API_CALL: float = 15.0
    MODEL_PULL: float = 3600.0


class LLMProvider(str, Enum):
    """Supported LLM provider backends."""
    OLLAMA = "ollama"
    OLLAMA_CLOUD = "ollama-cloud"
    OPENAI = "openai"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PullModelRequest(BaseModel):
    """Request schema for the model pull endpoint."""
    model: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Ollama model name (e.g. 'llama3', 'mistral:7b')",
    )

    @field_validator("model")
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Model name cannot be empty")
        if not MODEL_NAME_PATTERN.match(v):
            raise ValueError(
                "Model name contains invalid characters. "
                "Allowed: letters, digits, ':', '.', '-', '_', '/'"
            )
        return v


class ModelListResponse(BaseModel):
    """Response schema for the model listing endpoint."""
    models: list[str]


class PullStartedResponse(BaseModel):
    """Response schema for the model pull initiation endpoint."""
    status: str
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_ollama_url(url: str) -> str:
    """
    Validate and sanitize a provider server URL.

    Prevents invalid schemes and preserves valid path prefixes
    (e.g. '/v1' or '/api/v1' for OpenAI-compatible gateways).
    """
    url = url.strip().rstrip("/")
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid URL scheme '{parsed.scheme}'. Allowed: {', '.join(ALLOWED_URL_SCHEMES)}",
        )

    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL: missing hostname")

    clean_path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{clean_path}"


def normalize_model_name(name: str) -> str:
    """Ensure a model name contains a tag. Defaults to ':latest'."""
    return name if ":" in name else f"{name}:latest"


def _build_auth_headers(provider: str | None, api_key: str | None) -> dict[str, str]:
    """Build authorization headers if the provider requires them."""
    headers: dict[str, str] = {}
    if provider in (LLMProvider.OLLAMA_CLOUD, LLMProvider.OPENAI, "ollama-cloud", "openai") and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


# ---------------------------------------------------------------------------
# Concurrent pull guard
# ---------------------------------------------------------------------------

_active_pulls: dict[str, bool] = {}
_pull_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def is_model_installed(
    model_name: str,
    ollama_url: str | None = None,
    headers: dict[str, str] | None = None,
) -> bool:
    """
    Check whether a model is currently installed in an Ollama instance.
    For cloud/OpenAI providers, returns True when a model name is configured.
    """
    if not model_name or not model_name.strip():
        return False

    if config.LLM_PROVIDER in ("openai", "ollama-cloud"):
        return True

    target_url = (ollama_url or config.OLLAMA_URL).rstrip("/")
    req_headers = headers if headers is not None else _build_auth_headers(config.LLM_PROVIDER, config.LLM_API_KEY)
    try:
        async with httpx.AsyncClient(timeout=OllamaTimeouts.QUICK_CHECK) as client:
            resp = await client.get(f"{target_url}/api/tags", headers=req_headers)
            if resp.status_code != 200:
                config.logger.debug(
                    f"Model install check: non-200 from {target_url} ({resp.status_code})"
                )
                return False

            data = resp.json()
            installed_names: set[str] = {
                normalize_model_name(m["name"])
                for m in data.get("models", [])
                if "name" in m
            }
            return normalize_model_name(model_name) in installed_names

    except (httpx.HTTPError, httpx.TimeoutException, KeyError, ValueError) as e:
        config.logger.debug(f"Model install check failed for '{model_name}': {e}")
        return False


async def pull_stream_worker(
    model_name: str,
    target_url: str,
    provider: str,
    api_key: str | None,
) -> None:
    """
    Background worker that streams a model pull from Ollama.

    Emits real-time progress events via Socket.IO. Throttles emissions
    to prevent WebSocket flooding on large downloads.
    """
    config.logger.info(f"Pull started: model='{model_name}', target='{target_url}'")
    headers = _build_auth_headers(provider, api_key)

    try:
        async with httpx.AsyncClient(timeout=OllamaTimeouts.MODEL_PULL) as client:
            async with client.stream(
                "POST",
                f"{target_url.rstrip('/')}/api/pull",
                headers=headers,
                json={"name": model_name, "stream": True},
            ) as response:

                if response.status_code != 200:
                    config.logger.error(
                        f"Pull stream initiation failed: HTTP {response.status_code}"
                    )
                    await sio.emit("model_pull_progress", {
                        "model": model_name,
                        "status": "error",
                        "message": f"Ollama returned HTTP {response.status_code}",
                    })
                    return

                last_emit_time: float = 0

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        body = json.loads(line)
                    except json.JSONDecodeError as e:
                        config.logger.debug(f"Pull stream: skipping malformed line: {e}")
                        continue

                    # --- Error in stream ---
                    if "error" in body:
                        config.logger.error(f"Ollama pull error: {body['error']}")
                        await sio.emit("model_pull_progress", {
                            "model": model_name,
                            "status": "error",
                            "message": body["error"],
                        })
                        return

                    # --- Progress ---
                    status = body.get("status", "")
                    completed = body.get("completed", 0)
                    total = body.get("total", 0)
                    progress = int((completed / total) * 100) if total > 0 else 0

                    now = time.monotonic()
                    is_milestone = status in ("success", "error") or progress >= 100

                    if is_milestone or (now - last_emit_time) >= PROGRESS_EMIT_INTERVAL:
                        await sio.emit("model_pull_progress", {
                            "model": model_name,
                            "status": status,
                            "completed": completed,
                            "total": total,
                            "progress": min(progress, 100),
                        })
                        last_emit_time = now

        # --- Completed successfully ---
        config.logger.info(f"Pull completed: model='{model_name}'")
        await sio.emit("model_pull_progress", {
            "model": model_name,
            "status": "success",
            "progress": 100,
        })

    except httpx.TimeoutException:
        config.logger.error(f"Pull timed out for '{model_name}'")
        await sio.emit("model_pull_progress", {
            "model": model_name,
            "status": "error",
            "message": "Download timed out",
        })

    except Exception as e:
        config.logger.error(f"Pull worker critical error: {e}", exc_info=True)
        await sio.emit("model_pull_progress", {
            "model": model_name,
            "status": "error",
            "message": "Internal server error during download",
        })


async def _guarded_pull_worker(
    model_name: str,
    target_url: str,
    provider: str,
    api_key: str | None,
) -> None:
    """Wrapper that ensures the active-pull lock is always released."""
    try:
        await pull_stream_worker(model_name, target_url, provider, api_key)
    finally:
        async with _pull_lock:
            _active_pulls.pop(model_name, None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/ollama/models", response_model=ModelListResponse)
async def list_models(
    url: str = Query(None, description="Custom LLM server URL"),
    provider: LLMProvider = Query(None, description="LLM provider type"),
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    """
    List available models from an Ollama or OpenAI-compatible instance.
    """
    try:
        target_url = validate_ollama_url(url) if url else config.OLLAMA_URL.rstrip("/")
        target_provider = provider.value if provider else config.LLM_PROVIDER
        target_api_key = x_api_key if x_api_key is not None else config.LLM_API_KEY

        config.logger.info(f"Model list request: url='{target_url}', provider='{target_provider}'")

        headers = _build_auth_headers(target_provider, target_api_key)

        async with httpx.AsyncClient(timeout=OllamaTimeouts.API_CALL) as client:
            if target_provider == LLMProvider.OPENAI.value:
                models_endpoint = config.build_openai_url(target_url, "/v1/models")
                resp = await client.get(models_endpoint, headers=headers)
                if resp.status_code != 200:
                    config.logger.warning(
                        f"OpenAI model list: non-200 from {models_endpoint} ({resp.status_code})"
                    )
                    return ModelListResponse(models=[])
                data = resp.json()
                model_names = sorted(
                    m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m
                )
                return ModelListResponse(models=model_names)

            resp = await client.get(f"{target_url}/api/tags", headers=headers)

            if resp.status_code != 200:
                config.logger.warning(
                    f"Model list: non-200 from {target_url} ({resp.status_code})"
                )
                return ModelListResponse(models=[])

            data = resp.json()
            model_names = [m["name"] for m in data.get("models", []) if "name" in m]
            config.logger.info(f"Fetched {len(model_names)} models from {target_url}")
            return ModelListResponse(models=model_names)

    except HTTPException:
        raise  # Re-raise validation errors from validate_ollama_url
    except Exception as e:
        config.logger.error(f"Model list failed: {e}")
        return ModelListResponse(models=[])


@router.post("/ollama/pull", response_model=PullStartedResponse)
async def pull_model(req: PullModelRequest, background_tasks: BackgroundTasks):
    """
    Initiate a background model pull from Ollama.

    Streams download progress to connected clients via Socket.IO events.
    Prevents duplicate concurrent pulls of the same model.
    """
    model_name = req.model

    async with _pull_lock:
        if model_name in _active_pulls:
            raise HTTPException(
                status_code=409,
                detail=f"Model '{model_name}' is already being pulled",
            )
        _active_pulls[model_name] = True

    background_tasks.add_task(
        _guarded_pull_worker,
        model_name,
        config.OLLAMA_URL,
        config.LLM_PROVIDER,
        config.LLM_API_KEY,
    )

    return PullStartedResponse(
        status="started",
        message=f"Pulling '{model_name}' in background",
    )
