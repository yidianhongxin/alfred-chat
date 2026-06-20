#!/usr/bin/env python3
"""Test the agent_tools/ tool registry (W1 减法版).

覆盖:
- 导入 registry,3 个工具都被注册
- --tool-list 输出正确
- --tool-schema 输出符合 OpenAI function-calling 风格
- --tool '{"tool":"file_read",...}' 走 registry
- --tool '{"tool":"obsidian_read",...}' 走旧 if-elif 链(fallthrough)
- --tool '{"tool":"unknown",...}' 走旧链(返回 handled=False)
- 路径护栏正常
- 错误处理(无效 JSON / 缺参数)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / "Workflow"
PY = sys.executable


def run(args: list[str], expect_json: bool = True) -> dict | str:
    """Run python local_agent.py with given args, return parsed JSON or raw text."""
    result = subprocess.run(
        [PY, str(WORKFLOW_DIR / "local_agent.py"), *args],
        capture_output=True, text=True, timeout=30,
    )
    output = result.stdout.strip()
    if not expect_json:
        return output
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"_raw": output, "_stderr": result.stderr.strip()}


def assert_eq(actual, expected, label: str) -> None:
    if actual == expected:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        print(f"    expected: {expected!r}")
        print(f"    actual:   {actual!r}")
        sys.exit(1)


def assert_in(needle, haystack, label: str) -> None:
    if needle in haystack:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        print(f"    needle:   {needle!r}")
        print(f"    haystack: {haystack[:200]!r}")
        sys.exit(1)


def main() -> None:
    print("=" * 60)
    print("Test 1: --tool-list returns 3 registered tools")
    print("=" * 60)
    out = run(["--tool-list"], expect_json=True)
    # W2 added 12 more tools, so we check membership rather than exact list
    names = out["names"]
    for required in ("file_read", "memory", "obsidian_search"):
        assert_in(required, names, f"required tool {required} present")
    # toolsets should include at least the 3 from W1 (may have more after W2)
    toolsets = set(out["toolsets"].keys())
    for required in ("file", "memory", "obsidian"):
        assert_in(required, toolsets, f"required toolset {required} present")
    print()

    print("=" * 60)
    print("Test 2: --tool-schema returns OpenAI-style schemas")
    print("=" * 60)
    out = run(["--tool-schema"], expect_json=False)
    schemas = json.loads(out)
    assert len(schemas) >= 3, f"schema count should be >= 3 (got {len(schemas)})"
    file_read_schema = next(s for s in schemas if s["name"] == "file_read")
    assert_eq(file_read_schema["toolset"], "file", "file_read toolset")
    assert_eq(file_read_schema["parameters"]["required"], ["path"], "file_read required")
    assert_in("\"type\": \"object\"", json.dumps(file_read_schema, ensure_ascii=False), "JSON schema structure")
    print()

    print("=" * 60)
    print("Test 3: --tool with registered tool (file_read) goes through registry")
    print("=" * 60)
    out = run(["--tool", json.dumps({"tool": "file_read", "args": {"path": "/Users/DRLer/.zshrc"}})], expect_json=True)
    assert_eq(out.get("handled"), True, "handled flag")
    assert_eq(out.get("status"), "success", "status")
    assert_eq(out.get("tool"), "file_read", "echoed tool name")
    assert_in("export LANG", out.get("assistant_text", ""), "file content present")
    print()

    print("=" * 60)
    print("Test 4: --tool with NOT-registered tool (obsidian_read) falls through to old chain")
    print("=" * 60)
    out = run(["--tool", json.dumps({"tool": "obsidian_read", "args": {"path": "0.inbox/Alfred Chat 借鉴 Hermes 升级方案.md"}})], expect_json=True)
    assert_eq(out.get("handled"), True, "handled flag")
    assert_eq(out.get("status"), "success", "status")
    assert_eq(out.get("tool"), "obsidian_read", "echoed tool name")
    assert_in("OB 文件", out.get("assistant_text", ""), "old chain response marker")
    print()

    print("=" * 60)
    print("Test 5: --tool with memory tool uses registry")
    print("=" * 60)
    out = run(["--tool", json.dumps({"tool": "memory", "args": {"action": "list"}})], expect_json=True)
    assert_eq(out.get("handled"), True, "handled flag")
    assert_eq(out.get("status"), "success", "status")
    assert_eq(out.get("tool"), "memory", "echoed tool name")
    assert_in("USER", out.get("assistant_text", ""), "memory USER section")
    print()

    print("=" * 60)
    print("Test 6: --tool with invalid JSON returns error")
    print("=" * 60)
    out = run(["--tool", "not-valid-json"], expect_json=True)
    assert_eq(out.get("handled"), True, "handled flag (script handles it)")
    assert_eq(out.get("status"), "error", "error status")
    assert_in("JSON 解析失败", out.get("assistant_text", ""), "error message")
    print()

    print("=" * 60)
    print("Test 7: --tool with non-registered unknown tool returns handled=False")
    print("=" * 60)
    out = run(["--tool", json.dumps({"tool": "totally_fake_tool_xyz", "args": {}})], expect_json=True)
    assert_eq(out.get("handled"), False, "handled flag should be False")
    print()

    print("=" * 60)
    print("Test 8: Path guard works on registered tool (file_read rejects /etc/passwd)")
    print("=" * 60)
    out = run(["--tool", json.dumps({"tool": "file_read", "args": {"path": "/etc/passwd"}})], expect_json=True)
    assert_eq(out.get("status"), "error", "error status")
    assert_in("不存在或无权限", out.get("assistant_text", ""), "guard message")
    print()

    print("=" * 60)
    print("Test 9: memory.add writes to MEMORY/USER")
    print("=" * 60)
    test_entry = "W1-registry-test-2026-06-19"
    out = run(["--tool", json.dumps({"tool": "memory", "args": {"action": "add", "target": "user", "content": test_entry}})], expect_json=True)
    assert_eq(out.get("status"), "success", "add success")
    # Verify it's there
    out2 = run(["--tool", json.dumps({"tool": "memory", "args": {"action": "list"}})], expect_json=True)
    assert_in(test_entry, out2.get("assistant_text", ""), "entry visible in list")
    # Cleanup
    run(["--tool", json.dumps({"tool": "memory", "args": {"action": "remove", "target": "user", "content": test_entry}})], expect_json=True)
    print("  (cleanup done)")
    print()

    print("=" * 60)
    print("All tests passed ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
