from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx
import json
import re
import random
import time
import uuid
import datetime
from sqlalchemy import desc
from ..database import get_db
from ..models import ChatMessageRecord, LLMTrace, LLMJobRecord, GlobalLock
from ..schemas import ChatRequest, ChatMessageSchema, IdleChatRequest
from .. import config
from ..utils import safe_json_loads
from ..prompts import load_prompt
from ..app_instance import sio
from .sprint import _inject_missing_roles

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

    num_ctx = getattr(config, "LLM_NUM_CTX", 8192)

    # --- Build endpoint and payload based on provider ---
    if provider == "openai":
        # OpenAI-compatible API (OpenRouter, Azure, vLLM, etc.) — avoids /v1/v1 duplication
        endpoint = config.build_openai_url(config.OLLAMA_URL, "/v1/chat/completions")
        if config.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
        headers["Content-Type"] = "application/json"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
        }
    else:
        # Ollama native API (local or cloud)
        endpoint = f"{config.OLLAMA_URL.rstrip('/')}/api/chat"
        if provider == "ollama-cloud" and config.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "temperature": 0.2,
            },
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
            choices = data.get("choices", [])
            raw_response = (
                choices[0].get("message", {}).get("content", "")
                if choices
                else ""
            )
        else:
            raw_response = data.get("message", {}).get("content", "")

        # --- Empty response guard ---
        if not raw_response or not raw_response.strip():
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

        # Injection logic (DevOps/Security/Tester) using v2 structured tasks
        try:
            plan = safe_json_loads(raw_response)
            if plan and "tasks" in plan and isinstance(plan["tasks"], list):
                plan["tasks"] = _inject_missing_roles(list(plan["tasks"]))
                json_str = json.dumps(plan, indent=2, ensure_ascii=False)
                fence_pattern = r"```(?:json)?[\s\S]*?```"
                if re.search(fence_pattern, raw_response, flags=re.IGNORECASE):
                    raw_response = re.sub(
                        fence_pattern,
                        f"```json\n{json_str}\n```",
                        raw_response,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                else:
                    raw_response = f"{raw_response.strip()}\n\n```json\n{json_str}\n```"
        except Exception as e:
            config.logger.warning(f"Preview correction failed: {e}")

        return {"response": raw_response}
    except HTTPException:
        raise
    except Exception as e:
        config.logger.error(f"Chat preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════
# Idle Chat & Chat History Endpoints
# ═══════════════════════════════════════════════════════════════════

AGENT_PERSONALITIES = {
    "TeamLead": {
        "trait": "Vizyoner Senior Tech Lead. Mükemmeliyetçi, mimari bütünlüğe takıntılı ve ekibi teknik olarak domine eden bir lider. Coffee addict.",
        "quirks": ["en karmaşık bug'ları 5 dakikada çözer", "code review'da asla taviz vermez", "deadline'ları askeri disiplinle yönetir"],
    },
    "DevOps": {
        "trait": "Senior DevOps Architect & SRE. Sistem sürekliliği ve otomasyon gurusu. Kaos mühendisliğine inanır.",
        "quirks": ["K8s cluster'ını uykusunda yönetebilir", "her manuel işi script'e bağlamadan rahat etmez", "production'ın nefes alışını bile monitor eder"],
    },
    "Frontend": {
        "trait": "Senior UI/UX Engineer & Performance Architect. Rendering optimizasyonu ve modern web teknolojileri konusunda otorite.",
        "quirks": ["1 milisaniyelik gecikmeyi bile kabul etmez", "tasarımcıların hatalarını yüzüne vurur", "en temiz component mimarisini o kurar"],
    },
    "Backend": {
        "trait": "Mantık küpü, bazen aşırı detaycı, hafif uykusuz. Kahve markası konusunda çok seçici.",
        "quirks": ["database şişince gerilir", "geceleri daha iyi kod yazdığına inanır", "masasında bir sürü figür var"],
    },
    "Database": {
        "trait": "Senior Data Architect & DBA. Veri bütünlüğü, normalizasyon ve yüksek performanslı sorgu optimizasyonu uzmanı.",
        "quirks": ["indekssiz foreign key görünce gözü seğirir", "ACID prensiplerini kutsal kabul eder", "karmaşık SQL sorgularını akıldan çözer"],
    },
    "Tester": {
        "trait": "Şüpheci, detayları yakalamayı sever, aslında çok yardımsever. Ofisteki bitkileri o suluyor.",
        "quirks": ["'bi saniye, burası niye böyle?' diye yaklaşır", "sürekli yeni bir bitki getirir", "en sakin o kalır"],
    },
    "Security": {
        "trait": "Biraz gizemli, her şeye şüpheyle bakıyor ama ekibe çok güveniyor. Bilim kurgu hayranı.",
        "quirks": ["şifreleme konuşunca gözleri parlar", "masasında hep bir rubik küpü var", "kimsenin bilmediği bir podcast dinliyor"],
    },
    "Documenter": {
        "trait": "Baş Teknik Yazar ve Sistem Mimarı. Bilginin berraklığına, temiz OpenAPI kontratlarına ve görsel mimari diyagramlarına aşık.",
        "quirks": ["dokümansız kodu yazılmamış sayar", "Mermaid diyagramlarını bir sanat eseri gibi çizer", "yeni bir ekip üyesinin sıfırdan projeyi ayağa kaldırmasından mutluluk duyar"],
    }
}

IDLE_TRIGGERS = [
    "Yapay zeka falan güzel de, bazen sadece kağıt kalemle bir şeyler karalamayı özlüyorum.",
    "Sinema dünyasında son zamanlarda seni gerçekten şaşırtan bir film oldu mu?",
    "Bir ara sadece oturup hayatın gidişatı üzerine uzun uzun konuşsak mı?",
    "En son ne zaman gerçekten hiçbir şey yapmadan sadece gökyüzünü izledin?",
]

BUSY_IDLE_FALLBACKS = [
    "Sıradaki fazın teslimatını bekliyorum, kahvemi tazeledim.",
    "Pipeline akıyor, birazdan sıra bana gelecek.",
    "Diğer ajanların handover notlarını inceliyorum.",
    "Sessizlik güzel, sistem tam kapasite sprint üzerinde çalışıyor.",
    "Biraz nefes alayım, birazdan yoğun mesai başlıyor.",
]

@router.post("/chat/idle")
async def chat_idle(req: IdleChatRequest, db: Session = Depends(get_db)):
    # STABİLİTE KORUMASI: Gerçek bir sprint işi çalışırken veya kuyrukta beklerken
    # GPU / Ollama kaynağını idle sohbet istekleriyle meşgul etme.
    has_active_work = (
        db.query(GlobalLock).count() > 0
        or db.query(LLMJobRecord).filter(LLMJobRecord.status.in_(["PENDING", "PROCESSING"])).count() > 0
    )
    if has_active_work:
        return {"response": random.choice(BUSY_IDLE_FALLBACKS)}

    start_time = time.time()

    # Son 5 mesajı çek — kim ne dedi net görünsün
    recent_traces = db.query(LLMTrace).filter(
        LLMTrace.job_id == "idle",
        LLMTrace.prompt.like(f"[{req.location}]%"),
        LLMTrace.timestamp > datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
    ).order_by(desc(LLMTrace.timestamp)).limit(5).all()

    recent_traces = list(reversed(recent_traces))

    if recent_traces:
        conversation_lines = "\n".join(
            [f"  {t.agent_name}: {t.response}" for t in recent_traces]
        )
        context_str = (
            f"Az önce {req.location}'da şu konuşmalar geçti:\n"
            f"{conversation_lines}\n\n"
            f"Bu konuşmaya doğal olarak dahil ol — cevap verebilir, laf sokabilir, "
            f"konuyu değiştirebilir ya da tamamen başka bir şey başlatabilirsin."
        )
    else:
        trigger = random.choice(IDLE_TRIGGERS)
        context_str = (
            f"Ortam sakin, kimse bir şey konuşmuyor. "
            f"Aklından geçen: '{trigger}' — bunu doğal bir şekilde dile getir ya da "
            f"tamamen başka bir şey söyle, sen bilirsin."
        )

    personality = AGENT_PERSONALITIES.get(req.agent, AGENT_PERSONALITIES["TeamLead"])
    quirks_str = " | ".join(personality["quirks"])

    system_prompt = (
        f"Sen '{req.agent}' adlı yazılım geliştirme ekibinin son derece tecrübeli ve kıdemli bir Senior/Lead üyesisin. "
        f"Şu an '{req.location}' konumundasın.\n\n"
        f"Karakterin: {personality['trait']}\n"
        f"Senin uzmanlıkların ve takıntıların: {quirks_str}\n\n"
        f"DAVRANIŞ VE ÜSLUP KURALLARI:\n"
        f"- SADECE TÜRKÇE konuş.\n"
        f"- Ekip arkadaşlarına karşı SON DERECE KİBAR, NAZİK VE SAYGILI ol. Onlara değer verdiğini hissettir.\n"
        f"- SADECE İŞ KONUŞMAK ZORUNDA DEĞİLSİN. Hayatın içinden, hobilerden, sanattan, spordan, yemekten veya sadece o anki güzel bir manzaradan bahsedebilirsin.\n"
        f"- Samimi ve sıcak bir dostluk dili kullan (kanka/dost seviyesinde), ama nezaketi asla elden bırakma.\n"
        f"- Gerçek bir senior mühendis gibi, her şeyi işle bağlamak yerine insan ilişkilerine ve yaşam kalitesine de önem veren bir bilge gibi konuş.\n"
        f"- '{req.agent}:' veya tırnak işareti koyma başına"
    )

    user_prompt = (
        f"{context_str}\n\n"
        f"Tek bir kısa cümle söyle. Maksimum 40 kelime. "
        f"Karakterine ve ruh haline uygun, tamamen doğal."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try:
        raw_response = await _call_llm(messages, config.AGENT_MODEL)

        words = raw_response.split()
        if len(words) > 40:
            truncated = " ".join(words[:40])
            last_punct = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
            raw_response = truncated[:last_punct + 1] if last_punct > 20 else truncated + "..."

        raw_response = raw_response.strip('"\'').strip()
        if raw_response.lower().startswith(f"{req.agent.lower()}:"):
            raw_response = raw_response[len(req.agent) + 1:].strip()

        duration_ms = (time.time() - start_time) * 1000
        est_tokens = int((len(user_prompt) + len(raw_response)) / 4)
        trace = LLMTrace(
            id=str(uuid.uuid4()),
            job_id="idle",
            sprint_id="idle",
            agent_name=req.agent,
            worker_id="master",
            execution_node="local",
            priority=0,
            prompt=f"[{req.location}] {user_prompt}",
            response=raw_response,
            prompt_tokens=int(len(user_prompt) / 4),
            completion_tokens=int(len(raw_response) / 4),
            total_tokens=est_tokens,
            status="SUCCESS",
            duration_ms=duration_ms
        )
        db.add(trace)
        db.commit()
        
        return {"response": raw_response}
    except Exception as e:
        config.logger.error(f"Chat idle error: {e}")
        return {"response": "..."}

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
    if not old_id or not new_id:
        raise HTTPException(status_code=400, detail="old_id and new_id are required")
    if old_id != new_id:
        db.query(ChatMessageRecord).filter(ChatMessageRecord.sprint_id == old_id).update({"sprint_id": new_id})
        db.commit()
    return {"status": "ok"}

@router.get("/chat/sessions")
async def get_chat_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ChatMessageRecord.sprint_id).group_by(ChatMessageRecord.sprint_id).all()
    return {"sessions": [{"id": s[0], "name": s[0]} for s in sessions if s[0]]}
