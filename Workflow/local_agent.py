#!/usr/bin/env python3
"""Local agent harness for Alfred Chat.

Alfred provides the UI. This script provides a small, conservative tool layer:
file operations, batch desktop tools, Obsidian search, tasks, memory, action
logging/undo, and a tiny shell whitelist.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


HOME = Path("/Users/DRLer").resolve()
DESKTOP = HOME / "Desktop"
DEFAULT_OBSIDIAN = HOME / "Obsidian_250614"
MAX_READ_CHARS = 6000
MAX_LIST_ITEMS = 40


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
    reminder_title: str = ""
    reminder_due_iso: str = ""
    reminder_list: str = ""
    key: str = ""
    value: str = ""
    note: str = ""


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


def action_log_path() -> Path:
    return data_dir() / "action_log.jsonl"


def tasks_path() -> Path:
    return data_dir() / "tasks.json"


def memory_path() -> Path:
    return data_dir() / "memory.json"


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


def has_path_hint(candidate: str) -> bool:
    text = candidate.strip()
    if re.search(r"(如何|怎么|为什么|方法|教程|吗|？|\?)", text):
        return False
    return bool(
        re.search(r"^@|^/|^~|[/\\]|桌面", text, re.I)
        or re.search(r"(^|[\s/\\])\.env($|\s)", text, re.I)
        or re.search(r"\.[A-Za-z0-9]{1,8}$", text)
    )


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
        or re.search(r"^(列出|新增|完成)任务|^(你)?记住|^列出记忆|搜索(?:OB|Obsidian|ob)|(?:今天|今日)日记|(?:读|读取|查看).*(?:OB|Obsidian|ob).*(?:今天|今日)日记|运行命令[:：]|提醒", text, re.I)
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

    match = re.match(r"^(?:创建|新建|写入)(?:文件)?\s*(.+?)\s*(?:内容|正文)[:：]\s*([\s\S]+)$", text, re.I)
    if match and has_path_hint(match.group(1)):
        return Action("write", match.group(1).strip(), content=match.group(2))

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

    match = re.match(r"^(?:新建|创建|写入)(?:文件)?\s*(.+)$", text, re.I)
    if match and has_path_hint(match.group(1)):
        return Action("write", match.group(1).strip())

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
    memory = load_json(memory_path(), {})
    if action.type == "memory_append":
        notes = memory.get("_notes", [])
        if not isinstance(notes, list):
            notes = []
        notes.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "content": action.note,
        })
        memory["_notes"] = notes[-20:]
        save_json(memory_path(), memory)
        return "success", "已写入长期记忆", "已写入长期记忆"
    if action.type == "memory_set":
        memory[action.key] = action.value
        save_json(memory_path(), memory)
        return "success", f"已记住：{action.key} = {action.value}", "已记住"
    lines = []
    for key, value in sorted(memory.items()):
        if key == "_notes":
            continue
        lines.append(f"- {key}: {value}")
    for item in memory.get("_notes", []):
        lines.append(f"- {item.get('time', '')}: {item.get('content', '')[:120]}")
    return "success", "记忆：\n\n" + ("\n".join(lines) if lines else "暂无记忆"), f"{len(memory)} 条记忆"


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
    if action.type in {"write", "append", "replace", "obsidian_daily_append"}:
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
    if action.type == "obsidian_daily_append":
        return execute_daily_append(action)
    if action.type == "obsidian_daily_read":
        return execute_daily_read()
    if action.type in {"task_add", "task_done", "task_list"}:
        return execute_task(action)
    if action.type in {"memory_set", "memory_append", "memory_list"}:
        return execute_memory(action)
    if action.type == "shell":
        return execute_shell(action)
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
        return Action("write", path=args.get("path", ""), content=args.get("content", ""))
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
    if tool == "memory_set":
        return Action("memory_set", key=args.get("key", ""), value=args.get("value", ""))
    if tool == "memory_append":
        return Action("memory_append", note=args.get("note", ""))
    if tool == "memory_list":
        return Action("memory_list")
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


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--tool":
        run_tool_call(sys.argv[2])
        return

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
