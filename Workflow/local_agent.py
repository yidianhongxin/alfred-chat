#!/usr/bin/env python3
"""Local agent harness for Alfred Chat.

Alfred provides the UI. This script provides a small, conservative tool layer:
file operations, batch desktop tools, Obsidian search, tasks, memory, action
logging/undo, and a tiny shell whitelist.
"""

from __future__ import annotations

import json
import os
import random
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


WORKFLOW_DIR = Path(__file__).resolve().parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

HOME = Path("/Users/DRLer").resolve()
DESKTOP = HOME / "Desktop"
DEFAULT_OBSIDIAN = HOME / "Obsidian_250614"
MAX_READ_CHARS = 6000
MAX_LIST_ITEMS = 40
MAX_PATH_CHARS = 512

SKILLIFY_RE = re.compile(
    r"(?:^/skillify\b|"
    r"(?:生成|创建|提炼|固化|写成|整理成|做成|转成|转化为).*(?:skill|skills|Skill|技能)|"
    r"(?:skill|skills|Skill|技能).*(?:生成|创建|提炼|固化|写成|整理成|做成))",
    re.I,
)


@dataclass
class Action:
    type: str
    path: str = ""
    content: str = ""
    old_text: str = ""
    new_text: str = ""
    dest: str = ""
    ext: str = ""
    term: str = ""
    command: str = ""
    task_text: str = ""
    task_id: int = 0
    count: int = 0
    reminder_title: str = ""
    reminder_due_iso: str = ""
    reminder_list: str = ""
    key: str = ""
    value: str = ""
    note: str = ""
    memory_target: str = "user"


def json_result(**kwargs: Any) -> None:
    print(json.dumps(kwargs, ensure_ascii=False))


def data_dir() -> Path:
    path = Path(os.environ.get("alfred_workflow_data") or os.environ.get("ALFRED_WORKFLOW_DATA") or "/tmp/alfred-chat")
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = Path(os.environ.get("alfred_workflow_cache") or os.environ.get("ALFRED_WORKFLOW_CACHE") or "/tmp")
    path.mkdir(parents=True, exist_ok=True)
    return path


def pending_path() -> Path:
    return cache_dir() / "pending_action.json"


# [W9 continuation] 用户说"go on" / "继续"时,chat 读这个文件,
# 把 last_query + last_assistant_partial 拼成新一轮 user message 再调 LLM。
# 这是 Hermes _get_continuation_prompt 模式在 Alfred 上的本地实现
# (Alfred 单轮流式 → 用文件持久化跨 rerun 状态)。
def continuation_path() -> Path:
    return data_dir() / "pending_continuation.json"


def load_continuation() -> Optional[Dict[str, Any]]:
    """读 pending continuation;不存在/过期/损坏返回 None。"""
    p = continuation_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    expires_at = data.get("expires_at")
    if expires_at:
        try:
            if datetime.now() > datetime.fromisoformat(expires_at):
                p.unlink(missing_ok=True)
                return None
        except (ValueError, TypeError):
            pass
    return data


