import os
import json
import logging
import copy
import threading
from dotenv import load_dotenv

load_dotenv()

# DÜZELTME 4: LOG_LEVEL string → integer dönüşümü.
# Geçersiz değer gelirse WARNING'e düşmek yerine açıkça ERROR loglanır.
_log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
_log_level     = getattr(logging, _log_level_str, None)
if not isinstance(_log_level, int):
    _log_level = logging.INFO
    print(f"[config] Invalid LOG_LEVEL='{_log_level_str}', defaulting to INFO.")

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Orchestrator")


def _normalize_host_path(raw_path: str) -> str:
    """Maps Docker container '/app/...' paths to workspace-relative paths when running natively on Windows."""
    if os.name == "nt" and raw_path.startswith("/app/"):
        return raw_path[len("/app/"):]
    return raw_path


# --- CONFIGURATION ENGINE ---
CONFIG_PATH = _normalize_host_path(os.getenv("CONFIG_PATH", "data/config.json"))

# DÜZELTME 2: DEFAULT_CONFIG içindeki env değerleri burada bir kez okunur.
# refresh_runtime_config içinde fallback olarak bu sabitler kullanılır,
# boş string değil.
_DEFAULT_URL            = os.getenv("OLLAMA_URL",     "http://has-ai-ollama:11434")
_DEFAULT_MODEL          = os.getenv("AGENT_MODEL",    "llama3.1:latest")
_DEFAULT_TEAMLEAD_MODEL = os.getenv("TEAMLEAD_MODEL", _DEFAULT_MODEL)

DEFAULT_LLM_ROUTING = {
    "defaultChat": {
        "provider": "ollama",
        "model": _DEFAULT_MODEL,
        "url": _DEFAULT_URL,
        "apiKey": ""
    },
    "defaultTask": {
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "apiKey": ""
    },
    "agents": {}
}

DEFAULT_CONFIG = {
    "NODES": [
        {
            "id":            "default-edge",
            "name":          "Local Edge (Ollama)",
            "provider":      "ollama",
            "url":           _DEFAULT_URL,
            "apiKey":        "",
            "model":         _DEFAULT_MODEL,
            "teamleadModel": _DEFAULT_TEAMLEAD_MODEL,   # DÜZELTME 5: Ayrı alan
        }
    ],
    "ACTIVE_NODE_ID": "default-edge",
    "LLM_ROUTING": DEFAULT_LLM_ROUTING
}

config_lock = threading.Lock()


def build_openai_url(base_url: str, endpoint_path: str) -> str:
    """
    Constructs an OpenAI-compatible URL without duplicating '/v1'.
    Handles both 'https://api.openai.com' and 'https://api.openai.com/v1'.
    """
    base = (base_url or "").strip().rstrip("/")
    path = "/" + endpoint_path.lstrip("/")
    if not base.endswith("/v1") and not path.startswith("/v1/"):
        path = "/v1" + path
    elif base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return f"{base}{path}"


def _write_config_unsafe(cfg: dict) -> None:
    """config_lock ZATEN alınmış durumdayken dosyaya yazar. Atomic write."""
    os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    # DÜZELTME 3: Önce tmp'ye yaz, sonra rename — yarım dosya riski yok.
    os.replace(tmp_path, CONFIG_PATH)


def load_config() -> dict:
    with config_lock:
        if not os.path.exists(CONFIG_PATH):
            os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
            _write_config_unsafe(DEFAULT_CONFIG)
            return copy.deepcopy(DEFAULT_CONFIG)

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            # Migration: eski düz config → NODES yapısına geç
            if "NODES" not in cfg:
                logger.info("Migrating legacy config to Multi-Node structure...")
                migrated = copy.deepcopy(DEFAULT_CONFIG)
                node = migrated["NODES"][0]
                if "OLLAMA_URL"   in cfg: node["url"]      = cfg["OLLAMA_URL"]
                if "AGENT_MODEL"  in cfg:
                    node["model"]          = cfg["AGENT_MODEL"]
                    node["teamleadModel"]  = cfg.get("TEAMLEAD_MODEL", cfg["AGENT_MODEL"])
                if "LLM_PROVIDER" in cfg: node["provider"] = cfg["LLM_PROVIDER"]
                if "LLM_API_KEY"  in cfg: node["apiKey"]   = cfg["LLM_API_KEY"]

                # DÜZELTME 3: Atomic write — bozuk dosya riski yok
                _write_config_unsafe(migrated)
                logger.info("Migration complete.")
                return migrated

            if "LLM_ROUTING" not in cfg:
                cfg["LLM_ROUTING"] = copy.deepcopy(DEFAULT_LLM_ROUTING)

            return cfg

        except Exception as e:
            logger.error(f"Failed to load config, using defaults: {e}")
            return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    with config_lock:
        _write_config_unsafe(cfg)
    refresh_runtime_config(cfg)


def reload_runtime_config() -> dict:
    """Reloads config from disk and refreshes module-level runtime variables."""
    cfg = load_config()
    refresh_runtime_config(cfg)
    return cfg


