import os
from .config import logger


# DÜZELTME 1: __file__ her zaman absolute olmayabilir.
# Modül yüklendiğinde bir kez resolve et — her çağrıda tekrar hesaplama.
_PROMPTS_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")
)


def load_prompt(agent_name: str, key: str, fallback: str) -> str:
    """
    Loads a prompt from: prompts/{agent_name}/{key}.md

    Args:
        agent_name: Subdirectory name under prompts/ (e.g. 'backend', 'devops').
        key:        Filename without extension (e.g. 'BE_backend_worker').
        fallback:   Returned as-is if the file cannot be found or read.

    Returns:
        Prompt string (stripped), or fallback if file is missing/unreadable.
    """
    # DÜZELTME 4: Path'i normalize et — symlink ve relative cwd senaryolarını kapat.
    md_path = os.path.abspath(os.path.normpath(
        os.path.join(_PROMPTS_ROOT, agent_name, f"{key}.md")
    ))

    # Güvenlik: resolved path prompts root dışına çıkmamalı
    try:
        if os.path.commonpath([_PROMPTS_ROOT, md_path]) != _PROMPTS_ROOT:
            logger.error(f"Path traversal attempt blocked: {md_path}")
            return fallback
    except ValueError:
        logger.error(f"Path traversal attempt blocked: {md_path}")
        return fallback

    if os.path.isfile(md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                logger.warning(f"Prompt file is empty: {md_path}. Using fallback.")
                return fallback
            return content
        except Exception as e:
            logger.warning(f"Error reading prompt {md_path}: {e}. Using fallback.")
            return fallback

    # DÜZELTME 2 & 3: Fallback'e düşüldüğünde ne döndürüldüğünü logla.
    logger.warning(
        f"Prompt not found for agent='{agent_name}' key='{key}' "
        f"at '{md_path}'. "
        f"Falling back to {'provided fallback string' if fallback else 'empty string'}."
    )
    return fallback
