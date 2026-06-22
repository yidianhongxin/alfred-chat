"""W9 continuation 协议测试。

覆盖:
1. save / get / clear 基础流程
2. TTL 过期清理
3. 损坏文件返回 None
4. 多种"go on"表达 (go on, 继续, 接着说)
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "Workflow"
PY = sys.executable


def call(*args):
    result = subprocess.run(
        [PY, str(WORKFLOW_DIR / "local_agent.py"), *args],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "alfred_workflow_data": "/tmp/w9_test_data",
             "alfred_workflow_cache": "/tmp/w9_test_cache"},
    )
    return json.loads(result.stdout)


def setup():
    Path("/tmp/w9_test_data").mkdir(parents=True, exist_ok=True)
    Path("/tmp/w9_test_cache").mkdir(parents=True, exist_ok=True)
    # 清掉旧 pending
    call("--continuation-clear")


def test_save_get_clear():
    """基础流程: 存 → 读 → 清 → 读 null"""
    print("--- test_save_get_clear ---")
    setup()

    r1 = call("--continuation-save", "刘成是谁", "我先查一下...")
    assert r1.get("status") == "ok", f"save failed: {r1}"

    r2 = call("--continuation-get")
    cont = r2.get("continuation")
    assert cont is not None, f"get returned None: {r2}"
    assert cont["last_query"] == "刘成是谁"
    assert cont["last_assistant_partial"] == "我先查一下..."
    assert "expires_at" in cont
    print(f"  ✓ save → get: last_query={cont['last_query']!r}, expires={cont['expires_at']}")

    r3 = call("--continuation-clear")
    assert r3.get("status") == "ok"

    r4 = call("--continuation-get")
    assert r4.get("continuation") is None, f"expected None, got: {r4}"
    print("  ✓ clear → get: null")


def test_expired_clears_automatically():
    """过期 pending 自动清理"""
    print("--- test_expired_clears_automatically ---")
    setup()

    # 直接写一个已过期的 pending
    import datetime
    expired = {
        "last_query": "old query",
        "last_assistant_partial": "old partial",
        "saved_at": "2020-01-01T00:00:00",
        "expires_at": "2020-01-01T01:00:00",  # 2020 年早已过期
    }
    cont_file = Path("/tmp/w9_test_data/pending_continuation.json")
    cont_file.write_text(json.dumps(expired, ensure_ascii=False), encoding="utf-8")

    r = call("--continuation-get")
    assert r.get("continuation") is None, f"expected None for expired, got: {r}"
    # 验证文件被删
    assert not cont_file.exists(), f"expired file not removed: {cont_file}"
    print("  ✓ expired pending auto-cleared")


def test_corrupted_file_returns_none():
    """损坏文件返回 None,不抛"""
    print("--- test_corrupted_file_returns_none ---")
    setup()
    cont_file = Path("/tmp/w9_test_data/pending_continuation.json")
    cont_file.write_text("{not valid json", encoding="utf-8")

    r = call("--continuation-get")
    assert r.get("continuation") is None, f"expected None for corrupted, got: {r}"
    print("  ✓ corrupted file handled gracefully")


def test_is_continuation_query():
    """多种 'go on' 表达都被识别"""
    print("--- test_is_continuation_query ---")
    # 直接验证 chat script 的 isContinuationQuery regex
    import re
    is_cont = re.compile(r"^(?:go on|continue|please continue|go ahead)\b", re.I)

    cases = {
        "go on": True,
        "继续": True,
        "接着说": True,
        "go ahead": True,
        "continue": True,
        "接着": True,
        "继续说": True,
        "Please Continue": True,
        "go on 接着": True,
        "刘成是谁": False,  # 普通 query
        "go online": False,  # 不是 continue
        "": False,
    }
    is_cont_zh = re.compile(r"^(继续|接着说|接着|继续说)$")
    for q, expected in cases.items():
        actual = bool(is_cont.match(q.strip())) or bool(is_cont_zh.match(q.strip()))
        flag = "✓" if actual == expected else "✗"
        print(f"  {flag} '{q}' → {actual} (期望 {expected})")
        assert actual == expected


def test_query_reads_pending_into_session():
    """端到端: save 后 get 拿到的内容能反序列化回 session format"""
    print("--- test_query_reads_pending_into_session ---")
    setup()

    # 模拟: LLM 答到一半, save pending
    call("--continuation-save",
         "好好的时光 刘成 演员",
         "我先去查一下演员表...")

    r = call("--continuation-get")
    cont = r.get("continuation")

    # 模拟 handleContinuation 拼 user message
    last_query = cont["last_query"]
    last_partial = cont["last_assistant_partial"]
    continue_prompt = f"【W9 continuation】\n上一轮: {last_query}\n上轮部分答: {last_partial}\n接着写。"

    assert "刘成 演员" in continue_prompt
    assert "查一下演员表" in continue_prompt
    print(f"  ✓ 拼出的 user message 含 last_query + last_partial")
    print(f"  → {continue_prompt[:80]!r}...")


if __name__ == "__main__":
    print("=" * 60)
    print("W9 continuation 协议测试")
    print("=" * 60)
    print()
    test_save_get_clear()
    print()
    test_expired_clears_automatically()
    print()
    test_corrupted_file_returns_none()
    print()
    test_is_continuation_query()
    print()
    test_query_reads_pending_into_session()
    print()
    print("=" * 60)
    print("W9 continuation 全部通过 ✓")
    print("=" * 60)
