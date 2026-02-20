import os
import time
import logging
from .workers import FrontendAgent, BackendAgent, TesterAgent, SecurityAgent
from .teamlead import TeamLead

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WorkerEntry")

AGENT_TYPE = os.getenv("AGENT_TYPE", "Generic")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://api-orchestrator:8000")

def get_agent():
    if AGENT_TYPE == "TeamLead":
        return TeamLead(ORCHESTRATOR_URL)
    elif AGENT_TYPE == "Frontend":
        return FrontendAgent(ORCHESTRATOR_URL)
    elif AGENT_TYPE == "Backend":
        return BackendAgent(ORCHESTRATOR_URL)
    elif AGENT_TYPE == "Tester":
        return TesterAgent(ORCHESTRATOR_URL)
    elif AGENT_TYPE == "Security":
        return SecurityAgent(ORCHESTRATOR_URL)
    return None

def main():
    logger.info(f"Starting {AGENT_TYPE} worker...")
    agent = get_agent()
    
    if not agent:
        logger.error(f"Unknown AGENT_TYPE: {AGENT_TYPE}")
        return

    # In a real factory, this would be a long-running polling loop for tasks.
    # For now, we print a heart-beat.
    while True:
        logger.info(f"{AGENT_TYPE} worker heartbeat - Standing by for tasks...")
        time.sleep(30)

if __name__ == "__main__":
    main()
