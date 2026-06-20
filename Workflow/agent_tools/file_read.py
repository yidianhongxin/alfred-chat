"""file_read - 减法版 W1 代表工具 1/3。

保持与原 execute_read 100% 兼容的输入/输出。
- 路径必须在 /Users/DRLer 下(由 requires_args_in_user_dir 标记护栏)
- 二进制文件报错
- 长文件截断到 MAX_READ_CHARS(6000)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

# 让 agent_tools/ 里的模块能找到 local_agent 的工具函数
WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import (  # noqa: E402
    MAX_READ_CHARS,
    allowed,
    resolve_path,
)
from agent_tools.registry import REGISTRY, ToolDef


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    target = resolve_path(args.get("path", ""))
    if not allowed(target) or not target.exists() or not target.is_file():
        return "error", f"文件不存在或无权限:{target}", "读取失败"
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "error", f"无法读取二进制文件:{target}", "读取失败(二进制文件)"
    truncated = content[:MAX_READ_CHARS]
    suffix = "\n\n[内容过长,已截断]" if len(content) > MAX_READ_CHARS else ""
    return "success", f"{target} 内容:\n\n```text\n{truncated}\n```{suffix}", f"已读取 {target.name}"


REGISTRY.register(ToolDef(
    name="file_read",
    toolset="file",
    description="读取本地文件内容(限 /Users/DRLer 目录)",
    handler=handle,
    schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要读取的文件绝对路径,或裸文件名(默认指向桌面)"
            }
        },
        "required": ["path"]
    },
    requires_args_in_user_dir=True,
))
