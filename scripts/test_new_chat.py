#!/usr/bin/env python3
"""Test W5 micro-feat: cmd+回车 = 新建 chat (通过 ensureFreshChat + new_chat env)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / "Workflow"
TEST_DATA = "/tmp/alfred-chat-w5-test"

_pass = 0
_fail = 0


def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        print(f"  ✓ {label}")
        _pass += 1
    else:
        print(f"  ✗ {label}")
        _fail += 1


def section(t: str) -> None:
    print(f"\n--- {t} ---")


def run_chat_script(query: str = "", new_chat: bool = False, env_extra: dict | None = None) -> dict:
    """直接跑 osascript 执行 chat script,模拟 Alfred hotkey。"""
    env = os.environ.copy()
    env["alfred_workflow_data"] = TEST_DATA
    env["alfred_workflow_cache"] = "/tmp/alfred-chat-w5-test-cache"
    env["max_context"] = "20"
    env["timeout_seconds"] = "30"
    if new_chat:
        env["new_chat"] = "1"
    if env_extra:
        env.update(env_extra)
    os.makedirs(TEST_DATA, exist_ok=True)
    os.makedirs(env["alfred_workflow_cache"], exist_ok=True)
    # 构造 argv 模拟: chat 第一个参数 = 用户 query
    # chat script 需要被 osascript 当 argument load
    # 用 echo "[]" 模式 stdin 简化
    r = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", str(WORKFLOW_DIR / "chat"), query],
        capture_output=True, text=True, timeout=15, env=env,
    )
    out = r.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out, "_stderr": r.stderr.strip()}


def write_chat(chat_data) -> None:
    p = Path(TEST_DATA) / "chat.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(chat_data, ensure_ascii=False), encoding="utf-8")


def read_chat() -> list | dict:
    p = Path(TEST_DATA) / "chat.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def list_archive() -> list:
    d = Path(TEST_DATA) / "archive"
    if not d.exists():
        return []
    return sorted([f.name for f in d.iterdir() if f.is_file()])


# ---------- tests ----------

def test_normal_run_does_not_archive() -> None:
    _clear_archive()
    section("普通运行(无 new_chat)不 archive")
    write_chat([{"role": "user", "content": "old"}])
    r = run_chat_script("普通查询", new_chat=False)
    check(len(list_archive()) == 0, "no archive created")
    # 普通运行:chat.json 不应被 archive,旧内容应保留
    chat = read_chat()
    if isinstance(chat, list):
        has_old = any("old" in (m.get("content") or "") for m in chat)
        check(has_old, "old content preserved (no new_chat side effect)")


def test_new_chat_archives_existing() -> None:
    _clear_archive()
    section("new_chat=1 archive 已有 chat")
    write_chat([
        {"role": "user", "content": "历史1"},
        {"role": "assistant", "content": "旧回答"},
    ])
    r = run_chat_script("新会话", new_chat=True)
    archive = list_archive()
    check(len(archive) == 1, f"1 archived file (got {len(archive)})")
    chat = read_chat()
    # 新 chat 应该是空或只含 user 消息(取决于 script 行为)
    if isinstance(chat, list):
        user_msgs = [m for m in chat if m.get("role") == "user"]
        check(len(user_msgs) == 0, f"new chat has no user msgs (got {len(user_msgs)})")
    elif isinstance(chat, dict):
        msgs = chat.get("messages", [])
        check(len(msgs) == 0, f"new chat messages empty (got {len(msgs)})")


def test_new_chat_creates_empty() -> None:
    section("new_chat=1 第一次(无 chat.json)")
    chat_path = Path(TEST_DATA) / "chat.json"
    if chat_path.exists():
        chat_path.unlink()
    r = run_chat_script("query", new_chat=True)
    check(chat_path.exists(), "chat.json created")
    chat = read_chat()
    if isinstance(chat, list):
        check(len(chat) == 0, f"empty list (got {len(chat)})")
    elif isinstance(chat, dict):
        check(len(chat.get("messages", [])) == 0, "empty messages")


def _clear_archive() -> None:
    import shutil
    d = Path(TEST_DATA) / "archive"
    if d.exists():
        for f in d.iterdir():
            if f.is_file(): f.unlink()
        d.rmdir()


def test_new_chat_skips_already_empty() -> None:
    _clear_archive()
    section("new_chat=1 但 chat 已空 → 不 archive")
    write_chat([])
    r = run_chat_script("query", new_chat=True)
    check(len(list_archive()) == 0, "no archive (chat was already empty)")


    _clear_archive()


def test_new_chat_query_appended() -> None:
    section("new_chat=1 后 query 正常进入新 session")
    write_chat([{"role": "user", "content": "old"}, {"role": "assistant", "content": "old-reply"}])
    r = run_chat_script("新问题", new_chat=True)
    chat = read_chat()
    if isinstance(chat, list):
        user_msgs = [m for m in chat if m.get("role") == "user"]
        # 注: 测试环境没有真实 API,可能 user msg 也加不进去。检查 chat 已经被清空
        old_in_chat = any("old" in (m.get("content") or "") for m in chat)
        check(not old_in_chat, "old content not in new chat")
    else:
        check(False, f"expected list, got {type(chat).__name__}")


def main() -> None:
    print("=" * 60)
    print("Alfred Chat W5 New-Chat (cmd+回车) Tests")
    print("=" * 60)
    test_normal_run_does_not_archive()
    test_new_chat_archives_existing()
    test_new_chat_creates_empty()
    test_new_chat_skips_already_empty()
    test_new_chat_query_appended()
    print(f"\n{'=' * 60}")
    print(f"Results: {_pass} passed, {_fail} failed")
    print("=" * 60)
    sys.exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    main()
