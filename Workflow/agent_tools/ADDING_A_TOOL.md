# Alfred Chat Tool Registry — 添加新工具指南

> **本目录是 Alfred Chat 的"轻量级"工具系统**(W1 减法版)
> 与 Hermes 的 plugin framework 相比,我们**只**做自注册,**不**做 plugin.yaml、不做 pip 加载、不做 plugin context API。

## 0. 设计原则(为什么是「轻量版」)

| Hermes 的做法 | Alfred Chat 的做法 | 理由 |
|--------------|--------------------|------|
| 75 个 plugin + 17 类 | 30+ 工具,直接 import | Alfred 是单用户本地工具,不需要市场 |
| `plugin.yaml` + `__init__.py` 双文件 | 一个 `.py` 文件即可 | 形式主义,Alfred 工具不需要 manifest |
| pip entry points 自动加载 | 不做 | 避免污染 Alfred 自己的 Python 环境 |
| Plugin context API | 不做 | Alfred 没有「插件之间相互调用」需求 |
| 28 个 model-provider | 3 个 + 自定义 endpoint | Alfred 用户手选 LLM,不需要池化 |

**结论**:Alfred 的「插件」就是「JXA 调一个 Python 脚本」,不需要搞 plugin framework。Tool Registry 已经是「刚刚好」。

## 1. 目录结构(实际)

```
Workflow/agent_tools/
├── __init__.py            # 导入时自动 discover 所有子模块
├── registry.py            # ToolDef / REGISTRY / registry_tool_schemas
├── file_read.py           # 工具 1(file 类别)
├── obsidian_search.py     # 工具 2(obsidian 类别)
├── memory.py              # 工具 3(memory 类别)
└── ADDING_A_TOOL.md       # 本文档
```

**已搬工具**:3 个(file_read / obsidian_search / memory)
**未搬工具**:27 个(保留在 `local_agent.py` 的 if-elif 链里,继续工作)
**总覆盖率**:9%(W1 验证模式,后续 W2/W3 渐进搬)

## 2. 添加一个新工具的完整流程

### Step 1: 创建文件 `Workflow/agent_tools/<my_tool>.py`

模板:

```python
"""my_tool - 一句话描述。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

# 让 agent_tools/ 里的模块能找到 local_agent 的工具函数
WORKFLOW_DIR = Path(__file__).resolve().parent.parent
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

from local_agent import (  # noqa: E402  -  按需 import 共享工具
    allowed,
    resolve_path,
    # ... 任何 local_agent 里的函数
)
from agent_tools.registry import REGISTRY, ToolDef


def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    """handler 签名固定:(args: dict) -> (status, text, footer)"""
    # 1. 解析参数
    target = args.get("path", "")
    # 2. 业务逻辑
    content = target.read_text(encoding="utf-8")
    # 3. 返回 (status, assistant_text, footer)
    return "success", f"内容:\n\n{content}", f"已读取"


REGISTRY.register(ToolDef(
    name="my_tool",
    toolset="my_category",           # file / obsidian / memory / task / ...
    description="一句话描述(给 LLM 看的)",
    handler=handle,
    schema={                          # JSON Schema,OpenAI function-calling 风格
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要操作的路径"
            }
        },
        "required": ["path"]
    },
    requires_args_in_user_dir=True,   # 可选,标记是否走 /Users/DRLer 护栏
))
```

### Step 2: 在 `__init__.py` 中导入

```python
# Workflow/agent_tools/__init__.py 末尾加一行:
from . import my_tool
```

(也可以用 `pkgutil.iter_modules` 自动发现,但显式 import 更清晰、更容易调试。)

### Step 3: 测试

```bash
# 验证工具被注册
python3 Workflow/local_agent.py --tool-list
# 应输出包含 "my_tool"

# 验证 schema 正确
python3 Workflow/local_agent.py --tool-schema | grep -A 20 "my_tool"

# 验证能执行
python3 Workflow/local_agent.py --tool '{"tool":"my_tool","args":{"path":"/tmp/test.txt"}}'

# 跑测试套件
python3 scripts/test_tool_registry.py
```

完成。**不需要改 `local_agent.py` 任何代码**(registry 自动接管)。

## 3. handler 签名的契约

```python
def handle(args: Dict[str, Any]) -> Tuple[str, str, str]:
    return ("success" | "error" | "needs_confirmation", assistant_text, footer)
```

| 返回值 | 含义 | 例子 |
|--------|------|------|
| `"success"` | 成功 | `("success", "已读取", "已读取 foo.txt")` |
| `"error"` | 失败 | `("error", "文件不存在", "读取失败")` |
| `"needs_confirmation"` | 危险操作,需用户确认 | `("needs_confirmation", "将删除 foo.txt,输入「确认执行」继续", "删除待确认")` |

**`assistant_text`**:展示给用户的主要内容(可以含 Markdown)
**`footer`**:Alfred 底栏简短提示(< 30 字)

**`requires_args_in_user_dir=True` 标记**:registry **不强制**走护栏(那是 handler 自己的事),但标记是给未来护栏层用的。当前 W1 阶段,所有 file 类工具都自己调 `allowed(target)`。

