import os
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import time

app = Flask(__name__)

AGENT_ROLE = os.getenv("AGENT_ROLE", "unknown")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
AGENT_MODEL = os.getenv("AGENT_MODEL", "llama3:latest")
WORKSPACE_DIR = "/app/workspace"

STATUS = "idle"
HISTORY_FILE = os.path.join(WORKSPACE_DIR, f"history_{AGENT_ROLE}.json")
TASK_HISTORY = []
MAX_MEMORY = 50  # 🚀 RAM koruması

def load_history():
    global TASK_HISTORY
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                TASK_HISTORY = json.load(f)
        except:
            TASK_HISTORY = []

def save_history():
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(TASK_HISTORY, f)
    except:
        pass

SYSTEM_PROMPTS = {
    "frontend_dev": "You are a senior frontend developer. Focus on UI, UX and clean component structure. You can write files by using: WRITE_FILE: filename\n[CODE]\nEND_FILE",
    "backend_dev": "You are a senior backend engineer. Focus on APIs, architecture, performance and correctness. You can write files by using: WRITE_FILE: filename\n[CODE]\nEND_FILE",
    "designer": "You are a product designer. Focus on UX, UI, colors, spacing and usability. You can write files by using: WRITE_FILE: filename\n[CONTENT]\nEND_FILE"
}

def process_file_actions(text: str):
    """Basit bir parser: WRITE_FILE: filename\nCONTENT\nEND_FILE"""
    import re
    pattern = r"WRITE_FILE:\s*(\S+)\n(.*?)\nEND_FILE"
    matches = re.findall(pattern, text, re.DOTALL)
    for filename, content in matches:
        filepath = os.path.join(WORKSPACE_DIR, filename)
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content.strip())
            print(f"File written: {filepath}")
        except Exception as e:
            print(f"Error writing file {filename}: {e}")

def build_prompt(task: str, context_summary: str) -> str:
    return f"""
            {SYSTEM_PROMPTS.get(AGENT_ROLE, "")}

            Previous context (summary):
            {context_summary if context_summary else "No prior context"}

            Current task:
            {task}

            If you need to create or update a file, use the WRITE_FILE format.
            Respond clearly, professionally and with actionable output.
            """.strip()

def call_ollama(payload):
    retries = 5
    url = f"{OLLAMA_URL}/api/generate" # v1/completions yerine api/generate kullanalım orchestrator ile aynı olsun
    for i in range(retries):
        try:
            # stream=False ekleyelim tam cevap almak için
            payload["stream"] = False
            response = requests.post(url, json=payload, timeout=300)
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
            "max_tokens": 2048 # Artırılmış token
        }
        res_data = call_ollama(payload)
        llm_result = res_data.get("response", "") # api/generate response döner
    except Exception as e:
        STATUS = "idle"
        return jsonify({
            "error": "LLM call failed",
            "details": str(e)
        }), 500

    # Dosya yazılarını işle
    process_file_actions(llm_result)

    result = f"[{AGENT_ROLE}]\n{llm_result}"

    TASK_HISTORY.append({
        "task": task,
        "result": result,
        "time": datetime.utcnow().isoformat()
    })

    if len(TASK_HISTORY) > MAX_MEMORY:
        TASK_HISTORY.pop(0)
    
    save_history()

    STATUS = "idle"

    return jsonify({"result": result})



if __name__ == "__main__":
    import json # imports at top are better but let's keep it clean
    load_history()
    app.run(host="0.0.0.0", port=5000)
