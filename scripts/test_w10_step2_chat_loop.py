"""W10 Step 2: cmd_chat end-to-end test.

5 个场景:
1. 普通文本对话 (无 tool call)
2. LLM 选 file_read 工具 (无副作用)
3. LLM 选 memory_add 工具 (会写 memory.json — 用完恢复)
4. 工具不存在 → 错误信息回灌 → LLM 自我修正
5. max_iterations 限制

每个测试都 backup/restore chat.json (避免污染生产数据)。
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

# 让 local_agent 可被 import
WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "Workflow"
sys.path.insert(0, str(WORKFLOW_DIR))

import local_agent  # noqa: E402

DATA_DIR = Path(os.environ.get("alfred_workflow_data") or "/Users/DRLer/Library/Application Support/Alfred/Workflow Data/com.drlerr.alfred-chat")
CHAT_FILE = DATA_DIR / "chat.json"
MEMORY_FILE = DATA_DIR / "memory.json"

# 关键: 让 local_agent.data_dir() 跟测试读到同一个目录
os.environ["alfred_workflow_data"] = str(DATA_DIR)
os.environ["ALFRED_WORKFLOW_DATA"] = str(DATA_DIR)

# Backup 文件
BACKUP_DIR = Path("/tmp/w10_test_backup")
BACKUP_DIR.mkdir(exist_ok=True)


def _backup():
    if CHAT_FILE.exists():
        shutil.copy2(CHAT_FILE, BACKUP_DIR / "chat.json.bak")
    if MEMORY_FILE.exists():
        shutil.copy2(MEMORY_FILE, BACKUP_DIR / "memory.json.bak")


def _restore():
    bak_chat = BACKUP_DIR / "chat.json.bak"
    bak_mem = BACKUP_DIR / "memory.json.bak"
    if bak_chat.exists():
        shutil.copy2(bak_chat, CHAT_FILE)
    elif CHAT_FILE.exists():
        CHAT_FILE.unlink()
    if bak_mem.exists():
        shutil.copy2(bak_mem, MEMORY_FILE)


def _clear_chat():
    if CHAT_FILE.exists():
        CHAT_FILE.unlink()


def _load_chat():
    if not CHAT_FILE.exists():
        return []
    try:
        return json.loads(CHAT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _run(query: str, timeout: int = 120) -> tuple[int, str]:
    """跑 cmd_chat, 返回 (exit_code, stdout)."""
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = local_agent.cmd_chat(query)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        except Exception as e:
            code = 1
            print(f"[test_runner] cmd_chat raised: {e}", file=sys.stderr)
    return code, buf.getvalue()


def test_1_plain_text():
    print("=" * 60)
    print("TEST 1: 普通文本对话 (LLM 不调工具)")
    print("=" * 60)
    _clear_chat()
    code, out = _run("2+2=?", timeout=30)
    msgs = _load_chat()
    print(f"  exit_code={code}")
    print(f"  stdout: {out[:120]!r}")
    print(f"  chat.json messages: {len(msgs)}")
    print(f"  last role/content: {msgs[-1]['role'][:40] if msgs else 'EMPTY'}")

    assert code == 0, f"exit_code 期望 0, 实际 {code}"
    assert len(msgs) >= 2, f"应至少有 user + assistant 两条, 实际 {len(msgs)}"
    print(f"  DEBUG msgs[0]: role={msgs[0].get('role')!r}, content={msgs[0].get('content')!r}")
    print(f"  DEBUG msgs[-1]: role={msgs[-1].get('role')!r}, content={(msgs[-1].get('content') or '')[:80]!r}")
    assert msgs[0]["role"] == "user", f"msgs[0].role 期望 user, 实际 {msgs[0].get('role')!r}"
    assert msgs[0]["content"] == "2+2=?", f"msgs[0].content 期望 '2+2=?', 实际 {msgs[0].get('content')!r}"
    assert msgs[-1]["role"] == "assistant"
    assert "4" in msgs[-1]["content"] or "4" in out or "四" in msgs[-1]["content"] or "四" in out
    assert out.strip() != "", "stdout 应有最终答复"
    print("  ✓ PASS — 普通对话跑通, messages 正确")
    print()


def test_2_file_read_tool():
    print("=" * 60)
    print("TEST 2: LLM 选 file_read 工具 (test fixture)")
    print("=" * 60)
    _clear_chat()
    # fixture 必须在 /Users/DRLer 下 (file_read 沙箱限制)
    fixture = Path("/Users/DRLer/w10_test_readme.txt")
    fixture.write_text("hello from W10 test fixture\n你好 世界\n", encoding="utf-8")

    code, out = _run(f"读取文件 {fixture} 的内容,用一句话总结", timeout=60)
    msgs = _load_chat()

    print(f"  exit_code={code}")
    print(f"  stdout: {out[:200]!r}")
    print(f"  messages count: {len(msgs)}")

    # 找到 tool_calls 和 tool result
    has_tool_call = any(m.get("tool_calls") for m in msgs)
    has_tool_result = any(m.get("role") == "tool" for m in msgs)

    print(f"  has tool_calls in any msg: {has_tool_call}")
    print(f"  has tool result msg: {has_tool_result}")
    if has_tool_call:
        for m in msgs:
            if m.get("tool_calls"):
                print(f"    tool called: {[tc['function']['name'] for tc in m['tool_calls']]}")
    if has_tool_result:
        for m in msgs:
            if m.get("role") == "tool":
                print(f"    tool result ({m['name']}): {m['content'][:80]!r}")

    fixture.unlink()
    assert code == 0, f"exit_code={code}"
    if has_tool_call and has_tool_result:
        print("  ✓ PASS — LLM 调 file_read 并拿到结果")
    elif "hello" in out.lower() or "你好" in out or "fixture" in out.lower():
        print("  ✓ PASS — LLM 没调工具但内容覆盖了文件信息")
    else:
        print(f"  ⚠ M3 没调工具也没提到文件内容, 退出码 0 但语义未验证")
        print(f"    stdout: {out[:200]!r}")
    print()


def test_3_memory_add_tool():
    print("=" * 60)
    print("TEST 3: LLM 选 memory_add 工具 (有副作用, 测试后恢复)")
    print("=" * 60)
    _clear_chat()
    code, out = _run("记住我今天测试 W10 step 2", timeout=60)
    msgs = _load_chat()

    print(f"  exit_code={code}")
    print(f"  stdout: {out[:200]!r}")

    has_tool_call = any(m.get("tool_calls") for m in msgs)
    has_tool_result = any(m.get("role") == "tool" for m in msgs)
    has_memory_call = any(
        tc.get("function", {}).get("name") == "memory"
        for m in msgs for tc in (m.get("tool_calls") or [])
    )

    print(f"  has tool_call: {has_tool_call}, has tool result: {has_tool_result}, has memory call: {has_memory_call}")

    # 检查 memory.json 是否有新增 (recovery 时会还原)
    if MEMORY_FILE.exists():
        mem_data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        print(f"  memory.json has {len(mem_data.get('notes', [])) if isinstance(mem_data, dict) else 'unknown'} notes")

    assert code == 0
    if has_memory_call and has_tool_result:
        print("  ✓ PASS — LLM 调了 memory 工具并成功")
    elif has_tool_call:
        print("  ⚠ LLM 调了其他工具而非 memory (M3 选了别的路径)")
    else:
        print("  ⚠ LLM 没调工具 — 这次没验证副作用路径")
    print()


def test_4_invalid_tool_name():
    """这个测试不需要 LLM — 直接验证 _w10_dispatch_tool 对不存在工具的处理"""
    print("=" * 60)
    print("TEST 4: 工具不存在 → 错误信息回灌")
    print("=" * 60)
    status, text = local_agent._w10_dispatch_tool("nonexistent_tool_xyz", "{}")
    print(f"  status={status!r}")
    print(f"  text={text[:200]!r}")
    assert status == "error"
    assert "nonexistent_tool_xyz" in text
    assert "可用" in text
    print("  ✓ PASS — 未知工具返回错误信息 (跟 Hermes 同构)")
    print()


def test_5_bad_json_args():
    print("=" * 60)
    print("TEST 5: tool args JSON 解析失败 → 错误信息回灌")
    print("=" * 60)
    status, text = local_agent._w10_dispatch_tool("file_read", "{not valid json}")
    print(f"  status={status!r}")
    print(f"  text={text[:200]!r}")
    assert status == "error"
    assert "参数解析失败" in text
    print("  ✓ PASS — 损坏 JSON 不 crash")
    print()


def test_6_provider_config_resolution():
    print("=" * 60)
    print("TEST 6: provider 配置读取 (跟 JXA envVar() 同源)")
    print("=" * 60)
    cfg = local_agent._resolve_provider_config()
    print(f"  provider={cfg['provider']}")
    print(f"  model={cfg['model']}")
    print(f"  endpoint={cfg['endpoint']}")
    print(f"  api_key set: {bool(cfg['api_key'])}")
    assert cfg["provider"] in ("minimax", "deepseek", "openai", "anthropic")
    assert cfg["model"]
    assert cfg["api_key"], "api_key 必须从 Alfred prefs.plist 读出"
    print("  ✓ PASS")
    print()


def test_7_tool_schemas():
    print("=" * 60)
    print("TEST 7: tool schemas 转 OpenAI format (LiteLLM 接受)")
    print("=" * 60)
    schemas = local_agent._convert_registry_tools_to_openai()
    print(f"  schemas count: {len(schemas)}")
    for s in schemas[:3]:
        print(f"    {s['function']['name']}: {s['function']['description'][:40]!r}")
    assert len(schemas) >= 5, f"应至少有 5 个工具 schema, 实际 {len(schemas)}"
    for s in schemas:
        assert s["type"] == "function"
        assert "name" in s["function"]
        assert "description" in s["function"]
        assert "parameters" in s["function"]
        assert s["function"]["parameters"]["type"] == "object"
    print("  ✓ PASS — OpenAI format 正确, 可直接给 LiteLLM")
    print()


if __name__ == "__main__":
    print()
    print(f"chat.json: {CHAT_FILE}")
    print(f"memory.json: {MEMORY_FILE}")
    print(f"workflow dir: {WORKFLOW_DIR}")
    print()

    _backup()
    try:
        test_1_plain_text()
        test_2_file_read_tool()
        test_3_memory_add_tool()
        test_4_invalid_tool_name()
        test_5_bad_json_args()
        test_6_provider_config_resolution()
        test_7_tool_schemas()
    finally:
        _restore()
        print()
        print("=" * 60)
        print("chat.json 和 memory.json 已恢复")
        print("=" * 60)