def refresh_runtime_config(cfg: dict) -> None:
    # DÜZELTME 1 & 2: Global'lar burada declare edilir ve
    # fallback olarak DEFAULT_CONFIG'den gelen sabit değerler kullanılır,
    # boş string değil.
    global OLLAMA_URL, AGENT_MODEL, TEAMLEAD_MODEL, LLM_PROVIDER, LLM_API_KEY, runtime_config

    runtime_config = cfg
    nodes     = cfg.get("NODES", [])
    active_id = cfg.get("ACTIVE_NODE_ID")

    active_node = next((n for n in nodes if n.get("id") == active_id), None)
    if not active_node and nodes:
        active_node = nodes[0]
        logger.warning(f"Active node '{active_id}' not found, falling back to first node.")

    if active_node:
        # DÜZELTME 2: Fallback olarak _DEFAULT_URL/_DEFAULT_MODEL kullan, "" değil
        OLLAMA_URL     = active_node.get("url")           or _DEFAULT_URL
        AGENT_MODEL    = active_node.get("model")         or _DEFAULT_MODEL
        # DÜZELTME 5: teamleadModel alanı varsa kullan, yoksa AGENT_MODEL'e düş
        TEAMLEAD_MODEL = active_node.get("teamleadModel") or AGENT_MODEL
        LLM_PROVIDER   = active_node.get("provider")      or "ollama"
        LLM_API_KEY    = active_node.get("apiKey",        "")
        logger.info(
            f"Active Node [{active_node.get('name')}]: "
            f"AGENT={AGENT_MODEL}, TEAMLEAD={TEAMLEAD_MODEL}, PROVIDER={LLM_PROVIDER}"
        )
    else:
        # Node listesi boşsa env değerlerine dön
        OLLAMA_URL     = _DEFAULT_URL
        AGENT_MODEL    = _DEFAULT_MODEL
        TEAMLEAD_MODEL = _DEFAULT_TEAMLEAD_MODEL
        LLM_PROVIDER   = "ollama"
        LLM_API_KEY    = ""
        logger.warning("No nodes configured. Using environment variable defaults.")


# DÜZELTME 1: Global değişkenler refresh_runtime_config'den ÖNCE tanımlanıyor.
# Bu sayede refresh içindeki `global` declaration UnboundLocalError üretmez.
OLLAMA_URL     = _DEFAULT_URL
AGENT_MODEL    = _DEFAULT_MODEL
TEAMLEAD_MODEL = _DEFAULT_TEAMLEAD_MODEL
LLM_PROVIDER   = "ollama"
LLM_API_KEY    = ""
runtime_config = {}

# Tek seferlik başlatma — load → refresh zincirine gerek yok
runtime_config = load_config()
refresh_runtime_config(runtime_config)


def get_agent_llm_config(agent_name: str, purpose: str = "task") -> dict:
    """
    Returns resolved LLM configuration {provider, model, url, apiKey}
    for the given agent and purpose ('chat' or 'task').

    Priority:
    1. Agent specific override in LLM_ROUTING['agents'][agent_name]
    2. Global default for purpose (defaultChat or defaultTask in LLM_ROUTING)
    3. Active node fallback (from NODES)
    """
    routing = runtime_config.get("LLM_ROUTING") or {}
    agent_overrides = routing.get("agents", {}).get(agent_name, {})

    if purpose == "chat":
        provider = agent_overrides.get("chatProvider") or routing.get("defaultChat", {}).get("provider") or "ollama"
        model = agent_overrides.get("chatModel") or routing.get("defaultChat", {}).get("model") or AGENT_MODEL
        url = agent_overrides.get("url") or routing.get("defaultChat", {}).get("url") or OLLAMA_URL
        api_key = agent_overrides.get("apiKey") or routing.get("defaultChat", {}).get("apiKey") or LLM_API_KEY
    else:  # task
        provider = agent_overrides.get("taskProvider") or routing.get("defaultTask", {}).get("provider") or LLM_PROVIDER
        model = agent_overrides.get("taskModel") or routing.get("defaultTask", {}).get("model") or (TEAMLEAD_MODEL if agent_name == "TeamLead" else AGENT_MODEL)
        url = agent_overrides.get("url") or routing.get("defaultTask", {}).get("url") or (OLLAMA_URL if provider == "ollama" else "")
        api_key = agent_overrides.get("apiKey") or routing.get("defaultTask", {}).get("apiKey") or LLM_API_KEY

    # Intelligent endpoint fallbacks for known cloud providers
    if provider == "gemini":
        if not url:
            url = "https://generativelanguage.googleapis.com/v1beta/openai"
        if not model:
            model = "gemini-2.0-flash"
    elif provider == "openai":
        if not url:
            url = "https://api.openai.com/v1"
        if not model:
            model = "gpt-4o"
    elif provider == "anthropic":
        if not url:
            url = "https://api.anthropic.com/v1"
        if not model:
            model = "claude-3-5-sonnet-20241022"
    elif provider == "ollama":
        if not url:
            url = OLLAMA_URL or "http://has-ai-ollama:11434"
        if not model:
            model = AGENT_MODEL or "llama3.1:latest"

    return {
        "provider": provider,
        "model": model,
        "url": url,
        "apiKey": api_key or ""
    }

# Diğer ayarlar
DB_PATH          = _normalize_host_path(os.getenv("TRACE_DB_PATH", "data/traceability.db"))
LLM_TIMEOUT      = int(os.getenv("LLM_TIMEOUT_SEC", "600"))
LLM_MAX_RETRIES  = int(os.getenv("LLM_MAX_RETRIES", "2"))
LLM_NUM_CTX      = int(os.getenv("LLM_NUM_CTX", "8192"))
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://has-ai-orchestrator:8000")
AGENT_ROLE       = os.getenv("AGENT_ROLE",       "both")
