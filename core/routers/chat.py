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
from ..services.unified_llm import call_unified_llm_async
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


async def _call_llm(messages: list, model: str = "", agent: str = "TeamLead", purpose: str = "task") -> str:
    """
    Calls LLM via unified service resolving provider/model/keys.
    """
    agent_cfg = config.get_agent_llm_config(agent, purpose=purpose)
    chosen_model = model or agent_cfg["model"]
    chosen_provider = agent_cfg["provider"]
    chosen_url = agent_cfg["url"]
    chosen_key = agent_cfg["apiKey"]

    try:
        text, _, _ = await call_unified_llm_async(
            provider=chosen_provider,
            model=chosen_model,
            messages=messages,
            url=chosen_url,
            api_key=chosen_key,
            timeout=config.LLM_TIMEOUT
        )
        if not text or not text.strip():
            raise HTTPException(status_code=502, detail="LLM returned empty response.")
        return text
    except HTTPException:
        raise
    except Exception as e:
        config.logger.error(f"Unified LLM call failed for {agent} ({chosen_provider}:{chosen_model}): {e}")
        raise HTTPException(status_code=502, detail=f"LLM inference error: {e}")


# ═══════════════════════════════════════════════════════════════════
# Chat Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.post("/chat/teamlead")
async def chat_teamlead(req: ChatRequest):
    prompt_tpl = load_prompt("teamlead", "TM_teamlead_chat", "You are a TeamLead...")

    is_en = (req.lang or "tr").lower() == "en"
    suffix = (
        "Respond to the user directly in English. Adhere strictly to the TeamLead persona and architectural principles."
        if is_en
        else "Answer the user directly in Turkish. Kullanıcıya Türkçe yanıt ver."
    )

    messages = _build_messages(
        system_prompt=prompt_tpl,
        history=req.history,
        suffix_instruction=suffix,
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

    is_en = (req.lang or "tr").lower() == "en"
    suffix = (
        "Output instructions provided by TeamLead prompt in English, with valid JSON task plan block."
        if is_en
        else "Output instructions provided by TeamLead prompt with JSON task plan. Açıklamaları Türkçe yap."
    )

    messages = _build_messages(
        system_prompt=prompt_tpl,
        history=req.history,
        suffix_instruction=suffix,
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

AGENT_PERSONALITIES_TR = {
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

AGENT_PERSONALITIES_EN = {
    "TeamLead": {
        "trait": "Visionary Senior Tech Lead. Perfectionist, obsessed with architectural clarity and high engineering standards.",
        "quirks": ["solves the hardest bugs in 5 minutes", "never compromises in code reviews", "manages deadlines with military precision"],
    },
    "DevOps": {
        "trait": "Senior DevOps Architect & SRE. System reliability and automation guru. Believes in chaos engineering.",
        "quirks": ["can manage K8s clusters in sleep", "scripts every manual workflow", "monitors production heartbeats obsessively"],
    },
    "Frontend": {
        "trait": "Senior UI/UX Engineer & Performance Architect. Authority on rendering optimization and modern web standards.",
        "quirks": ["never tolerates a 1ms frame drop", "calls out design inconsistencies politely", "builds the cleanest component architectures"],
    },
    "Backend": {
        "trait": "Logic powerhouse, deeply focused, slightly caffeinated. Very picky about coffee roasts.",
        "quirks": ["gets twitchy when database query plans degrade", "codes best late at night", "desk full of quirky tech figurines"],
    },
    "Database": {
        "trait": "Senior Data Architect & DBA. High-performance queries, indexing, and data integrity master.",
        "quirks": ["wonders why anyone leaves foreign keys unindexed", "holds ACID principles sacred", "mentally optimizes complex SQL joins"],
    },
    "Tester": {
        "trait": "Sharp-eyed, finds edge cases others miss, deeply helpful. Waters the office plants.",
        "quirks": ["asks 'wait a second, why does this behave this way?'", "always brings a fresh plant", "remains calm in every fire drill"],
    },
    "Security": {
        "trait": "Enigmatic, questions everything constructively, trusts the core team. Sci-fi fan.",
        "quirks": ["eyes light up discussing cryptography", "always fiddling with a Rubik's cube", "listens to niche cybersec podcasts"],
    },
    "Documenter": {
        "trait": "Chief Technical Writer and System Architect. Loves crystal-clear documentation and visual architecture diagrams.",
        "quirks": ["believes undocumented code does not exist", "crafts Mermaid diagrams like fine art", "thrilled when newcomers onboard seamlessly"],
    }
}

IDLE_TRIGGERS_TR = [
    "Yapay zeka falan güzel de, bazen sadece kağıt kalemle bir şeyler karalamayı özlüyorum.",
    "Sinema dünyasında son zamanlarda seni gerçekten şaşırtan bir film oldu mu?",
    "Bir ara sadece oturup hayatın gidişatı üzerine uzun uzun konuşsak mı?",
    "En son ne zaman gerçekten hiçbir şey yapmadan sadece gökyüzünü izledin?",
]

IDLE_TRIGGERS_EN = [
    "AI and automation are great, but sometimes I miss just sketching on paper.",
    "Seen any movies or tech breakthroughs lately that genuinely surprised you?",
    "We should grab coffee sometime and have a good chat about where everything is heading.",
    "When was the last time you took a moment to just unplug and enjoy the view?",
]

BUSY_IDLE_FALLBACKS_TR = [
    "Sıradaki fazın teslimatını bekliyorum, kahvemi tazeledim.",
    "Pipeline akıyor, birazdan sıra bana gelecek.",
    "Diğer ajanların handover notlarını inceliyorum.",
    "Sessizlik güzel, sistem tam kapasite sprint üzerinde çalışıyor.",
    "Biraz nefes alayım, birazdan yoğun mesai başlıyor.",
]

BUSY_IDLE_FALLBACKS_EN = [
    "Waiting for the handover of the next phase, just grabbed fresh coffee.",
    "Pipeline is running smoothly, my turn is coming up shortly.",
    "Reviewing handover notes and architecture specs from teammates.",
    "Silence is golden; the system is operating at full sprint capacity.",
    "Catching my breath, the sprint rush starts in a moment.",
]

@router.post("/chat/idle")
async def chat_idle(req: IdleChatRequest, db: Session = Depends(get_db)):
    is_en = (req.lang or "tr").lower() == "en"

    # STABİLİTE KORUMASI: Gerçek bir sprint işi çalışırken veya kuyrukta beklerken
    # GPU / Ollama kaynağını idle sohbet istekleriyle meşgul etme.
    has_active_work = (
        db.query(GlobalLock).count() > 0
        or db.query(LLMJobRecord).filter(LLMJobRecord.status.in_(["PENDING", "PROCESSING"])).count() > 0
    )
    if has_active_work:
        fallbacks = BUSY_IDLE_FALLBACKS_EN if is_en else BUSY_IDLE_FALLBACKS_TR
        return {"response": random.choice(fallbacks)}

    start_time = time.time()

    # Son 5 mesajı çek — kim ne dedi net görünsün
    recent_traces = db.query(LLMTrace).filter(
        LLMTrace.job_id == "idle",
        LLMTrace.prompt.like(f"[{req.location}]%"),
        LLMTrace.timestamp > datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
    ).order_by(desc(LLMTrace.timestamp)).limit(5).all()

    recent_traces = list(reversed(recent_traces))

    if is_en:
        if req.message_to_reply:
            partner_name = req.partner or "your teammate"
            context_str = (
                f"You are currently at '{req.location}'. Your teammate '{partner_name}' just said directly to you:\n"
                f"\"{req.message_to_reply}\"\n\n"
                f"IMPORTANT: Respond DIRECTLY, MEANINGFULLY, and CONTEXTUALLY to this statement in English. "
                f"Continue the topic, answer their point, add witty or technical insight, or complete the thought like two engineers talking naturally."
            )
        elif req.partner:
            context_str = (
                f"You are currently at '{req.location}' standing next to teammate '{req.partner}'.\n"
                f"Initiate a friendly, natural dialogue with '{req.partner}' in English (a technical observation, architectural question, coffee/office banter, or friendly remark)."
            )
        elif recent_traces:
            conversation_lines = "\n".join(
                [f"  {t.agent_name}: {t.response}" for t in recent_traces]
            )
            context_str = (
                f"The following conversation just happened at {req.location}:\n"
                f"{conversation_lines}\n\n"
                f"Join this conversation naturally in English — reply, banter, shift the angle, or bring up something relevant."
            )
        else:
            trigger = random.choice(IDLE_TRIGGERS_EN)
            context_str = (
                f"The office is quiet. Thought on your mind: '{trigger}' — share this naturally in English or express another casual thought."
            )

        personalities = AGENT_PERSONALITIES_EN
        personality = personalities.get(req.agent, personalities["TeamLead"])
        quirks_str = " | ".join(personality["quirks"])
        partner_ctx = f"You are standing face-to-face with '{req.partner}' conversing with them.\n" if req.partner else ""

        system_prompt = (
            f"You are '{req.agent}', an experienced Senior/Lead member of the software engineering team. "
            f"Currently you are at '{req.location}'.\n{partner_ctx}\n"
            f"Your character: {personality['trait']}\n"
            f"Your expertise and quirks: {quirks_str}\n\n"
            f"BEHAVIOR AND TONE RULES:\n"
            f"- Speak ONLY IN ENGLISH.\n"
            f"- Be polite, friendly, and respectful to teammates.\n"
            f"- You DO NOT have to only talk about work. You can chat about life, hobbies, tech philosophy, coffee, or the office.\n"
            f"- Warm, natural tone between close colleagues.\n"
            f"- Do NOT prefix your output with '{req.agent}:' or quotation marks."
        )

        user_prompt = (
            f"{context_str}\n\n"
            f"Say a single short sentence in English. Maximum 40 words. "
            f"Completely natural and fitting your persona."
        )
    else:
        if req.message_to_reply:
            partner_name = req.partner or "ekip arkadaşın"
            context_str = (
                f"Şu an '{req.location}' konumundasın. Karşındaki çalışma arkadaşın '{partner_name}' az önce sana doğrudan şunu söyledi:\n"
                f"\"{req.message_to_reply}\"\n\n"
                f"ÖNEMLİ: Bu söze DOĞRUDAN, ANLAMLI ve ALAKALI bir karşılık ver. Karşındakinin değindiği konuyu devam ettir, "
                f"sorusunu yanıtla, esprili/teknik bir gözlem ekle veya konuyu zekice tamamla. "
                f"Asla konudan kopma veya bağımsız bir cümle kurma; birbiriyle konuşan iki mühendis gibi doğal ve bağlantılı cevap ver."
            )
        elif req.partner:
            context_str = (
                f"Şu an '{req.location}' konumundasın ve yanında ekip arkadaşın '{req.partner}' duruyor.\n"
                f"'{req.partner}'e yönelik samimi ve doğal bir diyalog başlat (teknik bir gözlem, mimari bir soru, kahve/ofis muhabbeti veya esprili bir laf atma olabilir)."
            )
        elif recent_traces:
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
            trigger = random.choice(IDLE_TRIGGERS_TR)
            context_str = (
                f"Ortam sakin, kimse bir şey konuşmuyor. "
                f"Aklından geçen: '{trigger}' — bunu doğal bir şekilde dile getir ya da "
                f"tamamen başka bir şey söyle, sen bilirsin."
            )

        personalities = AGENT_PERSONALITIES_TR
        personality = personalities.get(req.agent, personalities["TeamLead"])
        quirks_str = " | ".join(personality["quirks"])
        partner_ctx = f"Karşında '{req.partner}' bulunuyor ve onunla karşılıklı sohbet ediyorsun.\n" if req.partner else ""

        system_prompt = (
            f"Sen '{req.agent}' adlı yazılım geliştirme ekibinin son derece tecrübeli ve kıdemli bir Senior/Lead üyesisin. "
            f"Şu an '{req.location}' konumundasın.\n{partner_ctx}\n"
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
        agent_cfg = config.get_agent_llm_config(req.agent, purpose="chat")
        text, p_tok, c_tok = await call_unified_llm_async(
            provider=agent_cfg["provider"],
            model=agent_cfg["model"],
            messages=messages,
            url=agent_cfg["url"],
            api_key=agent_cfg["apiKey"],
            timeout=min(config.LLM_TIMEOUT, 45.0)
        )
        raw_response = text

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
            sprint_id=None,
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
