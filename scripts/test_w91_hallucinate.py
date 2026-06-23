"""W9.1 M3 hallucinate <toolcall> 修复测试。

覆盖:
1. isHallucinatedToolCall detect
2. extractHallucinatedToolCalls parse (单/多/坏 JSON)
3. runHallucinatedToolCalls 真跑 (M3 格式 → local_agent 格式转换)
4. 端到端: M3 模拟输出 → 真 web_search → 结果回拼
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "Workflow"
PY = sys.executable


def is_hallucinated(text: str) -> bool:
    return bool(re.search(r"<\s*tool[_]?call\b", text or "", re.I))


def extract(text: str):
    """Mirror JXA extractHallucinatedToolCalls: 支持 JSON + XML 风格。"""
    out = []
    if not text:
        return out

    block_re = re.compile(r"<\s*tool[_]?call\s*[^>]*>([\s\S]*?)<\s*\/\s*tool[_]?call\s*>", re.I)
    for block_match in block_re.finditer(text):
        body = block_match.group(1) or ""

        # 1) JSON 风格
        json_objs = re.findall(r"\{(?:[^{}]|\{[^{}]*\})*\}", body)
        for o in json_objs:
            try:
                obj = json.loads(o)
                if obj and (obj.get("name") or obj.get("tool")):
                    out.append({
                        "name": obj.get("name") or obj.get("tool"),
                        "arguments": obj.get("arguments") or obj.get("args") or {},
                    })
            except Exception:
                pass
        if out:
            continue

        # 2) XML 风格
        for inv in re.finditer(r"<\s*invoke\s+[^>]*name\s*=\s*[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)<\s*\/\s*invoke\s*>", body, re.I):
            name = (inv.group(1) or "").strip()
            inner = inv.group(2) or ""
            if not name:
                continue
            args = {}
            for p in re.finditer(r"<\s*([a-zA-Z_][a-zA-Z0-9_-]*)\s*>([\s\S]*?)<\s*\/\s*\1\s*>", inner):
                key, value = p.group(1), (p.group(2) or "").strip()
                if key and value and key not in args:
                    args[key] = value
            out.append({"name": name, "arguments": args})

        # 3) 容错: 单独的 invoke name
        if not out:
            loose = re.search(r"<\s*invoke\s+[^>]*name\s*=\s*[\"']([^\"']+)[\"']", body, re.I)
            if loose:
                name = loose.group(1).strip()
                args = {}
                for p in re.finditer(r"<\s*([a-zA-Z_][a-zA-Z0-9_-]*)\s*>([\s\S]*?)<\s*\/\s*\1\s*>", body):
                    key, value = p.group(1), (p.group(2) or "").strip()
                    if key and value and key not in args:
                        args[key] = value
                out.append({"name": name, "arguments": args})
    return out


def run_tool_calls_m3_style(tool_calls):
    """M3 输出风格 {name, arguments} → local_agent 调 {tool, args}"""
    results = []
    for tc in tool_calls or []:
        raw_name = tc.get("name") or tc.get("tool") or ""
        name = raw_name.lower()
        args = tc.get("arguments") or tc.get("args") or {}

        if name in ("web_search", "websearch", "search"):
            local = {"tool": "web_search", "args": {"query": args.get("query") or args.get("q") or ""}}
        elif name in ("web_fetch", "webfetch", "fetch"):
            local = {"tool": "web_fetch", "args": {"url": args.get("url") or ""}}
        else:
            results.append({"name": raw_name or "?", "ok": False, "text": f"unsupported: {raw_name}"})
            continue

        r = subprocess.run(
            [PY, str(WORKFLOW_DIR / "local_agent.py"), "--tool", json.dumps(local)],
            capture_output=True, text=True, timeout=30,
            env={**os.environ},
        )
        try:
            data = json.loads(r.stdout)
        except Exception:
            data = {"handled": False, "raw": r.stdout, "err": r.stderr[:200]}
        results.append({
            "name": raw_name,
            "ok": data.get("handled") and data.get("status") == "success",
            "text": data.get("assistant_text") or "(no text)",
            "_debug": data,
        })
    return results


# ----- tests -----

def test_is_hallucinated():
    print("--- test_is_hallucinated ---")
    cases = [
        ('<tool_call>{"name":"web_search"}</tool_call>', True),
        ('<toolcall>{}</toolcall>', True),
        ('<TOOLCALL>x</TOOLCALL>', True),  # case-insensitive
        ('<tool_call> {"name":"x"}</tool_call>', True),  # with space
        ('<tool_call>x</tool_call>', True),  # underscore variant
        ('<tool_call>{', True),  # malformed
        ('普通文本', False),
        ('<tool_call>with-no-end', True),  # 只要有 <toolcall 前缀就算 (extract 会处理 closing)
        ('', False),
    ]
    for text, expected in cases:
        actual = is_hallucinated(text)
        flag = "✓" if actual == expected else "✗"
        print(f"  {flag} {text[:50]!r} → {actual} (期望 {expected})")
        assert actual == expected, f"Failed on {text!r}"


def test_extract_single():
    print("--- test_extract_single ---")
    text = '<tool_call>{"name":"web_search","arguments":{"query":"英伟达 竞争对手"}}</tool_call>'
    out = extract(text)
    print(f"  → {out}")
    assert len(out) == 1
    assert out[0]["name"] == "web_search"
    assert out[0]["arguments"]["query"] == "英伟达 竞争对手"
    print("  ✓ single tool call parsed")


def test_extract_multiple():
    print("--- test_extract_multiple ---")
    # 多个相邻 <toolcall> 但只包了 blob, 没分别包
    text = '<tool_call>{"name":"web_search","arguments":{"query":"query1"}}{"name":"web_fetch","arguments":{"url":"https://example.com"}}</toolcall>'
    out = extract(text)
    print(f"  → {len(out)} calls: {[c['name'] for c in out]}")
    assert len(out) == 2
    assert out[0]["name"] == "web_search"
    assert out[1]["name"] == "web_fetch"
    print("  ✓ multiple calls parsed from blob")


def test_extract_malformed_returns_empty():
    print("--- test_extract_malformed_returns_empty ---")
    text = '<tool_call>not json</tool_call>'
    out = extract(text)
    print(f"  → {out}")
    assert out == []
    print("  ✓ malformed returns empty (no crash)")


def test_extract_with_prefix_text():
    print("--- test_extract_with_prefix_text ---")
    text = '好的,我先搜一下。\n<tool_call>{"name":"web_search","arguments":{"query":"x"}}\n</tool_call>\n稍等'
    out = extract(text)
    print(f"  → {out}")
    assert len(out) == 1
    assert out[0]["arguments"]["query"] == "x"
    print("  ✓ text around toolcall doesn't break parse")


def test_extract_xml_single():
    """M3 实际输出风格: <invoke name="web_search"><query>...</query></invoke>"""
    print("--- test_extract_xml_single ---")
    text = '<tool_call>\n<invoke name="web_search">\n<query>好好的时光 电视剧 剧情简介</query>\n</invoke>\n</toolcall>'
    out = extract(text)
    print(f"  → {out}")
    assert len(out) == 1, f"Expected 1, got {len(out)}"
    assert out[0]["name"] == "web_search"
    assert out[0]["arguments"]["query"] == "好好的时光 电视剧 剧情简介"
    print("  ✓ XML single tool call parsed")


def test_extract_xml_multiple():
    """M3 实际输出风格: 多个 invoke 同包在一个 toolcall 内"""
    print("--- test_extract_xml_multiple ---")
    text = '''<tool_call>
<invoke name="web_search">
<query>Broadcom AVGO Q4 2024 earnings AI revenue</query>
</invoke>
<invoke name="web_search">
<query>Marvell MRVL Q3 fiscal 2025 earnings</query>
</invoke>
<invoke name="web_search">
<query>Astera Labs ALAB Q3 2024 earnings</query>
</invoke>
</toolcall>'''
    out = extract(text)
    print(f"  → {len(out)} calls: {[c['name'] for c in out]}")
    assert len(out) == 3
    assert all(c["name"] == "web_search" for c in out)
    assert out[0]["arguments"]["query"].startswith("Broadcom")
    assert out[1]["arguments"]["query"].startswith("Marvell")
    assert out[2]["arguments"]["query"].startswith("Astera")
    print("  ✓ XML multiple tool calls parsed")


def test_extract_xml_with_prefix_text():
    """M3 在 <toolcall> 前后经常有中文引导语"""
    print("--- test_extract_xml_with_prefix_text ---")
    text = '我先查一下这部电视剧的资料。\n<tool_call>\n<invoke name="web_search">\n<query>好好的时光 电视剧</query>\n</invoke>\n</toolcall>'
    out = extract(text)
    print(f"  → {out}")
    assert len(out) == 1
    assert out[0]["arguments"]["query"] == "好好的时光 电视剧"
    print("  ✓ XML with surrounding text parsed")


def test_extract_xml_websearch_no_underscore():
    """M3 偶尔用 websearch (无下划线) 变体"""
    print("--- test_extract_xml_websearch_no_underscore ---")
    text = '<tool_call>\n<invoke name="websearch">\n<query>x</query>\n</invoke>\n</toolcall>'
    out = extract(text)
    print(f"  → {out}")
    assert len(out) == 1
    assert out[0]["name"] == "websearch"
    # run 阶段会 normalize 到 web_search
    print("  ✓ XML with websearch (no underscore) parsed")


def test_run_tool_call_web_search():
    print("--- test_run_tool_call_web_search ---")
    # 模拟 M3 输出
    m3_text = '<tool_call>{"name":"web_search","arguments":{"query":"python decorator tutorial"}}</tool_call>'
    tool_calls = extract(m3_text)
    results = run_tool_calls_m3_style(tool_calls)
    print(f"  → {len(results)} results")
    for r in results:
        print(f"  {r['name']}: ok={r['ok']} text={r['text'][:80]!r}")
    # 不需要真 Tavily (没 key 也走得到) — 至少 verify 不 crash
    assert len(results) == 1
    assert results[0]["name"] == "web_search"
    print("  ✓ web_search call dispatched")


def test_run_unsupported_tool():
    print("--- test_run_unsupported_tool ---")
    tool_calls = [{"name": "summarize_pdf", "arguments": {}}]
    results = run_tool_calls_m3_style(tool_calls)
    print(f"  → {results}")
    assert results[0]["ok"] is False
    assert "unsupported" in results[0]["text"] or "未" in results[0]["text"]
    print("  ✓ unsupported tool skipped gracefully")


if __name__ == "__main__":
    print("=" * 60)
    print("W9.1 hallucinate toolcall 修复测试")
    print("=" * 60)
    print()
    test_is_hallucinated()
    print()
    test_extract_single()
    print()
    test_extract_multiple()
    print()
    test_extract_malformed_returns_empty()
    print()
    test_extract_with_prefix_text()
    print()
    test_extract_xml_single()
    print()
    test_extract_xml_multiple()
    print()
    test_extract_xml_with_prefix_text()
    print()
    test_extract_xml_websearch_no_underscore()
    print()
    test_run_tool_call_web_search()
    print()
    test_run_unsupported_tool()
    print()
    print("=" * 60)
    print("W9.1 全部通过 ✓")
    print("=" * 60)
