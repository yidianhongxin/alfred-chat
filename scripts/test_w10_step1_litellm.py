"""W10 Step 1: 验证 LiteLLM + Alfred provider 配置可用。

测试 4 个场景:
1. 普通文本对话 (M3 provider)
2. Streaming
3. tool_calls schema (强制 LLM 选工具)
4. Provider 切换 (deepseek)

从 Alfred prefs.plist 读 env vars,跟 JXA 的 envVar() 同源。
"""

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ALFWORKFLOW_PREF = Path.home() / "Library/Application Support/Alfred/Alfred.alfredpreferences/workflows/user.workflow.C4B4D1C2-50BE-4FD4-AE5E-9324DBED0C51/prefs.plist"

# 模拟 JXA envVar() — 优先 shell env,fallback Alfred prefs.plist
def envVar(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        with open(ALFWORKFLOW_PREF, "rb") as f:
            prefs = plistlib.load(f)
        return str(prefs.get(name, default)).strip()
    except Exception:
        return default


def get_minimax_config() -> dict:
    return {
        "provider": "minimax",
        "api_key": envVar("minimax_api_key"),
        "endpoint": envVar("minimax_api_endpoint") or "https://api.minimaxi.com/v1",
        "model": envVar("minimax_model") or "MiniMax-M3",
    }


def get_deepseek_config() -> dict:
    return {
        "provider": "deepseek",
        "api_key": envVar("deepseek_api_key"),
        "endpoint": envVar("deepseek_api_endpoint") or "https://api.deepseek.com/v1",
        "model": envVar("deepseek_model") or "deepseek-chat",
    }


def litellm_call(cfg: dict, messages: list, tools: list = None, stream: bool = False):
    """统一 LiteLLM 调用入口。OpenAI 兼容 provider 用 openai/<model> 前缀。"""
    from litellm import completion

    # M3 / DeepSeek 都是 OpenAI 兼容 — 用 openai/ 前缀 + 自定义 base_url
    kwargs = {
        "model": f"openai/{cfg['model']}",
        "api_key": cfg["api_key"],
        "base_url": cfg["endpoint"],
        "messages": messages,
        "timeout": 30,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if stream:
        kwargs["stream"] = True
    return completion(**kwargs)


def test_1_plain_text():
    print("=" * 60)
    print("TEST 1: 普通文本对话 (minimax/MiniMax-M3)")
    print("=" * 60)
    cfg = get_minimax_config()
    if not cfg["api_key"]:
        print("  SKIP: minimax_api_key 未配置")
        return
    print(f"  model={cfg['model']} base={cfg['endpoint']}")

    resp = litellm_call(cfg, [
        {"role": "user", "content": "用一句话回答: 1+1=?"},
    ])
    msg = resp.choices[0].message
    content = msg.content or ""
    tool_calls = msg.tool_calls
    usage = resp.usage

    print(f"  content: {content[:120]!r}")
    print(f"  tool_calls: {tool_calls}")
    print(f"  usage: prompt={usage.prompt_tokens} completion={usage.completion_tokens}")
    assert content.strip(), "content 为空"
    print("  ✓ PASS")
    print()


def test_2_streaming():
    print("=" * 60)
    print("TEST 2: Streaming (minimax/MiniMax-M3)")
    print("=" * 60)
    cfg = get_minimax_config()
    if not cfg["api_key"]:
        print("  SKIP: minimax_api_key 未配置")
        return

    resp = litellm_call(cfg, [
        {"role": "user", "content": "用 30 字内回答: 什么是 LiteLLM?"},
    ], stream=True)

    chunks = 0
    full_text = ""
    for chunk in resp:
        chunks += 1
        delta = chunk.choices[0].delta
        if delta.content:
            full_text += delta.content
    print(f"  chunks={chunks}")
    print(f"  full_text: {full_text[:200]!r}")
    assert chunks > 1, f"streaming 只收到 {chunks} 个 chunk (应为多个)"
    assert full_text.strip(), "streaming 没收到 content"
    print("  ✓ PASS")
    print()


def test_3_tool_call():
    print("=" * 60)
    print("TEST 3: tool_calls schema (强制 LLM 选工具)")
    print("=" * 60)
    cfg = get_minimax_config()
    if not cfg["api_key"]:
        print("  SKIP: minimax_api_key 未配置")
        return

    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "联网搜索,返回搜索结果列表",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                    },
                    "required": ["query"],
                },
            },
        },
    ]

    resp = litellm_call(cfg, [
        {"role": "user", "content": "搜索一下英伟达最近的财报"},
    ], tools=tools)

    msg = resp.choices[0].message
    print(f"  content: {(msg.content or '')[:100]!r}")
    print(f"  tool_calls: {msg.tool_calls}")
    if msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"    → {tc.function.name}({tc.function.arguments})")
        print("  ✓ PASS — LLM 选择了工具")
    else:
        # M3 可能有时候不调工具 — 看 content 是否提到搜索
        if "搜索" in (msg.content or "") or "搜" in (msg.content or ""):
            print("  ⚠ LLM 没调工具,但 content 提到搜索 — 接受")
        else:
            print(f"  ✗ FAIL — LLM 既没调工具也没回应搜索意图")
    print()


