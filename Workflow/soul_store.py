#!/usr/bin/env python3
"""Agent soul/persona file — Hermes-inspired SOUL.md."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple


def memories_dir(data_dir: Path) -> Path:
    path = data_dir / "memories"
    path.mkdir(parents=True, exist_ok=True)
    return path


def soul_path(data_dir: Path, override: Optional[str] = None) -> Path:
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return memories_dir(data_dir) / "SOUL.md"


def default_soul_template(assistant_name: str = "Assistant") -> str:
    name = assistant_name.strip() or "Assistant"
    return f"""# 身份

你是 **{name}**，运行在 Alfred Chat 里的本地 Agent 助手。你的存在意义是帮用户把事情做完，而不是聊天打发时间。

# 性格

- 简洁、靠谱、有主见；少说「很高兴为您服务」这类空话
- 用简体中文回答；技术问题给可执行步骤，不写空洞建议
- 可以表达立场和偏好，但不过度说教
- 用户用 ⊙/⊚ 区分对话双方时，你就是 ⊚ 那一侧

# 工作方式

- 用户要求读写本地文件、OB 库、提醒、记忆时，主动走本地 Agent，不说「我无法访问你的电脑」
- 长期记忆在 `memories/MEMORY.md` 与 `memories/USER.md`；跨对话记得住，不要声称失忆
- 不确定时先问一个关键问题，而不是猜

# 边界

- 本地文件操作仅限 `/Users/DRLer` 目录（硬限制）
- 删除、覆盖等危险操作需用户确认
- 不编造未读取的文件内容；读了再说，没读就明说
"""


def ensure_soul(data_dir: Path, assistant_name: str = "Assistant", override: Optional[str] = None) -> bool:
    path = soul_path(data_dir, override)
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_soul_template(assistant_name), encoding="utf-8")
    return True


def read_soul(data_dir: Path, override: Optional[str] = None) -> str:
    path = soul_path(data_dir, override)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_soul(data_dir: Path, content: str, *, append: bool = False, override: Optional[str] = None) -> Tuple[bool, str]:
    path = soul_path(data_dir, override)
    text = content.strip()
    if not text:
        return False, "灵魂内容不能为空"

    path.parent.mkdir(parents=True, exist_ok=True)
    if append and path.exists():
        original = path.read_text(encoding="utf-8").rstrip()
        path.write_text(f"{original}\n\n{text}\n", encoding="utf-8")
    else:
        path.write_text(f"{text}\n", encoding="utf-8")
    return True, f"已更新灵魂：{path}"


def soul_prompt_block(data_dir: Path, override: Optional[str] = None) -> str:
    content = read_soul(data_dir, override)
    if not content:
        return ""
    return (
        "以下是你的灵魂与人格设定（SOUL.md）。回答时必须始终保持这一身份与风格；"
        "此文件定义你是谁，不是用户画像，也不是项目笔记：\n\n"
        f"{content}"
    )


def main() -> None:
    import sys

    data = Path(os.environ.get("alfred_workflow_data") or os.environ.get("ALFRED_WORKFLOW_DATA") or "/tmp/alfred-chat")
    override = os.environ.get("soul_file_path") or None
    assistant = os.environ.get("chat_assistant_label") or "Assistant"

    if len(sys.argv) > 1 and sys.argv[1] == "--ensure":
        created = ensure_soul(data, assistant, override)
        print('{"created": %s}' % ("true" if created else "false"))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--prompt":
        block = soul_prompt_block(data, override)
        print(block, end="" if block else "")
        return

    print(read_soul(data, override))


if __name__ == "__main__":
    main()
