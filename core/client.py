import os
import time
import requests
import logging

logger = logging.getLogger("AgentClient")

class AgentClient:
    def __init__(self, agent_name: str, orchestrator_url: str = "http://api-orchestrator:8000"):
        self.agent_name = agent_name
        self.orchestrator_url = orchestrator_url
        self.sprint_id = "default" # Should be set by TeamLead

    def set_sprint(self, sprint_id: str):
        self.sprint_id = sprint_id

    def submit_llm_call(self, prompt: str, priority: int, params: dict = {}):
        """Submit a job to the centralized sequential queue."""
        logger.info(f"Submitting LLM job for {self.agent_name} (Priority {priority})")
        
        try:
            res = requests.post(
                f"{self.orchestrator_url}/llm/submit",
                json={
                    "agent_name": self.agent_name,
                    "sprint_id": self.sprint_id,
                    "priority": priority,
                    "prompt": prompt,
                    "params": params
                }
            )
            res.raise_for_status()
            job_id = res.json()["job_id"]
            
            return self._poll_result(job_id)
        except Exception as e:
            logger.error(f"Failed to submit LLM job: {e}")
            return None

    def _poll_result(self, job_id: str):
        """Poll for LLM job completion."""
        while True:
            try:
                res = requests.get(f"{self.orchestrator_url}/llm/status/{job_id}")
                res.raise_for_status()
                status_data = res.json()
                
                status = status_data["status"]
                if status == "COMPLETED":
                    return status_data["result"]
                if status in ["FAILED", "CANCELLED"]:
                    logger.error(f"Job {job_id} {status}")
                    return None
                
                time.sleep(2) # Wait and poll
            except Exception as e:
                logger.error(f"Polling error for job {job_id}: {e}")
                time.sleep(5)

    def write_file(self, project_name: str, filename: str, content: str):
        """Safely write files into the shared /apps volume."""
        path = f"/app/apps/{project_name}/{filename}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"File written: {path}")
        return path
