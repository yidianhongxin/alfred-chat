"""W8 harness-first 路由测试。

核心:验证 looksLikeLocalAgentQuery 改宽后,OB 写入类 query 命中 harness 路径
(而不是 LLM 路由)。这是 W8 唯一新增的逻辑,其他都是删除 W7。
"""

import json
import subprocess
import sys
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "Workflow"
PY = sys.executable


def call_local_agent(query: str) -> dict:
    """直接调 local_agent.py main() 走 parse_intent 路径。

    这个函数是 W8 真正接通的链路 — 跟 chat script 的 handleLocalFileControl
    走的是同一条 parse_intent → execute。
    """
    result = subprocess.run(
        [PY, str(WORKFLOW_DIR / "local_agent.py"), query],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw_stdout": result.stdout, "raw_stderr": result.stderr}


# 期望: 命中 harness (handled=True) 的 query
HARNESS_HIT = [
    # 你说的两类失败 case
    "写刘成笔记到 0.inbox/好好的时光-刘成.md",
    "写 0.inbox/刘成.md",
    "新建 0.inbox/好的.md",
    "写OB 0.inbox/刘成.md",
    "写OB 刘成.md",
    "把对话存到 OB 0.inbox/笔记.md",
    # W8 之前已支持的(回归测试)
    "搜索OB 刘成",
    "读取 0.inbox/好的.md",
    "记住:我今天喝咖啡了",
    "新增任务:买菜",
]

# 期望: 不命中 harness (handled=False) — 走 LLM 路径
HARNESS_MISS = [
    "刘成是个什么样的人",
    "今天天气怎么样",
    "存到 OB 库",  # 无路径,走 LLM fallback (设计)
    "写入ob笔记",  # 无路径,走 LLM fallback (设计)
    "写入 ob 库",  # 无路径,走 LLM fallback (设计)
    "帮我写一首诗",
    "summarize this: hello world",
    "什么是 Hermes agent",
]


def test_harness_hit():
    """写 OB 类 query 走 harness,handled=True"""
    for q in HARNESS_HIT:
        r = call_local_agent(q)
        handled = r.get("handled", False)
        status = r.get("status", "?")
        text = r.get("assistant_text", "")[:60]
        flag = "✓" if handled else "✗"
        print(f"  {flag} '{q[:40]}' → handled={handled} status={status} text={text!r}")
        assert handled, f"Expected handled=True, got: {r}"


def test_harness_miss():
    """普通对话 query 不命中 harness,交给 LLM"""
    for q in HARNESS_MISS:
        r = call_local_agent(q)
        handled = r.get("handled", True)
        flag = "✓" if not handled else "✗"
        print(f"  {flag} '{q[:40]}' → handled={handled}")
        assert not handled, f"Expected handled=False, got: {r}"


def test_real_obsidian_write():
    """真写一个测试文件到 OB 库,验证链路端到端。

    ⚠️ 这个测试会真写文件。用完会清理。
    """
    test_path = "0.inbox/_test_w8_harness.md"
    full_path = Path("/Users/DRLer/Obsidian_250614") / test_path
    if full_path.exists():
        full_path.unlink()

    q = f"写入OB {test_path} 内容:这是W8 harness-first 端到端测试"
    r = call_local_agent(q)
    print(f"  → handled={r.get('handled')} status={r.get('status')} text={r.get('assistant_text', '')[:80]}")

    assert r.get("handled"), f"Expected handled, got: {r}"
    assert r.get("status") == "success", f"Expected success, got: {r}"

    # 验证文件真存在
    assert full_path.exists(), f"File not created: {full_path}"
    content = full_path.read_text(encoding="utf-8")
    assert "W8 harness-first" in content, f"Content wrong: {content[:200]}"
    print(f"  ✓ 真写入 {test_path}, {len(content)} chars")

    # 清理
    full_path.unlink()
    print(f"  ✓ 清理 {test_path}")


if __name__ == "__main__":
    print("=" * 60)
    print("W8 harness-first 路由测试")
    print("=" * 60)
    print()
    print("--- test_harness_hit (期望 handled=True) ---")
    try:
        test_harness_hit()
        print("  PASS\n")
    except AssertionError as e:
        print(f"  FAIL: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}\n")
        sys.exit(1)

    print("--- test_harness_miss (期望 handled=False) ---")
    try:
        test_harness_miss()
        print("  PASS\n")
    except AssertionError as e:
        print(f"  FAIL: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}\n")
        sys.exit(1)

    print("--- test_real_obsidian_write (端到端真写 OB) ---")
    try:
        test_real_obsidian_write()
        print("  PASS\n")
    except AssertionError as e:
        print(f"  FAIL: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}\n")
        sys.exit(1)

    print("=" * 60)
    print("W8 harness-first 全部通过 ✓")
    print("=" * 60)
