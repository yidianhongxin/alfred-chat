#!/usr/bin/env python3
"""Test the agent_skills/ system after W3 (Skills + retrieval + prompt-block injection)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / "Workflow"
PY = sys.executable
TEST_DATA = "/tmp/alfred-chat"


def run(args: list[str], env: dict | None = None) -> dict | str:
    """Run python local_agent.py with given args. Return parsed JSON if possible, else raw string."""
    full_env = os.environ.copy()
    full_env["alfred_workflow_data"] = TEST_DATA
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
        return out


# --- assertion helpers ---

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


def section(title: str) -> None:
    print(f"\n--- {title} ---")


# ---------- tests ----------

def test_load_all_skills_direct() -> None:
    section("load_all_skills (direct import)")
    sys.path.insert(0, str(WORKFLOW_DIR))
    from agent_skills import load_all_skills
    r = load_all_skills()
    check(len(r.skills) == 7, f"loads 7 skills (got {len(r.skills)})")
    check(len(r.errors) == 0, f"zero parse errors (got {len(r.errors)})")
    names = {s.name for s in r.skills}
    expected = {"ob-search", "ob-diary", "git-conflict", "daily-review", "research", "inbox-triage", "soul-tune"}
    check(expected.issubset(names), f"all expected skills present: {expected}")


def test_frontmatter_parsing() -> None:
    section("frontmatter parsing")
    sys.path.insert(0, str(WORKFLOW_DIR))
    from agent_skills import load_all_skills
    r = load_all_skills()
    by_name = {s.name: s for s in r.skills}
    ob = by_name.get("ob-search")
    check(ob is not None, "ob-search exists")
    if ob:
        check("OB" in ob.description or "obsidian" in ob.description.lower(), "ob-search has OB-related description")
        check(len(ob.tags) > 0, f"ob-search has tags: {ob.tags}")
        check(ob.version != "0.0.0", f"ob-search has version: {ob.version}")
        check(len(ob.body) > 0, f"ob-search has body ({len(ob.body)} chars)")


def test_retrieval() -> None:
    section("retrieve_relevant_skills (heuristic)")
    sys.path.insert(0, str(WORKFLOW_DIR))
    from agent_skills import retrieve_relevant_skills
    m = retrieve_relevant_skills("OB 搜索")
    check(len(m) > 0, f"OB 搜索 -> matches: {[s.name for s, _ in m]}")
    if m:
        check(m[0][0].name == "ob-search", f"top match is ob-search (got {m[0][0].name})")
    m2 = retrieve_relevant_skills("git 冲突")
    check(any(s.name == "git-conflict" for s, _ in m2), f"git 冲突 -> git-conflict in matches: {[s.name for s, _ in m2]}")
    m3 = retrieve_relevant_skills("复盘")
    check(any(s.name == "daily-review" for s, _ in m3), f"复盘 -> daily-review in matches: {[s.name for s, _ in m3]}")
    m4 = retrieve_relevant_skills("asdfqwer nonsense")
    check(len(m4) == 0, "nonsense query -> no matches")


def test_format_prompt_block() -> None:
    section("format_skills_prompt_block")
    sys.path.insert(0, str(WORKFLOW_DIR))
    from agent_skills import format_skills_prompt_block
    block = format_skills_prompt_block("OB 搜索", top_k=2)
    check("## 相关 Skill" in block, "block has header")
    check("**ob-search**" in block, "block mentions ob-search in bold")
    check("相关度" in block, "block shows relevance score")
    block2 = format_skills_prompt_block("", top_k=2)
    check(block2 == "", f"empty query -> empty block (got: {block2[:50]!r})")
    block3 = format_skills_prompt_block("xyz123nonsense", top_k=2)
    check(block3 == "", "no-match query -> empty block")


def test_cli_skill_list() -> None:
    section("--skill-list CLI")
    out = run(["--skill-list"])
    if isinstance(out, dict):
        check("skills" in out, "has skills key")
        check("errors" in out, "has errors key")
        check(len(out["skills"]) == 7, f"7 skills listed (got {len(out['skills'])})")
        s0 = out["skills"][0]
        check("name" in s0 and "description" in s0 and "version" in s0, "skill entry has name/description/version")
    else:
        check(False, f"--skill-list should return JSON, got: {str(out)[:100]}")


def test_cli_skills_prompt() -> None:
    section("--skills-prompt CLI")
    out = run(["--skills-prompt", "OB 搜索"])
    if isinstance(out, str):
        check("ob-search" in out, f"prompt block contains ob-search (got: {out[:120]!r})")
        check("## 相关 Skill" in out, "prompt block has header")
    else:
        check(False, f"--skills-prompt should return string, got: {out!r}")
    out2 = run(["--skills-prompt", "xyz123 nonsense"])
    if isinstance(out2, str):
        check(out2 == "" or out2.strip() == "", f"nonsense -> empty block (got: {out2[:60]!r})")
    out3 = run(["--skills-prompt", ""])
    if isinstance(out3, str):
        check(out3 == "" or out3.strip() == "", f"empty query -> empty block (got: {out3[:60]!r})")


def test_optional_skills_dir() -> None:
    section("optional-skills directory (filtering)")
    sys.path.insert(0, str(WORKFLOW_DIR))
    from agent_skills import load_all_skills
    # ensure optional dir doesn't accidentally promote a bundled skill
    r = load_all_skills()
    bundled_count = sum(1 for s in r.skills if s.bundled)
    optional_count = sum(1 for s in r.skills if not s.bundled)
    check(bundled_count == 7, f"7 bundled skills (got {bundled_count})")
    check(optional_count == 0, f"0 optional skills by default (got {optional_count})")


def main() -> None:
    print("=" * 60)
    print("Alfred Chat W3 Skills System Tests")
    print("=" * 60)
    test_load_all_skills_direct()
    test_frontmatter_parsing()
    test_retrieval()
    test_format_prompt_block()
    test_cli_skill_list()
    test_cli_skills_prompt()
    test_optional_skills_dir()
    print(f"\n{'=' * 60}")
    print(f"Results: {_pass} passed, {_fail} failed")
    print("=" * 60)
    sys.exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    main()
