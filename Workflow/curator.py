#!/usr/bin/env python3
"""Lightweight background skill curator (W4 — lazy + Alfred-triggered).

设计:
- 单一职责: 节流检查 + 调 run_curator() + 写 state
- 失败必须静默（绝不让 Alfred 弹错）
- 节流策略: 同一天内最多跑 1 次（除非 ALFRED_CURATOR_FORCE=1）
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

WORKFLOW_DIR = Path(__file__).resolve().parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from agent_skills.skillify import run_curator  # noqa: E402


STATE_FILE_NAME = "curator_state.json"
DEFAULT_THROTTLE_HOURS = 24


def data_dir() -> Path:
    path = Path(os.environ.get("alfred_workflow_data") or os.environ.get("ALFRED_WORKFLOW_DATA") or "/tmp/alfred-chat")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return data_dir() / STATE_FILE_NAME


def _read_state() -> Dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state: Dict[str, Any]) -> None:
    p = _state_path()
    try:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # state is best-effort


def should_run(force: bool = False) -> bool:
    """24h 节流: 同一天内最多跑 1 次。"""
    if force or os.environ.get("ALFRED_CURATOR_FORCE") == "1":
        return True
    if os.environ.get("memory_auto_write") == "0":
        return False
    state = _read_state()
    last_iso = state.get("last_run_at")
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
    except Exception:
        return True
    return datetime.now() - last > timedelta(hours=DEFAULT_THROTTLE_HOURS)


def tick(force: bool = False) -> Dict[str, Any]:
    """单次 tick: 节流检查 + 调 run_curator + 更新 state。"""
    if not should_run(force=force):
        return {"skipped": True, "reason": "throttled"}
    try:
        result = run_curator(limit=int(os.environ.get("ALFRED_CURATOR_LIMIT", "30")))
    except Exception as exc:
        # 失败必须静默（Alfred trigger 不能让用户看到崩溃）
        result = {"skipped": True, "reason": f"curator error: {exc}"}
    _write_state({
        "last_run_at": datetime.now().isoformat(timespec="seconds"),
        "last_result": result,
    })
    return result


# CLI
if __name__ == "__main__":
    force = "--force" in sys.argv
    out = tick(force=force)
    # 永远成功退出（Alfred trigger 不应看到非零码）
    try:
        print(json.dumps(out, ensure_ascii=False))
    except Exception:
        print(json.dumps({"skipped": True, "reason": "serialize failed"}))
    sys.exit(0)
