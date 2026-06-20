#!/usr/bin/env python3
"""Complete replacement for agent_skills/skillify.py (W4 self-evolution).

Three modes:
1. skill_create (explicit /skillify): create new SKILL.md from scratch
2. skill_improve (/skillify improve <name>): read existing SKILL.md + recent chat, generate incremental patch (version bump, changelog)
3. skill_curator (background auto): analyze recent chat + existing skills, produce create|update|archive recommendations
   (triggered by launchd, similar to background_review)
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .loader import skills_dir, optional_skills_dir


def _workflow_data_dir() -> Path:
    return Path(os.environ.get("alfred_workflow_data") or os.environ.get("ALFRED_WORKFLOW_DATA") or "/tmp/alfred-chat")


def _read_chat_messages(limit: int = 30) -> List[Dict[str, str]]:
    chat_file = _workflow_data_dir() / "chat.json"
    if not chat_file.exists():
        return []
    try:
        data = json.loads(chat_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        msgs = data["messages"]
    elif isinstance(data, list):
        msgs = data
    else:
        return []
    return msgs[-limit:]


def _format_recent(messages: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for m in messages:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"用户: {content[:600]}")
        elif role == "assistant":
            lines.append(f"助手: {content[:600]}")
    return "\n".join(lines)


def _resolve_provider() -> Optional[Tuple[str, str, str]]:
    provider = os.environ.get("chat_provider") or "minimax"
    if provider == "deepseek":
        endpoint = os.environ.get("deepseek_api_endpoint") or "https://api.deepseek.com/chat/completions"
        api_key = os.environ.get("deepseek_api_key") or ""
        model = os.environ.get("deepseek_model") or "deepseek-v4-flash"
        return endpoint, api_key, model
    region = os.environ.get("minimax_region") or "china"
    default = (
        "https://api.minimaxi.com/v1/chat/completions"
        if region == "china"
        else "https://api.minimax.io/v1/chat/completions"
    )
    endpoint = os.environ.get("minimax_api_endpoint") or default
    api_key = os.environ.get("minimax_api_key") or ""
    model = os.environ.get("minimax_model") or "MiniMax-M3"
    return endpoint, api_key, model


def _extract_skill_block(text: str) -> Optional[Dict[str, str]]:
    """Extract JSON from LLM output: {"name":..., "description":..., "tags":[...], "body":"..."}"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    candidate = m.group(1) if m else None
    if not candidate:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            return None
        candidate = text[start:end + 1]
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("name") or not data.get("description") or not data.get("body"):
        return None
    return {
        "name": str(data["name"]).strip(),
        "description": str(data["description"]).strip(),
        "tags": [str(t) for t in (data.get("tags") or [])][:8],
        "body": str(data["body"]).strip(),
    }


def _ask_llm_for_skill_raw(recent: str, user_hint: str = "") -> Optional[Dict[str, str]]:
    endpoint, api_key, model = _resolve_provider()
    if not api_key:
        return None
    prompt = (
        "你是 Alfred Chat 的 skill 提炼器。给定最近对话,判断是否有值得固化的操作手册。"
        "如果有,返回 JSON {\"name\":\"kebab-case-name\", \"description\":\"一句话\", "
        "\"tags\":[最多 6 个关键词], \"body\":\"Markdown 操作步骤(用 ## 标题和 bullet 列表)\"}。"
        "没有可提炼的就返回 {}。"
        + (f"\n\n用户提示:{user_hint}" if user_hint else "")
        + f"\n\n最近对话:\n{recent}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是 skill 提炼器,只返回 JSON,不解释。"},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0,
    }
    if os.environ.get("chat_provider", "minimax") != "deepseek":
        payload["thinking"] = {"type": "disabled"}
    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    return _extract_skill_block(content or "")


def _validate_name(name: str) -> str:
    """skill name must be kebab-case, alphanumeric + hyphens."""
    name = re.sub(r"[^a-z0-9-]", "-", name.lower())
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "unnamed-skill"


# ============ W3: skillify_from_recent (create) ============

