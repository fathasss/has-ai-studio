import os
import time
import uuid
import threading
import requests
import json
import sqlite3
from datetime import datetime

# Orchestrator URL
ORCH_URL = "http://localhost:8000"
DB_PATH = "data/traceability.db"


def submit_jobs():
    print("[TEST] Submitting 5 jobs with different priorities...")
    jobs = [
        {"agent": "Dev-1", "prio": 3, "prompt": "Task 1"},
        {"agent": "Security-High", "prio": 1, "prompt": "Urgent Scan"},
        {"agent": "Dev-2", "prio": 3, "prompt": "Task 2"},
        {"agent": "Tester-1", "prio": 4, "prompt": "Verify 1"},
        {"agent": "Dev-3", "prio": 3, "prompt": "[REPLAY] Task 1 Redo"},
    ]

    for j in jobs:
        res = requests.post(
            f"{ORCH_URL}/llm/submit",
            json={
                "agent_name": j["agent"],
                "sprint_id": "verify-sprint",
                "priority": j["prio"],
                "prompt": j["prompt"],
            },
        )
        print(
            f"  - Submitted {j['agent']} (Prio {j['prio']}) | JobID: {res.json()['job_id']}"
        )


def run_orchestrator():
    print("[TEST] Starting Orchestrator Master...")
    os.environ["AGENT_ROLE"] = "master"
    try:
        from core.main import app
        import uvicorn

        uvicorn.run(app, host="localhost", port=8000, log_level="warning")
    except Exception as e:
        import traceback

        print(f"[ERROR] Orchestrator crashed:\n{traceback.format_exc()}")


def run_worker(worker_idx):
    worker_id = f"worker-{worker_idx}"
    print(f"[TEST] Starting Worker {worker_id}...")
    os.environ["AGENT_ROLE"] = "worker"
    os.environ["ORCHESTRATOR_URL"] = ORCH_URL

    # Mock Ollama call to prevent hanging/network issues
    import unittest.mock as mock

    with mock.patch("requests.post") as mock_post:

        def side_effect(url, **kwargs):
            if "/api/generate" in url:
                m = mock.Mock()
                m.status_code = 200
                m.json.return_value = {
                    "response": f"Simulated response for worker {worker_id}",
                    "prompt_eval_count": 10,
                    "eval_count": 20,
                }
                return m
            # Real call for internal API
            return requests.Session().post(url, **kwargs)

        mock_post.side_effect = side_effect

        from core.main import llm_worker

        try:
            llm_worker()
        except Exception:
            pass  # Expect thread kill


def verify_results():
    print("\n[TEST] Verifying traceability database...")
    time.sleep(5)  # Wait for some processing

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, agent_name, worker_id, status FROM llm_traces")
    rows = cursor.fetchall()

    print(f"\nFound {len(rows)} execution traces:")
    for r in rows:
        print(f"  ID: {r[0]} | Agent: {r[1]} | Worker: {r[2]} | Status: {r[3]}")

    cursor.execute("SELECT worker_id, hostname, last_seen FROM worker_heartbeats")
    hbs = cursor.fetchall()
    print(f"\nActive Heartbeats: {len(hbs)}")
    for hb in hbs:
        print(f"  Worker: {hb[0]} | Host: {hb[1]} | LastSeen: {hb[2]}")

    conn.close()


if __name__ == "__main__":
    # Ensure fresh DB
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    # Start Master
    master_thread = threading.Thread(target=run_orchestrator, daemon=True)
    master_thread.start()

    time.sleep(2)  # Wait for API

    # Start 2 Workers
    w1 = threading.Thread(target=run_worker, args=(1,), daemon=True)
    w2 = threading.Thread(target=run_worker, args=(2,), daemon=True)
    w1.start()
    w2.start()

    time.sleep(1)

    # Submit Jobs
    submit_jobs()

    # Let them work
    time.sleep(10)

    # Verify
    verify_results()
