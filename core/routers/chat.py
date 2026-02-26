from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx
import json
from ..database import get_db
from ..models import ChatMessageRecord
from ..schemas import ChatRequest, ChatMessageSchema
from ..config import logger, TEAMLEAD_MODEL, OLLAMA_URL, LLM_TIMEOUT
from ..utils import safe_json_loads
from ..prompts import load_prompt
from ..app_instance import sio

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/preview")
async def chat_preview(req: ChatRequest):
    prompt_tpl = load_prompt("teamlead.json", "TM_teamlead_preview", "You are a TeamLead...")
    
    # Simple history formatting
    history_str = ""
    for m in req.history:
        history_str += f"{m['role']}: {m['content']}\n"
    
    full_prompt = f"{prompt_tpl}\n\nCONTEXT:\n{history_str}\n\nOutput instructions provided by TeamLead prompt."
    
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": TEAMLEAD_MODEL, "prompt": full_prompt, "stream": False}
            )
            data = resp.json()
            raw_response = data.get("response", "")
            logger.info(f"LLM Preview Response: {raw_response[:500]}...")
            
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
                logger.warning(f"Preview correction failed: {e}")
            
            return {"response": raw_response}
    except Exception as e:
        logger.error(f"Chat preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history/{sprint_id}")
async def get_chat_history(sprint_id: str, db: Session = Depends(get_db)):
    msgs = db.query(ChatMessageRecord).filter(ChatMessageRecord.sprint_id == sprint_id).order_by(ChatMessageRecord.timestamp).all()
    return [{"role": m.role, "content": m.content} for m in msgs]

@router.post("/save")
async def save_chat_message(msg: ChatMessageSchema, db: Session = Depends(get_db)):
    db.add(ChatMessageRecord(sprint_id=msg.sprint_id, role=msg.role, content=msg.content))
    db.commit()
    await sio.emit("new_chat_message", {"sprint_id": msg.sprint_id, "role": msg.role, "content": msg.content})
    return {"status": "ok"}
