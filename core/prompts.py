import os
import json
from .config import logger

def load_prompt(agent_name: str, key: str, fallback: str) -> str:
    """
    Loads a prompt from a file. 
    First looks for prompts/{agent_name}/{key}.md
    """
    prompts_root = os.path.join(os.path.dirname(__file__), "..", "prompts")
    
    # Try Markdown path: prompts/{agent_name}/{key}.md
    md_path = os.path.join(prompts_root, agent_name, f"{key}.md")
    if os.path.exists(md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.warning(f"Error reading MD prompt {md_path}: {e}")

    logger.warning(f"Could not load prompt {key} for agent {agent_name} at {md_path}")
    return fallback
