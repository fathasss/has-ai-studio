import logging
from .client import AgentClient

logger = logging.getLogger("Workers")

class WorkerAgent(AgentClient):
    def __init__(self, role: str, priority: int, orchestrator_url: str):
        super().__init__(agent_name=role, orchestrator_url=orchestrator_url)
        self.priority = priority

    def execute(self, task: str, project_name: str):
        self.set_sprint(project_name)
        prompt = self.get_system_prompt() + f"\n\nCurrent Task: {task}"
        
        logger.info(f"{self.agent_name} executing task for {project_name}")
        result = self.submit_llm_call(prompt, priority=self.priority)
        
        if result:
            self.handle_output(result, project_name)
        return result

    def get_system_prompt(self):
        return "You are an agent in a software factory."

    def handle_output(self, result: str, project_name: str):
        # Default behavior: log or save to a report
        filename = f"{self.agent_name}_output.md"
        self.write_file(project_name, filename, result)

class FrontendAgent(WorkerAgent):
    def __init__(self, orchestrator_url: str):
        super().__init__("Frontend", 3, orchestrator_url)
    
    def get_system_prompt(self):
        return "You are a Senior Frontend Engineer. Implement UI, styling, and client-side logic."

class BackendAgent(WorkerAgent):
    def __init__(self, orchestrator_url: str):
        super().__init__("Backend", 3, orchestrator_url)

    def get_system_prompt(self):
        return "You are a Senior Backend Engineer. Develop APIs, database logic, and server-side processing."

class TesterAgent(WorkerAgent):
    def __init__(self, orchestrator_url: str):
        super().__init__("Tester", 4, orchestrator_url)

    def handle_output(self, result: str, project_name: str):
        self.write_file(project_name, "TestReport.md", result)

class SecurityAgent(WorkerAgent):
    def __init__(self, orchestrator_url: str):
        super().__init__("SecurityManager", 1, orchestrator_url)

    def handle_output(self, result: str, project_name: str):
        self.write_file(project_name, "SecurityReport.md", result)
