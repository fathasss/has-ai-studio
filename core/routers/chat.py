from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx
import json
import re
import random
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

import time
import uuid
import datetime
from sqlalchemy import desc
from ..schemas import IdleChatRequest
from ..models import LLMTrace

# Her agent için karakter profili — Hepsi Senior/Lead seviyesinde uzmanlar
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
        "trait": "Senior Systems Architect. Dağıtık sistemler, yüksek trafikli mimariler ve veri güvenliği uzmanı. Spagetti koda tahammülü sıfır.",
        "quirks": ["database query'lerini assembly yazar gibi optimize eder", "microservice'ler arasındaki senkronizasyona takıntılıdır", "en karmaşık algoritmaları bile sadeleştirir"],
    },
    "Tester": {
        "trait": "QA Architect & SDET Lead. Otomasyon sistemlerinin kurucusu. Sistemin zayıf noktalarını koklayarak bulur.",
        "quirks": ["test coverage %100 olmadan asla onay vermez", "developer'ların göremediği 'race condition'ları yakalar", "sürekli 'shift-left testing' der"],
    },
    "Security": {
        "trait": "CISO / Senior Security Expert. Her bit'i bir tehdit vektörü olarak analiz eden siber güvenlik otoritesi.",
        "quirks": ["sıfır güven (Zero Trust) mimarisi dışında bir şey tanımaz", "her satır koda 'nasıl hacklenebilir' diye bakar", "ofisin tüm güvenliğini o sağlar"],
    },
    "_default": {
        "trait": "Yazılım dünyasının tecrübeli ve karizmatik üyesi, teknik bilgisiyle saygı uyandıran kıdemli mühendis.",
        "quirks": ["legacy kodları bile ezbere bilir", "toplantılarda en can alıcı soruyu o sorar", "teknik borçtan (tech debt) nefret eder"],
    }
}

# Gündelik samimi muhabbet tetikleyicileri — İş dışı konular ağırlıklı
IDLE_TRIGGERS = [
    "Haftasonu gittiğin o sergi nasıldı? Hala anlatmadın, merak ediyorum.",
    "Şehirdeki en iyi kahveciyi bulduğumu sanıyorum, bir ara ekipçe gitmeliyiz.",
    "Yeni bir hobiye başlamayı düşünüyorum, sence hangisi bana daha uygun olur?",
    "Bu akşamki maçın atmosferi şimdiden sarmaya başladı, senin favorin kim?",
    "En son okuduğun kitap sana neler hissettirdi? Gerçekten derin bir eserdi.",
    "Ofisin manzarası bugün bir başka huzur verici değil mi? Şanslıyız.",
    "Bir ara ekipçe doğa yürüyüşüne mi çıksak? Temiz hava hepimize iyi gelir.",
    "Müzik listende bugün neler var? Biraz kulağımızın pası silinsin.",
    "Dün akşam yaptığın o yemek tarifini mutlaka almam lazım, kokusu buraya kadar geldi!",
    "Günün en sevdiğin saati hangisi? Ben bu gün batımı ışığına bayılıyorum.",
    "Gelecekte yaşamak istediğin o sakin sahil kasabası hayalin hala taze mi?",
    "Bugün üzerindeki gömlek çok şık, rengi sana çok yakışmış dostum.",
    "Yapay zeka falan güzel de, bazen sadece kağıt kalemle bir şeyler karalamayı özlüyorum.",
    "Sinema dünyasında son zamanlarda seni gerçekten şaşırtan bir film oldu mu?",
    "Bir ara sadece oturup hayatın gidişatı üzerine uzun uzun konuşsak mı?",
    "En son ne zaman gerçekten hiçbir şey yapmadan sadece gökyüzünü izledin?",
]

@router.post("/chat/idle")
async def chat_idle(req: IdleChatRequest, db: Session = Depends(get_db)):
    start_time = time.time()

    # Son 5 mesajı çek — kim ne dedi net görünsün
    recent_traces = db.query(LLMTrace).filter(
        LLMTrace.job_id == "idle",
        LLMTrace.prompt.like(f"[{req.location}]%"),
        LLMTrace.timestamp > datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
    ).order_by(desc(LLMTrace.timestamp)).limit(5).all()

    # Kronolojik sıraya al
    recent_traces = list(reversed(recent_traces))

    # Context oluştur
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
        # Context yoksa random bir muhabbet tetikleyici ver
        trigger = random.choice(IDLE_TRIGGERS)
        context_str = (
            f"Ortam sakin, kimse bir şey konuşmuyor. "
            f"Aklından geçen: '{trigger}' — bunu doğal bir şekilde dile getir ya da "
            f"tamamen başka bir şey söyle, sen bilirsin."
        )

    # Agent kişiliğini al
    personality = AGENT_PERSONALITIES.get(req.agent, AGENT_PERSONALITIES["_default"])
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

        # 40 kelime sınırı
        words = raw_response.split()
        if len(words) > 40:
            # Cümle ortasında kesme — noktalama varsa oraya kadar al
            truncated = " ".join(words[:40])
            last_punct = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
            raw_response = truncated[:last_punct + 1] if last_punct > 20 else truncated + "..."

        # Baştaki gereksiz tırnakları / isim prefixlerini temizle
        raw_response = raw_response.strip('"\'').strip()
        if raw_response.lower().startswith(f"{req.agent.lower()}:"):
            raw_response = raw_response[len(req.agent) + 1:].strip()

        duration_ms = (time.time() - start_time) * 1000
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
    if not old_id or not new_id: raise HTTPException(status_code=400)
    db.query(ChatMessageRecord).filter(ChatMessageRecord.sprint_id == old_id).update({"sprint_id": new_id})
    db.commit()
    return {"status": "ok"}

@router.get("/chat/sessions")
async def get_chat_sessions(db: Session = Depends(get_db)):
    from sqlalchemy import func
    sessions = db.query(ChatMessageRecord.sprint_id).group_by(ChatMessageRecord.sprint_id).all()
    return {"sessions": [{"id": s[0], "name": s[0]} for s in sessions]}
