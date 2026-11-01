from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
import copy
from .. import config as cfg_module
from ..config import save_config, logger
from ..app_instance import sio

router = APIRouter(tags=["Config"])

@router.get("/config")
def get_runtime_config():
    return cfg_module.runtime_config

@router.post("/config")
def update_config(new_cfg: dict = Body(...)):
    try:
        old_nodes = {
            n.get("id"): n
            for n in cfg_module.runtime_config.get("NODES", [])
            if isinstance(n, dict) and n.get("id")
        }

        updated = dict(cfg_module.runtime_config)
        for k, v in new_cfg.items():
            updated[k] = v

        # DÜZELTME 5: teamleadModel senkronizasyonu.
        # Kullanıcı UI üzerinden model değiştirdiğinde eski teamleadModel takılı kalmamalı.
        for node in updated.get("NODES", []):
            nid = node.get("id")
            old_node = old_nodes.get(nid, {})
            new_model = node.get("model", "")
            old_model = old_node.get("model", "")
            old_tl = old_node.get("teamleadModel", "")

            if not node.get("teamleadModel"):
                node["teamleadModel"] = new_model
                logger.info(f"Auto-filled teamleadModel for node '{node.get('name', nid)}'")
            elif new_model and new_model != old_model and node.get("teamleadModel") == old_tl:
                # Model UI'dan değiştirildi fakat teamleadModel eski değerde kaldıysa eşitle
                node["teamleadModel"] = new_model
                logger.info(f"Synced teamleadModel='{new_model}' for node '{node.get('name', nid)}'")

        # Persist to data/config.json and refresh globals
        save_config(updated)

        redacted_log = {
            **updated,
            "NODES": [
                {**n, "apiKey": "***" if n.get("apiKey") else ""}
                for n in updated.get("NODES", [])
            ],
        }
        logger.info(f"Configuration updated: {redacted_log}")
        return {"status": "ok", "config": cfg_module.runtime_config}
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        return {"status": "error", "message": str(e)}


class AgentLLMUpdateRequest(BaseModel):
    agent: str  # e.g. "Backend" or "ALL"
    chatProvider: str = "ollama"
    chatModel: str = "llama3.1:latest"
    taskProvider: str = "gemini"
    taskModel: str = "gemini-2.0-flash"
    apiKey: str | None = None
    url: str | None = None


@router.get("/config/llm-routing")
def get_llm_routing():
    routing = cfg_module.runtime_config.get("LLM_ROUTING") or copy.deepcopy(cfg_module.DEFAULT_LLM_ROUTING)
    presets = {
        "chat": [
            {"provider": "ollama", "model": "llama3.1:latest", "label": "Llama 3.1 8B (Yerel Ollama - Hızlı)"},
            {"provider": "ollama", "model": "qwen2.5-coder:7b", "label": "Qwen 2.5 Coder 7B (Yerel)"},
            {"provider": "ollama", "model": "mistral:latest", "label": "Mistral 7B (Yerel)"},
            {"provider": "gemini", "model": "gemini-2.0-flash", "label": "Gemini 2.0 Flash (Cloud)"},
            {"provider": "openai", "model": "gpt-4o-mini", "label": "OpenAI GPT-4o Mini (Cloud)"}
        ],
        "task": [
            {"provider": "gemini", "model": "gemini-2.0-flash", "label": "Google Gemini 2.0 Flash (Önerilen - Hızlı)"},
            {"provider": "gemini", "model": "gemini-1.5-pro", "label": "Google Gemini 1.5 Pro (Derin Mimari & Kod)"},
            {"provider": "openai", "model": "gpt-4o", "label": "OpenAI GPT-4o (State of the Art)"},
            {"provider": "openai", "model": "gpt-4o-mini", "label": "OpenAI GPT-4o Mini (Hafif & Hızlı)"},
            {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022", "label": "Anthropic Claude 3.5 Sonnet"},
            {"provider": "ollama", "model": "qwen2.5-coder:7b", "label": "Qwen 2.5 Coder 7B (Yerel Ollama)"},
            {"provider": "ollama", "model": "llama3.1:latest", "label": "Llama 3.1 8B (Yerel Ollama)"}
        ]
    }
    return {
        "routing": routing,
        "presets": presets
    }


@router.post("/config/llm-routing")
async def update_llm_routing(routing_data: dict = Body(...)):
    try:
        updated = dict(cfg_module.runtime_config)
        updated["LLM_ROUTING"] = routing_data
        save_config(updated)
        try:
            await sio.emit("llm_routing_updated", routing_data)
        except Exception:
            pass
        return {"status": "ok", "routing": routing_data}
    except Exception as e:
        logger.error(f"Failed to update LLM routing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/agent-llm")
async def update_agent_llm(req: AgentLLMUpdateRequest):
    try:
        updated = dict(cfg_module.runtime_config)
        routing = dict(updated.get("LLM_ROUTING") or copy.deepcopy(cfg_module.DEFAULT_LLM_ROUTING))

        if req.agent.upper() == "ALL":
            # Apply to global defaults and propagate
            routing["defaultChat"] = {
                "provider": req.chatProvider,
                "model": req.chatModel,
                "url": req.url or (cfg_module.OLLAMA_URL if req.chatProvider == "ollama" else ""),
                "apiKey": req.apiKey or ""
            }
            routing["defaultTask"] = {
                "provider": req.taskProvider,
                "model": req.taskModel,
                "url": req.url or "",
                "apiKey": req.apiKey or ""
            }
            # Clear per-agent overrides so all agents inherit this global setting
            routing["agents"] = {}
            logger.info(f"Applied LLM routing to ALL agents: Chat={req.chatProvider}:{req.chatModel}, Task={req.taskProvider}:{req.taskModel}")
        else:
            agents_dict = dict(routing.get("agents") or {})
            agents_dict[req.agent] = {
                "chatProvider": req.chatProvider,
                "chatModel": req.chatModel,
                "taskProvider": req.taskProvider,
                "taskModel": req.taskModel,
                "apiKey": req.apiKey or "",
                "url": req.url or ""
            }
            routing["agents"] = agents_dict
            logger.info(f"Updated LLM routing for agent '{req.agent}': Chat={req.chatProvider}:{req.chatModel}, Task={req.taskProvider}:{req.taskModel}")

        updated["LLM_ROUTING"] = routing
        save_config(updated)

        try:
            await sio.emit("llm_routing_updated", routing)
        except Exception:
            pass

        return {"status": "ok", "agent": req.agent, "routing": routing}
    except Exception as e:
        logger.error(f"Failed to update agent LLM settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
