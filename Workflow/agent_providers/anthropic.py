"""Anthropic provider — Claude Messages API."""

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 120
DEFAULT_MAX_TOKENS = 4096


def schema() -> Dict[str, Any]:
    return {
        "provider": "anthropic",
        "label": "Anthropic (Claude)",
        "description": "Anthropic Messages API",
        "default_model": DEFAULT_MODEL,
        "env_vars": ["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"],
    }


def _api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("anthropic_api_key") or ""


def _model() -> str:
    return os.environ.get("ANTHROPIC_MODEL") or os.environ.get("anthropic_model") or DEFAULT_MODEL


def health_check() -> Tuple[bool, str]:
    if not _api_key():
        return False, "未设置 Anthropic API Key"
    return True, "OK (未实际调用, 仅检查 API key)"


def chat(
    prompt: str,
    system_prompt: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    **kwargs: Any,
) -> Tuple[str, Dict[str, Any]]:
    api_key = kwargs.get("api_key", _api_key())
    if not api_key:
        raise RuntimeError("缺少 Anthropic API Key")

    base_url = kwargs.get("base_url", os.environ.get("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    model = kwargs.get("model", _model())
    max_tokens = int(kwargs.get("max_tokens", DEFAULT_MAX_TOKENS))
    temperature = float(kwargs.get("temperature", 0.7))

    messages: List[Dict[str, Any]] = []
    if history:
        for h in history:
            role = h.get("role", "user")
            if role == "assistant":
                role = "assistant"
            elif role == "system":
                continue
            else:
                role = "user"
            messages.append({"role": role, "content": h.get("content", "")})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": model,
        "messages": messages,
        "system": system_prompt or None,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    url = f"{base_url}/messages"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", ANTHROPIC_VERSION)

    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode()[:500]
        raise RuntimeError(f"Anthropic HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Anthropic 连接失败: {exc.reason}") from exc

    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    usage = data.get("usage", {})
    return text, {
        "model": data.get("model", model),
        "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "provider": "anthropic",
    }
