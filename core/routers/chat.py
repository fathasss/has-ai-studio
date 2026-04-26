from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx
import json
import re
from ..database import get_db
from ..models import ChatMessageRecord
from ..schemas import ChatRequest, ChatMessageSchema
from .. import config
from ..utils import safe_json_loads, map_role
from ..prompts import load_prompt
from ..app_instance import sio

router = APIRouter(tags=["Chat"])


# ═══════════════════════════════════════════════════════════════════
# DÜZELTME: Shared LLM helpers — /api/generate yerine /api/chat
# kullanarak proper role separation sağlar. Ayrıca OpenAI-uyumlu
# provider desteği ve boş yanıt koruması ekler.
# ═══════════════════════════════════════════════════════════════════

def _build_messages(system_prompt: str, history: list, suffix_instruction: str = "") -> list:
    """
    Converts chat history into a proper messages array with system/user/assistant roles.
    This enables the LLM to correctly distinguish turns and maintain conversational memory.
    """
    messages = []

    # System prompt always first
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Convert history with proper role mapping
    for m in history:
        raw_role = m.get("role", "user")
        if raw_role in ("TeamLead", "assistant"):
            role = "assistant"
        else:
            role = "user"
        content = m.get("content", "")
        if content.strip():
            messages.append({"role": role, "content": content})

    # Optional suffix instruction (e.g. "Answer the user directly.")
    if suffix_instruction:
        messages.append({"role": "user", "content": suffix_instruction})

    return messages


async def _call_llm(messages: list, model: str) -> str:
    """
    Calls the LLM using the correct endpoint and format based on provider type.
    Supports: ollama, ollama-cloud, openai.
    Raises HTTP 502 if the LLM returns an empty response or an error status.
    """
    headers = {}
    provider = config.LLM_PROVIDER

    # --- Build endpoint and payload based on provider ---
    if provider == "openai":
        # OpenAI-compatible API (OpenRouter, Azure, etc.)
        endpoint = f"{config.OLLAMA_URL}/v1/chat/completions"
        if config.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
        headers["Content-Type"] = "application/json"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
    else:
        # Ollama native API (local or cloud)
        endpoint = f"{config.OLLAMA_URL}/api/chat"
        if provider == "ollama-cloud" and config.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }

    config.logger.info(
        f"LLM call: provider={provider}, model={model}, "
        f"endpoint={endpoint}, messages={len(messages)}"
    )

    async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
        resp = await client.post(endpoint, headers=headers, json=payload)

        # --- HTTP error guard ---
        if resp.status_code != 200:
            error_detail = resp.text[:500] if resp.text else "No response body"
            config.logger.error(
                f"LLM endpoint returned HTTP {resp.status_code}: {error_detail}"
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    f"LLM endpoint returned HTTP {resp.status_code}. "
                    f"Check your provider URL and API key in Settings."
                ),
            )

        data = resp.json()

        # --- Extract response based on provider format ---
        if provider == "openai":
            # OpenAI format: {"choices": [{"message": {"content": "..."}}]}
            choices = data.get("choices", [])
            raw_response = (
                choices[0].get("message", {}).get("content", "")
                if choices
                else ""
            )
        else:
            # Ollama /api/chat format: {"message": {"content": "..."}}
            raw_response = data.get("message", {}).get("content", "")

        # --- Empty response guard ---
        if not raw_response.strip():
            config.logger.error(
                f"LLM returned empty response. Provider={provider}, "
                f"Model={model}, Raw data keys={list(data.keys())}"
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "LLM returned an empty response. Possible causes: "
                    "wrong provider URL, model not installed, or API key invalid. "
                    "Check Settings → Active Node configuration."
                ),
            )

        return raw_response


# ═══════════════════════════════════════════════════════════════════
# Chat Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.post("/chat/teamlead")
async def chat_teamlead(req: ChatRequest):
    prompt_tpl = load_prompt("teamlead", "TM_teamlead_chat", "You are a TeamLead...")

    messages = _build_messages(
        system_prompt=prompt_tpl,
        history=req.history,
        suffix_instruction="Answer the user directly.",
    )

    try:
        raw_response = await _call_llm(messages, config.TEAMLEAD_MODEL)
        return {"response": raw_response}
    except HTTPException:
        raise
    except Exception as e:
        config.logger.error(f"Chat teamlead error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/preview")
async def chat_preview(req: ChatRequest):
    prompt_tpl = load_prompt("teamlead", "TM_teamlead_preview", "You are a TeamLead...")

    messages = _build_messages(
        system_prompt=prompt_tpl,
        history=req.history,
        suffix_instruction="Output instructions provided by TeamLead prompt.",
    )

    try:
        raw_response = await _call_llm(messages, config.TEAMLEAD_MODEL)
        config.logger.info(f"LLM Preview Response: {raw_response[:500]}...")

        # Injection logic (Security/Tester) if missing in JSON
        try:
            plan = safe_json_loads(raw_response)
            if plan and "tasks" in plan:
                tasks = plan["tasks"]
                roles = [map_role(t.get("role", "")) for t in tasks]

                if "DevOps" not in roles:
                    tasks.insert(0, {"role": "DevOps", "phase": "Setup", "task": "Initialise project skeleton in current directory."})
                if "Security" not in roles:
                    tasks.append({"role": "Security", "phase": "Audit", "task": "Security audit and hardening."})
                if "Tester" not in roles:
                    tasks.append({"role": "Tester", "phase": "Validation", "task": "Functional verification and bug fixing."})

                plan.pop("implementation_plan_md", None)
                json_str = json.dumps(plan, indent=2, ensure_ascii=False)
                raw_response = re.sub(r"```json[\s\S]*?```", f"```json\n{json_str}\n```", raw_response, count=1, flags=re.IGNORECASE)
        except Exception as e:
            config.logger.warning(f"Preview correction failed: {e}")

        return {"response": raw_response}
    except HTTPException:
        raise
    except Exception as e:
        config.logger.error(f"Chat preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════
# Chat History Endpoints (unchanged)
# ═══════════════════════════════════════════════════════════════════

@router.get("/chat/history/{sprint_id}")
async def get_chat_history(sprint_id: str, db: Session = Depends(get_db)):
    msgs = db.query(ChatMessageRecord).filter(ChatMessageRecord.sprint_id == sprint_id).order_by(ChatMessageRecord.timestamp).all()
    return [{"role": m.role, "content": m.content} for m in msgs]

@router.post("/chat/history")
async def save_chat_message(msg: ChatMessageSchema, db: Session = Depends(get_db)):
    db.add(ChatMessageRecord(sprint_id=msg.sprint_id, role=msg.role, content=msg.content))
    db.commit()
    await sio.emit("new_chat_message", {"sprint_id": msg.sprint_id, "role": msg.role, "content": msg.content})
    return {"status": "ok"}

@router.post("/chat/history/migrate")
async def migrate_chat(req: dict, db: Session = Depends(get_db)):
    old_id = req.get("old_id")
    new_id = req.get("new_id")
    if not old_id or not new_id: raise HTTPException(status_code=400)
    db.query(ChatMessageRecord).filter(ChatMessageRecord.sprint_id == old_id).update({"sprint_id": new_id})
    db.commit()
    return {"status": "ok"}

@router.get("/chat/sessions")
async def get_chat_sessions(db: Session = Depends(get_db)):
    from sqlalchemy import func
    sessions = db.query(ChatMessageRecord.sprint_id).group_by(ChatMessageRecord.sprint_id).all()
    return {"sessions": [{"id": s[0], "name": s[0]} for s in sessions]}
