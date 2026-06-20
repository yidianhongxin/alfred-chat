"""session_search - 跨会话 FTS5 全文搜索(W2)。

委托给 session_index.search_sessions + format_search_results。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from agent_tools.registry import REGISTRY, ToolDef


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    from session_index import format_search_results, search_sessions

    term = (args.get("term") or args.get("query") or "").strip()
    if not term:
        return "error", "请提供搜索关键词", "搜索失败"
    results = search_sessions(term)
    body = format_search_results(term, results)
    return "success", body, f"找到 {len(results)} 条"


REGISTRY.register(ToolDef(
    name="session_search",
    toolset="search",
    description="跨所有归档会话做 FTS5 全文搜索",
    handler=handle,
    schema={
        "type": "object",
        "properties": {
            "term": {"type": "string", "description": "搜索关键词"}
        },
        "required": ["term"]
    },
))
