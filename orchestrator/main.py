from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from db import init_db, save_task, get_tasks

app = Flask(__name__)
CORS(app)

# 🚀 Docker service isimleri
AGENTS = {
    "frontend_dev": "http://frontend_agent:5000",
    "backend_dev": "http://backend_agent:5000",
    "designer": "http://designer_agent:5000"
}

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


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

    # 🧠 Son 5 task → context
    recent_tasks = get_tasks()[:5]
    context = [
        {
            "task": row[1],
            "result": row[2]
        }
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
            timeout=15
        )
        agent_response = res.json()
    except Exception as e:
        return jsonify({
            "error": "Agent unreachable",
            "details": str(e)
        }), 502

    # 💾 DB’ye kaydet
    save_task(
        role=role,
        task=task,
        result=agent_response.get("result", "")
    )

    return jsonify({
        "status": "completed",
        "agent_response": agent_response
    })


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


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
