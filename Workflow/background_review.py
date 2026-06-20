#!/usr/bin/env python3
"""Lightweight background memory review (Hermes-inspired, single API call)."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


WORKFLOW_DIR = Path(__file__).resolve().parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from memory_store import MemoryStore  # noqa: E402


def data_dir() -> Path:
    path = Path(os.environ.get("alfred_workflow_data") or os.environ.get("ALFRED_WORKFLOW_DATA") or "/tmp/alfred-chat")
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_chat_messages() -> List[Dict[str, str]]:
    chat_file = data_dir() / "chat.json"
    if not chat_file.exists():
        return []
    try:
        data = json.loads(chat_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        return data["messages"]
    return []


def recent_turns(messages: List[Dict[str, str]], count: int = 10) -> str:
    lines: List[str] = []
    for message in messages[-count * 2 :]:
        role = message.get("role", "")
        content = (message.get("content") or "").strip()
        if not content:
            continue
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}: {content[:800]}")
    return "\n".join(lines)


def resolve_provider() -> Tuple[str, str, str]:
    provider = os.environ.get("chat_provider") or "minimax"
    if provider == "openai":
        endpoint = (os.environ.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        api_key = os.environ.get("openai_api_key") or ""
        model = os.environ.get("openai_model") or "gpt-4o"
        return endpoint, api_key, model
    if provider == "deepseek":
        endpoint = os.environ.get("deepseek_api_endpoint") or "https://api.deepseek.com/chat/completions"
        api_key = os.environ.get("deepseek_api_key") or ""
        model = os.environ.get("deepseek_model") or "deepseek-v4-flash"
        return endpoint, api_key, model

    region = os.environ.get("minimax_region") or "china"
    default = (
        "https://api.minimaxi.com/v1/chat/completions"
        if region == "china"
        else "https://api.minimax.io/v1/chat/completions"
    )
    endpoint = os.environ.get("minimax_api_endpoint") or default
    api_key = os.environ.get("minimax_api_key") or ""
    model = os.environ.get("minimax_model") or "MiniMax-M3"
    return endpoint, api_key, model


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate, re.I)
    if fenced:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except Exception:
        return None


def call_review_model(prompt: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    provider = os.environ.get("chat_provider") or "minimax"
    if provider == "anthropic":
        return _call_review_via_bridge(provider, prompt, timeout)

    endpoint, api_key, model = resolve_provider()
    if not api_key and provider != "ollama":
        return None

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 Alfred Chat 的记忆审阅器。根据最近对话，判断是否应向长期记忆写入少量高价值事实。"
                    "只返回 JSON，不要 Markdown。"
                    '格式：{"actions":[{"action":"add|replace|remove|none","target":"user|memory","content":"...","old_text":"..."}]}'
                    "若无价值信息，返回 {\"actions\":[]}。"
                    "user=用户画像偏好；memory=环境/项目笔记。content 应简短。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0,
    }
    if provider not in {"deepseek", "openai", "openai_custom"}:
        payload["thinking"] = {"type": "disabled"}

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = extract_json_object(content or "")
    return parsed if isinstance(parsed, dict) else None


def _call_review_via_bridge(provider: str, prompt: str, timeout: int) -> Optional[Dict[str, Any]]:
    import subprocess

    payload = {
        "provider": provider,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 Alfred Chat 的记忆审阅器。根据最近对话，判断是否应向长期记忆写入少量高价值事实。"
                    "只返回 JSON，不要 Markdown。"
                    '格式：{"actions":[{"action":"add|replace|remove|none","target":"user|memory","content":"...","old_text":"..."}]}'
                    "若无价值信息，返回 {\"actions\":[]}。"
                    "user=用户画像偏好；memory=环境/项目笔记。content 应简短。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    script = WORKFLOW_DIR / "provider_bridge.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--complete", json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            return None
        result = json.loads(proc.stdout)
        if result.get("error"):
            return None
        parsed = extract_json_object(result.get("content") or "")
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def apply_actions(store: MemoryStore, actions: List[Dict[str, Any]]) -> List[str]:
    logs: List[str] = []
    for item in actions:
        action = (item.get("action") or "none").strip().lower()
        target = (item.get("target") or "user").strip().lower()
        if target not in {"user", "memory"}:
            target = "user"
        if action == "none":
            continue
        if action == "add":
            ok, msg = store.add(target, item.get("content", ""), auto=True)
            if ok:
                logs.append(msg)
        elif action == "replace":
            ok, msg = store.replace(target, item.get("old_text", ""), item.get("content", ""))
            if ok:
                logs.append(msg)
        elif action == "remove":
            ok, msg = store.remove(target, item.get("old_text", "") or item.get("content", ""))
            if ok:
                logs.append(msg)
    return logs


def run_review() -> Dict[str, Any]:
    if os.environ.get("memory_auto_write") == "0":
        return {"skipped": True, "reason": "memory_auto_write disabled"}

    messages = read_chat_messages()
    if not messages:
        return {"skipped": True, "reason": "no messages"}

    store = MemoryStore(data_dir())
    prompt = (
        "当前 MEMORY.md 条目：\n"
        f"{store.list_formatted()}\n\n"
        "最近对话：\n"
        f"{recent_turns(messages)}\n\n"
        "请仅提取值得长期记住的用户偏好、固定路径、工作习惯或项目背景。"
    )

    decision = call_review_model(prompt)
    if not decision:
        return {"skipped": True, "reason": "review call failed"}

    actions = decision.get("actions") or []
    if not isinstance(actions, list):
        return {"skipped": True, "reason": "invalid actions"}

    applied = apply_actions(store, actions)
    return {"applied": applied, "action_count": len(applied)}


def main() -> None:
    result = run_review()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
