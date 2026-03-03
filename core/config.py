import os
import json
import logging
import copy
import threading
from dotenv import load_dotenv

load_dotenv()

# Set up logging early
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Orchestrator")

# --- CONFIGURATION ENGINE ---
CONFIG_PATH = "data/config.json"
DEFAULT_CONFIG = {
    "NODES": [
        {
            "id": "default-edge",
            "name": "Local Edge (Ollama)",
            "provider": "ollama",
            "url": os.getenv("OLLAMA_URL", "http://has-ai-ollama:11434"),
            "apiKey": "",
            "model": os.getenv("AGENT_MODEL", "llama3.1:latest")
        }
    ],
    "ACTIVE_NODE_ID": "default-edge"
}

config_lock = threading.Lock()

def load_config():
    with config_lock:
        if not os.path.exists(CONFIG_PATH):
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
            return DEFAULT_CONFIG
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                
                # Migration: If old flat config, move to NODES structure
                if "NODES" not in cfg:
                    logger.info("Migrating legacy config to Multi-Node structure...")
                    migrated = copy.deepcopy(DEFAULT_CONFIG)
                    node = migrated["NODES"][0]
                    if "OLLAMA_URL" in cfg: node["url"] = cfg["OLLAMA_URL"]
                    if "AGENT_MODEL" in cfg: node["model"] = cfg["AGENT_MODEL"]
                    if "LLM_PROVIDER" in cfg: node["provider"] = cfg["LLM_PROVIDER"]
                    if "LLM_API_KEY" in cfg: node["apiKey"] = cfg["LLM_API_KEY"]
                    
                    # Save immediately to stabilize
                    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                        json.dump(migrated, f, ensure_ascii=False, indent=2)
                    return migrated
                    
                return cfg
        except Exception as e:
            logger.error(f"Failed to load config, fallback to default: {e}")
            return DEFAULT_CONFIG

def save_config(config):
    with config_lock:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    refresh_runtime_config(config)

def refresh_runtime_config(config):
    global OLLAMA_URL, AGENT_MODEL, TEAMLEAD_MODEL, LLM_PROVIDER, LLM_API_KEY, runtime_config
    runtime_config = config
    
    nodes = config.get("NODES", [])
    active_id = config.get("ACTIVE_NODE_ID")
    
    # Find active node
    active_node = next((n for n in nodes if n.get("id") == active_id), None)
    if not active_node and nodes:
        active_node = nodes[0]
    
    if active_node:
        OLLAMA_URL = active_node.get("url", OLLAMA_URL)
        AGENT_MODEL = active_node.get("model", AGENT_MODEL)
        TEAMLEAD_MODEL = active_node.get("model", AGENT_MODEL)
        LLM_PROVIDER = active_node.get("provider", "ollama")
        LLM_API_KEY = active_node.get("apiKey", "")
        logger.info(f"Active Node [{active_node.get('name')}]: AGENT={AGENT_MODEL}, PROVIDER={LLM_PROVIDER}")

runtime_config = load_config()


# Initialize globals from active node
OLLAMA_URL = ""
AGENT_MODEL = ""
TEAMLEAD_MODEL = ""
LLM_PROVIDER = "ollama"
LLM_API_KEY = ""
refresh_runtime_config(runtime_config)

DB_PATH = os.getenv("TRACE_DB_PATH", "data/traceability.db")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SEC", "600"))
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://has-ai-orchestrator:8000")
AGENT_ROLE = os.getenv("AGENT_ROLE", "both")
