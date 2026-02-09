import os
import time
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

AGENT_ROLE = os.getenv("AGENT_ROLE", "unknown")

STATUS = "idle"
TASK_HISTORY = []

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "alive",
        "agent_state": STATUS,
        "tasks_completed": len(TASK_HISTORY)
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

    STATUS = "working"

    # 🧠 Context özetleme
    context_summary = ""
    if context:
        context_summary = "\n".join(
            f"- {c['task']} → {c['result']}" for c in context
        )

    # ⏳ Simülasyon
    time.sleep(2)

    result = f"""
[{AGENT_ROLE}] TASK COMPLETED

Current Task:
- {task}

Previous Context:
{context_summary if context_summary else "No prior context"}
""".strip()

    TASK_HISTORY.append({
        "task": task,
        "result": result,
        "time": datetime.utcnow().isoformat()
    })

    STATUS = "idle"

    return jsonify({
        "result": result
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
