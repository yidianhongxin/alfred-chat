"""obsidian_diary_* / obsidian_daily_* - 日记相关 4 个工具(W2)。

包括:
- obsidian_diary_browse 翻阅(随机/最新)
- obsidian_diary_recent 最近 N 天
- obsidian_daily_read  读今日
- obsidian_daily_append 追加到今日
"""

from __future__ import annotations

import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import (  # noqa: E402
    Action,
    MAX_READ_CHARS,
    allowed,
    diary_files,
    find_daily_note,
    log_action,
    obsidian_allowed,
    obsidian_root,
    read_markdown_excerpt,
    snapshot_file,
)
from agent_tools.registry import REGISTRY, ToolDef


def handle_diary_browse(args: Dict[str, Any]) -> Tuple[str, str, str]:
    root = obsidian_root()
    if not obsidian_allowed(root, root):
        return "error", f"Obsidian 库超出允许范围:{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在:{root}", "OB 库不存在"
    diaries = diary_files(root)
    if not diaries:
        return "error", f"未找到日记。已搜索 {root}", "未找到日记"
    count = int(args.get("count", 1) or 1)
    target = random.choice(diaries) if count < 0 else diaries[0]
    excerpt = read_markdown_excerpt(target)
    return "success", f"翻到这篇日记:{target.relative_to(root)}\n\n```text\n{excerpt}\n```", f"已翻阅日记:{target.name}"


def handle_diary_recent(args: Dict[str, Any]) -> Tuple[str, str, str]:
    root = obsidian_root()
    if not obsidian_allowed(root, root):
        return "error", f"Obsidian 库超出允许范围:{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在:{root}", "OB 库不存在"
    count = int(args.get("count", 7) or 7)
    diaries = diary_files(root)[:count]
    if not diaries:
        return "error", f"未找到日记。已搜索 {root}", "未找到日记"
    sections = []
    per_file_limit = max(800, MAX_READ_CHARS // max(1, len(diaries)))
    for path in diaries:
        sections.append(f"## {path.relative_to(root)}\n\n```text\n{read_markdown_excerpt(path, per_file_limit)}\n```")
    return "success", f"最近 {len(diaries)} 篇日记:\n\n" + "\n\n".join(sections), f"已读取 {len(diaries)} 篇日记"


def handle_daily_read(args: Dict[str, Any]) -> Tuple[str, str, str]:
    root = obsidian_root()
    if not allowed(root):
        return "error", f"Obsidian 库超出允许范围:{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在:{root}", "OB 库不存在"
    target = find_daily_note(root)
    if not target:
        today = datetime.now().strftime("%Y-%m-%d")
        return "error", f"未找到今天的日记:{today}。已搜索 {root}", "未找到今日日记"
    content = target.read_text(encoding="utf-8")
    truncated = content[:MAX_READ_CHARS]
    suffix = "\n\n[内容过长,已截断]" if len(content) > MAX_READ_CHARS else ""
    return "success", f"今日日记 {target}:\n\n```text\n{truncated}\n```{suffix}", "已读取今日日记"


def handle_daily_append(args: Dict[str, Any]) -> Tuple[str, str, str]:
    root = obsidian_root()
    target = root / "0.inbox" / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    if not allowed(target):
        return "error", "日记路径不在允许范围内", "追加失败"
    before = snapshot_file(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = args.get("content", "")
    if target.exists():
        original = target.read_text(encoding="utf-8")
        target.write_text(f"{original.rstrip()}\n\n{content}\n", encoding="utf-8")
    else:
        target.write_text(f"# {datetime.now().strftime('%Y-%m-%d')}\n\n{content}\n", encoding="utf-8")

    log_action(Action(
        type="obsidian_daily_append",
        path=str(target),
        content=content,
    ), target, before)
    return "success", f"已追加到今天日记:{target}", "已追加到今天日记"


REGISTRY.register(ToolDef(
    name="obsidian_diary_browse",
    toolset="obsidian",
    description="翻阅 OB 库的日记(默认最新一篇,count<0 随机)",
    handler=handle_diary_browse,
    schema={
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "1=最新一篇(默认);-1=随机一篇",
                "default": 1
            }
        }
    },
))

REGISTRY.register(ToolDef(
    name="obsidian_diary_recent",
    toolset="obsidian",
    description="读最近 N 天日记(默认 7 天)",
    handler=handle_diary_recent,
    schema={
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "天数,默认 7",
                "default": 7
            }
        }
    },
))

REGISTRY.register(ToolDef(
    name="obsidian_daily_read",
    toolset="obsidian",
    description="读取今日日记(自动识别 0.inbox/日记/Daily 目录)",
    handler=handle_daily_read,
    schema={"type": "object", "properties": {}},
))

REGISTRY.register(ToolDef(
    name="obsidian_daily_append",
    toolset="obsidian",
    description="追加内容到今日日记(自动创建日期文件)",
    handler=handle_daily_append,
    schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要追加的内容"}
        },
        "required": ["content"]
    },
))
