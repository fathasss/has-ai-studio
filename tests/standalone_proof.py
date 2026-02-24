import time
import uuid
import threading
import logging
import sqlite3
from datetime import datetime
from queue import PriorityQueue

# Setup logging to capture sequential flow
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s'
)
logger = logging.getLogger("Validator")

# --- REPLICATING CORE LOGIC ---
class LLMJob:
    def __init__(self, agent_name, sprint_id, priority, prompt):
        self.agent_name = agent_name
        self.sprint_id = sprint_id
        self.priority = priority
        self.prompt = prompt

class MockOrchestrator:
    def __init__(self):
        self.queue = PriorityQueue()
        self.results = {}
        self.db_path = "validation_traces.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('''CREATE TABLE IF NOT EXISTS llm_traces 
                     (id TEXT, sprint_id TEXT, agent_name TEXT, priority INTEGER, 
                      prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, 
                      status TEXT, duration_ms FLOAT, timestamp DATETIME)''')
        conn.close()

    def submit(self, agent, priority, prompt):
        job_id = str(uuid.uuid4())
        job = LLMJob(agent, "sprint-001", priority, prompt)
        self.queue.put((priority, job_id, job))
        self.results[job_id] = {"status": "PENDING"}
        logger.info(f"JOB SUBMITTED: {job_id} | Agent: {agent} | Priority: {priority}")
        return job_id

    def worker_loop(self):
        logger.info("WORKER STARTED: Sequential processing active.")
        while not self.queue.empty():
            priority, job_id, job = self.queue.get()
            logger.info(f"PROCESSING START: {job_id} (Agent: {job.agent_name}, Priority: {priority})")
            
            # Simulate LLM Latency
            time.sleep(2) 
            
            duration = 2000.0
            p_tokens = len(job.prompt) * 2
            c_tokens = 50
            
            # Persist to DB
            conn = sqlite3.connect(self.db_path)
            conn.execute("INSERT INTO llm_traces (id, sprint_id, agent_name, priority, prompt_tokens, completion_tokens, total_tokens, status, duration_ms, timestamp) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (job_id, job.sprint_id, job.agent_name, priority, p_tokens, c_tokens, p_tokens + c_tokens, "SUCCESS", duration, datetime.now()))
            conn.commit()
            conn.close()
            
            logger.info(f"PROCESSING COMPLETED: {job_id} | Total Tokens: {p_tokens + c_tokens}")
            self.queue.task_done()

# --- RUNNING VALIDATION ---
def run_validation():
    factory = MockOrchestrator()
    
    # 1. Concurrent Submissions
    logger.info("STEP 1: Submitting concurrent jobs...")
    factory.submit("Frontend", 3, "Create React Component")
    factory.submit("Security", 1, "Scan for vulnerabilities") # HIGH PRIORITY
    factory.submit("Tester", 4, "Run unit tests")
    
    # 2. Sequential Processing
    logger.info("STEP 2: Processing jobs sequentially...")
    factory.worker_loop()
    
    # 3. Evidence Extraction
    logger.info("STEP 3: Extraction of Traceability Evidence")
    conn = sqlite3.connect("validation_traces.db")
    cursor = conn.cursor()
    cursor.execute("SELECT agent_name, priority, total_tokens FROM llm_traces")
    rows = cursor.fetchall()
    print("\n--- TRACEABILITY.DB EVIDENCE ---")
    for row in rows:
        print(f"Agent: {row[0]:<15} | Priority: {row[1]} | Total Tokens: {row[2]}")
    conn.close()

if __name__ == "__main__":
    run_validation()
