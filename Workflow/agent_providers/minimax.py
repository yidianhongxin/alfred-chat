"""MiniMax provider — openai-compatible endpoint."""

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BASE_URL = "https://api.minimax.chat/v1"
DEFAULT_MODEL = "MiniMax-Text-01"
DEFAULT_TIMEOUT = 120


def schema() -> Dict[str, Any]:
    return {
        "provider": "minimax",
        "label": "MiniMax",
        "description": "MiniMax Chat API (openai-compatible)",
        "default_model": DEFAULT_MODEL,
        "env_vars": ["MINIMAX_API_KEY"],
    }


def health_check() -> Tuple[bool, str]:
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        return False, "未设置 MINIMAX_API_KEY"
    return True, "OK (未实际调用)"


def chat(
    prompt: str,
    system_prompt: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    **kwargs: Any,
) -> Tuple[str, Dict[str, Any]]:
    api_key = kwargs.get("api_key", os.environ.get("MINIMAX_API_KEY", ""))
    if not api_key:
        raise RuntimeError("缺少 MINIMAX_API_KEY")

    base_url = kwargs.get("base_url", os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    model = kwargs.get("model", os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL))
    temperature = float(kwargs.get("temperature", 0.7))
    max_tokens = int(kwargs.get("max_tokens", 4096))

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")

    url = f"{base_url}/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode()[:500]
        raise RuntimeError(f"MiniMax HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniMax 连接失败: {exc.reason}") from exc

    choice = data.get("choices", [{}])[0]
    text = choice.get("message", {}).get("content", "")
    usage = data.get("usage", {})
    return text, {
        "model": data.get("model", model),
        "tokens": usage.get("total_tokens", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "provider": "minimax",
    }
