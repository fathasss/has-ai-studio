import json
import logging
from .client import AgentClient

logger = logging.getLogger("TeamLead")

class TeamLead(AgentClient):
    def __init__(self, orchestrator_url: str = "http://api-orchestrator:8000"):
        super().__init__(agent_name="TeamLead", orchestrator_url=orchestrator_url)

    def analyze_project(self, user_goal: str):
        """Analyze the user's goal and generate a Sprint Plan."""
        prompt = f"""
        You are the TeamLead in the AI Software Factory.
        Your goal is to analyze the following user request and create a technical sprint plan.

        User Request: {user_goal}

        You must:
        1. Decide the tech stack.
        2. Design the folder structure within /app/apps/{{project_name}}.
        3. Break the work into a Sprint Plan with specific JSON tasks for:
           - Frontend Agent
           - Backend Agent
           - Tester Agent
           - Security Manager Agent

        Respond ONLY with a valid JSON in this format:
        {{
            "project_name": "...",
            "tech_stack": "...",
            "sprint_plan": "...",
            "tasks": [
                {{ "role": "Frontend", "task": "..." }},
                ...
            ]
        }}
        """
        
        # Priority 2 for TeamLead
        logger.info("Requesting Sprint Plan through sequential queue...")
        sprint_json = self.submit_llm_call(prompt, priority=2)
        
        try:
            plan = json.loads(sprint_json)
            # Store plan in workspace
            self.set_sprint(plan["project_name"])
            self.write_file(plan["project_name"], "sprint_plan.json", json.dumps(plan, indent=2))
            self.write_file(plan["project_name"], "Architecture.md", f"# Architecture Design: {plan['project_name']}\n\nStack: {plan['tech_stack']}\n\nPlan: {plan['sprint_plan']}")
            
            return plan
        except Exception as e:
            logger.error(f"Failed to parse sprint plan: {e}")
            return None

    def finalize_delivery(self, project_name: str):
        """Review all agent outputs and prepare final presentation."""
        # Logic to aggregate reports
        pass
