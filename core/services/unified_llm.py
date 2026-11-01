import httpx
import json
import time
from typing import Tuple, List, Dict, Any
from .. import config
from ..config import logger

def build_llm_request(
    provider: str,
    model: str,
    messages: List[Dict[str, str]],
    url: str = "",
    api_key: str = "",
    num_ctx: int = 8192,
    temperature: float = 0.2
):
    """
    Constructs (endpoint, headers, payload, response_extractor)
    based on the provider type (ollama, gemini, openai, anthropic).
    """
    headers = {"Content-Type": "application/json"}
    provider_clean = (provider or "ollama").lower().strip()

    if provider_clean in ("openai", "gemini"):
        # Both OpenAI and Google Gemini (OpenAI-compatible endpoint)
        base = (url or "").rstrip("/")
        if provider_clean == "gemini":
            if not base:
                base = "https://generativelanguage.googleapis.com/v1beta/openai"
            if not base.endswith("/chat/completions"):
                endpoint = f"{base}/chat/completions"
            else:
                endpoint = base
            if not model:
                model = "gemini-2.0-flash"
        else: # openai
            if not base:
                base = "https://api.openai.com/v1"
            if not base.endswith("/chat/completions"):
                endpoint = config.build_openai_url(base, "/v1/chat/completions")
            else:
                endpoint = base
            if not model:
                model = "gpt-4o"

        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature
        }

        def extract_resp(data: dict) -> Tuple[str, int, int]:
            choices = data.get("choices", [])
            text = choices[0].get("message", {}).get("content", "") if choices else ""
            usage = data.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            return text, prompt_tokens, completion_tokens

        return endpoint, headers, payload, extract_resp

    elif provider_clean == "anthropic":
        endpoint = "https://api.anthropic.com/v1/messages"
        headers["x-api-key"] = api_key or ""
        headers["anthropic-version"] = "2023-06-01"

        system_msg = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        chat_msgs = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages if m.get("role") != "system"
        ]
        if not chat_msgs:
            chat_msgs = [{"role": "user", "content": "..."}]

        payload = {
            "model": model or "claude-3-5-sonnet-20241022",
            "messages": chat_msgs,
            "max_tokens": 4096,
            "temperature": temperature
        }
        if system_msg:
            payload["system"] = system_msg

        def extract_resp(data: dict) -> Tuple[str, int, int]:
            content_list = data.get("content", [])
            text = content_list[0].get("text", "") if content_list else ""
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            return text, input_tokens, output_tokens

        return endpoint, headers, payload, extract_resp

    else:
        # Default: Ollama (local edge or cloud)
        base = (url or config.OLLAMA_URL or "http://has-ai-ollama:11434").rstrip("/")
        endpoint = f"{base}/api/chat"
        if api_key and provider_clean == "ollama-cloud":
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model or config.AGENT_MODEL or "llama3.1:latest",
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "temperature": temperature
            }
        }

        def extract_resp(data: dict) -> Tuple[str, int, int]:
            text = data.get("message", {}).get("content", "")
            prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
            completion_tokens = int(data.get("eval_count", 0) or 0)
            return text, prompt_tokens, completion_tokens

        return endpoint, headers, payload, extract_resp


async def call_unified_llm_async(
    provider: str,
    model: str,
    messages: List[Dict[str, str]],
    url: str = "",
    api_key: str = "",
    timeout: float = 600.0,
    allow_fallback: bool = True
) -> Tuple[str, int, int]:
    """
    Executes an async LLM call across any configured provider.
    Returns (response_text, prompt_tokens, completion_tokens).
    """
    endpoint, headers, payload, extractor = build_llm_request(
        provider=provider,
        model=model,
        messages=messages,
        url=url,
        api_key=api_key,
        num_ctx=getattr(config, "LLM_NUM_CTX", 8192)
    )

    logger.info(f"[UnifiedLLM Async] Calling {provider}:{model} at {endpoint}")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            if resp.status_code != 200:
                err_text = resp.text[:300]
                logger.warning(f"[UnifiedLLM Async] Provider {provider} returned HTTP {resp.status_code}: {err_text}")
                if allow_fallback and provider != "ollama":
                    logger.info("[UnifiedLLM Async] Falling back to local Ollama...")
                    return await call_unified_llm_async(
                        provider="ollama",
                        model=config.AGENT_MODEL or "llama3.1:latest",
                        messages=messages,
                        url=config.OLLAMA_URL,
                        api_key="",
                        timeout=timeout,
                        allow_fallback=False
                    )
                raise RuntimeError(f"LLM HTTP {resp.status_code}: {err_text}")

            data = resp.json()
            text, p_tok, c_tok = extractor(data)
            return text, p_tok, c_tok

    except Exception as e:
        logger.error(f"[UnifiedLLM Async] Failed on {provider}:{model}: {e}")
        if allow_fallback and provider != "ollama":
            logger.info("[UnifiedLLM Async] Exception caught. Attempting fallback to local Ollama...")
            return await call_unified_llm_async(
                provider="ollama",
                model=config.AGENT_MODEL or "llama3.1:latest",
                messages=messages,
                url=config.OLLAMA_URL,
                api_key="",
                timeout=timeout,
                allow_fallback=False
            )
        raise e


def call_unified_llm_sync(
    provider: str,
    model: str,
    messages: List[Dict[str, str]],
    url: str = "",
    api_key: str = "",
    timeout: float = 600.0,
    allow_fallback: bool = True
) -> Tuple[str, int, int]:
    """
    Executes a synchronous LLM call across any configured provider.
    Returns (response_text, prompt_tokens, completion_tokens).
    """
    endpoint, headers, payload, extractor = build_llm_request(
        provider=provider,
        model=model,
        messages=messages,
        url=url,
        api_key=api_key,
        num_ctx=getattr(config, "LLM_NUM_CTX", 8192)
    )

    logger.info(f"[UnifiedLLM Sync] Calling {provider}:{model} at {endpoint}")

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
            if resp.status_code != 200:
                err_text = resp.text[:300]
                logger.warning(f"[UnifiedLLM Sync] Provider {provider} returned HTTP {resp.status_code}: {err_text}")
                if allow_fallback and provider != "ollama":
                    logger.info("[UnifiedLLM Sync] Falling back to local Ollama...")
                    return call_unified_llm_sync(
                        provider="ollama",
                        model=config.AGENT_MODEL or "llama3.1:latest",
                        messages=messages,
                        url=config.OLLAMA_URL,
                        api_key="",
                        timeout=timeout,
                        allow_fallback=False
                    )
                raise RuntimeError(f"LLM HTTP {resp.status_code}: {err_text}")

            data = resp.json()
            text, p_tok, c_tok = extractor(data)
            return text, p_tok, c_tok

    except Exception as e:
        logger.error(f"[UnifiedLLM Sync] Failed on {provider}:{model}: {e}")
        if allow_fallback and provider != "ollama":
            logger.info("[UnifiedLLM Sync] Exception caught. Attempting fallback to local Ollama...")
            return call_unified_llm_sync(
                provider="ollama",
                model=config.AGENT_MODEL or "llama3.1:latest",
                messages=messages,
                url=config.OLLAMA_URL,
                api_key="",
                timeout=timeout,
                allow_fallback=False
            )
        raise e