def skillify_from_recent(limit: int = 30, user_hint: str = "", bundled: bool = True) -> Tuple[str, str, str]:
    """Create a new skill from recent chat (explicit /skillify)."""
    messages = _read_chat_messages(limit=limit)
    if not messages:
        return "error", "没有对话可提炼,先聊几句再 /skillify", "无对话历史"

    recent = _format_recent(messages)
    extracted = _ask_llm_for_skill_raw(recent, user_hint=user_hint)
    if not extracted:
        return "error", "对话里没找到值得固化的 workflow(可能太短或太临时)", "无可提炼 skill"

    name = _validate_name(extracted["name"])
    base = skills_dir() if bundled else optional_skills_dir()
    target = base / name
    if (target / "SKILL.md").exists():
        return "needs_confirmation", (
            f"Skill `{name}` 已存在。要覆盖吗?\n\n"
            f"输入 `skillify confirm {name}` 确认覆盖,或 `skillify new <other-name>` 换名字。"
        ), f"skill {name} 已存在"

    target.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    tags_yaml = "[" + ", ".join(extracted["tags"]) + "]" if extracted["tags"] else "[]"
    skill_md = f"""---
name: {name}
description: \"{extracted["description"]}\"
version: 1.0.0
author: Alfred Chat (auto-skillify)
created: {today}
metadata:
  hermes:
    tags: {tags_yaml}
---

{extracted["body"]}
"""
    (target / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return "success", (
        f"已创建 skill:`{name}`\n\n"
        f"描述:{extracted['description']}\n"
        f"位置:`{target / 'SKILL.md'}`\n"
        f"下次类似问题会自动召回。"
    ), f"已创建 skill {name}"


def skillify_confirm_overwrite(name: str) -> Tuple[str, str, str]:
    """Confirm overwriting an existing skill."""
    name = _validate_name(name)
    target = skills_dir() / name
    if not (target / "SKILL.md").exists():
        return "error", f"skill `{name}` 不存在,无法覆盖", "skill 不存在"
    messages = _read_chat_messages(limit=30)
    if not messages:
        return "error", "没有对话可提炼", "无对话历史"
    recent = _format_recent(messages)
    extracted = _ask_llm_for_skill_raw(recent)
    if not extracted:
        return "error", "无可提炼内容", "无可提炼 skill"
    extracted_name = _validate_name(extracted["name"])
    if extracted_name != name:
        return "error", f"提炼出的 name({extracted_name})与原 skill({name})不一致,先 `skillify new <name>`", "name 冲突"
    target.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    tags_yaml = "[" + ", ".join(extracted["tags"]) + "]" if extracted["tags"] else "[]"
    skill_md = f"""---
name: {name}
description: \"{extracted["description"]}\"
version: 1.1.0
author: Alfred Chat (auto-skillify, confirmed overwrite)
updated: {today}
metadata:
  hermes:
    tags: {tags_yaml}
---

{extracted["body"]}
"""
    (target / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return "success", f"已覆盖 skill:`{name}`(更新为 1.1.0)", f"已覆盖 {name}"


# ============ W4 NEW: skill_improve ============

def _read_existing_skill(name: str) -> Optional[str]:
    """Read body of existing skill SKILL.md (without frontmatter)."""
    name = _validate_name(name)
    for base in (skills_dir(), optional_skills_dir()):
        md = base / name / "SKILL.md"
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8")
        m = re.match(r"\A---\s*\n.*?\n---\s*\n", text, re.S)
        return text[m.end():].strip() if m else text.strip()
    return None


def _read_skill_frontmatter(name: str) -> Dict[str, Any]:
    """Read frontmatter fields from existing skill."""
    name = _validate_name(name)
    for base in (skills_dir(), optional_skills_dir()):
        md = base / name / "SKILL.md"
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8")
        m = re.match(r"\A---\s*\n(.*?)\n---", text, re.S)
        if not m:
            return {}
        fm = {}
        for line in m.group(1).splitlines():
            line = line.strip()
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip('"').strip("'")
        return fm
    return {}


def _increment_version(version_str: str) -> str:
    """Bump minor version: '1.0.0' → '1.1.0'"""
    try:
        parts = [int(x) for x in version_str.strip().split(".")]
        if len(parts) >= 2:
            parts[1] += 1
            if len(parts) >= 3:
                parts[2] = 0
            return ".".join(str(x) for x in parts)
        return "2.0.0"
    except Exception:
        return "2.0.0"


def _ask_llm_improve_skill(
    skill_name: str,
    existing_body: str,
    recent: str,
    user_hint: str = "",
) -> Optional[Dict[str, str]]:
    """Ask LLM to generate incremental improvement patch for existing skill."""
    endpoint, api_key, model = _resolve_provider()
    if not api_key:
        return None

    prompt = (
        "你是 Alfred Chat 的 skill 改进器。用户已经有一个操作手册，现在有新对话可能包含了更好的做法或新情况。"
        "请在**不重写整个 skill** 的前提下，给出**增量改进 patch**。"
        f"\n\n当前 skill `{skill_name}` 正文:\n{existing_body}\n\n"
        "最近对话:\n" + recent + "\n\n"
        + (f"用户提示:{user_hint}\n\n" if user_hint else "")
        + (
            "返回 JSON {\"body_patch\": \"改进后的 skill 正文的新增/替换段落 (Markdown)\", "
            "\"changelog\": \"一句话说明本次改进了什么\"}。"
            "如果没有值得改进的，返回 {}。"
            "注意 body_patch 只需要给出**新增或替换的段落**，不是全文。"
        )
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是 skill 改进器，只返回 JSON，不解释。"},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.2,
    }
    if os.environ.get("chat_provider", "minimax") != "deepseek":
        payload["thinking"] = {"type": "disabled"}

    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    # reuse _extract_skill_block but body_patch is in the 'body' field
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S | re.I)
    candidate = m.group(1) if m else None
    if not candidate:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end < start:
            return None
        candidate = content[start:end + 1]
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    # body_patch and changelog are the expected fields
    if not data.get("body_patch"):
        return None
    return {"body_patch": str(data["body_patch"]).strip(), "changelog": str(data.get("changelog") or "基于新对话改进").strip()}


def skillify_improve(name: str, user_hint: str = "") -> Tuple[str, str, str]:
    """Improve an existing skill based on recent conversations.

    Returns: (status, message, footer)
    """
    name = _validate_name(name)
    existing = _read_existing_skill(name)
    if existing is None:
        return "error", f"skill `{name}` 不存在，请先 /skillify 创建一个", "skill 不存在"

    messages = _read_chat_messages(limit=30)
    if not messages:
        return "error", "没有对话可分析", "无对话历史"

    recent = _format_recent(messages)
    patch = _ask_llm_improve_skill(name, existing, recent, user_hint=user_hint)
    if not patch:
        return "error", "无法分析改进点", "LLM 无输出"

    body_patch = (patch.get("body_patch") or "").strip()
    if not body_patch:
        return "error", "当前对话没有值得改进的内容", "无可改进"

    fm = _read_skill_frontmatter(name)
    old_version = fm.get("version", "1.0.0")
    new_version = _increment_version(old_version)
    changelog_entry = (patch.get("changelog") or "基于新对话改进").strip()

    # find the skill directory
    for base in (skills_dir(), optional_skills_dir()):
        md = base / name / "SKILL.md"
        if md.exists():
            break
    else:
        return "error", "找不到 skill 文件", "文件丢失"

    today = datetime.now().strftime("%Y-%m-%d")
    tags = fm.get("tags", "[]")
    old_changelog = fm.get("changelog", "")
    new_changelog = f"{old_changelog}\n- v{new_version} ({today}): {changelog_entry}" if old_changelog else f"v{new_version} ({today}): {changelog_entry}"

    new_body = existing + "\n\n---\n\n" + body_patch

    skill_md = f"""---
name: {name}
description: \"{fm.get('description', '无描述')}\"
version: {new_version}
author: Alfred Chat (auto-skillify improve)
updated: {today}
changelog: \"{new_changelog}\"
metadata:
  hermes:
    tags: {tags}
---

{new_body}
"""
    md.write_text(skill_md, encoding="utf-8")
    return "success", (
        f"已改进 skill `{name}` ({old_version} → {new_version})\n\n"
        f"改进内容:{changelog_entry}\n"
        f"位置:`{md}`"
    ), f"skill {name} 已改进"


# ============ W4 NEW: skill_curator ============

def _format_skill_index() -> str:
    """Generate index summary of all existing skills (name + description + version)."""
    from .loader import load_all_skills, SkillLoadResult

    result: SkillLoadResult = load_all_skills()
    if not result.skills:
        return "(无已有 skill)"
    lines: List[str] = []
    for s in result.skills:
        lines.append(
            f"- `{s.name}` v{s.version} [{', '.join(s.tags)}] {s.description}"
        )
    return "\n".join(lines)


def _extract_curator_actions(text: str) -> List[Dict[str, Any]]:
    """Extract actions list from curator LLM output.

    Expected format: {"actions": [{"action":"create|update|archive|none", "skill_name":"...", ...}]}
    """
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    candidate = m.group(1) if m else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        return []
    try:
        data = json.loads(candidate[start:end + 1])
    except Exception:
        return []
    if isinstance(data, dict):
        return data.get("actions") or []
    return data if isinstance(data, list) else []


def run_curator(limit: int = 30) -> Dict[str, Any]:
    """Background curator: analyze recent chat + existing skills, suggest create|update|archive.

    (triggered by launchd, similar to background_review)

    Returns: {"applied": [...], "action_count": N}
    """
    if os.environ.get("memory_auto_write") == "0":
        return {"skipped": True, "reason": "memory_auto_write disabled"}

    messages = _read_chat_messages(limit=limit)
    if not messages:
        return {"skipped": True, "reason": "no messages"}

    recent = _format_recent(messages)
    index = _format_skill_index()

    endpoint, api_key, model = _resolve_provider()
    if not api_key:
        return {"skipped": True, "reason": "no API key"}

    prompt = (
        "你是 Alfred Chat 的 skill curator(技能馆长)。\n\n"
        "当前已有 skill 索引:\n" + index + "\n\n"
        "最近对话:\n" + recent + "\n\n"
        "请判断是否需要创建新 skill、改进已有 skill、或归档过时 skill。"
        "返回 JSON {\"actions\": [{\"action\": \"create|update|archive|none\", \"skill_name\": \"...\", "
        "\"description\": \"...\", \"tags\": [\"...\"], \"body\": \"...\", \"changelog\": \"...\"}]}。"
        '若无需操作，返回 {\"actions\": []}。'
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是 skill curator，只返回 JSON，不解释。"},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0,
    }
    if os.environ.get("chat_provider", "minimax") != "deepseek":
        payload["thinking"] = {"type": "disabled"}

    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"skipped": True, "reason": "curator call failed"}

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    actions = _extract_curator_actions(content or "")
    if not actions:
        return {"skipped": True, "reason": "no actionable suggestions"}

    applied: List[str] = []
    for item in actions:
        action = (item.get("action") or "none").strip().lower()
        skill_name = (item.get("skill_name") or "").strip()
        if action == "none":
            continue
        if action == "create":
            name = _validate_name(skill_name)
            target = skills_dir() / name
            if (target / "SKILL.md").exists():
                applied.append(f"skip create {name}: already exists")
                continue
            target.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            desc = (item.get("description") or "curator auto-created").strip()
            tags = item.get("tags") or []
            body_text = (item.get("body") or "").strip()
            tags_yaml = "[" + ", ".join(str(t) for t in tags) + "]" if tags else "[]"
            skill_md = f"""---
name: {name}
description: \"{desc}\"
version: 1.0.0
author: Alfred Chat (auto-curator)
created: {today}
metadata:
  hermes:
    tags: {tags_yaml}
---

{body_text}
"""
            (target / "SKILL.md").write_text(skill_md, encoding="utf-8")
            applied.append(f"created skill {name}")
        elif action == "update":
            existing_body = _read_existing_skill(skill_name)
            if existing_body is None:
                applied.append(f"skip update {skill_name}: not found")
                continue
            body_patch = (item.get("body") or "").strip()
            if not body_patch:
                continue
            fm = _read_skill_frontmatter(skill_name)
            old_version = fm.get("version", "1.0.0")
            new_version = _increment_version(old_version)
            changelog = (item.get("changelog") or "curator auto-update").strip()
            for base in (skills_dir(), optional_skills_dir()):
                md = base / skill_name / "SKILL.md"
                if md.exists():
                    break
            else:
                continue
            today = datetime.now().strftime("%Y-%m-%d")
            old_changelog = fm.get("changelog", "")
            new_changelog = f"{old_changelog}\n- v{new_version} ({today}): {changelog}" if old_changelog else f"v{new_version} ({today}): {changelog}"
            new_body = existing_body + "\n\n---\n\n" + body_patch
            skill_md = f"""---
name: {skill_name}
description: \"{fm.get('description', '无描述')}\"
version: {new_version}
author: Alfred Chat (auto-curator update)
updated: {today}
changelog: \"{new_changelog}\"
metadata:
  hermes:
    tags: {fm.get('tags', '[]')}
---

{new_body}
"""
            md.write_text(skill_md, encoding="utf-8")
            applied.append(f"updated skill {skill_name} ({old_version} → {new_version})")
        elif action == "archive":
            for base in (skills_dir(), optional_skills_dir()):
                target_dir = base / skill_name
                if target_dir.exists():
                    (target_dir / "ARCHIVED").write_text(
                        f"archived on {datetime.now().strftime('%Y-%m-%d')}\n"
                        f"reason: {(item.get('description') or item.get('changelog') or 'curator archive').strip()}"
                    )
                    applied.append(f"archived skill {skill_name}")
                    break
            else:
                applied.append(f"skip archive {skill_name}: not found")

    return {"applied": applied, "action_count": len(applied)}


