import os
import time
import uuid
import threading
import sqlite3
import requests
from datetime import datetime

# Orchestrator URL (Local for validation)
ORCH_URL = "http://localhost:8000"
DB_PATH = "data/traceability.db"

def submit_job(agent, text, priority, sprint="validation"):
    try:
        res = requests.post(f"{ORCH_URL}/llm/submit", json={
            "agent_name": agent,
            "sprint_id": sprint,
            "priority": priority,
            "prompt": text
        })
        return res.json()["job_id"]
    except Exception as e:
        print(f"Submission failed: {e}")
        return None

def poll_job(job_id):
    while True:
        res = requests.get(f"{ORCH_URL}/llm/status/{job_id}")
        data = res.json()
        if data["status"] in ["COMPLETED", "FAILED", "CANCELLED"]:
            return data
        time.sleep(1)

def run_sequential_test():
    print("\n--- TEST 1: Sequential Execution Proof ---")
    threads = []
    job_ids = []
    
    # Concurrent submission
    def worker(name, priority):
        jid = submit_job(name, f"Task from {name}", priority)
        job_ids.append((name, jid))
        print(f"[{name}] Submitted Job ID: {jid}")

    t1 = threading.Thread(target=worker, args=("Frontend", 3))
    t2 = threading.Thread(target=worker, args=("Security", 1)) # Higher priority
    t3 = threading.Thread(target=worker, args=("Tester", 4))
    
    for t in [t1, t2, t3]: t.start()
    for t in [t1, t2, t3]: t.join()

    print("Waiting for jobs to finish in sequence...")
    results = []
    for name, jid in job_ids:
        res = poll_job(jid)
        results.append((name, res))
        print(f"[{name}] Finished with status: {res['status']}")

    print("\n--- TEST 2: Traceability Metrics ---")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT agent_name, prompt_tokens, completion_tokens, total_tokens FROM llm_traces")
    rows = cursor.fetchall()
    print("Sample rows from traceability.db:")
    for row in rows:
        print(f"Agent: {row[0]} | Prompt: {row[1]} | Comp: {row[2]} | Total: {row[3]}")
    conn.close()

if __name__ == "__main__":
    run_sequential_test()
