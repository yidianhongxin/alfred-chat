#!/usr/bin/env python3
"""Test W6 micro-feat: rename 关键字点击最近对话 → 不空白。

模拟流程:
1. chat.json 当前内容 = X0
2. archive/ 有 X1.json(用户点的那条)
3. 模拟 F87E8DE0 跑完: chat.json ← archive/X1.json, archive/X0.json ← 原 chat.json
4. 模拟 8296D113 覆盖 new_chat=1 + 把 replace_with_chat=X1 传下去
5. Workflow/chat 运行
6. 期望: chat.json 仍是 X1(不是空 []), archive/ 没有再添 X1 副本
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / "Workflow"
TEST_DATA = "/tmp/alfred-chat-w6-test"

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


def reset() -> None:
    if Path(TEST_DATA).exists():
        shutil.rmtree(TEST_DATA)
    Path(TEST_DATA).mkdir(parents=True)
    Path(TEST_DATA, "archive").mkdir()


def write_chat(chat_data) -> None:
    p = Path(TEST_DATA) / "chat.json"
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


def run_chat_script(query: str = "", env_extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env["alfred_workflow_data"] = TEST_DATA
    env["alfred_workflow_cache"] = "/tmp/alfred-chat-w6-test-cache"
    env["max_context"] = "20"
    env["timeout_seconds"] = "30"
    if env_extra:
        env.update(env_extra)
    os.makedirs(env["alfred_workflow_cache"], exist_ok=True)
    r = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", str(WORKFLOW_DIR / "chat"), query],
        capture_output=True, text=True, timeout=15, env=env,
    )
    out = r.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out, "_stderr": r.stderr.strip()}


# ---------- tests ----------

def test_rename_click_does_not_wipe() -> None:
    """rename 关键字点击最近对话 → chat.json 应保留原 archive 内容,不被 ensureFreshChat 清空。"""
    section("rename 关键字点击最近对话 → 不再空白")
    reset()

    # 1) 准备: archive/ 有 X1.json(用户要 load 的旧对话)
    x1 = [
        {"role": "user", "content": "X1 第一条问题"},
        {"role": "assistant", "content": "X1 旧回答"},
    ]
    archive_path = Path(TEST_DATA) / "archive" / "2026.06.19.12.00.00-loadme.json"
    archive_path.write_text(json.dumps(x1, ensure_ascii=False), encoding="utf-8")

    # 2) 准备: 当前 chat.json 有 X0(刚进行中的对话,会被 F87E8DE0 归档)
    write_chat([
        {"role": "user", "content": "X0 当前问"},
        {"role": "assistant", "content": "X0 当前答"},
    ])

    # 3) 模拟 F87E8DE0 跑完: archive current → archive/<ts>.json; move X1 → chat.json
    current_chat = Path(TEST_DATA) / "chat.json"
    archived_old = Path(TEST_DATA) / "archive" / "2026.06.19.23.50.00-oldchat.json"
    shutil.move(str(current_chat), str(archived_old))
    shutil.move(str(archive_path), str(current_chat))

    # 4) 模拟 rename 关键字 → new_chat trigger → 8296D113 覆盖 new_chat=1,
    #    replace_with_chat 仍指 X1(模拟 plist 变量流)
    r = run_chat_script("", env_extra={
        "new_chat": "1",
        "replace_with_chat": str(current_chat),  # 实际指向 chat.json (F87E8DE0 刚 move 过来)
    })

    # 5) 验证
    chat = read_chat()
    if isinstance(chat, list):
        contents = " ".join((m.get("content") or "") for m in chat)
        check("X1 第一条问题" in contents, "chat.json 保留 X1 第一条问题(没被清空)")
        check("X1 旧回答" in contents, "chat.json 保留 X1 旧回答")
        check("X0 当前" not in contents, "X0 没混入当前 chat.json")
    else:
        check(False, f"expected list chat, got {type(chat).__name__}")

    archive_files = list_archive()
    check(len(archive_files) == 1, f"archive/ 只有 1 个文件(原 X0),got {len(archive_files)}: {archive_files}")
    if archive_files:
        check("oldchat" in archive_files[0], f"归档的是 X0 (oldchat), not X1 re-archive")

    # 6) 验证 run 输出把 replace_with_chat 清空(防止下次 Cmd+回车 残留)
    if isinstance(r, dict) and "variables" in r:
        check(r["variables"].get("replace_with_chat") == "", "run 输出清空 replace_with_chat")
        check(r["variables"].get("new_chat") == "0", "run 输出清空 new_chat")
    else:
        check(False, f"run output has variables field, got {type(r).__name__}: {r}")


def test_replace_with_chat_takes_precedence_over_new_chat() -> None:
    """replace_with_chat + new_chat=1 同时存在时,不应归档(load 而非开新)。"""
    section("replace_with_chat 优先级高于 new_chat")
    reset()

    # archive 里有 X1
    x1 = [{"role": "user", "content": "X1 question"}, {"role": "assistant", "content": "X1 answer"}]
    (Path(TEST_DATA) / "archive" / "x1.json").write_text(json.dumps(x1), encoding="utf-8")

    # chat.json 有 X0
    write_chat([{"role": "user", "content": "X0"}])

    # 模拟 F87E8DE0 完成 swap
    shutil.move(str(Path(TEST_DATA) / "chat.json"), str(Path(TEST_DATA) / "archive" / "x0.json"))
    shutil.move(str(Path(TEST_DATA) / "archive" / "x1.json"), str(Path(TEST_DATA) / "chat.json"))

    r = run_chat_script("", env_extra={"new_chat": "1", "replace_with_chat": "/some/x1.json"})

    chat = read_chat()
    if isinstance(chat, list):
        contents = " ".join((m.get("content") or "") for m in chat)
        check("X1 question" in contents, "X1 内容保留")
    check(len(list_archive()) == 1, "archive 数量不变 (X0 已存,X1 没被重复归档)")


def test_normal_cmd_enter_still_works() -> None:
    """回归保险:Cmd+回车 不带 replace_with_chat 时,应正常归档并清空。"""
    section("Cmd+回车 (无 replace_with_chat) 仍能正常归档")
    reset()

    write_chat([
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
    ])

    r = run_chat_script("new question", env_extra={"new_chat": "1"})

    archive = list_archive()
    check(len(archive) == 1, f"1 archive file (got {len(archive)})")
    chat = read_chat()
    if isinstance(chat, list):
        contents = " ".join((m.get("content") or "") for m in chat)
        check("old question" not in contents, "old content wiped on Cmd+回车")
    else:
        check(False, f"expected list chat, got {type(chat).__name__}")


def test_load_then_cmd_enter_starts_new() -> None:
    """回归保险:load 一个最近对话后,Cmd+回车 应该正常开新(不残留 replace_with_chat)。"""
    section("load 后 Cmd+回车 → 正常开新 (无残留)")
    reset()

    # 准备 archive/X1
    x1 = [{"role": "user", "content": "X1 q"}, {"role": "assistant", "content": "X1 a"}]
    (Path(TEST_DATA) / "archive" / "x1.json").write_text(json.dumps(x1), encoding="utf-8")

    # 准备 chat.json = X0
    write_chat([{"role": "user", "content": "X0"}])

    # 模拟 F87E8DE0 swap
    shutil.move(str(Path(TEST_DATA) / "chat.json"), str(Path(TEST_DATA) / "archive" / "x0.json"))
    shutil.move(str(Path(TEST_DATA) / "archive" / "x1.json"), str(Path(TEST_DATA) / "chat.json"))

    # 第一次:rename click → new_chat=1 + replace_with_chat
    r1 = run_chat_script("", env_extra={"new_chat": "1", "replace_with_chat": "/x1.json"})
    chat = read_chat()
    if isinstance(chat, list):
        contents = " ".join((m.get("content") or "") for m in chat)
        check("X1 q" in contents, "第一次 load: X1 在 chat.json 里")

    # 第二次:用户输入 + Cmd+回车 → new_chat=1, replace_with_chat 应已被清空
    r2 = run_chat_script("next question", env_extra={"new_chat": "1"})
    archive = list_archive()
    # 期望: archive 里有 X0 和 X1(now archived because user hit Cmd+回车)
    check(len(archive) == 2, f"archive 有 2 个 (X0 旧 + X1 因 Cmd+回车 被归档),got {len(archive)}")
    chat2 = read_chat()
    if isinstance(chat2, list):
        contents = " ".join((m.get("content") or "") for m in chat2)
        check("X1" not in contents, "Cmd+回车 后 X1 被归档,chat.json 不含 X1")


def main() -> None:
    print("=" * 60)
    print("Alfred Chat W6: rename → recent chat 不空白")
    print("=" * 60)
    test_rename_click_does_not_wipe()
    test_replace_with_chat_takes_precedence_over_new_chat()
    test_normal_cmd_enter_still_works()
    test_load_then_cmd_enter_starts_new()
    print(f"\n{'=' * 60}")
    print(f"Results: {_pass} passed, {_fail} failed")
    print("=" * 60)
    sys.exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    main()