## 4. 不要做的事(减法版的核心)

### ❌ 不要创建 plugin.yaml

```yaml
# 这是 Hermes 的做法,我们不要学
name: my_tool
version: 1.0.0
pip_dependencies: [requests]
hooks: [on_session_end]
```

理由:Alfred 工具就是一个 Python 文件,不需要 manifest。

### ❌ 不要做 pip 加载

```python
# 不要做
def discover_plugins_from_pip():
    import importlib.metadata
    for ep in importlib.metadata.entry_points(group="alfred_chat.tools"):
        ep.load()
```

理由:Alfred Workflow 用 `/usr/bin/python3` 跑,**不会**安装用户的 pip 包;做 pip 加载会污染环境或失败。

### ❌ 不要做 plugin context API

```python
# 不要做
class PluginContext:
    def register_tool(self, ...): ...
    def register_hook(self, ...): ...
    def call_other_plugin(self, ...): ...
```

理由:Alfred 工具之间不需要相互调用,一个工具 = 一个独立函数。

### ❌ 不要做 hot reload

```python
# 不要做
import watchdog
observer = Observer()
observer.schedule(...)
```

理由:Alfred Workflow 关闭即死,重启才生效;热加载是过度工程。

### ❌ 不要做用户可装第三方工具的目录

```python
# 不要做
USER_TOOLS_DIR = Path.home() / "Alfred Chat Data" / "tools"
for f in USER_TOOLS_DIR.glob("*.py"):
    importlib.import_module(f.stem)
```

理由(W1 阶段):Alfred 用户就一个,**不需要第三方工具市场**;后续 W2+ 看用户反馈再决定。

## 5. 已搬工具的迁移范例(参考用)

把原 `local_agent.py` 里的 `execute_xxx()` 搬过来,做 3 件事:
1. 把 `action: Action` 改成 `args: dict`
2. 提取参数用 `args.get("xxx", "")` 替代 `action.xxx`
3. 加 `@REGISTRY.register(ToolDef(...))`

**`file_read.py` 的关键差异**:
- 原:`def execute_read(action: Action)` 用 `action.path`
- 新:`def handle(args: dict)` 用 `args.get("path", "")`

**`memory.py` 的关键差异**:
- 原:`memory_add` / `memory_replace` / `memory_remove` / `memory_list` 是 4 个不同 tool
- 新:统一用 `memory` 一个 tool,通过 `args.get("action")` 分发(LLM 协议更简洁)

## 6. 未来(W2+)该搬的工具

按优先级:

| 工具 | 类别 | 工作量 | 价值 |
|------|------|------:|-----:|
| `obsidian_read` | obsidian | 0.5 天 | 高(LLM 经常调) |
| `obsidian_write` / `obsidian_append` | obsidian | 0.5 天 | 高 |
| `obsidian_daily_read` / `obsidian_daily_append` | obsidian | 0.5 天 | 高(每天用) |
| `task_add` / `task_list` / `task_done` | task | 0.5 天 | 中 |
| `session_search` | search | 0.5 天 | 中 |
| `reminder_add` | reminder | 0.5 天 | 中 |
| `obsidian_search` ← 已搬 | obsidian | — | — |
| `memory` ← 已搬 | memory | — | — |
| `file_read` ← 已搬 | file | — | — |

W2 一次搬 5-6 个,W3 搬完所有。

## 7. 故障排查

### 工具没出现在 `--tool-list` 输出里

1. 检查 `Workflow/agent_tools/__init__.py` 是否 `from . import my_tool`
2. 检查 `my_tool.py` 顶层是否调用了 `REGISTRY.register(ToolDef(...))`
3. 跑 `python3 -c "from agent_tools import REGISTRY; print(REGISTRY.names())"` 看是否抛异常

### 工具执行报 "未知工具"

说明 `run_tool_call` 没走 registry 路由,可能原因:
- 工具名拼写不一致(LLM 用大写 vs 你注册小写)
- `data["tool"]` 是 None(LLM 没出 tool_call)

### 工具执行抛异常

handler 内 try/except 已经捕获,会返回 `("error", f"工具 {name} 执行失败:{exc}", ...)`。看 `assistant_text` 即可。

### chat.js 没看到新工具的 schema

`loadToolSchemas()` 有缓存,Alfred 重启后才会重新调用 `--tool-schema`。改完代码要重启 Alfred。

## 8. 参考资料

- `/Users/DRLer/Desktop/cursor项目/alfred chat/Workflow/agent_tools/registry.py` — 注册表实现
- `/Users/DRLer/Desktop/cursor项目/alfred chat/scripts/test_tool_registry.py` — 测试套件
- [[Alfred Chat 借鉴 Hermes 升级方案]] — 升级决策
- [[Alfred Chat 不该借鉴 Hermes 的能力]] — 反模式
- Hermes `tools/registry.py` — 灵感来源,**不是照搬**

---

**作者**:DRLer
**最后更新**:2026-06-19
**版本**:W1(减法版,3 个示范工具)
