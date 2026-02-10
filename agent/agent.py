import os
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

AGENT_ROLE = os.getenv("AGENT_ROLE", "unknown")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
AGENT_MODEL = os.getenv("AGENT_MODEL", "llama3")

STATUS = "idle"
TASK_HISTORY = []
MAX_MEMORY = 20  # 🔥 RAM koruması

SYSTEM_PROMPTS = {
    "frontend_dev": "You are a senior frontend developer. Focus on UI, UX and clean component structure.",
    "backend_dev": "You are a senior backend engineer. Focus on APIs, architecture, performance and correctness.",
    "designer": "You are a product designer. Focus on UX, UI, colors, spacing and usability."
}


def build_prompt(task: str, context_summary: str) -> str:
    return f"""
{SYSTEM_PROMPTS.get(AGENT_ROLE, "")}

Previous context (summary):
{context_summary if context_summary else "No prior context"}

Current task:
{task}

Respond clearly, professionally and with actionable output.
""".strip()


def call_llm(prompt: str) -> str:
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": AGENT_MODEL,
            "prompt": prompt,
            "stream": False
        },
        timeout=300
    )

    response.raise_for_status()
    return response.json().get("response", "").strip()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "alive",
        "agent_state": STATUS,
        "tasks_completed": len(TASK_HISTORY),
        "role": AGENT_ROLE,
        "model": AGENT_MODEL
    })


@app.route("/execute-task", methods=["POST"])
def execute_task():
    global STATUS

    data = request.json or {}
    role = data.get("role")
    task = data.get("task")
    context = data.get("context", [])

    if role != AGENT_ROLE:
        return jsonify({"error": "Role mismatch"}), 400

    STATUS = "thinking"

    # 🧠 Context özetleme
    context_summary = ""
    if context:
        context_summary = "\n".join(
            f"- {c['task']} → {c['result'][:200]}"
            for c in context[-5:]  # 🔥 sadece son 5
        )

    try:
        prompt = build_prompt(task, context_summary)
        llm_result = call_llm(prompt)
    except Exception as e:
        STATUS = "idle"
        return jsonify({
            "error": "LLM call failed",
            "details": str(e)
        }), 500

    result = f"[{AGENT_ROLE}]\n{llm_result}"

    TASK_HISTORY.append({
        "task": task,
        "result": result,
        "time": datetime.utcnow().isoformat()
    })

    # 🔥 Memory limit
    if len(TASK_HISTORY) > MAX_MEMORY:
        TASK_HISTORY.pop(0)

    STATUS = "idle"

    return jsonify({"result": result})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
