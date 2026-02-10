import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

from db import init_db, save_task, get_tasks

app = Flask(__name__)
CORS(app)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DECOMPOSER_MODEL = "llama3"

# 🚀 Docker service isimleri
AGENTS = {
    "frontend_dev": "http://frontend_agent:5000",
    "backend_dev": "http://backend_agent:5000",
    "designer": "http://designer_agent:5000"
}


# --------------------------------------------------
# HEALTH
# --------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# --------------------------------------------------
# TASK DECOMPOSITION
# --------------------------------------------------
def decompose_task(user_task: str):
    prompt = f"""
You are a technical project manager.

Break the following task into smaller tasks.
Each task must have a role:
- frontend_dev
- backend_dev
- designer

Respond ONLY with valid JSON in this format:
{{
  "tasks": [
    {{ "role": "...", "task": "..." }}
  ]
}}

Task:
{user_task}
""".strip()

    res = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": DECOMPOSER_MODEL,
            "prompt": prompt,
            "stream": False
        },
        timeout=120
    )

    res.raise_for_status()
    return json.loads(res.json()["response"])


# --------------------------------------------------
# RUN FULL PROJECT (TEAM MODE)
# --------------------------------------------------
@app.route("/run-project", methods=["POST"])
def run_project():
    data = request.json or {}
    user_task = data.get("task")

    if not user_task:
        return jsonify({"error": "task is required"}), 400

    # 1️⃣ Task decomposition
    try:
        decomposition = decompose_task(user_task)
        tasks = decomposition.get("tasks", [])
    except Exception as e:
        return jsonify({"error": "Decomposition failed", "details": str(e)}), 500

    agent_results = []

    # 2️⃣ Agent’lara sırayla gönder ve çalıştır
    for t in tasks:
        role = t.get("role")
        task = t.get("task")
        agent_url = AGENTS.get(role)

        if not agent_url:
            agent_results.append({
                "role": role,
                "task": task,
                "result": "Unknown role"
            })
            continue

        try:
            res = requests.post(
                f"{agent_url}/execute-task",
                json={
                    "role": role,
                    "task": task,
                    "context": []  # opsiyonel: son 5 task buraya eklenebilir
                },
                timeout=120
            )
            result = res.json().get("result", "")
        except Exception as e:
            result = f"Agent call failed: {str(e)}"

        agent_results.append({
            "role": role,
            "task": task,
            "result": result
        })

        # DB’ye kaydet
        save_task(role, task, result)

    # 3️⃣ Team Lead summary
    try:
        final_summary = summarize_results(user_task, agent_results)
    except Exception as e:
        final_summary = f"Team Lead summary failed: {str(e)}"

    return jsonify({
        "status": "completed",
        "task": user_task,
        "agents": agent_results,
        "final_summary": final_summary
    })

# --------------------------------------------------
# SINGLE TASK (MANUAL MODE)
# --------------------------------------------------
@app.route("/assign-task", methods=["POST"])
def assign_task():
    data = request.json or {}

    role = data.get("role")
    task = data.get("task")

    if not role or not task:
        return jsonify({"error": "role and task are required"}), 400

    agent_url = AGENTS.get(role)
    if not agent_url:
        return jsonify({"error": f"No agent found for role: {role}"}), 404

    # 🧠 son 5 task → context
    recent_tasks = get_tasks()[:5]
    context = [
        {"task": row[1], "result": row[2]}
        for row in recent_tasks
    ]

    try:
        res = requests.post(
            f"{agent_url}/execute-task",
            json={
                "role": role,
                "task": task,
                "context": context
            },
            timeout=30
        )
        agent_response = res.json()
    except Exception as e:
        return jsonify({
            "error": "Agent unreachable",
            "details": str(e)
        }), 502

    save_task(
        role=role,
        task=task,
        result=agent_response.get("result", "")
    )

    return jsonify({
        "status": "completed",
        "agent_response": agent_response
    })


# --------------------------------------------------
# HISTORY & AGENTS
# --------------------------------------------------
@app.route("/tasks", methods=["GET"])
def tasks():
    rows = get_tasks()
    return jsonify([
        {
            "role": row[0],
            "task": row[1],
            "result": row[2],
            "created_at": row[3]
        }
        for row in rows
    ])


@app.route("/agents", methods=["GET"])
def agents():
    statuses = []

    for role, url in AGENTS.items():
        try:
            res = requests.get(f"{url}/health", timeout=2)
            data = res.json()
            data["role"] = role
            statuses.append(data)
        except:
            statuses.append({
                "role": role,
                "status": "offline"
            })

    return jsonify(statuses)

# --------------------------------------------------
# SUMMARY & CONTEXT BUILDING
# --------------------------------------------------
def summarize_results(user_task: str, agent_results: list):
    summary_prompt = f"""
You are the team lead of a software team.

Original user task:
{user_task}

Below are the results from your team members:
"""

    for r in agent_results:
        summary_prompt += f"""
Role: {r['role']}
Result:
{r['result']}
"""

    summary_prompt += """
Your job:
- Merge all results
- Resolve conflicts
- Produce a clean, professional final output
- Be concise but complete

Respond as plain text.
"""

    res = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": DECOMPOSER_MODEL,
            "prompt": summary_prompt,
            "stream": False
        },
        timeout=120
    )

    res.raise_for_status()
    return res.json()["response"]


# --------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
