import os
import time
import requests
import threading
import sqlite3
import statistics
from datetime import datetime

ORCH_URL = "http://localhost:8000"
DB_PATH = "data/traceability.db"


class ProductionBenchmark:
    def __init__(self, job_count=1000, worker_count=5):
        self.job_count = job_count
        self.worker_count = worker_count
        self.contention_times = []
        self.stop_signal = threading.Event()
        self.start_time = None
        self.completion_count = 0
        self.lock = threading.Lock()

    def submit_bulk(self):
        print(f"[BENCHMARK] Submitting {self.job_count} jobs...")
        payloads = [
            {
                "agent_name": f"LoadAgent-{i}",
                "sprint_id": "load-test-01",
                "priority": (i % 4) + 1,
                "prompt": f"Load test task {i}",
            }
            for i in range(self.job_count)
        ]

        # Using a session for faster submission if possible
        s = requests.Session()
        for p in payloads:
            s.post(f"{ORCH_URL}/llm/submit", json=p)
        print("[BENCHMARK] Submission complete.")

    def run_worker(self, worker_id):
        wid = f"bench-worker-{worker_id}"
        s = requests.Session()
        while not self.stop_signal.is_set():
            try:
                # Measure contention (time to pull)
                t_start = time.time()
                res = s.post(
                    f"{ORCH_URL}/jobs/pull?worker_id={wid}&hostname=bench-host"
                )
                t_end = time.time()

                if res.status_code == 200 and res.json():
                    with self.lock:
                        self.contention_times.append(t_end - t_start)

                    job = res.json()
                    # Simulate work
                    time.sleep(0.01)  # 10ms work

                    s.post(
                        f"{ORCH_URL}/jobs/complete/{job['id']}?worker_id={wid}",
                        json={"result": "OK", "metrics": {"duration_ms": 10}},
                    )

                    with self.lock:
                        self.completion_count += 1
                        if self.completion_count >= self.job_count:
                            self.stop_signal.set()
                else:
                    if self.stop_signal.is_set():
                        break
                    time.sleep(0.1)
            except Exception:
                time.sleep(0.5)

    def run(self):
        self.start_time = time.time()

        # 1. Start Workers
        workers = []
        for i in range(self.worker_count):
            t = threading.Thread(target=self.run_worker, args=(i,))
            t.start()
            workers.append(t)

        # 2. Submit Jobs
        self.submit_bulk()

        # 3. Wait for completion
        while not self.stop_signal.is_set():
            elapsed = time.time() - self.start_time
            print(
                f"[PROGRESS] {self.completion_count}/{self.job_count} jobs done ({elapsed:.1f}s)",
                end="\r",
            )
            time.sleep(1)

        total_time = time.time() - self.start_time
        print(f"\n\n=== BENCHMARK RESULTS ===")
        print(f"Total Time: {total_time:.2f}s")
        print(f"Throughput: {self.job_count / total_time:.2f} jobs/sec")
        if self.contention_times:
            print(
                f"Avg Lock Contention (Pull Latency): {statistics.mean(self.contention_times)*1000:.2f}ms"
            )
            print(f"Max Lock Contention: {max(self.contention_times)*1000:.2f}ms")
        print("=========================\n")


if __name__ == "__main__":
    # Ensure freshly cleared data for clean test
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    # This assumes the master is already running on port 8000
    bench = ProductionBenchmark(1000, 5)
    bench.run()
