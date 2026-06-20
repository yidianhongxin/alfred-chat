"""obsidian_search - 减法版 W1 代表工具 2/3。

保持与原 execute_obsidian_search 100% 兼容。
- 在 OB 库根目录下递归搜 .md
- 命中文件名或正文含关键词
- 最多 MAX_LIST_ITEMS 条
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import (  # noqa: E402
    DEFAULT_OBSIDIAN,
    MAX_LIST_ITEMS,
    allowed,
    format_paths,
    obsidian_root,
)
from agent_tools.registry import REGISTRY, ToolDef


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    root = obsidian_root()
    if not allowed(root):
        return "error", f"Obsidian 库超出允许范围:{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在:{root}", "OB 库不存在"
    term = (args.get("term") or args.get("query") or "").strip()
    if not term:
        return "error", "缺少 term 参数", "缺少搜索关键词"
    matches = []
    for path in root.rglob("*.md"):
        if len(matches) >= MAX_LIST_ITEMS:
            break
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if term in path.name or term in text:
            matches.append(path)
    return "success", f"OB 中关于「{term}」的笔记:\n\n{format_paths(matches, root)}", f"找到 {len(matches)} 条 OB 匹配"


REGISTRY.register(ToolDef(
    name="obsidian_search",
    toolset="obsidian",
    description="在 Obsidian 库里按关键词搜索笔记",
    handler=handle,
    schema={
        "type": "object",
        "properties": {
            "term": {
                "type": "string",
                "description": "搜索关键词(命中文件名或正文)"
            }
        },
        "required": ["term"]
    },
))
