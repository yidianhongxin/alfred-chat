"""Tool registry for Alfred Chat local_agent.

减法版 W2:
- 11 个工具全部进 registry
- 19 个旧工具继续走 if-elif 链(保留兼容)
- 新工具成本:1 个文件 + 1 行 REGISTRY.register

不再做:
- plugin.yaml / pip 加载 / plugin context API
"""

from .registry import REGISTRY, ToolDef, registry_tool_schemas, registry_tool_names

# W1: 3 个示范工具
from . import file_read
from . import obsidian_search
from . import memory

# W2: 8 个新增工具
from . import obsidian_read
from . import obsidian_write      # 内含 obsidian_write + obsidian_append
from . import obsidian_diary      # 内含 browse / recent / daily_read / daily_append
from . import task                # 内含 task_add / task_list / task_done
from . import session_search
from . import reminder_add

__all__ = [
    "REGISTRY",
    "ToolDef",
    "registry_tool_schemas",
    "registry_tool_names",
]
