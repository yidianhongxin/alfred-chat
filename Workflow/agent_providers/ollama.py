"""Ollama provider — 本地 LLM (http://localhost:11434).

支持 openai-compatible chat completions API (Ollama v0.5+).
"""

import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "llama3.2"
DEFAULT_TIMEOUT = 120


def schema() -> Dict[str, Any]:
    return {
        "provider": "ollama",
        "label": "Ollama (本地)",
        "description": "本地运行的 Ollama 模型",
        "default_model": DEFAULT_MODEL,
        "base_url": DEFAULT_BASE_URL,
        "env_vars": ["OLLAMA_BASE_URL", "OLLAMA_MODEL"],
    }


def health_check() -> Tuple[bool, str]:
    import os
    base = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/models"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [m.get("name", "?") for m in data.get("data", [])]
            if models:
                return True, f"已连接, 可用模型: {', '.join(models[:5])}"
            return True, "已连接, 暂无可用模型"
    except Exception as exc:
        return False, f"连接失败: {exc}"


def chat(
    prompt: str,
    system_prompt: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    **kwargs: Any,
) -> Tuple[str, Dict[str, Any]]:
    """发起对话。

    kwargs 可包含:
        model: str = DEFAULT_MODEL
        base_url: str = DEFAULT_BASE_URL
        temperature: float = 0.7
        max_tokens: int = 4096
    """
    import os
    base_url = kwargs.get("base_url", os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    model = kwargs.get("model", os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL))
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

    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode()[:500]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama 连接失败 ({base_url}): {exc.reason}") from exc

    choice = data.get("choices", [{}])[0]
    text = choice.get("message", {}).get("content", "")
    usage = data.get("usage", {})
    return text, {
        "model": data.get("model", model),
        "tokens": usage.get("total_tokens", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "provider": "ollama",
    }
