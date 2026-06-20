"""web_fetch - 用 baoyu-fetch CLI 抓取指定 URL 并返回 Markdown。

baoyu-fetch 是 JimLiu/baoyu-skills 里的 CLI(Chrome CDP + 站点适配器),
适合抓取 X/Twitter / YouTube / HN / 通用网页(Defuddle 清洗)。

依赖:
- Node.js + bun
- Chrome 浏览器(系统默认即可)
- baoyu-fetch CLI 安装:npx -y skills add jimliu/baoyu-skills

CLI 路径覆盖(按优先级):
1. 环境变量 BAOYU_FETCH_BIN
2. 默认 ~/.agents/skills/baoyu-url-to-markdown/scripts/baoyu-fetch

典型调用链:
    web_search("好好的时光 刘成")
        → 返回搜索结果(链接列表)
    web_fetch("https://movie.douban.com/...")
        → 返回该页完整 Markdown 给 LLM 阅读
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from agent_tools.registry import REGISTRY, ToolDef


DEFAULT_BAOYU_FETCH = Path.home() / ".agents" / "skills" / "baoyu-url-to-markdown" / "scripts" / "baoyu-fetch"
TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 200_000  # ~200KB markdown,超出截断


def _resolve_baoyu_fetch() -> Optional[str]:
    override = (os.environ.get("BAOYU_FETCH_BIN") or "").strip()
    if override and Path(override).exists():
        return override
    if DEFAULT_BAOYU_FETCH.exists():
        return str(DEFAULT_BAOYU_FETCH)
    return None


def _check_bun() -> Optional[str]:
    """bun 是 baoyu-fetch 的运行时,缺失时给出明确指引。"""
    bun = shutil.which("bun")
    if bun:
        return bun
    return None


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    url = (args.get("url") or "").strip()
    if not url:
        return "error", "缺少 url 参数", "缺少 url"
    if not (url.startswith("http://") or url.startswith("https://")):
        return "error", f"url 必须是 http/https,收到:{url[:50]}", "url 协议无效"

    bun_path = _check_bun()
    if not bun_path:
        return (
            "error",
            "未检测到 bun 运行时。\n\n"
            "安装方式:`curl -fsSL https://bun.sh/install | bash`\n"
            "或 `brew install bun`",
            "缺少 bun",
        )

    fetch_bin = _resolve_baoyu_fetch()
    if not fetch_bin:
        return (
            "error",
            f"找不到 baoyu-fetch CLI({DEFAULT_BAOYU_FETCH})。\n\n"
            "安装方式:`npx -y skills add jimliu/baoyu-skills -y -g`",
            "缺少 baoyu-fetch",
        )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        proc = subprocess.run(
            [
                fetch_bin,
                url,
                "--format", "markdown",
                "--headless",
                "--timeout", str(TIMEOUT_SECONDS * 1000),
                "--output", str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS + 10,
        )
    except subprocess.TimeoutExpired:
        tmp_path.unlink(missing_ok=True)
        return "error", f"抓取超时(>{TIMEOUT_SECONDS + 10}s):{url}", "抓取超时"
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        return "error", f"启动 baoyu-fetch 失败:{exc}", f"fetch 启动失败:{type(exc).__name__}"

    if proc.returncode != 0:
        err_msg = (proc.stderr or proc.stdout or "").strip()[:500]
        tmp_path.unlink(missing_ok=True)
        return "error", f"抓取失败(returncode={proc.returncode}):\n{err_msg}", "抓取失败"

    if not tmp_path.exists() or tmp_path.stat().st_size == 0:
        tmp_path.unlink(missing_ok=True)
        return "error", "baoyu-fetch 未产出文件", "无输出"

    try:
        content = tmp_path.read_text(encoding="utf-8", errors="replace")
    finally:
        tmp_path.unlink(missing_ok=True)

    if len(content) > MAX_OUTPUT_BYTES:
        content = content[:MAX_OUTPUT_BYTES] + f"\n\n... [截断,共 {len(content)} 字节]"

    return "success", content, f"已抓取 {len(content)} 字节"


REGISTRY.register(ToolDef(
    name="web_fetch",
    toolset="web",
    description="用 baoyu-fetch 抓取指定 URL,返回完整 Markdown(含 YAML frontmatter)",
    handler=handle,
    schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要抓取的 http/https URL"
            },
        },
        "required": ["url"],
    },
))