# ============ CLI ============

if __name__ == "__main__":
    usage = (
        "usage: python -m agent_skills.skillify <command> [args]\n"
        "  from-recent [--hint '...']  显式创建 skill\n"
        "  improve <name> [--hint '...'] 改进已有 skill\n"
        "  curator                    后台自动审核\n"
        "  confirm <name>             确认覆盖已存在的 skill"
    )
    if len(sys.argv) < 2:
        print(usage)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "curator":
        result = run_curator()
        print(json.dumps(result, ensure_ascii=False))
    elif cmd == "improve":
        if len(sys.argv) < 3:
            print("用法: python -m agent_skills.skillify improve <skill-name> [--hint '...']")
            sys.exit(1)
        skill_name = sys.argv[2]
        hint = ""
        if "--hint" in sys.argv:
            i = sys.argv.index("--hint")
            if i + 1 < len(sys.argv):
                hint = sys.argv[i + 1]
        status, msg, footer = skillify_improve(skill_name, user_hint=hint)
        print(json.dumps({"status": status, "assistant_text": msg, "footer": footer}, ensure_ascii=False))
    elif cmd == "confirm":
        if len(sys.argv) < 3:
            print("用法: python -m agent_skills.skillify confirm <skill-name>")
            sys.exit(1)
        status, msg, footer = skillify_confirm_overwrite(sys.argv[2])
        print(json.dumps({"status": status, "assistant_text": msg, "footer": footer}, ensure_ascii=False))
    elif cmd == "from-recent":
        hint = ""
        if "--hint" in sys.argv:
            i = sys.argv.index("--hint")
            if i + 1 < len(sys.argv):
                hint = sys.argv[i + 1]
        status, msg, footer = skillify_from_recent(user_hint=hint)
        print(json.dumps({"status": status, "assistant_text": msg, "footer": footer}, ensure_ascii=False))
    else:
        print(f"未知命令:{cmd}")
        print(usage)
        sys.exit(1)
