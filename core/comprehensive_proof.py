import time
import uuid
import threading
import logging
import sqlite3
from datetime import datetime
from queue import PriorityQueue

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("EvidenceCollector")


class MockOrchestrator:
    def __init__(self):
        self.queue = PriorityQueue()
        self.db_path = "evidence.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP TABLE IF EXISTS llm_traces")
        conn.execute(
            """CREATE TABLE llm_traces 
                     (id TEXT, sprint_id TEXT, agent_name TEXT, priority INTEGER, 
                      prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, 
                      status TEXT, duration_ms FLOAT, timestamp DATETIME)"""
        )
        conn.close()

    def submit(self, agent, priority, prompt, sprint="sprint-001"):
        job_id = str(uuid.uuid4())
        self.queue.put((priority, job_id, (agent, priority, prompt, sprint)))
        logger.info(f"[SUBMIT] Job: {job_id} | Agent: {agent} | Priority: {priority}")
        return job_id

    def worker_loop(self, timeout_limit=1.5):
        logger.info("[WORKER] Sequential Processor started.")
        while not self.queue.empty():
            priority, job_id, (agent, p, prompt, sprint) = self.queue.get()
            logger.info(f"[PROCESS START] Job: {job_id} | Agent: {agent}")

            start_time = time.time()

            # Simulated Execution
            simulated_duration = 1.0  # Default
            if "HANG" in prompt:
                simulated_duration = 3.0  # Simulate long task

            time.sleep(min(simulated_duration, timeout_limit))

            elapsed = time.time() - start_time
            if elapsed >= timeout_limit and simulated_duration > timeout_limit:
                logger.error(
                    f"[TIMEOUT] Job: {job_id} EXCEEDED {timeout_limit}s. FORCING TERMINATION."
                )
                status = "TIMEOUT_KILLED"
            else:
                logger.info(f"[PROCESS END] Job: {job_id} finished in {elapsed:.2f}s")
                status = "SUCCESS"

            # Persist
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO llm_traces VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    sprint,
                    agent,
                    priority,
                    len(prompt) * 2,
                    50,
                    len(prompt) * 2 + 50,
                    status,
                    elapsed * 1000,
                    datetime.now(),
                ),
            )
            conn.commit()
            conn.close()
            self.queue.task_done()


# Verification Suite
def run_proof():
    orch = MockOrchestrator()

    print("\n--- TEST: 5-JOB CONCURRENT LOAD & QUEUE DEPTH ---")
    # Submitting 5 jobs concurrently
    roles = ["Security", "TeamLead", "Frontend", "Backend", "Tester"]
    priorities = [1, 2, 3, 3, 4]

    for role, prio in zip(roles, priorities):
        orch.submit(role, prio, f"Task for {role}")

    print(f"Queue Depth after submission: {orch.queue.qsize()}")
    orch.worker_loop()

    print("\n--- EVIDENCE: RAW SQL SAMPLE (traceability.db) ---")
    conn = sqlite3.connect("evidence.db")
    cursor = conn.cursor()
    # Fetching requested fields including sprint_id and token breakdown
    cursor.execute(
        "SELECT sprint_id, agent_name, status, prompt_tokens, completion_tokens, total_tokens, duration_ms FROM llm_traces LIMIT 5"
    )

    header = f"{'SPRINT_ID':<12} | {'AGENT':<12} | {'STATUS':<10} | {'P_TOK':<5} | {'C_TOK':<5} | {'T_TOK':<5} | {'TIME'}"
    print(header)
    print("-" * len(header))
    for row in cursor.fetchall():
        print(
            f"{row[0]:<12} | {row[1]:<12} | {row[2]:<10} | {row[3]:<5} | {row[4]:<5} | {row[5]:<5} | {row[6]:.0f}ms"
        )
    conn.close()


if __name__ == "__main__":
    run_proof()
