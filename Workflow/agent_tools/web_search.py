"""web_search - 用 Tavily 搜索公网信息。

Tavily 是为 AI Agent 设计的搜索 API,返回「综合答案 + 列表」,中文支持良好。
免费额度 1000 次/月,适合个人 Alfred Chat 使用。

API Key 在 Alfred Preferences → Workflows → Alfred Chat → 右侧 Configure Workflow
面板里的 "Tavily API Key" 字段填写(由 Alfred 自动注入为环境变量 tavily_api_key)。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from agent_tools.registry import REGISTRY, ToolDef


TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_MAX_RESULTS = 5
MAX_RESULTS_LIMIT = 10
TIMEOUT_SECONDS = 20


def _tavily_search(query: str, api_key: str, max_results: int) -> dict:
    body = json.dumps({
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": True,
        "include_raw_content": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
        return json.loads(r.read().decode("utf-8"))


def _format_results(data: dict) -> Tuple[str, int]:
    answer = (data.get("answer") or "").strip()
    results = data.get("results") or []
    parts = []
    if answer:
        parts.append(f"**综合答案**:\n\n{answer}\n")
    parts.append(f"**{len(results)} 条搜索结果**:\n")
    for i, r in enumerate(results, 1):
        title = r.get("title", "(无标题)")
        url = r.get("url", "")
        content = r.get("content", "").strip()
        parts.append(f"{i}. [{title}]({url})\n   {content}\n")
    return "\n".join(parts), len(results)


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    api_key = (os.environ.get("tavily_api_key") or "").strip()
    if not api_key:
        return (
            "error",
            "未配置 Tavily API Key。\n\n"
            "配置方式:Alfred Preferences → Workflows → Alfred Chat → 右侧\n"
            "Configure Workflow → 「Tavily API Key」字段填入你的 key → 保存。\n\n"
            "注册拿 key:https://tavily.com (免费 1000 次/月)",
            "缺少 Tavily API Key",
        )
    query = (args.get("query") or args.get("q") or "").strip()
    if not query:
        return "error", "缺少 query 参数", "缺少搜索关键词"
    try:
        max_results = int(args.get("max_results") or DEFAULT_MAX_RESULTS)
    except (TypeError, ValueError):
        max_results = DEFAULT_MAX_RESULTS
    max_results = max(1, min(MAX_RESULTS_LIMIT, max_results))

    try:
        data = _tavily_search(query, api_key, max_results)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        return "error", f"Tavily HTTP {exc.code}: {body or exc.reason}", f"搜索失败 HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return "error", f"网络错误:{exc.reason}", "搜索失败:网络"
    except (TimeoutError, json.JSONDecodeError) as exc:
        return "error", f"搜索失败:{type(exc).__name__}: {exc}", f"搜索失败:{type(exc).__name__}"

    text, count = _format_results(data)
    if count == 0 and not data.get("answer"):
        return "success", "未找到相关结果。", "0 条结果"
    return "success", text, f"找到 {count} 条结果"


REGISTRY.register(ToolDef(
    name="web_search",
    toolset="web",
    description="用 Tavily 搜索公网信息,返回综合答案 + 结果列表(标题/链接/摘要)",
    handler=handle,
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或问题,例如「好好的时光 刘成 角色」"
            },
            "max_results": {
                "type": "integer",
                "description": "最多返回几条结果,默认 5,范围 1-10",
                "default": DEFAULT_MAX_RESULTS,
                "minimum": 1,
                "maximum": MAX_RESULTS_LIMIT,
            },
        },
        "required": ["query"],
    },
))