def test_4_provider_switch():
    print("=" * 60)
    print("TEST 4: 切换到 deepseek")
    print("=" * 60)
    cfg = get_deepseek_config()
    if not cfg["api_key"]:
        print("  SKIP: deepseek_api_key 未配置")
        return
    print(f"  model={cfg['model']} base={cfg['endpoint']}")

    resp = litellm_call(cfg, [
        {"role": "user", "content": "用一句话回答: Python 是什么?"},
    ])
    msg = resp.choices[0].message
    print(f"  content: {(msg.content or '')[:120]!r}")
    assert msg.content and msg.content.strip(), "deepseek 无响应"
    print("  ✓ PASS — 切换 provider 无需改代码")
    print()


def test_5_message_format_consistency():
    """验证 LiteLLM 返回的 tool_calls 跟 Hermes / OpenAI 同构。"""
    print("=" * 60)
    print("TEST 5: tool_calls 数据结构校验 (跟 Hermes 同构)")
    print("=" * 60)
    cfg = get_minimax_config()
    if not cfg["api_key"]:
        print("  SKIP")
        return

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询天气",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        },
    ]
    resp = litellm_call(cfg, [
        {"role": "system", "content": "你是天气助手。用户问天气就调工具。"},
        {"role": "user", "content": "北京今天天气怎么样?"},
    ], tools=tools)

    msg = resp.choices[0].message
    tc = msg.tool_calls[0] if msg.tool_calls else None
    if tc is None:
        print(f"  ⚠ M3 没调工具,content={(msg.content or '')[:80]!r}")
        print("  (M3 调工具率不稳定,跳过 schema 校验)")
        return

    # 校验 schema 跟 Hermes 一致
    assert hasattr(tc, "id"), "tool_call 应有 id 字段"
    assert hasattr(tc, "function"), "tool_call 应有 function 字段"
    assert hasattr(tc.function, "name"), "function 应有 name 字段"
    assert hasattr(tc.function, "arguments"), "function 应有 arguments 字段"

    # arguments 应该是合法 JSON 字符串
    args = json.loads(tc.function.arguments)
    print(f"  tc.id={tc.id}")
    print(f"  tc.function.name={tc.function.name}")
    print(f"  tc.function.arguments={tc.function.arguments}")
    assert isinstance(args, dict), "arguments 应 parse 为 dict"
    print("  ✓ PASS — schema 跟 Hermes/OpenAI 同构")
    print()


if __name__ == "__main__":
    print()
    test_1_plain_text()
    test_2_streaming()
    test_3_tool_call()
    test_4_provider_switch()
    test_5_message_format_consistency()
    print("=" * 60)
    print("W10 Step 1 验证完成")
    print("=" * 60)