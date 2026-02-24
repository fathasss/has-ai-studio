import os
import time
import uuid
import threading
import requests
import sqlite3
from datetime import datetime

ORCH_URL = "http://localhost:8000"
DB_PATH = "data/traceability.db"


class ChaosTester:
    def __init__(self, job_count=50):
        self.job_count = job_count
        self.worker_threads = []
        self.stop_signal = threading.Event()
        self.results = []

    def submit_flood(self):
        print(f"[CHAOS] Submitting {self.job_count} mixed-priority jobs...")
        for i in range(self.job_count):
            prio = (i % 4) + 1
            requests.post(
                f"{ORCH_URL}/llm/submit",
                json={
                    "agent_name": f"Agent-{i}",
                    "sprint_id": "chaos-test",
                    "priority": prio,
                    "prompt": f"Task {i}",
                },
            )
        print("[CHAOS] Flood complete.")

    def run_worker_node(self, node_id, crash_at=None):
        worker_id = f"chaos-worker-{node_id}"
        print(f"[NODE-{node_id}] Started.")

        # We manually implement worker loop to simulate crash
        processed = 0
        while not self.stop_signal.is_set():
            if crash_at and processed >= crash_at:
                print(f"[NODE-{node_id}] !!! SIMULATING SUDDEN CRASH !!!")
                return  # Thread dies

            try:
                # 1. Heartbeat
                requests.post(
                    f"{ORCH_URL}/jobs/heartbeat?worker_id={worker_id}&hostname=host-{node_id}"
                )
                # 2. Pull
                res = requests.post(
                    f"{ORCH_URL}/jobs/pull?worker_id={worker_id}&hostname=host-{node_id}"
                )
                if res.status_code == 200 and res.json():
                    job = res.json()
                    print(f"[NODE-{node_id}] Processing {job['id']}")
                    time.sleep(0.1)  # Fast simulation
                    # 3. Simulate success
                    requests.post(
                        f"{ORCH_URL}/jobs/complete/{job['id']}?worker_id={worker_id}",
                        json={"result": "Success", "metrics": {"duration_ms": 10}},
                    )
                    processed += 1
                else:
                    time.sleep(0.5)
            except Exception:
                time.sleep(0.5)

    def validate_integrity(self):
        print("\n=== CHAOS VALIDATION REPORT ===")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 1. Trace Integrity
        cursor.execute("SELECT COUNT(*) FROM llm_traces")
        trace_count = cursor.fetchone()[0]
        print(f"1. Trace Persistence: {trace_count}/{self.job_count} jobs captured.")

        # 2. Queue Consistency
        cursor.execute("SELECT status, COUNT(*) FROM llm_jobs GROUP BY status")
        stats = cursor.fetchall()
        print(f"2. Job Status Distribution: {dict(stats)}")

        # 3. Zombie Cleanup (Leases)
        cursor.execute("SELECT COUNT(*) FROM worker_heartbeats")
        hb_count = cursor.fetchone()[0]
        print(
            f"3. Active Heartbeats: {hb_count} (Should exclude crashed nodes after 60s)"
        )

        conn.close()


if __name__ == "__main__":
    # Setup Master in background
    print("[CHAOS] Booting Master...")
    os.environ["AGENT_ROLE"] = "master"
    # Note: In a real test environment, we'd run this as a separate process
    # For now, assume a running Orchestrator or run logic

    tester = ChaosTester(50)

    # 1. Start 3 Workers
    for i in range(3):
        crash_point = 5 if i == 0 else None  # Worker 0 will crash after 5 jobs
        t = threading.Thread(target=tester.run_worker_node, args=(i, crash_point))
        t.daemon = True
        t.start()

    # 2. Submit Flood
    tester.submit_flood()

    # 3. Wait for progress
    time.sleep(5)

    # 4. Final Validation
    tester.validate_integrity()
