"""obsidian_write / obsidian_append - 写入或追加 OB 库内文件(W2)。

用 args.action 区分 write/append(模仿 memory 工具的 pattern)。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import (  # noqa: E402
    Action,
    log_action,
    obsidian_allowed,
    obsidian_path_error,
    obsidian_root,
    resolve_obsidian_path,
    snapshot_file,
)
from agent_tools.registry import REGISTRY, ToolDef


def _make_action(tool_name: str, args: Dict[str, Any]) -> Action:
    """构造一个真正的 Action dataclass(供 log_action.asdict 用)。"""
    return Action(
        type="obsidian_write" if tool_name == "obsidian_write" else "obsidian_append",
        path=args.get("path", ""),
        content=args.get("content", ""),
    )


def handle_write(args: Dict[str, Any]) -> Tuple[str, str, str]:
    path_err = obsidian_path_error(args.get("path", ""))
    if path_err:
        return "error", path_err, "写入失败"
    root = obsidian_root()
    target = resolve_obsidian_path(args.get("path", ""), root)
    if target.suffix == "":
        target = target.with_suffix(".md")
    if not obsidian_allowed(target, root):
        return "error", "只允许写入 OB 库内文件", "写入失败"
    before = snapshot_file(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.get("content", ""), encoding="utf-8")
    log_action(_make_action("obsidian_write", args), target, before)
    return "success", f"已写入 OB:{target.relative_to(root)}", "已写入 OB"


def handle_append(args: Dict[str, Any]) -> Tuple[str, str, str]:
    path_err = obsidian_path_error(args.get("path", ""))
    if path_err:
        return "error", path_err, "追加失败"
    root = obsidian_root()
    target = resolve_obsidian_path(args.get("path", ""), root)
    if target.suffix == "":
        target = target.with_suffix(".md")
    if not obsidian_allowed(target, root):
        return "error", "只允许追加到 OB 库内文件", "追加失败"
    before = snapshot_file(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        original = target.read_text(encoding="utf-8")
        target.write_text(f"{original.rstrip()}\n\n{args.get('content', '')}\n", encoding="utf-8")
    else:
        target.write_text(args.get("content", ""), encoding="utf-8")
    log_action(_make_action("obsidian_append", args), target, before)
    return "success", f"已追加到 OB:{target.relative_to(root)}", "已追加到 OB"


# 保留原 tool 名称(LLM 已经习惯),用独立 handler
REGISTRY.register(ToolDef(
    name="obsidian_write",
    toolset="obsidian",
    description="写入(或覆盖)OB 库内文件;路径缺后缀自动加 .md",
    handler=handle_write,
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "OB 内相对路径"},
            "content": {"type": "string", "description": "完整内容"}
        },
        "required": ["path", "content"]
    },
))

REGISTRY.register(ToolDef(
    name="obsidian_append",
    toolset="obsidian",
    description="追加内容到 OB 库内文件(不存在则创建)",
    handler=handle_append,
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "OB 内相对路径"},
            "content": {"type": "string", "description": "要追加的内容"}
        },
        "required": ["path", "content"]
    },
))
