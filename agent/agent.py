import os
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import time

app = Flask(__name__)

AGENT_ROLE = os.getenv("AGENT_ROLE", "unknown")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
AGENT_MODEL = os.getenv("AGENT_MODEL", "llama3:latest")

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

def call_ollama(payload):
    retries = 5
    url = f"{OLLAMA_URL}/v1/completions" 
    for i in range(retries):
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Attempt {i+1} failed: {e}")
            time.sleep(5)
    raise RuntimeError("Ollama unreachable after multiple attempts")


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

    # Context özetleme
    context_summary = ""
    if context:
        context_summary = "\n".join(
            f"- {c['task']} → {c['result'][:200]}"
            for c in context[-5:]
        )

    try:
        prompt = build_prompt(task, context_summary)
        payload = {
            "model": AGENT_MODEL,
            "prompt": prompt,
            "max_tokens": 256
        }
        llm_result = call_ollama(payload)["choices"][0]["text"]
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

    if len(TASK_HISTORY) > MAX_MEMORY:
        TASK_HISTORY.pop(0)

    STATUS = "idle"

    return jsonify({"result": result})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
