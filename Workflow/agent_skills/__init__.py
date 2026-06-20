"""Skills System for Alfred Chat (W3).

符合 agentskills.io 规范的 SKILL.md frontmatter:
---
name: skill-name
description: "一句话描述"
version: 1.0.0
metadata:
  hermes:
    tags: [tag1, tag2]
    related_skills: [other-skill]
---

减法版原则:
- 不做 marketplace
- 不做跨设备同步(用户自己开 iCloud)
- 加载 / 检索 / 注入 prompt / skill_create / skill_improve / skill_curator(后台)
"""

from .loader import (
    Skill, SkillLoadResult, load_all_skills, find_skill,
    skills_dir, optional_skills_dir,
)
from .retrieve import retrieve_relevant_skills, format_skills_prompt_block
from .skillify import (
    skillify_from_recent, skillify_confirm_overwrite,
    skillify_improve, run_curator,
)

__all__ = [
    "Skill", "SkillLoadResult", "load_all_skills", "find_skill",
    "skills_dir", "optional_skills_dir",
    "retrieve_relevant_skills", "format_skills_prompt_block",
    "skillify_from_recent", "skillify_confirm_overwrite",
    "skillify_improve", "run_curator",
]
