"""Skill retrieval - 关键词匹配相关 SKILL。

减法版:
- 不做向量检索(不引 embedding 依赖)
- 不做 FTS5 单独索引(直接关键词 + 标签匹配)
- 启发式:description 包含词 + tags 命中 + name 命中,加权重排序
"""

from __future__ import annotations

import re
from typing import List, Set, Tuple

from .loader import Skill, load_all_skills


# Match CJK chars individually OR alphabetic word chunks
_CJK_RE = re.compile(r"[\u4e00-\u9fff]", re.UNICODE)
_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
_STOPWORDS = {
    # 中文常见停用词
    "的", "了", "在", "是", "我", "你", "他", "她", "它", "们",
    "和", "与", "或", "也", "都", "就", "把", "被", "给", "让",
    "什么", "怎么", "为什么", "可以", "需要", "想", "要", "一下", "帮忙",
    # 英文常见停用词
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "with", "by", "and", "or", "not",
    "i", "you", "he", "she", "it", "we", "they", "this", "that", "do", "does",
    "did", "have", "has", "had", "will", "would", "should", "can", "could", "may",
}


def _tokenize(text: str) -> Set[str]:
    """分词: 英文单词 + CJK 单字拆开，去停用词，转小写。"""
    text = text or ""
    out: Set[str] = set()
    # English words (2+ chars)
    for tok in _WORD_RE.findall(text):
        t = tok.lower().strip()
        if t and t not in _STOPWORDS and len(t) >= 2:
            out.add(t)
    # CJK: each single char is a token (2-char bigrams for better matching)
    cjk = _CJK_RE.findall(text)
    for i, ch in enumerate(cjk):
        if ch not in _STOPWORDS:
            out.add(ch)
        # Add bigram
        if i + 1 < len(cjk):
            out.add(ch + cjk[i + 1])
    return out


def _score_skill(skill: Skill, query_tokens: Set[str]) -> int:
    """打分:每个 query token 命中一次 +3 (description), +2 (tags), +1 (name/body)。"""
    if not query_tokens:
        return 0
    desc_tokens = _tokenize(skill.description)
    tag_tokens = {_t.lower() for _t in skill.tags}
    name_tokens = _tokenize(skill.name)
    body_tokens = _tokenize(skill.body)
    score = 0
    for qt in query_tokens:
        if qt in desc_tokens:
            score += 3
        if qt in tag_tokens:
            score += 2
        if qt in name_tokens:
            score += 1
        if qt in body_tokens:
            score += 1
    return score


def retrieve_relevant_skills(query: str, top_k: int = 3, min_score: int = 2) -> List[Tuple[Skill, int]]:
    """给定用户 query,返回 top_k 相关 skill + 分数。"""
    tokens = _tokenize(query)
    if not tokens:
        return []
    result = load_all_skills()
    scored: List[Tuple[Skill, int]] = []
    for skill in result.skills:
        s = _score_skill(skill, tokens)
        if s >= min_score:
            scored.append((skill, s))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def format_skills_prompt_block(query: str, top_k: int = 2) -> str:
    """生成注入 system prompt 的 SKILL 摘要 block。

    格式:
    ## 相关 Skill(供你参考)
    - **ob-search**: 在 OB 库内搜索笔记
      摘要: 第一段...
    - **git-conflict**: 解决 git 冲突
      摘要: 第一段...

    如果 query 没有相关 skill,返回空字符串。
    """
    matches = retrieve_relevant_skills(query, top_k=top_k)
    if not matches:
        return ""
    lines = ["## 相关 Skill(供你参考,需要时调用对应工具)", ""]
    for skill, score in matches:
        # 提取 body 第一段(去掉 markdown 标题)作为摘要
        first_para = ""
        for para in skill.body.split("\n\n"):
            p = para.strip()
            if p and not p.startswith("#"):
                first_para = p[:200]
                break
        lines.append(f"- **{skill.name}** (v{skill.version}, 相关度 {score})")
        lines.append(f"  描述:{skill.description}")
        if first_para:
            lines.append(f"  摘要:{first_para}")
        if skill.tags:
            lines.append(f"  标签:{', '.join(skill.tags[:6])}")
        lines.append("")
    return "\n".join(lines).rstrip()


# CLI 支持
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m agent_skills.retrieve <query>")
        sys.exit(1)
    q = " ".join(sys.argv[1:])
    matches = retrieve_relevant_skills(q)
    if not matches:
        print(f"(no skills matched for: {q!r})")
    for skill, score in matches:
        print(f"[{score}] {skill.name} v{skill.version}: {skill.description}")
