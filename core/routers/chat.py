from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx
import json
from ..database import get_db
from ..models import ChatMessageRecord
from ..schemas import ChatRequest, ChatMessageSchema
from .. import config
from ..utils import safe_json_loads, map_role
from ..prompts import load_prompt
from ..app_instance import sio

router = APIRouter(tags=["Chat"])

@router.post("/chat/teamlead")
async def chat_teamlead(req: ChatRequest):
    prompt_tpl = load_prompt("teamlead", "TM_teamlead_chat", "You are a TeamLead...")
    
    # Simple history formatting
    history_str = ""
    for m in req.history:
        history_str += f"{m['role']}: {m['content']}\n"
    
    full_prompt = f"{prompt_tpl}\n\nCONTEXT:\n{history_str}\n\nAnswer the user directly."
    
    try:
        headers = {}
        endpoint = f"{config.OLLAMA_URL}/api/generate"
        if config.LLM_PROVIDER == "ollama-cloud" and config.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
            endpoint = f"{config.OLLAMA_URL}/api/generate"
            
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
            resp = await client.post(
                endpoint,
                headers=headers,
                json={"model": config.TEAMLEAD_MODEL, "prompt": full_prompt, "stream": False}
            )
            data = resp.json()
            raw_response = data.get("response", "")
            return {"response": raw_response}
    except Exception as e:
        config.logger.error(f"Chat teamlead error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/preview")
async def chat_preview(req: ChatRequest):
    prompt_tpl = load_prompt("teamlead", "TM_teamlead_preview", "You are a TeamLead...")
    
    # Simple history formatting
    history_str = ""
    for m in req.history:
        history_str += f"{m['role']}: {m['content']}\n"
    
    full_prompt = f"{prompt_tpl}\n\nCONTEXT:\n{history_str}\n\nOutput instructions provided by TeamLead prompt."
    
    try:
        headers = {}
        endpoint = f"{config.OLLAMA_URL}/api/generate"
        if config.LLM_PROVIDER == "ollama-cloud" and config.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
            endpoint = f"{config.OLLAMA_URL}/api/generate"
            
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
            resp = await client.post(
                endpoint,
                headers=headers,
                json={"model": config.TEAMLEAD_MODEL, "prompt": full_prompt, "stream": False}
            )
            data = resp.json()
            raw_response = data.get("response", "")
            config.logger.info(f"LLM Preview Response: {raw_response[:500]}...")
            
            # Injection logic (Security/Tester) if missing in JSON
            try:
                import re
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
    except Exception as e:
        config.logger.error(f"Chat preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
