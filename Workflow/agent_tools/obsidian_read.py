"""obsidian_read - 读取 OB 库内文件(W2)。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import (  # noqa: E402
    obsidian_allowed,
    obsidian_root,
    read_markdown_excerpt,
    resolve_obsidian_path,
)
from agent_tools.registry import REGISTRY, ToolDef


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    root = obsidian_root()
    target = resolve_obsidian_path(args.get("path", ""), root)
    if not obsidian_allowed(target, root):
        return "error", "只允许读取 OB 库内文件", "读取失败"
    if not target.exists() or not target.is_file():
        rel = target.relative_to(root) if root in target.parents else target
        return "error", f"OB 文件不存在:{rel}", "读取失败"
    try:
        excerpt = read_markdown_excerpt(target)
    except UnicodeDecodeError:
        return "error", f"无法读取二进制文件:{target}", "读取失败"
    return "success", f"OB 文件 {target.relative_to(root)}:\n\n```text\n{excerpt}\n```", f"已读取 OB:{target.name}"


REGISTRY.register(ToolDef(
    name="obsidian_read",
    toolset="obsidian",
    description="读取 Obsidian 库内文件(限 vault 范围内)",
    handler=handle,
    schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "OB 内相对路径(如 0.inbox/note.md)或绝对路径"
            }
        },
        "required": ["path"]
    },
))
