import os
import requests
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OllamaInit")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL_NAME = os.getenv("AGENT_MODEL", "llama3.1:latest")

def pull_model():
    logger.info(f"Checking for model {MODEL_NAME}...")
    try:
        # Check if already present
        res = requests.get(f"{OLLAMA_URL}/api/tags")
        if res.ok:
            models = [m['name'] for m in res.json().get('models', [])]
            if MODEL_NAME in models or f"{MODEL_NAME}:latest" in models:
                logger.info(f"Model {MODEL_NAME} already exists.")
                return True
        
        logger.info(f"Pulling model {MODEL_NAME}... this may take a while.")
        res = requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": MODEL_NAME}
        )
        res.raise_for_status()
        logger.info(f"Pull request for {MODEL_NAME} submitted successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to pull model: {e}")
        return False

if __name__ == "__main__":
    while not pull_model():
        logger.info("Retrying in 10 seconds...")
        time.sleep(10)
