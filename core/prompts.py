import os
import json
from .config import logger

def load_prompt(filename: str, key: str, fallback: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get(key, fallback)
    except Exception as e:
        logger.warning(f"Could not load prompt {key} from {filename}: {e}")
        return fallback
