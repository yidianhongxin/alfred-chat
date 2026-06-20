"""Tool registry - 减法版。

设计原则:
- 一个 ToolDef = 一行数据(name / toolset / description / handler / schema)
- handler 签名:def handler(args: dict) -> Tuple[str, str, str]
  返回 (status, assistant_text, footer),与原 execute_* 函数一致
- REGISTRY 是 module-level 单例,import 时自动填充
- 提供 --tool-schema JSON 输出,给 LLM 替代手写 prompt
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


ToolHandler = Callable[[Dict[str, Any]], Tuple[str, str, str]]


@dataclass
class ToolDef:
    """一个工具的元数据 + 处理函数。

    Attributes:
        name: 工具名(全局唯一,小写下划线,例:"file_read")
        toolset: 工具集分组(例:"file"、"obsidian"、"memory"),用于批量启停
        description: 一句话描述(给 LLM 看的)
        handler: 实际执行函数,签名 (args: dict) -> (status, text, footer)
        schema: 参数的 JSON Schema(给 LLM 看的,可选;缺省视为无参)
        requires_args_in_user_dir: 是否要求参数里的路径在 /Users/DRLer 下(护栏)
    """
    name: str
    toolset: str
    description: str
    handler: ToolHandler
    schema: Dict[str, Any] = field(default_factory=dict)
    requires_args_in_user_dir: bool = False


class _Registry:
    """Module-level 单例注册表。"""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDef] = {}
        self._toolsets: Dict[str, Set[str]] = {}

    def register(self, tool: ToolDef) -> ToolDef:
        """注册一个工具。同名会被覆盖(并打 warning)。"""
        if tool.name in self._tools:
            import sys
            print(f"[agent_tools] warn: '{tool.name}' 被重复注册,后者覆盖前者", file=sys.stderr)
        self._tools[tool.name] = tool
        self._toolsets.setdefault(tool.toolset, set()).add(tool.name)
        return tool

    def get(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)

    def all(self) -> List[ToolDef]:
        return sorted(self._tools.values(), key=lambda t: (t.toolset, t.name))

    def names(self) -> List[str]:
        return sorted(self._tools.keys())

    def toolsets(self) -> Dict[str, List[str]]:
        return {ts: sorted(names) for ts, names in self._toolsets.items()}

    def dispatch(self, name: str, args: Dict[str, Any], allowed_toolsets: Optional[set] = None) -> Tuple[str, str, str]:
        """通过名字执行工具。找不到返回 (error, ..., ...)。

        allowed_toolsets: 工具集白名单,None 或 {"all"} 表示全部启用。
        """
        tool = self.get(name)
        if not tool:
            return "error", f"未知工具:{name}", f"未知工具:{name}"
        if allowed_toolsets and "all" not in allowed_toolsets and tool.toolset not in allowed_toolsets:
            return "error", f"工具 {name} 已被禁用(所属 toolset: {tool.toolset})", f"{name} 被禁用"
        try:
            return tool.handler(args or {})
        except Exception as exc:  # noqa: BLE001
            import traceback
            return "error", f"工具 {name} 执行失败:{exc}", f"{name} 失败: {type(exc).__name__}"

    def filter_schemas(self, allowed_toolsets: Optional[set] = None) -> List[Dict[str, Any]]:
        """根据工具集白名单过滤 schemas(给 LLM 看的)。"""
        all_schemas = registry_tool_schemas()
        if not allowed_toolsets or "all" in allowed_toolsets:
            return all_schemas
        return [s for s in all_schemas if s.get("toolset") in allowed_toolsets]


REGISTRY = _Registry()


def registry_tool_names() -> List[str]:
    """返回所有注册工具的名字(给 chat.js / --tool-schema 用)。"""
    return REGISTRY.names()


def registry_tool_schemas() -> List[Dict[str, Any]]:
    """把注册表转成 LLM 友好的 OpenAI function-calling 风格 schema 列表。

    输出示例:
    [
      {
        "name": "file_read",
        "description": "读取本地文件内容",
        "parameters": {
          "type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]
        }
      },
      ...
    ]
    """
    out: List[Dict[str, Any]] = []
    for tool in REGISTRY.all():
        entry: Dict[str, Any] = {
            "name": tool.name,
            "toolset": tool.toolset,
            "description": tool.description,
        }
        if tool.schema:
            entry["parameters"] = tool.schema
        else:
            entry["parameters"] = {"type": "object", "properties": {}}
        out.append(entry)
    return out
