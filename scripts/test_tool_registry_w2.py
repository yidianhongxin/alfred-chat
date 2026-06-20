#!/usr/bin/env python3
"""Test the agent_tools/ registry after W2 (12 new tools, enabled_toolsets filter)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / "Workflow"
PY = sys.executable


def run(args: list[str], env: dict | None = None) -> dict:
    """Run python local_agent.py with given args, return parsed JSON."""
    import os
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    result = subprocess.run(
        [PY, str(WORKFLOW_DIR / "local_agent.py"), *args],
        capture_output=True, text=True, timeout=30, env=full_env,
    )
    out = result.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out, "_stderr": result.stderr.strip()}


def assert_eq(actual, expected, label: str) -> None:
    if actual == expected:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: expected {expected!r}, got {actual!r}")
        sys.exit(1)


def assert_in(needle, haystack, label: str) -> None:
    if needle in haystack:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: needle {needle!r} not in {str(haystack)[:200]!r}")
        sys.exit(1)


def main() -> None:
    print("=" * 60)
    print("Test W2-1: --tool-list shows 15 tools (W1 3 + W2 12)")
    print("=" * 60)
    out = run(["--tool-list"])
    assert_eq(len(out["names"]), 15, "total tool count")
    expected = {
        "file_read", "memory",
        "obsidian_read", "obsidian_write", "obsidian_append", "obsidian_search",
        "obsidian_diary_browse", "obsidian_diary_recent",
        "obsidian_daily_read", "obsidian_daily_append",
        "task_add", "task_list", "task_done",
        "session_search", "reminder_add",
    }
    assert_eq(set(out["names"]), expected, "exact tool set")
    print()

    print("=" * 60)
    print("Test W2-2: obsidian_read reads a real OB file")
    print("=" * 60)
    out = run(["--tool", json.dumps({
        "tool": "obsidian_read",
        "args": {"path": "0.inbox/Alfred Chat 不该借鉴 Hermes 的能力.md"}
    })])
    assert_eq(out.get("status"), "success", "status")
    assert_in("OB 文件", out.get("assistant_text", ""), "marker present")
    assert_in("不该借鉴", out.get("assistant_text", ""), "content present")
    print()

    print("=" * 60)
    print("Test W2-3: obsidian_read rejects path outside vault")
    print("=" * 60)
    out = run(["--tool", json.dumps({"tool": "obsidian_read", "args": {"path": "/etc/passwd"}})])
    assert_eq(out.get("status"), "error", "status")
    assert_in("只允许", out.get("assistant_text", ""), "guard message")
    print()

    print("=" * 60)
    print("Test W2-4: obsidian_write + obsidian_append (round-trip)")
    print("=" * 60)
    test_path = "0.inbox/w2_test_registry.md"
    out = run(["--tool", json.dumps({
        "tool": "obsidian_write",
        "args": {"path": test_path, "content": "# W2 Test\n\nHello from registry"}
    })])
    assert_eq(out.get("status"), "success", "write status")
    out2 = run(["--tool", json.dumps({
        "tool": "obsidian_append",
        "args": {"path": test_path, "content": "\n## Appended\n\nMore content"}
    })])
    assert_eq(out2.get("status"), "success", "append status")
    # Read back
    out3 = run(["--tool", json.dumps({"tool": "obsidian_read", "args": {"path": test_path}})])
    body = out3.get("assistant_text", "")
    assert_in("Hello from registry", body, "original content preserved")
    assert_in("More content", body, "appended content present")
    # Cleanup
    test_file = ROOT.parent / "Obsidian_250614" / test_path
    if test_file.exists():
        test_file.unlink()
        print("  (test file cleaned up)")
    print()

    print("=" * 60)
    print("Test W2-5: task_add / task_list / task_done end-to-end")
    print("=" * 60)
    out = run(["--tool", json.dumps({"tool": "task_add", "args": {"text": "W2-registry-test-task"}})])
    assert_eq(out.get("status"), "success", "add status")
    # extract task id: response is like "已新增任务 4:W2-registry-test-task"
    import re
    m = re.search(r"\d+", out.get("assistant_text", ""))
    assert m is not None, f"could not extract task id from {out.get('assistant_text', '')!r}"
    task_id = int(m.group(0))
    print(f"  (created task id: {task_id})")
    out2 = run(["--tool", json.dumps({"tool": "task_list", "args": {}})])
    assert_in("W2-registry-test-task", out2.get("assistant_text", ""), "task visible in list")
    out3 = run(["--tool", json.dumps({"tool": "task_done", "args": {"id": task_id}})])
    assert_eq(out3.get("status"), "success", "done status")
    out4 = run(["--tool", json.dumps({"tool": "task_list", "args": {}})])
    assert_in(f"{task_id}. [x]", out4.get("assistant_text", ""), "task marked done")
    print()

    print("=" * 60)
    print("Test W2-6: session_search works (no crash even if no results)")
    print("=" * 60)
    out = run(["--tool", json.dumps({"tool": "session_search", "args": {"term": "W2-registry-unlikely-term-xyz"}})])
    assert_eq(out.get("handled"), True, "handled")
    assert_eq(out.get("status"), "success", "status")
    print()

    print("=" * 60)
    print("Test W2-7: enabled_toolsets=obsidian filters schema")
    print("=" * 60)
    out = run(["--tool-schema"], env={"enabled_toolsets": "obsidian"})
    schemas = json.loads(out.stdout.strip() if hasattr(out, "stdout") else json.dumps(out))
    # handle both raw text and parsed
    if "_raw" in out:
        schemas = json.loads(out["_raw"])
    toolsets = sorted({s["toolset"] for s in schemas})
    assert_eq(toolsets, ["obsidian"], "only obsidian toolset")
    print()

    print("=" * 60)
    print("Test W2-8: enabled_toolsets=file blocks obsidian_*")
    print("=" * 60)
    out = run(["--tool", json.dumps({
        "tool": "obsidian_search",
        "args": {"term": "test"}
    })], env={"enabled_toolsets": "file"})
    assert_eq(out.get("status"), "error", "blocked status")
    assert_in("已被禁用", out.get("assistant_text", ""), "block message")
    print()

    print("=" * 60)
    print("Test W2-9: enabled_toolsets=file allows file_read")
    print("=" * 60)
    out = run(["--tool", json.dumps({
        "tool": "file_read",
        "args": {"path": "/Users/DRLer/.zshrc"}
    })], env={"enabled_toolsets": "file"})
    assert_eq(out.get("status"), "success", "status")
    print()

    print("=" * 60)
    print("Test W2-10: unknown toolset value passes through (all enabled)")
    print("=" * 60)
    out = run(["--tool", json.dumps({
        "tool": "obsidian_search",
        "args": {"term": "hermes"}
    })], env={"enabled_toolsets": "all"})
    assert_eq(out.get("status"), "success", "status (all = no filter)")
    print()

    print("=" * 60)
    print("All W2 tests passed ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
