import time
import uuid
import threading
import logging
import sqlite3
import psutil
import os
from queue import PriorityQueue
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("StressTest")


class StressTestSimulator:
    def __init__(self):
        self.queue = PriorityQueue()
        self.db_path = "stress_test.db"
        self.results = []
        self._init_db()
        self.process = psutil.Process(os.getpid())
        self.start_mem = self.process.memory_info().rss / 1024 / 1024

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP TABLE IF EXISTS llm_traces")
        conn.execute(
            """CREATE TABLE llm_traces 
                     (id TEXT, agent_name TEXT, priority INTEGER, status TEXT, duration_ms FLOAT, memory_mb FLOAT)"""
        )
        conn.close()

    def submit(self, agent, priority, prompt):
        job_id = str(uuid.uuid4())
        self.queue.put((priority, time.time(), job_id, (agent, prompt)))
        return job_id

    def worker(self, timeout_limit=2.0):
        while not self.queue.empty():
            prio, timestamp, job_id, (agent, prompt) = self.queue.get()
            mem_before = self.process.memory_info().rss / 1024 / 1024
            logger.info(
                f"[EXEC] Start: {agent} (Prio:{prio}) | Mem: {mem_before:.1f}MB"
            )

            start_time = time.time()
            sim_duration = 3.0 if "HANG" in prompt else 0.5

            time.sleep(min(sim_duration, timeout_limit))

            elapsed = time.time() - start_time
            mem_after = self.process.memory_info().rss / 1024 / 1024

            status = "SUCCESS"
            if elapsed >= timeout_limit and sim_duration > timeout_limit:
                status = "TIMEOUT_KILLED"
                logger.warning(f"[KILL] {agent} terminated at {elapsed:.1f}s")

            self.results.append(
                {
                    "agent": agent,
                    "priority": prio,
                    "status": status,
                    "duration": elapsed,
                }
            )

            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO llm_traces VALUES (?,?,?,?,?,?)",
                (job_id, agent, prio, status, elapsed * 1000, mem_after),
            )
            conn.commit()
            conn.close()

            self.queue.task_done()

    def run_flood_test(self):
        logger.info("--- STARTING PHASE 1 FLOOD TEST ---")

        # 1. Fill queue with normal/low priority jobs
        for i in range(5):
            self.submit(f"Dev-{i}", 3, "Regular task")

        # 2. Inject HIGH priority
        high_id = self.submit("Security-High", 1, "Urgent scan")

        # 3. Inject HANG job
        self.submit("Backend-Hang", 3, "HANG_SIMULATION")

        logger.info(f"Queue filled. Depth: {self.queue.qsize()}")

        # Start worker
        self.worker(timeout_limit=1.5)

        self.validate_criteria()

    def validate_criteria(self):
        print("\n=== SUCCESS CRITERIA VALIDATION ===")

        # 1. Priority Integrity
        first_job = self.results[0]
        prio_integrity = first_job["agent"] == "Security-High"
        print(
            f"1. Priority Bypassing: {'[PASS]' if prio_integrity else '[FAIL]'} (First job was {first_job['agent']})"
        )

        # 2. Termination Precision
        kill_job = next(r for r in self.results if r["agent"] == "Backend-Hang")
        kill_pass = (
            kill_job["status"] == "TIMEOUT_KILLED" and kill_job["duration"] < 2.0
        )
        print(
            f"2. Termination Precision: {'[PASS]' if kill_pass else '[FAIL]'} ({kill_job['duration']:.1f}s)"
        )

        # 3. Memory Stability
        end_mem = self.process.memory_info().rss / 1024 / 1024
        mem_growth = end_mem - self.start_mem
        mem_pass = mem_growth < 50
        print(
            f"3. Memory Stability: {'[PASS]' if mem_pass else '[FAIL]'} (Growth: {mem_growth:.1f}MB)"
        )


if __name__ == "__main__":
    tester = StressTestSimulator()
    tester.run_flood_test()
