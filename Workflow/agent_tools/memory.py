"""memory - 减法版 W1 代表工具 3/3。

统一封装 memory_add / memory_replace / memory_remove / memory_list。
通过 args.action 区分,与原 LLM tool call 协议保持一致。

注意:这里保留原 'memory' 这个总工具名(LLM 已经习惯),
内部按 args.action 分发到 MemoryStore 的方法。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import get_memory_store  # noqa: E402
from agent_tools.registry import REGISTRY, ToolDef


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    store = get_memory_store()
    action_name = (args.get("action") or "list").strip().lower()
    target = (args.get("target") or "user").strip().lower()
    if target in {"memory", "mem", "notes"}:
        target = "memory"
    elif target in {"user", "profile"}:
        target = "user"
    else:
        target = "user"

    if action_name == "add":
        content = args.get("content") or args.get("note") or ""
        ok, message = store.add(target, content, auto=bool(args.get("auto")))
        status = "success" if ok else "error"
        return status, message, message

    if action_name == "replace":
        ok, message = store.replace(
            target,
            args.get("old_text", ""),
            args.get("new_text") or args.get("content", ""),
        )
        status = "success" if ok else "error"
        return status, message, message

    if action_name == "remove":
        ok, message = store.remove(target, args.get("old_text") or args.get("content", ""))
        status = "success" if ok else "error"
        return status, message, message

    if action_name == "list":
        body = store.list_formatted()
        return "success", f"记忆:\n\n{body}" if body else "记忆:\n\n暂无记忆", "已列出记忆"

    return "error", f"未知 memory action:{action_name}", f"未知 action:{action_name}"


REGISTRY.register(ToolDef(
    name="memory",
    toolset="memory",
    description="读写长期记忆(MEMORY.md / USER.md)",
    handler=handle,
    schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove", "list"],
                "description": "操作类型"
            },
            "target": {
                "type": "string",
                "enum": ["user", "memory"],
                "description": "user=用户画像;memory=笔记/项目背景"
            },
            "content": {
                "type": "string",
                "description": "要写入的内容(add/remove 时用)"
            },
            "old_text": {
                "type": "string",
                "description": "要替换/删除的旧内容(replace/remove 时用)"
            },
            "new_text": {
                "type": "string",
                "description": "新内容(replace 时用)"
            },
            "auto": {
                "type": "boolean",
                "description": "是否自动写入(后台审阅用)"
            }
        },
        "required": ["action"]
    },
))
