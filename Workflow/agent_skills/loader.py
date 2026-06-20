"""SKILL.md loader - 减法版 W3。

兼容 agentskills.io frontmatter spec:
---
name: ...
description: ...
version: ...
metadata:
  hermes:
    tags: [...]
    related_skills: [...]
---

设计原则:
- 不做 pip 加载 / plugin discovery framework
- 只扫描本地两个目录:bundled skills/ + optional optional-skills/
- 每个 SKILL.md = 一个 skill = 一份完整 prompt-injection
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------- 路径 ----------

def _workflow_data_dir() -> Path:
    import os
    return Path(os.environ.get("alfred_workflow_data") or os.environ.get("ALFRED_WORKFLOW_DATA") or "/tmp/alfred-chat")


def skills_dir() -> Path:
    """bundled skills(始终可用)。"""
    p = _workflow_data_dir() / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def optional_skills_dir() -> Path:
    """optional skills(显式启用)。"""
    p = _workflow_data_dir() / "optional-skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- frontmatter 解析 ----------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)


@dataclass
class Skill:
    """一个 SKILL.md 的完整表示。"""
    name: str
    description: str
    version: str
    tags: List[str] = field(default_factory=list)
    related_skills: List[str] = field(default_factory=list)
    body: str = ""                       # Markdown body(frontmatter 之后)
    source_path: Path = field(default_factory=Path)  # 原始 SKILL.md 路径
    bundled: bool = True                 # True=bundled, False=optional


@dataclass
class SkillLoadResult:
    skills: List[Skill] = field(default_factory=list)
    errors: List[Tuple[Path, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0



def _strip_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        return v[1:-1]
    return v


def _parse_inline_list(v: str) -> List[str]:
    v = v.strip()
    if not (v.startswith("[") and v.endswith("]")):
        return []
    inner = v[1:-1]
    out = []
    for item in inner.split(","):
        item = item.strip()
        if not item:
            continue
        out.append(_strip_quotes(item))
    return out


def _indent_of(line: str) -> int:
    """Count leading spaces (each 2 spaces = 1 level)."""
    n = 0
    for c in line:
        if c == " ":
            n += 1
        else:
            break
    return n


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    head, body = m.group(1), m.group(2)
    lines = head.splitlines()
    root: Dict[str, Any] = {}
    # stack of (indent_level, dict) — we descend into top dict when we see 0-indent keys,
    # and for deeper levels we track the path
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]

    for raw in lines:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = _indent_of(raw)
        content = raw[indent:].strip() if indent else raw.strip()
        if ":" not in content:
            continue
        k, _, v = content.partition(":")
        k = k.strip()
        v = v.strip()
        # pop stack to find parent
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if v:
            if v.startswith("[") and v.endswith("]"):
                parent[k] = _parse_inline_list(v)
            else:
                parent[k] = _strip_quotes(v)
        else:
            # new sub-dict
            new_dict: Dict[str, Any] = {}
            parent[k] = new_dict
            stack.append((indent, new_dict))
    return root, body



def _load_skill_file(path: Path, bundled: bool) -> Optional[Skill]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return None
    meta, body = parse_frontmatter(text)
    name = meta.get("name") or path.parent.name
    description = meta.get("description") or ""
    version = str(meta.get("version") or "0.0.0")
    hermes = meta.get("metadata", {})
    if not isinstance(hermes, dict):
        hermes = {}
    hermes_dict = hermes.get("hermes", {}) if isinstance(hermes.get("hermes"), dict) else {}
    tags = hermes_dict.get("tags", []) if isinstance(hermes_dict.get("tags"), list) else []
    related = hermes_dict.get("related_skills", []) if isinstance(hermes_dict.get("related_skills"), list) else []
    return Skill(
        name=name,
        description=description,
        version=version,
        tags=[str(t) for t in tags],
        related_skills=[str(r) for r in related],
        body=body.strip(),
        source_path=path,
        bundled=bundled,
    )


def find_skill(name: str) -> Optional[Skill]:
    """按 name 找一个 skill。"""
    for s in load_all_skills().skills:
        if s.name == name:
            return s
    return None


def load_all_skills() -> SkillLoadResult:
    """扫描 bundled + optional 两个目录,返回所有 SKILL.md。

    目录结构(每个 skill 一个子目录):
        skills/<skill-name>/SKILL.md
        optional-skills/<skill-name>/SKILL.md
    """
    result = SkillLoadResult()
    for base, bundled in [(skills_dir(), True), (optional_skills_dir(), False)]:
        if not base.exists():
            continue
        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            skill = _load_skill_file(skill_file, bundled=bundled)
            if skill is None:
                result.errors.append((skill_file, "无法读取文件"))
                continue
            if not skill.name or not skill.description:
                result.errors.append((skill_file, "缺 name 或 description"))
                continue
            result.skills.append(skill)
    return result
