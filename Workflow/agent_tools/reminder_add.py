"""reminder_add - 写入 macOS 提醒事项(W2)。

通过 AppleScript 调系统 Reminders app。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import (  # noqa: E402
    applescript_escape,
    format_reminder_time,
)
from agent_tools.registry import REGISTRY, ToolDef


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    title = (args.get("title") or "").strip()
    if not title:
        return "error", "提醒标题不能为空", "提醒创建失败"

    try:
        due = datetime.fromisoformat(args.get("due", "")) if args.get("due") else datetime.now()
    except ValueError:
        return "error", f"提醒时间无效:{args.get('due', '')}", "提醒创建失败"

    list_name = applescript_escape((args.get("list") or "").strip())
    safe_title = applescript_escape(title)

    if list_name:
        list_block = f'set targetList to list "{list_name}"'
    else:
        list_block = "set targetList to default list"

    script = f'''
set dueDate to current date
set year of dueDate to {due.year}
set month of dueDate to {due.month}
set day of dueDate to {due.day}
set hours of dueDate to {due.hour}
set minutes of dueDate to {due.minute}
set seconds of dueDate to 0
tell application "Reminders"
    {list_block}
    tell targetList
        make new reminder with properties {{name:"{safe_title}", due date:dueDate}}
    end tell
    return name of targetList
end tell
'''.strip()

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            text=True, capture_output=True, timeout=15, check=False,
        )
    except subprocess.TimeoutExpired:
        return "error", "创建提醒超时,请检查「提醒事项」权限", "提醒创建失败"

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "未知错误").strip()
        return "error", f"抱歉,提醒没建成功:{message}", "提醒创建失败"

    when = format_reminder_time(due)
    body = f"好的,已新建提醒:**{title}**({when})"
    return "success", body, "已新建提醒"


REGISTRY.register(ToolDef(
    name="reminder_add",
    toolset="reminder",
    description="在 macOS 提醒事项里新建一条提醒(due 用 ISO 本地时间)",
    handler=handle,
    schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "提醒标题"},
            "due": {
                "type": "string",
                "description": "提醒时间(ISO 格式,如 2026-06-19T09:30:00,缺省=现在)"
            },
            "list": {"type": "string", "description": "目标提醒列表名(可选,默认 default list)"}
        },
        "required": ["title"]
    },
))
