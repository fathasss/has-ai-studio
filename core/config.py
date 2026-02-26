import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ENGINE ---
CONFIG_PATH = "data/config.json"
DEFAULT_CONFIG = {
    "AGENT_MODEL": os.getenv("AGENT_MODEL", "llama3.1:latest"),
    "TEAMLEAD_MODEL": os.getenv("TEAMLEAD_MODEL", "llama3.1:latest"),
    "OLLAMA_URL": os.getenv("OLLAMA_URL", "http://has-ai-ollama:11434"),
    "LLM_PROVIDER": "ollama",
    "LLM_API_KEY": "",
}

def load_config():
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except:
        return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, ensure_ascii=False)

runtime_config = load_config()

OLLAMA_URL = runtime_config["OLLAMA_URL"]
AGENT_MODEL = runtime_config["AGENT_MODEL"]
TEAMLEAD_MODEL = runtime_config.get("TEAMLEAD_MODEL", AGENT_MODEL)
DB_PATH = os.getenv("TRACE_DB_PATH", "data/traceability.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SEC", "600"))
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://has-ai-orchestrator:8000")
AGENT_ROLE = os.getenv("AGENT_ROLE", "both")

# Set up logging early
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Orchestrator")
