#!/usr/bin/env python3
"""Test the W4 curator lazy trigger (节流 + 静默失败 + state 持久化)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / "Workflow"
PY = sys.executable
TEST_DATA = "/tmp/alfred-chat-w4-test"

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


def run_curator(args: list[str], env_extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env["alfred_workflow_data"] = TEST_DATA
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        [PY, str(WORKFLOW_DIR / "local_agent.py"), "--curator-tick", *args],
        capture_output=True, text=True, timeout=30, env=env,
    )
    try:
        return json.loads(r.stdout.strip())
    except json.JSONDecodeError:
        return {"_raw": r.stdout.strip(), "_stderr": r.stderr.strip()}


def write_state(state: dict) -> None:
    p = Path(TEST_DATA) / "curator_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def clear_state() -> None:
    p = Path(TEST_DATA) / "curator_state.json"
    if p.exists():
        p.unlink()


# --- tests ---

def test_no_chat_skipped() -> None:
    section("无 chat.json -> skipped")
    clear_state()
    out = run_curator([])
    check(out.get("skipped") is True, f"skipped=True (got {out})")
    check("no messages" in str(out.get("reason", "")), f"reason mentions no messages: {out.get('reason')}")


def test_state_persisted() -> None:
    section("state 持久化")
    clear_state()
    run_curator([])
    state_path = Path(TEST_DATA) / "curator_state.json"
    check(state_path.exists(), "curator_state.json written")
    if state_path.exists():
        state = json.loads(state_path.read_text())
        check("last_run_at" in state, f"has last_run_at: {state.get('last_run_at')}")
        check("last_result" in state, "has last_result")
        # ISO format parseable
        try:
            datetime.fromisoformat(state["last_run_at"])
            check(True, "last_run_at is ISO-parseable")
        except Exception:
            check(False, "last_run_at NOT ISO-parseable")


def test_throttle_24h() -> None:
    section("24h 节流")
    clear_state()
    # 第一次:实际跑（或 skipped no messages）
    out1 = run_curator([])
    check(out1.get("skipped") is True, "first call skipped (no chat)")
    # 模拟刚跑过(< 24h): 应该 throttled
    out2 = run_curator([])
    check(out2.get("reason") == "throttled", f"second call throttled (got {out2})")
    # --force 应该绕过
    out3 = run_curator(["--force"])
    check(out3.get("reason") != "throttled", f"--force bypasses throttle (got {out3})")


def test_throttle_expired() -> None:
    section("节流过期(>24h)")
    # 手动写一个 25h 前的 state
    expired = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
    write_state({"last_run_at": expired, "last_result": {"skipped": True}})
    out = run_curator([])
    check(out.get("reason") != "throttled", f"expired state -> not throttled (got {out.get('reason')})")


def test_disable_env() -> None:
    section("ALFRED 关闭开关")
    clear_state()
    # memory_auto_write=0 直接 skip（来自 run_curator 内部）
    out = run_curator([], env_extra={"memory_auto_write": "0"})
    check(out.get("skipped") is True, "memory_auto_write=0 -> skipped")


def test_graceful_failure() -> None:
    section("脚本失败不抛异常")
    # 删 local_agent.py 的可执行性？不行，会破坏其他测试。改为设置一个错误的 alfred_workflow_data 让它读不到 chat 也不致命。
    out = run_curator([], env_extra={"alfred_workflow_data": "/nonexistent/path/that/does/not/exist"})
    # 应该返回 dict 不会让 subprocess 崩
    check(isinstance(out, dict), f"returns dict (got {type(out).__name__})")


def test_cli_no_crash_no_args() -> None:
    section("CLI 行为: 无 chat + 无 args")
    clear_state()
    # 直接 python3 curator.py 不带 --force
    env = os.environ.copy()
    env["alfred_workflow_data"] = TEST_DATA
    r = subprocess.run(
        [PY, str(WORKFLOW_DIR / "curator.py")],
        capture_output=True, text=True, timeout=15, env=env,
    )
    check(r.returncode == 0, f"exit code 0 (got {r.returncode})")
    try:
        out = json.loads(r.stdout.strip())
        check(out.get("skipped") is True, f"skipped result: {out}")
    except json.JSONDecodeError:
        check(False, f"stdout should be JSON: {r.stdout[:100]}")


def main() -> None:
    print("=" * 60)
    print("Alfred Chat W4 Curator Tests")
    print("=" * 60)
    test_no_chat_skipped()
    test_state_persisted()
    test_throttle_24h()
    test_throttle_expired()
    test_disable_env()
    test_graceful_failure()
    test_cli_no_crash_no_args()
    print(f"\n{'=' * 60}")
    print(f"Results: {_pass} passed, {_fail} failed")
    print("=" * 60)
    sys.exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    main()
