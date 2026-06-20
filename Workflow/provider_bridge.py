#!/usr/bin/env python3
"""Bridge Alfred Chat JXA to agent_providers for non-OpenAI-compatible APIs."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List


WORKFLOW_DIR = Path(__file__).resolve().parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _map_alfred_env(provider: str) -> None:
    """Map Alfred workflow variables to provider module env names."""
    if provider == "openai":
        os.environ.setdefault("OPENAI_API_KEY", _env("openai_api_key"))
        os.environ.setdefault("OPENAI_BASE_URL", _env("openai_base_url", "https://api.openai.com/v1"))
        os.environ.setdefault("OPENAI_MODEL", _env("openai_model", "gpt-4o"))
    elif provider == "anthropic":
        os.environ.setdefault("ANTHROPIC_API_KEY", _env("anthropic_api_key"))
        os.environ.setdefault("ANTHROPIC_MODEL", _env("anthropic_model", "claude-sonnet-4-20250514"))
    elif provider == "deepseek":
        os.environ.setdefault("DEEPSEEK_API_KEY", _env("deepseek_api_key"))
        os.environ.setdefault("DEEPSEEK_MODEL", _env("deepseek_model", "deepseek-v4-flash"))
        endpoint = _env("deepseek_api_endpoint", "https://api.deepseek.com/chat/completions")
        if endpoint.endswith("/chat/completions"):
            endpoint = endpoint.replace("/chat/completions", "/v1")
        os.environ.setdefault("DEEPSEEK_BASE_URL", endpoint)


def _split_messages(messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, str]], str]:
    system = ""
    turns: List[Dict[str, str]] = []
    for message in messages:
        role = message.get("role", "")
        content = message.get("content", "")
        if role == "system":
            system = content
        elif role in {"user", "assistant"}:
            turns.append({"role": role, "content": content})
    if not turns:
        return system, [], ""
    prompt = turns[-1].get("content", "")
    history = turns[:-1]
    return system, history, prompt


def complete(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = (payload.get("provider") or "openai").strip().lower()
    _map_alfred_env(provider)

    try:
        module = importlib.import_module(f"agent_providers.{provider}")
    except Exception as exc:
        return {"error": f"未知 provider: {provider} ({exc})"}

    system, history, prompt = _split_messages(payload.get("messages") or [])
    if not prompt:
        return {"error": "缺少 user 消息"}

    kwargs: Dict[str, Any] = {}
    if payload.get("model"):
        kwargs["model"] = payload["model"]
    if "temperature" in payload:
        kwargs["temperature"] = payload["temperature"]

    try:
        text, meta = module.chat(prompt, system_prompt=system, history=history, **kwargs)
        return {"content": text, "meta": meta}
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] != "--complete":
        print(json.dumps({"error": "usage: provider_bridge.py --complete '<json>'"}, ensure_ascii=False))
        return

    try:
        payload = json.loads(sys.argv[2])
    except Exception as exc:
        print(json.dumps({"error": f"JSON 解析失败: {exc}"}, ensure_ascii=False))
        return

    print(json.dumps(complete(payload), ensure_ascii=False))


if __name__ == "__main__":
    main()