def save_continuation(last_query: str, last_assistant_partial: str, ttl_minutes: int = 30) -> None:
    """存 pending continuation,默认 30 分钟过期。"""
    p = continuation_path()
    expires = datetime.now() + timedelta(minutes=ttl_minutes)
    data = {
        "last_query": last_query,
        "last_assistant_partial": last_assistant_partial,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "expires_at": expires.isoformat(timespec="seconds"),
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_continuation() -> None:
    continuation_path().unlink(missing_ok=True)


def action_log_path() -> Path:
    return data_dir() / "action_log.jsonl"


def tasks_path() -> Path:
    return data_dir() / "tasks.json"


def memory_path() -> Path:
    return data_dir() / "memory.json"


def memories_dir() -> Path:
    path = data_dir() / "memories"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_allowed_toolsets():
    """读 enabled_toolsets 环境变量,返回 set 或 None(=全启用)。

    支持预设:all / read_only / 逗号分隔的 toolset 名。
    """
    raw = os.environ.get("enabled_toolsets", "").strip()
    if not raw or raw == "all":
        return None
    if raw == "read_only":
        return {"file", "obsidian", "memory", "search", "task"}  # read-only filter is loose; specific filtering in handler
    return {item.strip() for item in raw.split(",") if item.strip()}


def get_memory_store():
    from memory_store import MemoryStore

    return MemoryStore(data_dir())


def save_pending(action: Action) -> None:
    pending_path().write_text(json.dumps(asdict(action), ensure_ascii=False), encoding="utf-8")


def load_pending() -> Optional[Action]:
    path = pending_path()
    if not path.exists():
        return None
    try:
        return Action(**json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        path.unlink(missing_ok=True)
        return None


def clear_pending() -> None:
    pending_path().unlink(missing_ok=True)


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_path_hint(raw: str) -> str:
    text = raw.strip().strip("\"'").removeprefix("@").strip()
    text = re.sub(r"^\./", "", text)
    text = re.sub(r"^~/", f"{HOME}/", text)
    text = re.sub(r"^[在到于]?桌面(?:上)?(?:新建|创建|写入|删除|移除|读取|查看|移动)?(?:文件)?[/\\\s]*", "Desktop/", text, flags=re.I)
    return text.strip()


def is_bare_relative_path(raw: str) -> bool:
    text = normalize_path_hint(raw)
    return bool(text) and not text.startswith("/") and "/" not in text and "\\" not in text


def resolve_path(raw: str, prefer_desktop_for_file: bool = True) -> Path:
    text = normalize_path_hint(raw)
    if not text:
        return HOME
    if prefer_desktop_for_file and is_bare_relative_path(text):
        desktop_candidate = (DESKTOP / text).resolve()
        if desktop_candidate.exists() or "." in text:
            return desktop_candidate
    if text.startswith("/"):
        return Path(text).expanduser().resolve()
    return (HOME / text).resolve()


def allowed(path: Path) -> bool:
    return path == HOME or HOME in path.parents


def looks_like_skillify_request(text: str) -> bool:
    return bool(SKILLIFY_RE.search((text or "").strip()))


def is_plausible_path(candidate: str) -> bool:
    text = (candidate or "").strip()
    if not text or len(text) > MAX_PATH_CHARS:
        return False
    if "\n" in text or "\r" in text:
        return False
    if re.search(r"\s{2,}", text):
        return False
    if len(text) > 120 and "/" not in text and "\\" not in text:
        return False
    return True


def obsidian_path_error(candidate: str) -> Optional[str]:
    if is_plausible_path(candidate):
        return None
    return "路径无效：请提供 OB 内相对路径（如 0.wiki资料/概念名.md），不要把整段正文当路径"


def has_path_hint(candidate: str) -> bool:
    text = candidate.strip()
    if not is_plausible_path(text):
        return False
    if re.search(r"(如何|怎么|为什么|方法|教程|吗|？|\?)", text):
        return False
    return bool(
        re.search(r"^@|^/|^~|[/\\]|桌面", text, re.I)
        or re.search(r"(^|[\s/\\])\.env($|\s)", text, re.I)
        or re.search(r"\.[A-Za-z0-9]{1,8}$", text)
    )


def strip_target_path_noise(raw: str) -> str:
    text = raw.strip().strip("\"'").removeprefix("@").strip()
    text = re.sub(r"^(?:一篇|一个|一份|到)\s*", "", text)
    text = re.sub(r"^\./", "", text)
    return text.strip()


def looks_like_obsidian_relative_path(raw: str) -> bool:
    text = strip_target_path_noise(raw)
    if not text or not is_plausible_path(text):
        return False
    if text.startswith(str(HOME)) or text.startswith("/Users"):
        return False
    if re.search(r"(?:^|[/\\])(?:0\.inbox|10\.DL日记)(?:[/\\]|$)", text, re.I):
        return True
    if re.match(r"^\d+\.[\w\u4e00-\u9fa5]", text):
        return True
    if re.match(r"^(?:OB|Obsidian)/", text, re.I):
        return True
    root = obsidian_root()
    vault = root.name
    if text == vault or text.startswith(f"{vault}/") or f"/{vault}/" in text:
        return True
    if text.startswith("/"):
        try:
            Path(text).resolve().relative_to(root)
            return True
        except ValueError:
            return False
    return False


def format_paths(paths: Iterable[Path], base: Optional[Path] = None) -> str:
    lines = []
    for path in list(paths)[:MAX_LIST_ITEMS]:
        try:
            display = path.relative_to(base or HOME)
        except ValueError:
            display = path
        lines.append(f"- {display}")
    return "\n".join(lines) if lines else "未找到匹配文件"


def snapshot_file(path: Path) -> Dict[str, Any]:
    if path.exists() and path.is_file():
        try:
            return {"exists": True, "content": path.read_text(encoding="utf-8")}
        except UnicodeDecodeError:
            return {"exists": True, "binary": True}
    return {"exists": False}


def log_action(action: Action, target: Optional[Path], before: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": asdict(action),
        "target": str(target) if target else "",
        "before": before,
        "extra": extra or {},
    }
    with action_log_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_last_log() -> Optional[Dict[str, Any]]:
    path = action_log_path()
    if not path.exists():
        return None
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except Exception:
        return None


def response(status: str, assistant_text: str, footer: Optional[str] = None, **extra: Any) -> None:
    json_result(handled=True, status=status, assistant_text=assistant_text, footer=footer or assistant_text, **extra)


def looks_like_local_file_command(text: str) -> bool:
    file_hint = r"([/\\]|(^|[\s/\\])\.env($|\s)|\.[A-Za-z0-9]{1,8}($|\s))"
    return bool(
        re.search(r"^确认执行$|^(取消|取消执行)$|^(撤销上一步|undo last)$", text, re.I)
        or re.search(r"^@/|^/Users/DRLer/", text, re.I)
        or re.search(r"桌面(?:上)?(?:新建|创建|写入|追加|附加|替换|删除|移除|读取|查看|列出|整理|移动)", text, re.I)
        or re.search(r"(?:新建|创建|写入|追加|附加|替换|删除|移除|读取|查看|列出|整理|移动)(?:到)?桌面", text, re.I)
        or re.search(rf"(创建|新建|写入|追加|附加|替换|删除|移除|读取|查看).*{file_hint}", text, re.I)
        or re.search(rf"{file_hint}.*(内容|正文)[:：]", text, re.I)
        or re.search(r"^(列出|新增|完成)任务|^(你)?记住|^列出记忆|(?:查看|列出|读取|显示)?灵魂|(?:写入|更新|设定|追加)灵魂|搜索(?:OB|Obsidian|ob)|(?:OB|Obsidian|ob)库|(?:0\.inbox|inbox).*(?:文章|文件|笔记)|(?:今天|今日)日记|(?:近|最近)\s*\d*\s*(?:天|篇)?日记|(?:翻阅|回顾|随便读|随机读).*(?:日记|OB|Obsidian|ob)|(?:读|读取|查看).*(?:OB|Obsidian|ob).*(?:今天|今日)日记|运行命令[:：]|提醒", text, re.I)
    )


def day_offset_from_token(token: Optional[str]) -> int:
    if not token:
        return 0
    if token in {"今天", "今日"}:
        return 0
    if token == "明天":
        return 1
    if token == "后天":
        return 2
    return 0


def apply_day_period(hour: int, period: Optional[str]) -> int:
    if not period:
        return hour
    if period in {"下午", "晚上", "晚间"} and hour < 12:
        return hour + 12
    if period == "中午" and hour < 12:
        return 12
    return hour


def build_reminder_due(day_token: Optional[str], period: Optional[str], hour: int, minute: int) -> datetime:
    now = datetime.now().replace(second=0, microsecond=0)
    due = now.replace(hour=apply_day_period(hour, period), minute=minute)
    due += timedelta(days=day_offset_from_token(day_token))
    if day_offset_from_token(day_token) == 0 and due <= now:
        due += timedelta(days=1)
    return due


def parse_reminder_intent(text: str) -> Optional[Action]:
    raw = text.strip()
    if not raw or "提醒" not in raw:
        return None

    patterns = [
        re.compile(
            r"^(?:(明天|后天|今天|今日)\s*)?(早上|上午|中午|下午|晚上|晚间)?\s*(\d{1,2})\s*[点:：]\s*(\d{1,2}|半)?\s*(?:分)?\s*(?:提醒我|提醒)\s*(.+)$",
            re.I,
        ),
        re.compile(
            r"^提醒(?:我)?(?:在)?\s*(?:(明天|后天|今天|今日)\s*)?(早上|上午|中午|下午|晚上|晚间)?\s*(\d{1,2})\s*[点:：]\s*(\d{1,2}|半)?\s*(?:分)?\s*(.+)$",
            re.I,
        ),
        re.compile(
            r"^(?:(明天|后天|今天|今日)\s*)?(早上|上午|中午|下午|晚上|晚间)?\s*(\d{1,2})\s*[点:：]\s*(\d{1,2}|半)?\s*(?:分)?\s*(.+?)(?:的)?提醒$",
            re.I,
        ),
        re.compile(
            r"^(\d{1,2})\s*[：:]\s*(\d{2})\s*(?:提醒我|提醒)?\s*(.+)$",
            re.I,
        ),
    ]

    for index, pattern in enumerate(patterns):
        match = pattern.match(raw)
        if not match:
            continue

        if index == 3:
            hour = int(match.group(1))
            minute = int(match.group(2))
            title = match.group(3).strip()
            due = build_reminder_due(None, None, hour, minute)
        else:
            day_token = match.group(1)
            period = match.group(2)
            hour = int(match.group(3))
            minute_token = match.group(4)
            minute = 30 if minute_token == "半" else int(minute_token or 0)
            title = match.group(5).strip()
            due = build_reminder_due(day_token, period, hour, minute)

        title = re.sub(r"^[：:，,\s]+", "", title)
        title = re.sub(r"[。！!？?]+$", "", title).strip()
        if not title:
            return None

        return Action(
            "reminder_add",
            reminder_title=title,
            reminder_due_iso=due.isoformat(timespec="seconds"),
        )

    return None


def parse_small_count(raw: str, default: int = 3) -> int:
    if not raw:
        return default
    raw = raw.strip()
    digits = re.search(r"\d+", raw)
    if digits:
        return max(1, min(int(digits.group(0)), 20))
    chinese_numbers = {
        "一": 1,
        "两": 2,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return chinese_numbers.get(raw, default)


def parse_obsidian_list_path(text: str) -> Optional[str]:
    if not re.search(r"(?:列出|查看)", text) or not re.search(r"(?:文章|文件|笔记)", text):
        return None
    if not re.search(r"(?:OB|Obsidian|ob|0\.inbox|inbox|/)", text, re.I):
        return None

    cleaned = re.sub(r"^(?:列出|查看)\s*(?:OB|Obsidian|ob)?(?:库)?\s*", "", text, flags=re.I)
    cleaned = re.sub(r"(?:里的|里|下|中|中的)?(?:所有)?(?:文章|文件|笔记)$", "", cleaned, flags=re.I)
    cleaned = cleaned.strip()
    return cleaned or "0.inbox"


def applescript_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def format_reminder_time(due: datetime) -> str:
    return f"{due.month}月{due.day}日 {due.hour:02d}:{due.minute:02d}"


def execute_reminder(action: Action) -> Tuple[str, str, str]:
    title = (action.reminder_title or "").strip()
    if not title:
        return "error", "提醒标题不能为空", "提醒创建失败"

    try:
        due = datetime.fromisoformat(action.reminder_due_iso) if action.reminder_due_iso else datetime.now()
    except ValueError:
        return "error", f"提醒时间无效：{action.reminder_due_iso}", "提醒创建失败"

    list_name = applescript_escape((action.reminder_list or "").strip())
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
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "error", "创建提醒超时，请检查「提醒事项」权限", "提醒创建失败"

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "未知错误").strip()
        return "error", f"抱歉，提醒没建成功：{message}", "提醒创建失败"

    when = format_reminder_time(due)
    body = f"好的，已新建提醒：**{title}**（{when}）"
    return "success", body, "已新建提醒"


def parse_intent(query: str) -> Optional[Action]:
    text = query.strip()
    if not text:
        return None

    if re.match(r"^(撤销上一步|undo last)$", text, re.I):
        return Action("undo")

    if looks_like_skillify_request(text):
        return Action("skillify", note=text)

    match = re.match(r"^列出任务$", text)
    if match:
        return Action("task_list")
    match = re.match(r"^新增任务[:：]\s*(.+)$", text)
    if match:
        return Action("task_add", task_text=match.group(1).strip())
    match = re.match(r"^完成任务\s*(\d+)$", text)
    if match:
        return Action("task_done", task_id=int(match.group(1)))

    match = re.match(r"^(?:你)?记住(?:以下内容|一下|这些)?[:：]\s*([\s\S]+)$", text)
    if match:
        return Action("memory_append", note=match.group(1).strip())

    match = re.match(r"^(?:你)?记住\s*(.+?)\s*(?:是|=|指向)\s*(.+)$", text)
    if match:
        return Action("memory_set", key=match.group(1).strip(" “”\"'"), value=match.group(2).strip())
    if re.match(r"^列出记忆$", text):
        return Action("memory_list")

    if re.match(r"^(?:查看|列出|读取|显示)?灵魂$", text, re.I):
        return Action("soul_read")
    match = re.match(r"^(?:写入|更新|设定)灵魂\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text, re.I)
    if match:
        return Action("soul_write", content=match.group(1).strip())
    match = re.match(r"^追加灵魂\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text, re.I)
    if match:
        return Action("soul_append", content=match.group(1).strip())

    match = re.match(r"^(?:搜索|查找)(?:对话|聊天记录|历史)[:：]?\s*(.+)$", text, re.I)
    if match:
        return Action("session_search", term=match.group(1).strip())
    match = re.search(r"(?:上次|之前|earlier).*(?:讨论|聊|说过|提到).*(.+?)(?:吗|？|\?|$)", text, re.I)
    if match:
        return Action("session_search", term=match.group(1).strip("「」\"' "))

    if re.search(r"(?:能|可以).*(?:读|读取|访问|打开).*(?:OB|Obsidian|ob)库", text, re.I) or re.search(r"(?:OB|Obsidian|ob)库.*(?:能读|能访问|状态)", text, re.I):
        return Action("obsidian_status")

    match = re.search(r"(?:读|读取|查看|翻阅|回顾|总结).*(?:近|最近)\s*([一二两三四五六七八九十\d]+)?\s*(?:天|篇)?日记", text, re.I)
    if match:
        return Action("obsidian_diary_recent", count=parse_small_count(match.group(1), default=7))

    if re.search(r"(?:翻阅|回顾|随便读|随机读|看看以前).*(?:日记|OB|Obsidian|ob)", text, re.I):
        return Action("obsidian_diary_browse", count=1 if "随机" not in text else -1)

    match = re.match(r"^(?:写入|新建|创建)(?:到)?(?:OB|Obsidian|ob)(?:库)?\s+(.+?)\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text, re.I)
    if match:
        return Action("obsidian_write", path=match.group(1).strip(), content=match.group(2))

    match = re.match(
        r"^(?:写入|新建|创建)(?:一篇|一个|一份|到)?(?:文件)?\s*(.+?)\s*(?:内容|正文)[:：]\s*([\s\S]+)$",
        text,
        re.I,
    )
    if match:
        path = strip_target_path_noise(match.group(1))
        if looks_like_obsidian_relative_path(path):
            return Action("obsidian_write", path=path, content=match.group(2))

    match = re.match(r"^(?:写入|新建|创建)(?:一篇|一个|一份|到)?(?:文件)?\s*(.+)$", text, re.I)
    if match:
        path = strip_target_path_noise(match.group(1))
        if looks_like_obsidian_relative_path(path) and has_path_hint(path):
            return Action("obsidian_write", path=path, content="")

    match = re.match(r"^(?:追加|附加)(?:到)?(?:OB|Obsidian|ob)(?:库)?\s+(.+?)\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text, re.I)
    if match:
        return Action("obsidian_append", path=match.group(1).strip(), content=match.group(2))

    # [W8] 写 X 笔记/内容 到 0.inbox/Y.md (动词+标题提示+目的路径)
    match = re.match(r"^写(?:一篇|个|份)?(.+?)(?:笔记|文章|内容)?(?:到|进|入|至)\s*(0\.inbox/[^\s？?。]+\.md)$", text, re.I)
    if match:
        return Action("obsidian_write", path=match.group(2).strip(), content="")

    # [W8] 0.inbox/xxx.md 单独出现 + 动词 (写/存/放/录/塞)
    match = re.match(r"^(?:写|存|放|录|塞|新建|创建|写入)\s+(0\.inbox/[^\s？?。]+\.md)$", text, re.I)
    if match:
        return Action("obsidian_write", path=match.group(1).strip(), content="")

    # [W8] 简单 OB 写入 (无内容 — 让 LLM fallback 补充)
    match = re.match(r"^(?:写|存|放|录|塞|新建|创建|写入)(?:一篇|一个|一份|到|进|给)?\s*(?:OB|Obsidian|ob|笔记)(?:库|文件)?\s*$", text, re.I)
    if match:
        # 路径缺失,让 chat 端 LLM 引导用户补路径
        return Action("obsidian_status")  # 触发"OB 库状态"提示作为兜底
    # [W8] 写/存/放 OB path.md (动词+OB+path 紧凑写法)
    match = re.match(r"^(?:写|存|放|录|塞|新建|创建|写入)(?:一篇|一个|一份)?\s*(?:OB|Obsidian|ob|到OB|到Obsidian|到ob)\s+(\S+\.md)\s*$", text, re.I)
    if match:
        return Action("obsidian_write", path=match.group(1).strip(), content="")
    # [W8] 把/将 对话 X 存到 OB 0.inbox/xxx.md (口语化) - 用单一 capture group
    match = re.search(r"((?:0\.inbox|10\.DL|2\.AI-Garden|3\.wiki)/[^\s？?。]+\.md)", text, re.I)
    if match and re.search(r"(?:存|放|录|塞|写入|写)", text):
        return Action("obsidian_write", path=match.group(1).strip(), content="")

    obsidian_list_path = parse_obsidian_list_path(text)
    if obsidian_list_path:
        return Action("obsidian_list", path=obsidian_list_path)

    match = re.match(r"^(?:读|读取|查看|打开)(?:OB|Obsidian|ob)(?:库)?\s+(.+)$", text, re.I)
    if match:
        return Action("obsidian_read", path=match.group(1).strip())

    reminder = parse_reminder_intent(text)
    if reminder:
        return reminder

    match = re.match(r"^运行命令[:：]\s*(.+)$", text)
    if match:
        return Action("shell", command=match.group(1).strip())

    match = re.match(r"^(?:列出|查看)(?:桌面)?(?:所有)?\s*([A-Za-z0-9]+)?\s*(?:文件)?$", text)
    if match and ("桌面" in text or match.group(1)):
        ext = (match.group(1) or "").strip(".")
        return Action("list_dir", path="Desktop", ext=ext)

    match = re.match(r"^把?桌面(?:所有)?([A-Za-z0-9]+)(?:文件)?(?:移动|整理)到\s*(.+)$", text)
    if match:
        return Action("move_ext", path="Desktop", ext=match.group(1).strip("."), dest=match.group(2).strip())

    match = re.match(r"^(?:读取|查看)(?:文件)?\s*(.+)$", text)
    if match and has_path_hint(match.group(1)):
        return Action("read", path=match.group(1).strip())

    match = re.match(r"^(?:总结文件|总结)\s*(.+)$", text)
    if match and has_path_hint(match.group(1)):
        return Action("read", path=match.group(1).strip())

    match = re.match(r"^搜索(?:OB|Obsidian|ob)(?:里)?(?:关于)?\s*(.+?)(?:\s*的笔记)?$", text, re.I)
    if match:
        return Action("obsidian_search", term=match.group(1).strip())

    if re.search(r"(?:读|读取|查看).*(?:OB|Obsidian|ob).*(?:今天|今日)日记", text, re.I) or re.match(r"^(?:读|读取|查看)?(?:今天|今日)日记$", text):
        return Action("obsidian_daily_read")

    match = re.match(r"^(?:追加到)?(?:今天|今日)日记\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text)
    if match:
        return Action("obsidian_daily_append", content=match.group(1))

    match = re.match(r"^@?([/~.\w\-\u4e00-\u9fa5][^:：]*?)\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text, re.I)
    if match and re.search(r"[/\\.]|桌面", match.group(1)):
        return Action("write", match.group(1).strip(), content=match.group(2))

    match = re.match(r"^(?:创建|新建|写入)(?:一篇|一个|一份|到)?(?:文件)?\s*(.+?)\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text, re.I)
    if match and has_path_hint(match.group(1)):
        path = strip_target_path_noise(match.group(1))
        if looks_like_obsidian_relative_path(path):
            return Action("obsidian_write", path=path, content=match.group(2))
        return Action("write", path, content=match.group(2))

    match = re.match(r"^(?:追加|附加)(?:到文件)?\s*(.+?)\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text, re.I)
    if match and has_path_hint(match.group(1)):
        return Action("append", match.group(1).strip(), content=match.group(2))

    match = re.match(r"^替换(?:文件)?\s+(.+?)\s+中\s+([\s\S]+?)\s+为\s+([\s\S]+)$", text, re.I)
    if match and has_path_hint(match.group(1)):
        return Action("replace", match.group(1).strip(), old_text=match.group(2), new_text=match.group(3))

    match = re.match(r"^(?:删除|移除)(?:文件)?\s*(.+)$", text, re.I)
    if match and has_path_hint(match.group(1)):
        return Action("delete", match.group(1).strip())

    match = re.match(r"^(?:在)?桌面(?:上)?(?:删除|移除)(?:文件)?\s*(.+)$", text, re.I)
    if match:
        return Action("delete", f"Desktop/{match.group(1).strip()}")

    match = re.match(r"^(?:在)?桌面(?:上)?(?:新建|创建|写入)(?:文件)?\s*(.+)$", text, re.I)
    if match:
        return Action("write", f"Desktop/{match.group(1).strip()}")

    match = re.match(r"^(?:新建|创建|写入)(?:一篇|一个|一份|到)?(?:文件)?\s*(.+)$", text, re.I)
    if match and has_path_hint(match.group(1)):
        path = strip_target_path_noise(match.group(1))
        if looks_like_obsidian_relative_path(path):
            return Action("obsidian_write", path=path, content="")
        return Action("write", path)

    return None


def execute_file_action(action: Action) -> Tuple[str, str, str]:
    target = resolve_path(action.path)
    if not allowed(target):
        return "error", "只允许操作 /Users/DRLer 目录内文件", "只允许操作 /Users/DRLer 目录内文件"

    if action.type == "write":
        before = snapshot_file(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(action.content, encoding="utf-8")
        log_action(action, target, before)
        return "success", f"已新建完成：{target}", f"已新建完成：{target}"

    if action.type == "append":
        before = snapshot_file(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(f"{original}{action.content}", encoding="utf-8")
        log_action(action, target, before)
        return "success", f"已追加完成：{target}", f"已追加完成：{target}"

    if action.type == "replace":
        if not target.exists():
            return "error", f"文件不存在：{target}", f"文件不存在：{target}"
        before = snapshot_file(target)
        original = target.read_text(encoding="utf-8")
        if action.old_text not in original:
            return "error", "未找到要替换的原文", "未找到要替换的原文"
        target.write_text(original.replace(action.old_text, action.new_text), encoding="utf-8")
        log_action(action, target, before)
        return "success", f"已替换完成：{target}", f"已替换完成：{target}"

    if action.type == "delete":
        if not target.exists():
            return "error", f"文件不存在：{target}", f"文件不存在：{target}"
        before = snapshot_file(target)
        target.unlink()
        log_action(action, target, before)
        return "success", f"已删除完成：{target}", f"已删除完成：{target}"

    return "error", "未识别本地文件操作", "未识别本地文件操作"


def execute_list_dir(action: Action) -> Tuple[str, str, str]:
    root = resolve_path(action.path or "Desktop")
    if not allowed(root) or not root.is_dir():
        return "error", f"目录不存在或无权限：{root}", f"目录不可用：{root}"
    ext = action.ext.strip(".")
    files = [p for p in sorted(root.iterdir()) if p.is_file() and (not ext or p.suffix.lower() == f".{ext.lower()}")]
    title = f"{root} 下的 {ext or ''} 文件".strip()
    return "success", f"{title}：\n\n{format_paths(files, root)}", f"已列出 {len(files)} 个文件"


def execute_move_ext(action: Action) -> Tuple[str, str, str]:
    source = resolve_path(action.path or "Desktop")
    dest = resolve_path(action.dest)
    if not allowed(source) or not allowed(dest) or not source.is_dir():
        return "error", "源目录或目标目录不可用", "移动失败"
    ext = action.ext.strip(".").lower()
    files = [p for p in sorted(source.iterdir()) if p.is_file() and p.suffix.lower() == f".{ext}"]
    if not files:
        return "success", f"未找到桌面上的 .{ext} 文件", "没有可移动文件"
    plan = "\n".join(f"- {p.name} -> {dest / p.name}" for p in files[:MAX_LIST_ITEMS])
    save_pending(action)
    return "needs_confirmation", f"将移动 {len(files)} 个文件到 {dest}：\n\n{plan}\n\n输入“确认执行”继续，输入“取消”放弃。", f"移动 {len(files)} 个 .{ext} 文件待确认"


def execute_move_ext_confirmed(action: Action) -> Tuple[str, str, str]:
    source = resolve_path(action.path or "Desktop")
    dest = resolve_path(action.dest)
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    ext = action.ext.strip(".").lower()
    for src in sorted(source.iterdir()):
        if not src.is_file() or src.suffix.lower() != f".{ext}":
            continue
        dst = dest / src.name
        counter = 2
        while dst.exists():
            dst = dest / f"{src.stem}-{counter}{src.suffix}"
            counter += 1
        src.rename(dst)
        moved.append({"from": str(src), "to": str(dst)})
    log_action(action, dest, extra={"moved": moved})
    return "success", f"已移动 {len(moved)} 个 .{ext} 文件到 {dest}", f"已移动 {len(moved)} 个文件"


def execute_read(action: Action) -> Tuple[str, str, str]:
    target = resolve_path(action.path)
    if not allowed(target) or not target.exists() or not target.is_file():
        return "error", f"文件不存在或无权限：{target}", "读取失败"
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "error", f"无法读取二进制文件：{target}", "读取失败（二进制文件）"
    truncated = content[:MAX_READ_CHARS]
    suffix = "\n\n[内容过长，已截断]" if len(content) > MAX_READ_CHARS else ""
    return "success", f"{target} 内容：\n\n```text\n{truncated}\n```{suffix}", f"已读取 {target.name}"


def obsidian_root() -> Path:
    return Path(os.environ.get("obsidian_vault_path") or DEFAULT_OBSIDIAN).resolve()


def obsidian_allowed(path: Path, root: Path) -> bool:
    return allowed(path) and (path == root or root in path.parents)


def resolve_obsidian_path(raw: str, root: Path) -> Path:
    text = strip_target_path_noise(raw)
    if text.startswith(str(root)):
        return Path(text).resolve()
    if text.startswith("/"):
        return Path(text).resolve()
    return (root / text.lstrip("/")).resolve()


def diary_date_key(path: Path) -> Tuple[str, float, str]:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", path.stem)
    date = match.group(1) if match else ""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0
    return date, mtime, str(path)


def diary_files(root: Path) -> List[Path]:
    common_roots = [
        root / "10.DL日记",
        root / "日记",
        root / "Daily",
        root / "daily",
        root,
    ]
    seen = set()
    result: List[Path] = []
    for diary_root in common_roots:
        if not diary_root.exists():
            continue
        for path in diary_root.rglob("*.md"):
            if path in seen:
                continue
            if re.match(r"\d{4}-\d{2}-\d{2}(?:-\d+)?$", path.stem):
                seen.add(path)
                result.append(path)
    return sorted(result, key=diary_date_key, reverse=True)


def read_markdown_excerpt(path: Path, max_chars: int = MAX_READ_CHARS) -> str:
    content = path.read_text(encoding="utf-8")
    excerpt = content[:max_chars]
    if len(content) > max_chars:
        excerpt += "\n\n[内容过长，已截断]"
    return excerpt


def execute_obsidian_status() -> Tuple[str, str, str]:
    root = obsidian_root()
    if not obsidian_allowed(root, root):
        return "error", f"Obsidian 库超出允许范围：{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在：{root}", "OB 库不存在"
    note_count = sum(1 for _ in root.rglob("*.md"))
    diaries = diary_files(root)
    latest = diaries[0].relative_to(root) if diaries else "未找到日记"
    body = f"能读到 OB 库：{root}\n\n- Markdown 笔记：{note_count} 篇\n- 日记：{len(diaries)} 篇日记\n- 最新日记：{latest}\n\n你可以说：`翻阅一下日记`、`读下最近7天日记`、`写入OB 0.inbox/test.md 内容：...`。"
    return "success", body, "OB 库可读取"


def execute_obsidian_search(action: Action) -> Tuple[str, str, str]:
    root = obsidian_root()
    if not allowed(root):
        return "error", f"Obsidian 库超出允许范围：{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在：{root}", "OB 库不存在"
    term = action.term
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
    return "success", f"OB 中关于「{term}」的笔记：\n\n{format_paths(matches, root)}", f"找到 {len(matches)} 条 OB 匹配"


def execute_obsidian_read(action: Action) -> Tuple[str, str, str]:
    root = obsidian_root()
    target = resolve_obsidian_path(action.path, root)
    if not obsidian_allowed(target, root):
        return "error", "只允许读取 OB 库内文件", "读取失败"
    if not target.exists() or not target.is_file():
        return "error", f"OB 文件不存在：{target.relative_to(root) if root in target.parents else target}", "读取失败"
    try:
        excerpt = read_markdown_excerpt(target)
    except UnicodeDecodeError:
        return "error", f"无法读取二进制文件：{target}", "读取失败"
    return "success", f"OB 文件 {target.relative_to(root)}：\n\n```text\n{excerpt}\n```", f"已读取 OB：{target.name}"


def execute_obsidian_list(action: Action) -> Tuple[str, str, str]:
    root = obsidian_root()
    target = resolve_obsidian_path(action.path or "0.inbox", root)
    if not obsidian_allowed(target, root):
        return "error", "只允许列出 OB 库内目录", "列出失败"
    if not target.exists() or not target.is_dir():
        return "error", f"OB 目录不存在：{target.relative_to(root) if root in target.parents else target}", "列出失败"

    files = sorted(
        [path for path in target.iterdir() if path.is_file() and path.suffix.lower() == ".md"],
        key=lambda path: path.name.lower(),
    )
    rows = []
    for index, path in enumerate(files[:MAX_LIST_ITEMS], start=1):
        rel = path.relative_to(root)
        rows.append(f"{index}. {rel}")

    omitted = len(files) - len(rows)
    suffix = f"\n\n[还有 {omitted} 篇未显示]" if omitted > 0 else ""
    body = f"{target.relative_to(root)} 里文章：{len(files)} 篇\n\n" + ("\n".join(rows) if rows else "未找到 .md 文章") + suffix
    return "success", body, f"{target.relative_to(root)}：{len(files)} 篇"


def execute_obsidian_write(action: Action, append: bool = False) -> Tuple[str, str, str]:
    path_err = obsidian_path_error(action.path)
    if path_err:
        return "error", path_err, "写入失败"
    root = obsidian_root()
    target = resolve_obsidian_path(action.path, root)
    if target.suffix == "":
        target = target.with_suffix(".md")
    if not obsidian_allowed(target, root):
        return "error", "只允许写入 OB 库内文件", "写入失败"
    before = snapshot_file(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if append and target.exists():
        original = target.read_text(encoding="utf-8")
        target.write_text(f"{original.rstrip()}\n\n{action.content}\n", encoding="utf-8")
    else:
        target.write_text(action.content, encoding="utf-8")
    log_action(action, target, before)
    verb = "追加到" if append else "写入"
    return "success", f"已{verb} OB：{target.relative_to(root)}", f"已{verb} OB"


def execute_diary_browse(action: Action) -> Tuple[str, str, str]:
    root = obsidian_root()
    if not obsidian_allowed(root, root):
        return "error", f"Obsidian 库超出允许范围：{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在：{root}", "OB 库不存在"
    diaries = diary_files(root)
    if not diaries:
        return "error", f"未找到日记。已搜索 {root}", "未找到日记"
    target = random.choice(diaries) if action.count < 0 else diaries[0]
    excerpt = read_markdown_excerpt(target)
    return "success", f"翻到这篇日记：{target.relative_to(root)}\n\n```text\n{excerpt}\n```", f"已翻阅日记：{target.name}"


def execute_diary_recent(action: Action) -> Tuple[str, str, str]:
    root = obsidian_root()
    if not obsidian_allowed(root, root):
        return "error", f"Obsidian 库超出允许范围：{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在：{root}", "OB 库不存在"
    count = action.count or 7
    diaries = diary_files(root)[:count]
    if not diaries:
        return "error", f"未找到日记。已搜索 {root}", "未找到日记"
    sections = []
    per_file_limit = max(800, MAX_READ_CHARS // max(1, len(diaries)))
    for path in diaries:
        sections.append(f"## {path.relative_to(root)}\n\n```text\n{read_markdown_excerpt(path, per_file_limit)}\n```")
    return "success", f"最近 {len(diaries)} 篇日记：\n\n" + "\n\n".join(sections), f"已读取 {len(diaries)} 篇日记"


def execute_daily_append(action: Action) -> Tuple[str, str, str]:
    root = obsidian_root()
    target = root / "0.inbox" / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    if not allowed(target):
        return "error", "日记路径不在允许范围内", "追加失败"
    before = snapshot_file(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    original = target.read_text(encoding="utf-8") if target.exists() else f"# {datetime.now().strftime('%Y-%m-%d')}\n\n"
    target.write_text(f"{original.rstrip()}\n\n{action.content}\n", encoding="utf-8")
    log_action(action, target, before)
    return "success", f"已追加到今天日记：{target}", "已追加到今天日记"


def find_daily_note(root: Path) -> Optional[Path]:
    today = datetime.now().strftime("%Y-%m-%d")
    candidates = [
        root / "0.inbox" / f"{today}.md",
        root / f"{today}.md",
        root / "日记" / f"{today}.md",
        root / "Daily" / f"{today}.md",
        root / "daily" / f"{today}.md",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    for candidate in root.rglob(f"*{today}*.md"):
        if candidate.is_file():
            return candidate
    return None


def execute_daily_read() -> Tuple[str, str, str]:
    root = obsidian_root()
    if not allowed(root):
        return "error", f"Obsidian 库超出允许范围：{root}", "OB 库不在允许范围"
    if not root.exists():
        return "error", f"Obsidian 库不存在：{root}", "OB 库不存在"
    target = find_daily_note(root)
    if not target:
        today = datetime.now().strftime("%Y-%m-%d")
        return "error", f"未找到今天的日记：{today}。已搜索 {root}", "未找到今日日记"
    content = target.read_text(encoding="utf-8")
    truncated = content[:MAX_READ_CHARS]
    suffix = "\n\n[内容过长，已截断]" if len(content) > MAX_READ_CHARS else ""
    return "success", f"今日日记 {target}：\n\n```text\n{truncated}\n```{suffix}", f"已读取今日日记"


def execute_task(action: Action) -> Tuple[str, str, str]:
    tasks = load_json(tasks_path(), [])
    if action.type == "task_add":
        next_id = max([item.get("id", 0) for item in tasks], default=0) + 1
        tasks.append({"id": next_id, "text": action.task_text, "done": False, "created": datetime.now().isoformat(timespec="seconds")})
        save_json(tasks_path(), tasks)
        return "success", f"已新增任务 {next_id}：{action.task_text}", "已新增任务"
    if action.type == "task_done":
        for item in tasks:
            if item.get("id") == action.task_id:
                item["done"] = True
                save_json(tasks_path(), tasks)
                return "success", f"已完成任务 {action.task_id}：{item.get('text')}", "已完成任务"
        return "error", f"未找到任务 {action.task_id}", "任务不存在"
    lines = [f"{item['id']}. [{'x' if item.get('done') else ' '}] {item.get('text')}" for item in tasks]
    return "success", "当前任务：\n\n" + ("\n".join(lines) if lines else "暂无任务"), f"{len(tasks)} 个任务"


def execute_memory(action: Action) -> Tuple[str, str, str]:
    store = get_memory_store()
    target = (action.memory_target or action.key or "user").strip().lower()
    if target in {"memory", "mem", "notes"}:
        target = "memory"
    elif target in {"user", "profile"}:
        target = "user"
    else:
        target = "user"

    if action.type == "memory_add":
        ok, message = store.add(target, action.note or action.content, auto=action.value == "auto")
        status = "success" if ok else "error"
        return status, message, message

    if action.type == "memory_replace":
        ok, message = store.replace(target, action.old_text, action.new_text or action.content)
        status = "success" if ok else "error"
        return status, message, message

    if action.type == "memory_remove":
        ok, message = store.remove(target, action.old_text or action.note)
        status = "success" if ok else "error"
        return status, message, message

    if action.type == "memory_append":
        ok, message = store.add("memory", action.note)
        status = "success" if ok else "error"
        return status, message if ok else message, "已写入长期记忆" if ok else message

    if action.type == "memory_set":
        entry = f"{action.key}: {action.value}".strip(": ").strip()
        ok, message = store.add("user", entry)
        status = "success" if ok else "error"
        return status, message if ok else message, f"已记住：{action.key}" if ok else message

    body = store.list_formatted()
    entry_count = sum(len(store.load_entries(t)) for t in ("user", "memory"))
    return "success", f"记忆：\n\n{body}" if body else "记忆：\n\n暂无记忆", f"{entry_count} 条记忆"


def execute_shell(action: Action) -> Tuple[str, str, str]:
    allowed_commands = {"ls", "pwd", "mkdir"}
    try:
        parts = shlex.split(action.command)
    except ValueError as error:
        return "error", f"命令解析失败：{error}", "命令解析失败"
    if not parts or parts[0] not in allowed_commands:
        return "error", "只允许运行白名单命令：ls、pwd、mkdir", "命令不在白名单"
    for arg in parts[1:]:
        if arg.startswith("-"):
            continue
        path = resolve_path(arg)
        if not allowed(path):
            return "error", f"命令参数超出允许范围：{arg}", "命令被拒绝"
    result = subprocess.run(parts, cwd=str(HOME), text=True, capture_output=True, timeout=5)
    output = (result.stdout or result.stderr or "").strip()
    if len(output) > MAX_READ_CHARS:
        output = output[:MAX_READ_CHARS] + "\n...[输出过长，已截断]"
    if result.returncode != 0:
        return "error", f"命令失败：\n\n```text\n{output}\n```", "命令失败"
    return "success", f"命令输出：\n\n```text\n{output or 'done'}\n```", "命令已完成"


def execute_session_search(action: Action) -> Tuple[str, str, str]:
    from session_index import format_search_results, search_sessions

    term = action.term.strip()
    if not term:
        return "error", "请提供搜索关键词", "搜索失败"
    results = search_sessions(term)
    body = format_search_results(term, results)
    return "success", body, f"找到 {len(results)} 条"


def soul_override() -> Optional[str]:
    value = os.environ.get("soul_file_path", "").strip()
    return value or None


def execute_soul(action: Action) -> Tuple[str, str, str]:
    from soul_store import ensure_soul, read_soul, soul_path, write_soul

    override = soul_override()
    root = data_dir()
    assistant = os.environ.get("chat_assistant_label") or "Assistant"
    ensure_soul(root, assistant, override)

    if action.type == "soul_read":
        content = read_soul(root, override)
        path = soul_path(root, override)
        if not content:
            return "success", "灵魂文件为空，可以说「设定灵魂 内容：...」来写入。", "灵魂为空"
        return "success", f"灵魂（{path}）：\n\n```markdown\n{content}\n```", "已读取灵魂"

    if action.type == "soul_write":
        ok, message = write_soul(root, action.content, append=False, override=override)
        status = "success" if ok else "error"
        return status, message, message

    if action.type == "soul_append":
        ok, message = write_soul(root, action.content, append=True, override=override)
        status = "success" if ok else "error"
        return status, message, message

    return "error", "未知灵魂操作", "灵魂操作失败"


def execute_undo() -> Tuple[str, str, str]:
    record = read_last_log()
    if not record:
        return "error", "没有可撤销的操作", "没有可撤销操作"
    action = Action(**record["action"])
    target = Path(record.get("target") or "").resolve()
    if target and not allowed(target):
        return "error", "日志记录路径不在允许范围，拒绝撤销", "撤销失败"
    before = record.get("before") or {}
    extra = record.get("extra") or {}
    if action.type in {"write", "append", "replace", "obsidian_daily_append", "obsidian_write", "obsidian_append"}:
        if before.get("exists") and not before.get("binary"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(before.get("content", ""), encoding="utf-8")
        elif target.exists():
            target.unlink()
        return "success", f"已撤销上一步：{target}", "已撤销"
    if action.type == "delete" and before.get("exists") and not before.get("binary"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(before.get("content", ""), encoding="utf-8")
        return "success", f"已恢复删除的文件：{target}", "已撤销删除"
    if action.type == "move_ext":
        for item in reversed(extra.get("moved", [])):
            src = Path(item["to"])
            dst = Path(item["from"])
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
        return "success", "已撤销上一次批量移动", "已撤销移动"
    return "error", "上一步操作不支持撤销", "无法撤销"


def execute(action: Action, confirmed: bool = False) -> Tuple[str, str, str]:
    if action.type in {"write", "append", "replace", "delete"}:
        return execute_file_action(action)
    if action.type == "list_dir":
        return execute_list_dir(action)
    if action.type == "move_ext":
        return execute_move_ext_confirmed(action) if confirmed else execute_move_ext(action)
    if action.type == "read":
        return execute_read(action)
    if action.type == "obsidian_search":
        return execute_obsidian_search(action)
    if action.type == "obsidian_status":
        return execute_obsidian_status()
    if action.type == "obsidian_read":
        return execute_obsidian_read(action)
    if action.type == "obsidian_list":
        return execute_obsidian_list(action)
    if action.type == "obsidian_write":
        return execute_obsidian_write(action, append=False)
    if action.type == "obsidian_append":
        return execute_obsidian_write(action, append=True)
    if action.type == "obsidian_diary_browse":
        return execute_diary_browse(action)
    if action.type == "obsidian_diary_recent":
        return execute_diary_recent(action)
    if action.type == "obsidian_daily_append":
        return execute_daily_append(action)
    if action.type == "obsidian_daily_read":
        return execute_daily_read()
    if action.type in {"task_add", "task_done", "task_list"}:
        return execute_task(action)
    if action.type in {"memory_set", "memory_append", "memory_list", "memory_add", "memory_replace", "memory_remove"}:
        return execute_memory(action)
    if action.type == "shell":
        return execute_shell(action)
    if action.type == "session_search":
        return execute_session_search(action)
    if action.type in {"soul_read", "soul_write", "soul_append"}:
        return execute_soul(action)
    if action.type == "reminder_add":
        return execute_reminder(action)
    if action.type == "undo":
        return execute_undo()
    return "error", "未识别本地操作", "未识别本地操作"


def action_from_tool_call(data: Dict[str, Any]) -> Optional[Action]:
    tool = (data.get("tool") or "").strip()
    args = data.get("args") or {}
    if tool in {"", "none"}:
        return None

    if tool == "write_file":
        path = strip_target_path_noise(args.get("path", ""))
        content = args.get("content", "")
        if looks_like_obsidian_relative_path(path):
            return Action("obsidian_write", path=path, content=content)
        return Action("write", path=path, content=content)
    if tool == "append_file":
        return Action("append", path=args.get("path", ""), content=args.get("content", ""))
    if tool == "replace_file":
        return Action("replace", path=args.get("path", ""), old_text=args.get("old_text", ""), new_text=args.get("new_text", ""))
    if tool == "delete_file":
        return Action("delete", path=args.get("path", ""))
    if tool == "read_file":
        return Action("read", path=args.get("path", ""))
    if tool == "list_dir":
        return Action("list_dir", path=args.get("path", "Desktop"), ext=args.get("ext", ""))
    if tool == "move_ext":
        return Action("move_ext", path=args.get("path", "Desktop"), ext=args.get("ext", ""), dest=args.get("dest", ""))
    if tool == "obsidian_search":
        return Action("obsidian_search", term=args.get("term", ""))
    if tool == "obsidian_status":
        return Action("obsidian_status")
    if tool == "obsidian_read":
        return Action("obsidian_read", path=args.get("path", ""))
    if tool == "obsidian_list":
        return Action("obsidian_list", path=args.get("path", ""))
    if tool == "obsidian_write":
        return Action(
            "obsidian_write",
            path=strip_target_path_noise(args.get("path", "")),
            content=args.get("content", ""),
        )
    if tool == "obsidian_append":
        return Action("obsidian_append", path=args.get("path", ""), content=args.get("content", ""))
    if tool == "obsidian_diary_browse":
        return Action("obsidian_diary_browse", count=int(args.get("count", 1) or 1))
    if tool == "obsidian_diary_recent":
        return Action("obsidian_diary_recent", count=int(args.get("count", 7) or 7))
    if tool == "obsidian_daily_read":
        return Action("obsidian_daily_read")
    if tool == "obsidian_daily_append":
        return Action("obsidian_daily_append", content=args.get("content", ""))
    if tool == "task_add":
        return Action("task_add", task_text=args.get("text", ""))
    if tool == "task_list":
        return Action("task_list")
    if tool == "task_done":
        return Action("task_done", task_id=int(args.get("id", 0) or 0))
    if tool == "memory":
        action_name = (args.get("action") or "add").strip().lower()
        target = (args.get("target") or "user").strip().lower()
        content = args.get("content") or args.get("note") or ""
        if action_name == "add":
            return Action("memory_add", memory_target=target, note=content)
        if action_name == "replace":
            return Action(
                "memory_replace",
                memory_target=target,
                old_text=args.get("old_text", ""),
                new_text=args.get("new_text", content),
            )
        if action_name == "remove":
            return Action("memory_remove", memory_target=target, old_text=args.get("old_text", content))
        if action_name == "list":
            return Action("memory_list")
        return None
    if tool == "memory_set":
        return Action("memory_set", key=args.get("key", ""), value=args.get("value", ""))
    if tool == "memory_append":
        return Action("memory_append", note=args.get("note", ""))
    if tool == "memory_list":
        return Action("memory_list")
    if tool == "soul_read":
        return Action("soul_read")
    if tool == "soul_write":
        return Action("soul_write", content=args.get("content", ""))
    if tool == "soul_append":
        return Action("soul_append", content=args.get("content", ""))
    if tool == "session_search":
        return Action("session_search", term=args.get("term", "") or args.get("query", ""))
    if tool == "shell":
        return Action("shell", command=args.get("command", ""))
    if tool == "reminder_add":
        return Action(
            "reminder_add",
            reminder_title=args.get("title", ""),
            reminder_due_iso=args.get("due", ""),
            reminder_list=args.get("list", ""),
        )
    if tool == "undo":
        return Action("undo")
    return None


def run_tool_call(raw_json: str) -> None:
    try:
        data = json.loads(raw_json)
    except Exception as error:
        response("error", f"工具调用 JSON 解析失败：{error}", "工具调用失败")
        return

    # 减法版 W1：先尝试走注册表（已搬的 3 个工具）
    # 未注册的工具 fallthrough 到下面的 action_from_tool_call 旧链
    tool_name = (data.get("tool") or "").strip()
    if tool_name:
        try:
            from agent_tools import REGISTRY as _TOOL_REGISTRY
        except Exception:
            _TOOL_REGISTRY = None
        if _TOOL_REGISTRY is not None and _TOOL_REGISTRY.get(tool_name) is not None:
            allowed_toolsets = _resolve_allowed_toolsets()
            status, assistant_text, footer = _TOOL_REGISTRY.dispatch(
                tool_name, data.get("args") or {}, allowed_toolsets=allowed_toolsets
            )
            response(status, assistant_text, footer, tool=tool_name)
            return

    action = action_from_tool_call(data)
    if not action:
        json_result(handled=False)
        return

    target = resolve_path(action.path) if action.path else HOME
    if action.path and not allowed(target):
        response("error", "只允许操作 /Users/DRLer 目录内文件")
        return

    dangerous = action.type == "delete" or action.type == "move_ext" or (action.type == "write" and target.exists())
    if dangerous:
        save_pending(action)
        if action.type == "move_ext":
            status, assistant_text, footer = execute_move_ext(action)
            response(status, assistant_text, footer, tool=data.get("tool", ""))
        else:
            response("needs_confirmation", f"危险操作待确认：{action.type} {target}，输入“确认执行”继续，输入“取消”放弃", f"危险操作待确认：{action.type} {target}", tool=data.get("tool", ""))
        return

    status, assistant_text, footer = execute(action)
    response(status, assistant_text, footer, tool=data.get("tool", ""))


# === W10: in-process chat harness with LiteLLM ===
# 设计要点 (跟 Hermes run_conversation 同构):
#   while max_iterations: LLM(streaming=False Step 2; streaming Step 3) →
#     parse tool_calls → REGISTRY.dispatch → append tool result → continue
# LiteLLM 把所有 provider (minimax/deepseek/openai/anthropic) 统一成 OpenAI 协议。
# 不再需要 W9.1 的 M3 XML hallucinate 解析 (Step 1 验证: M3 原生支持 tool_calls)。
import plistlib as _plistlib

W10_MAX_ITERATIONS = 5
W10_TIMEOUT_SECONDS = 60
W10_LITELLM_IMPORT_ERROR: Optional[str] = None
try:
    import litellm as _litellm
except Exception as _exc:  # noqa: BLE001
    _litellm = None
    W10_LITELLM_IMPORT_ERROR = str(_exc)


def _alfred_env(name: str, default: str = "") -> str:
    """跟 JXA envVar() 一致: 优先 shell env, fallback Alfred prefs.plist."""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        prefs_path = Path.home() / "Library/Application Support/Alfred/Alfred.alfredpreferences/workflows/user.workflow.C4B4D1C2-50BE-4FD4-AE5E-9324DBED0C51/prefs.plist"
        with open(prefs_path, "rb") as f:
            prefs = _plistlib.load(f)
        return str(prefs.get(name, default)).strip()
    except Exception:
        return default


def _resolve_provider_config() -> dict:
    """读当前 provider 配置 (跟 JXA envVar() 同源, 默认 minimax)."""
    provider = (_alfred_env("ac_provider") or "minimax").strip().lower()
    if provider == "deepseek":
        return {
            "provider": "deepseek",
            "api_key": _alfred_env("deepseek_api_key"),
            "endpoint": _alfred_env("deepseek_api_endpoint") or "https://api.deepseek.com/v1",
            "model": _alfred_env("deepseek_model") or "deepseek-chat",
        }
    if provider == "openai":
        return {
            "provider": "openai",
            "api_key": _alfred_env("openai_api_key"),
            "endpoint": _alfred_env("openai_base_url") or "https://api.openai.com/v1",
            "model": _alfred_env("openai_model") or "gpt-4o",
        }
    if provider == "anthropic":
        return {
            "provider": "anthropic",
            "api_key": _alfred_env("anthropic_api_key"),
            "endpoint": _alfred_env("anthropic_base_url") or "",
            "model": _alfred_env("anthropic_model") or "claude-sonnet-4-20250514",
        }
    # 默认 minimax (M3)
    return {
        "provider": "minimax",
        "api_key": _alfred_env("minimax_api_key"),
        "endpoint": _alfred_env("minimax_api_endpoint") or "https://api.minimaxi.com/v1",
        "model": _alfred_env("minimax_model") or "MiniMax-M3",
    }


def _litellm_model_name(cfg: dict) -> str:
    """把内部 provider 名转 LiteLLM model 字符串. OpenAI 兼容用 openai/ 前缀."""
    provider = cfg["provider"]
    model = cfg["model"]
    if provider in ("minimax", "deepseek", "openai"):
        return f"openai/{model}"
    if provider == "anthropic":
        return f"anthropic/{model}"
    return model


def _litellm_complete(cfg: dict, messages: list, tools: list = None, stream: bool = False):
    """LiteLLM completion. 返回 ModelResponse 或 iterator (stream=True)."""
    if _litellm is None:
        raise RuntimeError(f"litellm 未安装: {W10_LITELLM_IMPORT_ERROR}")
    kwargs = {
        "model": _litellm_model_name(cfg),
        "api_key": cfg["api_key"],
        "messages": messages,
        "timeout": W10_TIMEOUT_SECONDS,
    }
    if cfg.get("endpoint"):
        kwargs["base_url"] = cfg["endpoint"]
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if stream:
        kwargs["stream"] = True
    return _litellm.completion(**kwargs)


def _assistant_message_to_dict(msg) -> dict:
    """LiteLLM Message 对象 → dict (写回 chat.json)."""
    out: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
    if getattr(msg, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    # M3 / DeepSeek 思考链 (Hermes 同款: reasoning_content 字段)
    if getattr(msg, "reasoning_content", None):
        out["reasoning_content"] = msg.reasoning_content
    return out


def _convert_registry_tools_to_openai() -> list:
    """agent_tools.REGISTRY schemas → LiteLLM 接受的 OpenAI format."""
    try:
        from agent_tools import REGISTRY
    except Exception:
        return []
    schemas: List[Dict[str, Any]] = []
    for tool in REGISTRY.all():
        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.schema or {"type": "object", "properties": {}},
            },
        })
    return schemas


def _w10_load_chat(chat_file: Path) -> list:
    if not chat_file.exists():
        return []
    try:
        data = json.loads(chat_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return data["messages"]
    except Exception:
        pass
    return []


def _w10_save_chat(chat_file: Path, messages: list) -> None:
    chat_file.parent.mkdir(parents=True, exist_ok=True)
    chat_file.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def _w10_dispatch_tool(name: str, arguments_json: str) -> tuple[str, str]:
    """跑一个 tool, 返回 (status, result_text). 出错也返回 status='error'."""
    try:
        from agent_tools import REGISTRY
    except Exception as exc:
        return "error", f"REGISTRY 不可用: {exc}"

    if REGISTRY.get(name) is None:
        available = ", ".join(REGISTRY.names())
        return "error", f"工具 {name} 不存在.可用: {available}"

    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except Exception as exc:
        return "error", f"参数解析失败: {exc}"
    if not isinstance(args, dict):
        args = {}

    try:
        allowed_toolsets = _resolve_allowed_toolsets()
        status, text, footer = REGISTRY.dispatch(name, args, allowed_toolsets=allowed_toolsets)
    except Exception as exc:  # noqa: BLE001
        return "error", f"工具 {name} 执行失败: {exc}"

    # 跟 W9.1 一致: 拼 text + footer
    combined = text
    if footer and footer != text:
        combined = f"{text}\n\n({footer})"
    return status, combined


def _load_context_file() -> str:
    """跟 JXA loadContextFile() 一致: 读 context_file_path 或 OB 库 AGENTS.md."""
    configured = _alfred_env("context_file_path", "").strip()
    vault = _alfred_env("obsidian_vault_path", "").strip()
    candidates = [configured, Path(f"{vault}/AGENTS.md") if vault else ""]
    for path_str in candidates:
        if not path_str:
            continue
        p = Path(path_str)
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8").strip()
        if content:
            return f"以下是项目上下文（来自 {path_str}）：\n\n{content}"
    return ""


_RUNTIME_GUARD_PROMPT = (
    '【运行约束 · 最高优先级，与上文任何"主动去做"的指令冲突时以本节为准】\n'
    "你实际拥有的能力（仅这些，由本地 Agent 在你回复前自动完成，你无法在回复中途临时调用）：\n"
    "- 读写 /Users/DRLer 下的本地文件、Obsidian 库；新增提醒；读写长期记忆。\n"
    "- 联网搜索 web_search（调 Tavily API，免费 1000 次/月，需配 tavily_api_key）。\n"
    "- 网页抓取 web_fetch（调 baoyu-fetch CLI，需 bun + Chrome）。\n"
    "- 工具可以连续调用直到拿到完整信息。\n"
    "- 工具调用结束后会有一步「合成」:把原始搜索结果/网页 markdown 整理成简洁答案。\n"
    "你没有的能力（绝不要声称会去做）：\n"
    "- 跑未授权的本地 shell 命令、调未列出的外部服务、查未授权的数据库、等待后续结果。\n"
    "硬性输出规则：\n"
    "- 禁止用「我先看下…」「我去查一下」「稍等/接下来我来…」这类只表态不给结果的句子作为整段回复或结尾。\n"
    "- 工具返回「未找到相关结果」时直接告诉用户搜不到，禁止用训练数据常识编造答案。\n"
    "- 工具结果与用户问题不直接相关时明确说明，不要把无关结果强行套到问题上。\n"
    "- 引用工具结果时显式标注来源，不要把搜索结果伪装成自己知道。\n"
    "- 每次回复都必须当场给出完整结论、可执行答案、或一个明确的问题。"
)


def _compose_chat_system_prompt(user_query: str) -> str:
    """组合 system prompt: soul + user.custom + context_file + skills + memory + runtime_guard."""
    parts: List[str] = []

    # 1. Soul
    try:
        from soul_store import soul_prompt_block
        soul = soul_prompt_block(data_dir(), soul_override())
    except Exception:
        soul = ""
    if soul:
        parts.append(soul)

    # 2. 用户自定义 system_prompt (来自 Alfred env vars)
    custom = _alfred_env("system_prompt", "").strip()
    if custom:
        parts.append(custom)

    # 3. 项目上下文 (AGENTS.md)
    ctx = _load_context_file()
    if ctx:
        parts.append(ctx)

    # 4. 相关 Skill
    try:
        from agent_skills import format_skills_prompt_block
        skills = format_skills_prompt_block(user_query or "", top_k=2)
    except Exception:
        skills = ""
    if skills:
        parts.append(skills)

    # 5. 长期记忆
    try:
        store = get_memory_store()
        mem = store.prompt_block()
    except Exception:
        mem = ""
    if mem:
        parts.append(mem)

    # 6. Runtime guard (最高优先级)
    parts.append(_RUNTIME_GUARD_PROMPT)

    return "\n\n".join(parts)


def cmd_chat(user_query: str) -> int:
    """W10: in-process chat harness. CLI: --chat "<query>".

    单进程内跑 LLM ↔ tool loop, 跟 Hermes run_conversation 同构。
    最终回复写 stdout (供 Alfred 显示), 中间 messages 写 chat.json。
    """
    if _litellm is None:
        print(f"[W10] litellm 未安装: {W10_LITELLM_IMPORT_ERROR}", file=sys.stderr)
        return 1

    chat_file = data_dir() / "chat.json"
    messages = _w10_load_chat(chat_file)

    # 拼 system prompt 注入 (仅在 session 开始 / 无 system msg 时)
    if not messages or messages[0].get("role") != "system":
        sys_prompt = _compose_chat_system_prompt(user_query)
        if sys_prompt:
            messages.insert(0, {"role": "system", "content": sys_prompt})

    messages.append({"role": "user", "content": user_query})

    cfg = _resolve_provider_config()
    if not cfg["api_key"]:
        print(f"[W10] {cfg['provider']} provider 未配 api_key", file=sys.stderr)
        return 2

    tool_schemas = _convert_registry_tools_to_openai()
    final_text = ""
    exit_code = 0

    # 上下文窗口: 保留 system msg + 最近 N 条 (默认 40, 跟原 JXA 一致)
    max_ctx = int(_alfred_env("max_context") or 40)
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    tail = messages[1:] if system_msg else messages
    truncated_tail = tail[-max_ctx:] if len(tail) > max_ctx else tail
    messages = ([system_msg] if system_msg else []) + truncated_tail

    for iteration in range(W10_MAX_ITERATIONS):
        try:
            resp = _litellm_complete(cfg, messages, tools=tool_schemas or None)
        except Exception as exc:  # noqa: BLE001
            print(f"[W10] LLM 调用失败 (iter {iteration + 1}): {exc}", file=sys.stderr)
            exit_code = 3
            break

        assistant_msg = resp.choices[0].message
        assistant_dict = _assistant_message_to_dict(assistant_msg)
        messages.append(assistant_dict)
        final_text = assistant_dict.get("content", "")

        # 没 tool_calls → 最终回复, 退出 loop
        if not getattr(assistant_msg, "tool_calls", None):
            break

        # 执行 tool calls
        for tc in assistant_msg.tool_calls:
            status, tool_result = _w10_dispatch_tool(tc.function.name, tc.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": tool_result,
            })
    else:
        # for-else: 达到 max_iterations 还没 break
        print(f"[W10] 警告: 达到 max_iterations={W10_MAX_ITERATIONS}, 强制退出", file=sys.stderr)
        exit_code = 4

    _w10_save_chat(chat_file, messages)
    # stdout 只输出最终答复 (供 Alfred 抓取)
    print(final_text)
    return exit_code


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--ensure-soul":
        from soul_store import ensure_soul

        created = ensure_soul(
            data_dir(),
            os.environ.get("chat_assistant_label") or "Assistant",
            soul_override(),
        )
        json_result(handled=True, status="success", assistant_text="灵魂已初始化" if created else "灵魂已存在", created=created)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--soul-prompt":
        from soul_store import soul_prompt_block

        block = soul_prompt_block(data_dir(), soul_override())
        json_result(handled=True, status="success", assistant_text=block, prompt=block)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--migrate-memory":
        from memory_store import ensure_migrated

        migrated = ensure_migrated(data_dir())
        json_result(handled=True, status="success", assistant_text="记忆已迁移" if migrated else "无需迁移", migrated=migrated)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--memory-prompt":
        store = get_memory_store()
        block = store.prompt_block()
        json_result(handled=True, status="success", assistant_text=block, prompt=block)
        return

    if len(sys.argv) > 2 and sys.argv[1] == "--tool":
        run_tool_call(sys.argv[2])
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--tool-schema":
        try:
            from agent_tools import REGISTRY as _TOOL_REGISTRY
            allowed_toolsets = _resolve_allowed_toolsets()
            schemas = _TOOL_REGISTRY.filter_schemas(allowed_toolsets)
            print(json.dumps(schemas, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--tool-list":
        try:
            from agent_tools import REGISTRY as _TOOL_REGISTRY
            print(json.dumps({"names": _TOOL_REGISTRY.names(), "toolsets": _TOOL_REGISTRY.toolsets()}, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--skills-prompt":
        # argv: --skills-prompt <query>
        user_query = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            from agent_skills import format_skills_prompt_block
            block = format_skills_prompt_block(user_query, top_k=2)
            print(block if block else "")
        except Exception as exc:
            print("")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--skill-list":
        try:
            from agent_skills import load_all_skills
            result = load_all_skills()
            out = {
                "skills": [{"name": s.name, "description": s.description, "version": s.version, "bundled": s.bundled, "tags": s.tags} for s in result.skills],
                "errors": [{"path": str(p), "error": e} for p, e in result.errors],
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--curator-tick":
        # 轻量后台 tick:24h 节流,失败静默。给 Alfred 外部 trigger + 懒触发用。
        try:
            from curator import tick
            force = "--force" in sys.argv
            result = tick(force=force)
        except Exception as exc:
            result = {"skipped": True, "reason": f"curator import error: {exc}"}
        print(json.dumps(result, ensure_ascii=False))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--skillify":
        # argv: --skillify <subcommand> [args...]
        #   from-recent [--hint "..."]  创建新 skill
        #   improve <name> [--hint "..."] 改进已有 skill
        #   curator                    后台自动审核
        #   confirm <name>             确认覆盖已存在的 skill
        try:
            from agent_skills.skillify import (
                skillify_from_recent,
                skillify_confirm_overwrite,
                skillify_improve,
                run_curator,
            )
            args = sys.argv[2:]
            subcmd = args[0] if args else "from-recent"

            hint = ""
            if "--hint" in args:
                i = args.index("--hint")
                if i + 1 < len(args):
                    hint = args[i + 1]

            if subcmd == "curator":
                result = run_curator()
                print(json.dumps({"status": "ok", "curator": result}, ensure_ascii=False))
            elif subcmd == "improve":
                if len(args) < 2:
                    print(json.dumps({"status": "error", "assistant_text": "用法: --skillify improve <skill-name> [--hint '...']", "footer": "参数不足"}, ensure_ascii=False))
                else:
                    status, msg, footer = skillify_improve(args[1], user_hint=hint)
                    print(json.dumps({"status": status, "assistant_text": msg, "footer": footer}, ensure_ascii=False))
            elif subcmd == "confirm":
                if len(args) < 2:
                    print(json.dumps({"status": "error", "assistant_text": "用法: --skillify confirm <skill-name>", "footer": "参数不足"}, ensure_ascii=False))
                else:
                    status, msg, footer = skillify_confirm_overwrite(args[1])
                    print(json.dumps({"status": status, "assistant_text": msg, "footer": footer}, ensure_ascii=False))
            else:
                # default: from-recent (backward compatible)
                status, msg, footer = skillify_from_recent(user_hint=hint)
                print(json.dumps({"status": status, "assistant_text": msg, "footer": footer}, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"status": "error", "assistant_text": str(exc), "footer": "失败"}, ensure_ascii=False))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--continuation-get":
        data = load_continuation()
        print(json.dumps({"continuation": data}, ensure_ascii=False))
        return

    if len(sys.argv) > 2 and sys.argv[1] == "--continuation-save":
        # argv: --continuation-save <last_query> <last_assistant_partial>
        save_continuation(sys.argv[2], sys.argv[3], ttl_minutes=30)
        print(json.dumps({"status": "ok", "saved": True}, ensure_ascii=False))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--continuation-clear":
        clear_continuation()
        print(json.dumps({"status": "ok", "cleared": True}, ensure_ascii=False))
        return

    if len(sys.argv) > 2 and sys.argv[1] == "--chat":
        # argv: --chat "<user_query>"
        # W10: in-process chat harness with LiteLLM + tool dispatch
        sys.exit(cmd_chat(sys.argv[2]))

    query = sys.argv[1] if len(sys.argv) > 1 else ""
    trimmed = query.strip()

    if re.match(r"^确认执行$", trimmed, re.I):
        pending = load_pending()
        if not pending:
            response("error", "没有待确认的危险操作")
            return
        clear_pending()
        status, assistant_text, footer = execute(pending, confirmed=True)
        response(status, assistant_text, footer)
        return

    if re.match(r"^(取消|取消执行)$", trimmed, re.I):
        clear_pending()
        response("success", "已取消待执行操作")
        return

    action = parse_intent(trimmed)
    if not action:
        json_result(handled=False)
        return

    if action.type == "skillify":
        from agent_skills.skillify import skillify_from_recent

        status, assistant_text, footer = skillify_from_recent(user_hint=action.note or trimmed)
        response(status, assistant_text, footer)
        return

    target = resolve_path(action.path) if action.path else HOME
    if action.path and not allowed(target):
        response("error", "只允许操作 /Users/DRLer 目录内文件")
        return

    dangerous = action.type == "delete" or action.type == "move_ext" or (action.type == "write" and target.exists())
    if dangerous:
        save_pending(action)
        if action.type == "move_ext":
            status, assistant_text, footer = execute_move_ext(action)
            response(status, assistant_text, footer)
        else:
            response("needs_confirmation", f"危险操作待确认：{action.type} {target}，输入“确认执行”继续，输入“取消”放弃", f"危险操作待确认：{action.type} {target}")
        return

    status, assistant_text, footer = execute(action)
    response(status, assistant_text, footer)


if __name__ == "__main__":
    main()
