"""task_add / task_list / task_done - 任务管理 3 个工具(W2)。

存储在 data_dir()/tasks.json,简单 JSON 列表。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import (  # noqa: E402
    load_json,
    save_json,
    tasks_path,
)
from agent_tools.registry import REGISTRY, ToolDef


def _load() -> list:
    return load_json(tasks_path(), [])


def _save(tasks: list) -> None:
    save_json(tasks_path(), tasks)


def handle_add(args: Dict[str, Any]) -> Tuple[str, str, str]:
    text = (args.get("text") or "").strip()
    if not text:
        return "error", "任务内容不能为空", "新增失败"
    tasks = _load()
    next_id = max([item.get("id", 0) for item in tasks], default=0) + 1
    tasks.append({
        "id": next_id,
        "text": text,
        "done": False,
        "created": datetime.now().isoformat(timespec="seconds"),
    })
    _save(tasks)
    return "success", f"已新增任务 {next_id}:{text}", "已新增任务"


def handle_done(args: Dict[str, Any]) -> Tuple[str, str, str]:
    try:
        task_id = int(args.get("id", 0) or 0)
    except (TypeError, ValueError):
        return "error", "无效的任务 id", "完成失败"
    if not task_id:
        return "error", "缺少 id 参数", "完成失败"
    tasks = _load()
    for item in tasks:
        if item.get("id") == task_id:
            item["done"] = True
            _save(tasks)
            return "success", f"已完成任务 {task_id}:{item.get('text')}", "已完成任务"
    return "error", f"未找到任务 {task_id}", "任务不存在"


def handle_list(args: Dict[str, Any]) -> Tuple[str, str, str]:
    tasks = _load()
    if not tasks:
        return "success", "当前任务:\n\n暂无任务", "0 个任务"
    lines = [f"{item['id']}. [{'x' if item.get('done') else ' '}] {item.get('text')}" for item in tasks]
    return "success", "当前任务:\n\n" + "\n".join(lines), f"{len(tasks)} 个任务"


REGISTRY.register(ToolDef(
    name="task_add",
    toolset="task",
    description="新增一个任务",
    handler=handle_add,
    schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "任务描述"}
        },
        "required": ["text"]
    },
))

REGISTRY.register(ToolDef(
    name="task_done",
    toolset="task",
    description="把指定 id 的任务标记为完成",
    handler=handle_done,
    schema={
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "任务 id(task_list 可见)"}
        },
        "required": ["id"]
    },
))

REGISTRY.register(ToolDef(
    name="task_list",
    toolset="task",
    description="列出所有任务(含已完成)",
    handler=handle_list,
    schema={"type": "object", "properties": {}},
))
