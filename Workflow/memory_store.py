#!/usr/bin/env python3
"""Hermes-inspired persistent memory: MEMORY.md + USER.md with §-delimited entries."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


ENTRY_DELIMITER = "\n§\n"
MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375

THREAT_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|your)\s+", re.I),
    re.compile(r"system\s*prompt\s*[:：]", re.I),
    re.compile(r"<\s*/?\s*system\s*>", re.I),
    re.compile(r"\[INST\]|\[/INST\]", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a\s+)?(?:DAN|jailbreak)", re.I),
    re.compile(r"forget\s+(?:everything|all)\s+(?:you|your)", re.I),
    re.compile(r"override\s+(?:your\s+)?(?:instructions|rules)", re.I),
]


@dataclass
class MemoryTarget:
    name: str
    label: str
    char_limit: int


TARGETS = {
    "memory": MemoryTarget("MEMORY", "MEMORY (notes & context)", MEMORY_CHAR_LIMIT),
    "user": MemoryTarget("USER", "USER (profile & preferences)", USER_CHAR_LIMIT),
}


def memories_dir(data_dir: Path) -> Path:
    path = data_dir / "memories"
    path.mkdir(parents=True, exist_ok=True)
    return path


def target_path(data_dir: Path, target: str) -> Path:
    info = TARGETS.get(target, TARGETS["user"])
    return memories_dir(data_dir) / f"{info.name}.md"


def scan_threats(text: str) -> Optional[str]:
    for pattern in THREAT_PATTERNS:
        if pattern.search(text):
            return "记忆内容疑似包含 prompt 注入模式，已拒绝写入"
    return None


def parse_entries(raw: str) -> List[str]:
    if not raw.strip():
        return []
    return [entry.strip() for entry in raw.split(ENTRY_DELIMITER) if entry.strip()]


def serialize_entries(entries: List[str]) -> str:
    cleaned = [entry.strip() for entry in entries if entry.strip()]
    if not cleaned:
        return ""
    return ENTRY_DELIMITER.join(cleaned)


def usage_header(target: str, used: int) -> str:
    info = TARGETS[target]
    pct = min(100, round(used / info.char_limit * 100)) if info.char_limit else 0
    return f"{info.label} [{pct}% — {used:,}/{info.char_limit:,} chars]"


class MemoryStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        ensure_migrated(data_dir)

    def load_entries(self, target: str) -> List[str]:
        path = target_path(self.data_dir, target)
        if not path.exists():
            return []
        return parse_entries(path.read_text(encoding="utf-8"))

    def save_entries(self, target: str, entries: List[str]) -> None:
        path = target_path(self.data_dir, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_entries(entries), encoding="utf-8")

    def total_chars(self, target: str) -> int:
        path = target_path(self.data_dir, target)
        if not path.exists():
            return 0
        return len(path.read_text(encoding="utf-8"))

    def would_exceed(self, target: str, new_content: str) -> bool:
        info = TARGETS[target]
        current = self.load_entries(target)
        trial = serialize_entries(current + [new_content.strip()])
        return len(trial) > info.char_limit

    def add(self, target: str, content: str, *, auto: bool = False) -> Tuple[bool, str]:
        text = content.strip()
        if not text:
            return False, "记忆内容不能为空"
        threat = scan_threats(text)
        if threat:
            return False, threat
        if auto and not text.startswith("[auto]"):
            text = f"[auto] {text}"

        entries = self.load_entries(target)
        if any(entry.strip() == text for entry in entries):
            return False, "条目已存在，未重复写入"

        if self.would_exceed(target, text):
            info = TARGETS[target]
            used = self.total_chars(target)
            return False, (
                f"{info.name}.md 已满（{used}/{info.char_limit} chars）。"
                "请先 consolidate：用 replace/remove 合并或删除旧条目。"
            )

        entries.append(text)
        self.save_entries(target, entries)
        return True, f"已写入 {TARGETS[target].name}.md"

    def replace(self, target: str, old_text: str, new_text: str) -> Tuple[bool, str]:
        old = old_text.strip()
        new = new_text.strip()
        if not old or not new:
            return False, "replace 需要 old_text 与 new_text"
        threat = scan_threats(new)
        if threat:
            return False, threat

        entries = self.load_entries(target)
        match_index = next((i for i, e in enumerate(entries) if old in e), None)
        if match_index is None:
            return False, f"未找到包含「{old[:80]}」的条目"

        trial = entries[:]
        trial[match_index] = new
        if len(serialize_entries(trial)) > TARGETS[target].char_limit:
            return False, f"替换后会超出 {TARGETS[target].name}.md 字符上限"

        entries[match_index] = new
        self.save_entries(target, entries)
        return True, f"已更新 {TARGETS[target].name}.md 条目"

    def remove(self, target: str, old_text: str) -> Tuple[bool, str]:
        old = old_text.strip()
        if not old:
            return False, "remove 需要 old_text 子串"

        entries = self.load_entries(target)
        match_index = next((i for i, e in enumerate(entries) if old in e), None)
        if match_index is None:
            return False, f"未找到包含「{old[:80]}」的条目"

        entries.pop(match_index)
        self.save_entries(target, entries)
        return True, f"已删除 {TARGETS[target].name}.md 条目"

    def list_formatted(self) -> str:
        lines: List[str] = []
        for key in ("user", "memory"):
            entries = self.load_entries(key)
            info = TARGETS[key]
            lines.append(usage_header(key, self.total_chars(key)))
            if entries:
                for entry in entries:
                    preview = entry.replace("\n", " ")[:200]
                    lines.append(f"- {preview}")
            else:
                lines.append("- （空）")
            lines.append("")
        return "\n".join(lines).strip()

    def prompt_block(self) -> str:
        sections: List[str] = []
        for key in ("user", "memory"):
            entries = self.load_entries(key)
            if not entries:
                continue
            header = usage_header(key, self.total_chars(key))
            body = "\n".join(f"- {entry.strip()}" for entry in entries)
            sections.append(f"{header}\n{body}")

        if not sections:
            return ""

        return (
            "以下是用户要求长期记住的背景信息和使用偏好。回答时请主动遵守，"
            "不要声称自己无法跨对话记住；这些内容来自本地 memories/MEMORY.md 与 USER.md：\n\n"
            + "\n\n".join(sections)
        )


def ensure_migrated(data_dir: Path) -> bool:
    legacy = data_dir / "memory.json"
    mem_dir = memories_dir(data_dir)
    memory_file = mem_dir / "MEMORY.md"
    user_file = mem_dir / "USER.md"

    if not legacy.exists():
        return False
    if memory_file.exists() and memory_file.read_text(encoding="utf-8").strip():
        return False
    if user_file.exists() and user_file.read_text(encoding="utf-8").strip():
        return False

    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except Exception:
        return False

    store = MemoryStore.__new__(MemoryStore)
    store.data_dir = data_dir

    user_entries: List[str] = []
    memory_entries: List[str] = []

    if isinstance(data, dict):
        for key, value in sorted(data.items()):
            if key == "_notes":
                continue
            user_entries.append(f"{key}: {value}")
        notes = data.get("_notes", [])
        if isinstance(notes, list):
            for item in notes:
                if isinstance(item, dict) and item.get("content"):
                    memory_entries.append(str(item["content"]).strip())
                elif isinstance(item, str):
                    memory_entries.append(item.strip())

    if user_entries:
        store.save_entries("user", user_entries)
    if memory_entries:
        store.save_entries("memory", memory_entries)

    backup = data_dir / "memory.json.bak"
    if not backup.exists():
        shutil.copy2(legacy, backup)

    return True


def main() -> None:
    import os
    import sys

    data = Path(os.environ.get("alfred_workflow_data") or os.environ.get("ALFRED_WORKFLOW_DATA") or "/tmp/alfred-chat")
    store = MemoryStore(data)

    if len(sys.argv) > 1 and sys.argv[1] == "--prompt":
        block = store.prompt_block()
        print(block, end="" if block else "")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--migrate":
        migrated = ensure_migrated(data)
        print(json.dumps({"migrated": migrated}, ensure_ascii=False))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        print(store.list_formatted())
        return

    print(store.prompt_block())


if __name__ == "__main__":
    main()
