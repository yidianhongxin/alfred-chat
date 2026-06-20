"""Alfred Chat — Provider Plugin System (W5).

每个 provider 是一个 Python 模块，放在 agent_providers/ 目录下。
模块必须实现函数:
    def chat(prompt: str, system_prompt: str = "", history: list[dict] | None = None, **kwargs) -> tuple[str, dict]:
        返回 (response_text, usage_meta)
        usage_meta 示例: {"model": "gpt-4o", "tokens": 150, "provider": "openai"}

可选实现:
    def schema() -> dict | None:
        返回 provider 的描述 schema，供 Alfred UI 使用。

    def health_check() -> tuple[bool, str]:
        返回 (ok, detail)。

配置:
    优先级: provider_single 环境变量 → PROFILE 文件 → 默认
    PROFILE 文件: $alfred_workflow_data/profile.json
    格式:
    {
      "provider": "openai",
      "settings": {
        "api_key": "sk-...",
        "model": "gpt-4o",
        "base_url": null
      }
    }
"""

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROVIDER_DIR = Path(__file__).resolve().parent
CONFIG_HOME = Path(os.environ.get("alfred_workflow_data", "/tmp/alfred-chat"))
PROFILE_PATH = CONFIG_HOME / "profile.json"
DEFAULT_PROVIDER = "openai"

_config_cache: Optional[Dict[str, Any]] = None
_config_mtime: float = 0.0


def _discover_providers() -> Dict[str, Path]:
    """扫描 agent_providers/ 目录下的所有 provider 模块。"""
    providers: Dict[str, Path] = {}
    for f in PROVIDER_DIR.glob("*.py"):
        name = f.stem
        if name.startswith("_") or name.startswith("."):
            continue
        providers[name] = f
    return providers


def _load_config() -> Dict[str, Any]:
    global _config_cache, _config_mtime
    try:
        mtime = PROFILE_PATH.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _config_cache is not None and mtime <= _config_mtime:
        return _config_cache
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    _config_cache = data
    _config_mtime = mtime
    return data


def _module_name_for(provider: str) -> str:
    return f"agent_providers.{provider}"


def get_provider() -> str:
    """返回当前生效的 provider。"""
    env = os.environ.get("provider_single", "").strip().lower()
    if env:
        return env
    cfg = _load_config()
    return cfg.get("provider", DEFAULT_PROVIDER).strip().lower()


def get_settings() -> Dict[str, Any]:
    """返回当前 provider 配置。"""
    cfg = _load_config()
    return dict(cfg.get("settings", {})) if "settings" in cfg else {}


def list_providers() -> List[str]:
    return sorted(_discover_providers().keys())


def resolve_module(name: str):
    """动态加载 provider 模块。"""
    try:
        mod = importlib.import_module(_module_name_for(name))
    except ImportError as exc:
        raise RuntimeError(f"Provider '{name}' 未安装或格式不正确: {exc}") from exc
    if not hasattr(mod, "chat"):
        raise RuntimeError(f"Provider '{name}' 模块缺少 chat 函数")
    return mod


def chat(
    prompt: str,
    system_prompt: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    **kwargs: Any,
) -> Tuple[str, Dict[str, Any]]:
    """使用当前 provider 发起对话。

    Returns:
        (response_text, usage_meta)
    """
    prov = get_provider()
    mod = resolve_module(prov)
    settings = get_settings()
    merged = {**settings, **kwargs}
    return mod.chat(prompt, system_prompt=system_prompt, history=history, **merged)


def health_check(provider: Optional[str] = None) -> Tuple[bool, str]:
    prov = provider or get_provider()
    try:
        mod = resolve_module(prov)
    except Exception as exc:
        return False, str(exc)
    if hasattr(mod, "health_check"):
        return mod.health_check()
    return True, "ok"


if __name__ == "__main__":
    print(f"Providers: {list_providers()}")
    print(f"Active: {get_provider()}")
    ok, detail = health_check()
    print(f"Health: {ok}, {detail}")
