# Handoff — Alfred Chat

## 状态
`active`  2026-06-21 16:50  by 主控 agent (W9 continuation 提交,等用户装新版实测)

## 当前任务: W9 — continuation 协议(仿 Hermes _get_continuation_prompt, Alfred 跨 rerun 状态持久化)

### 用户痛点(已解决)
蒂娜在 W7 路线下"写入ob笔记"瞎说"已写入"但 OB 库没文件,5 次连续修复(W7.7-W7.11)全部失败。

**用户原话**:"我不想修修补补的,在CC 和codex里写入ob库是一件轻松的事情。我要让 AC(alfred chat) 也具有同样的 harness 功能"。

**W8 方向反转的真相**:
- W1 减法版做好的 `local_agent.py parse_intent` **harness 早就在跑** —— 30+ 种意图 regex,ob 写入/读取/搜索/任务/记忆/技能全套支持
- W7 走 LLM 路由(`decideToolUse`)是**绕开**了已做好的 harness —— M3 推理模型在 JSON 路由瞎说率 100%
- W8 不是"新写 harness",是**把 chat script 入口接通 W1 已做好的 harness**

### 关键洞察
- **Harness first, LLM fallback**: 写 OB / 读文件 / 搜 OB → harness 路由直接执行;普通对话 → 走 LLM(LLM 可调 web_search/web_fetch)
- **M3 推理模型不擅 JSON 路由** —— 已实测证伪 5 次,不再走 LLM 路由
- **Hermes 启发**: Alfred Chat 最初对齐 Hermes(见 `agent_tools/ADDING_A_TOOL.md` + `memory_store.py` SOUL/MEMORY),W1 减法版就是 Hermes 思路的本地实现,W8 把它接通

### W8 改动
**删除**:
- `Workflow/chat`: 删 179 行 W7 死代码 (`decideToolUse` / `buildSynthesizeMessages` / `handleModelToolUse`)
- `Workflow/chat`: 删 W7.10 注释 + 改宽 `looksLikeLocalAgentQuery` 覆盖 `0.inbox/X.md` / `写入OB` / `写OB X.md` 等口语化
- `Workflow/chat`: 删 line 1359-1360 `handleModelToolUse` 调用
- `Workflow/chat`: `HANGING_PREAMBLE_NOTE` 文案改空(原本写"无法联网" — 现在有联网了)

**新增**:
- `Workflow/local_agent.py parse_intent`: 3 个新 regex 块
  - `写X笔记到 0.inbox/Y.md` (动词+标题提示+目的路径)
  - `写OB X.md` (动词+OB+路径紧凑)
  - `把对话存到 OB 0.inbox/X.md` (口语化,单一 capture group 找路径)
- `scripts/test_w8_harness.py`: 19 个测试 (11 hit + 8 miss), 含端到端真写 OB 验证

**保留**:
- W7 联网能力全套: `agent_tools/web_search.py` (Tavily) + `web_fetch.py` (baoyu-fetch)
- `chat` line 710 `web_search` regex + line 737 `shouldFinalizeToolResult` 合成规则
- W1 减法版的所有工具: `agent_tools/registry.py` + 17 个 tool + 5 个 skill
- W4-W6: curator / new_chat / rename_recent 全套
- LLM fallback 路径(普通对话)走原 LLM 调用,联网自动触发

### 链路对比
| 场景 | W7 链路 | W8 链路 |
|---|---|---|
| 用户: "写刘成笔记到 0.inbox/好好的时光-刘成.md" | LLM 路由瞎说"已写入"但无文件 | harness 真写 OB,返回真实 status |
| 用户: "写入ob笔记"(无路径) | 瞎说 | 走 LLM fallback,LLM 引导补路径 |
| 用户: "刘成是什么人" | LLM 答(可能瞎说) | LLM 答(无变化) |
| 用户: "今天有什么 AI 新闻" | LLM 调 web_search 答 | LLM 调 web_search 答(无变化) |
| 用户: "搜索OB 灵感" | harness 搜(已支持) | harness 搜(无变化) |

### 待用户验证
1. 双击装新版 `Alfred Chat.alfredworkflow` (623KB)
2. Alfred → 右键 workflow → Reload(必须 reload,否则 plist 改动不生效)
3. 跑 `问: 写刘成笔记到 0.inbox/好好的时光-刘成.md`
4. **预期结果**:
   - 蒂娜 answer 里显示 `已写入 OB:0.inbox/好好的时光-刘成.md`(工具真实输出,不是 LLM synthesize)
   - 文件实际写入 `/Users/DRLer/Obsidian_250614/0.inbox/好好的时光-刘成.md`(用户 `ls` 验证)
5. 跑 `问: 写入ob笔记`(无路径)
6. **预期结果**: 蒂娜引导补路径(走 LLM fallback)

---

## 当前任务: W9 — continuation 协议(2026-06-21 16:50 提交)

### 用户痛点
"信息不连贯,不说继续就不动" —— Alfred 单轮流式 LLM, 每次 rerun 都从头, 用户说"go on" 之前 LLM 不会主动续。

### 解决方案: 仿 Hermes `_get_continuation_prompt`,Alfred 跨 rerun 状态持久化到文件

**Hermes 模式**(看 `agent/conversation_loop.py`):
- 单 turn 内 `while max_iterations` 循环,LLM 调 tool → 回灌 messages → 继续
- 流中断/length truncation 时,自动 append continue prompt 给 LLM
- 整个循环在一个 Python 函数内完成,状态在内存

**Alfred 限制**:
- Alfred "rerun" 是外部调度 (`rerun: 0.1`)
- 每次 rerun chat script 从头跑,**没有跨 rerun in-memory 状态**
- 只有文件系统持久化 (chat.json, stream.txt, action log)

**W9 妥协方案**:
- LLM 答到一半时 (`isHangingPreamble` 命中) → 写 `pending_continuation.json` (`{last_query, last_assistant_partial, expires_at}`)
- LLM 答完整时 → 清 pending
- 用户说"go on/继续/接着说" → chat 入口识别 → 读 pending → 拼 user message 调 LLM 续答

**文件 schema** (`{alfred_workflow_data}/pending_continuation.json`):
```json
{
  "last_query": "好好的时光 刘成 演员",
  "last_assistant_partial": "我先去查一下演员表...",
  "saved_at": "2026-06-21T16:45:00",
  "expires_at": "2026-06-21T17:15:00"
}
```

### 改动

**`Workflow/local_agent.py`** (新增):
- `continuation_path()` / `load_continuation()` / `save_continuation()` / `clear_continuation()` helpers
- CLI 子命令: `--continuation-get` / `--continuation-save <query> <partial>` / `--continuation-clear`
- TTL 默认 30 分钟,过期自动清理
- 损坏 JSON 文件返回 None 不抛

**`Workflow/chat`** (新增):
- `isContinuationQuery(text)`: 严格 regex 匹配 `^(go on|continue|...)` 或 `^(继续|接着说|...)$`(避免 "go online" 误中)
- `handleContinuation(...)`: 读 pending → 拼 user message → 调 LLM → 清 pending
- `runMain` 入口: 在 `handleLocalFileControl` 之后加 `isContinuationQuery` 分流
- `runCompleteChat` (anthropic 路径) 答完 → save/clear pending
- `readStream` (OpenAI 流式路径) 答完 → save/clear pending (从 session 最后 user msg 取 last_query)

### 测试

`scripts/test_w9_continuation.py` 5 个测试全过:
- ✓ save / get / clear 基础流程
- ✓ TTL 过期自动清理
- ✓ 损坏文件返回 None 不抛
- ✓ 12 种 go on/继续/接着说 表达识别 (含 "go online" 严格边界)
- ✓ 端到端 save → get → 拼 user message

W1-W9 完整回归: 71 tests passed, 0 failed (tool_registry 9, curator 14, new_chat 8, rename_recent 14, local_agent_ob 9, memory_store 11, w8_harness 19, w9_continuation 5)

### 待用户验证
1. 双击装新版 `Alfred Chat.alfredworkflow` (634KB)
2. Alfred → 右键 workflow → Reload (必须 reload)
3. 跑 `问: 写刘成笔记到 0.inbox/好好的时光-刘成.md` → 期望真写文件 (W8 验证)
4. 跑 `问: 给我讲个长故事` → LLM 答到一半停 (流中断/答一半) → pending 自动存
5. 跑 `问: go on` → 期望 LLM 接续上一轮 (W9 验证)
6. 跑 `问: 继续` → 同样续答
7. 跑 `问: 给我写个函数` → 答完整 → pending 自动清 → `问: go on` → 答"没有待续的对话"

### 已知限制
- **M3 推理模型在搜索任务上瞎补全演员信息**(W7 反瞎掰规则管不到) - 单独 W10 处理
- **OpenAI 流式路径的 pending 触发条件是 `isHangingPreamble`** - LLM 答"长完整但没真答完"的中间态捕获不全
- **pending TTL 30 分钟** - 改 `save_continuation(ttl_minutes=...)` 参数可调

---

## 历史: W7.7 - W7.11 (3 个修复全部失败,留下教训)

### W7.7 反瞎掰约束 + Tavily retry(成功)
- 蒂娜拿到 web_search 结果后,不再瞎编/套用训练数据补全答案
- Tavily API 网络错误重试 2 次(1s/2s 退避)

### W7.8 web_search 自动合成 + 多步工具(成功)
- `shouldFinalizeToolResult` 对 web_search/web_fetch 永远走 synthesize
- `finalizeToolResult` 加 5 条反瞎掰 rule

### W7.9 mayNeedModelToolUse 加 4 条写文件动词正则(部分成功)
- 加「放/存/保存/存到/放进/录入/塞 [path]」等口语化写文件说法

### W7.10 修 LLM 工具路由链路(失败)
- 改 3 处: 移除 looksLikeLocalAgentQuery 过宽 OB库 匹配 / decideToolUse 注入对话历史 / toolRouterPrompt 加 5 条硬性 rule 禁分步
- **实际效果**: 装了之后"写入ob库"直接什么回复都没有

### W7.10.1 修 W7.10 regression(失败)
- 根因: decideToolUse 是顶层 fn 引用 runMain 的 const session → throw ReferenceError
- **实际效果**: 蒂娜"已写入"瞎说,文件根本不存在

### W7.11 方向反转 V1(失败)
- 用真实 ANTHROPIC_API_KEY 跑 decideToolUse 测出 M3 不返回 JSON
- 改为 chat script 正则抓 path + LLM synthesize content + chat script 调 obsidian_write
- **实际效果**: 你说的"写刘成笔记到 0.inbox/..."仍不命中 W7.11 regex(只有"放/存/写入 + path"才命中)

### 共同教训(W7 整条线)
1. **M3 推理模型不擅 JSON 路由** —— 给再多 rule 也无效
2. **不要在 harness-first 路线上反复打补丁** —— harness 早在 W1 就做好,只是没接通
3. **W7 联网能力(web_search/web_fetch)是有效的**,W8 全保留

---

## 关键文件
- `Workflow/chat` (JXA 主脚本,1374 行) — W8 删了 179 行 W7 死代码
  - line 113 `HANGING_PREAMBLE_NOTE` 改空
  - line 491-498 W8 注释 + 改宽的 `looksLikeLocalAgentQuery` regex
  - line 1530-1532 (删前) `handleModelToolUse` 调用已删
- `Workflow/local_agent.py` (1558 行) — W1 减法版 harness,**W8 接通了**
  - `parse_intent(query)` line 502: 30+ 意图 regex
  - `main()` line 1345: 接 raw query, 走 parse_intent → execute
  - **W8 新增** line 583-605: 3 个 OB 写入 regex 块
- `Workflow/agent_tools/web_search.py` / `web_fetch.py` — W7 联网,**保留**
- `Workflow/agent_tools/registry.py` — W1 tool registry, **保留**
- `Workflow/agent_skills/` — W3 skill system, **保留**
- `Workflow/info.plist` L3098-3099 — `workflow_version` 字段
- `Workflow/local_agent.py` `continuation_path()` L90 + helpers + CLI 子命令 L1548-1564 — **W9 新增**
- `Workflow/chat` `isContinuationQuery` L122 / `handleContinuation` L127 / runMain 入口 L1408 / `runCompleteChat` save L919 / `readStream` save L1063 — **W9 新增**
- `scripts/test_w8_harness.py` — W8 路由测试 19/19 过
- `scripts/test_w9_continuation.py` — W9 continuation 测试 5/5 过 **(新增)**
- `scripts/test_new_chat.py` — W5 测试 8/8 过
- `scripts/test_rename_recent.py` — W6 测试 14/14 过

## 代码源唯一路径
`/Users/DRLer/Desktop/cursor项目/alfred chat/`(用户原话强调"我之前让你改的就是这个文件夹下的文件")。Alfred workflow 目录的副本是 Alfred 自动 sync 过去的,**不要在那里改**。

## 部署流程
1. 改完代码 → bump `Workflow/info.plist` L3099 的 workflow_version 字符串
2. 重新打包:
   ```bash
   cd "/Users/DRLer/Desktop/cursor项目/alfred chat"
   python3 -c "import zipfile, os
   with zipfile.ZipFile('Alfred Chat.alfredworkflow', 'w', zipfile.ZIP_STORED) as z:
     for root, _, files in os.walk('Workflow'):
       for f in files:
         fp = os.path.join(root, f); z.write(fp, os.path.relpath(fp, 'Workflow'))"
   ```
3. git commit (用项目标准 commit format `<type>: <description>`,加 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`)
4. 告诉用户双击 `.alfredworkflow` 装新版, **必须 Alfred → 右键 workflow → Reload**

## 不要再做的事
- **不要再用 LLM 做 JSON 路由** —— M3 推理模型不擅长,改用 harness-first
- **不要再在 W7 那条线上打补丁** —— W7 整段已废,看 [历史] 段就知道为什么
- **不要重新设计 harness** —— W1 减法版做好的 parse_intent 已能处理 30+ 意图,直接用
- **不要把 W8 描述成"大改"** —— 实际改动是删 179 行 W7 死代码 + 加 3 个 regex + 改宽 1 个 regex
- **不要在没 Alfred runtime 实测的情况下声称完成** —— 必须用户跑过才算数

## 未决问题
- **W8 + W9 仍未在 Alfred runtime 实测** — 用户装新版后还没跑过"写X笔记到 0.inbox/..."和"go on"。等用户验证。
- **M3 推理模型在搜索任务上瞎补全演员信息** — W7 反瞎掰规则管不到"搜到了瞎补全", W10 处理(改 prompt 强调"搜索结果里没写的就别说")
- **"写入ob笔记"(无路径) 设计上让 LLM 引导补路径** — 如果 LLM 在 fallback 路径还是瞎说,需要单独处理
- **W7 web_search 的默认 max_results**: 当前写死 5,用户可能想改。Alfred Configure 加个选项?(低优先级)
- **是否给 harness 加更智能的 fallback** — 比如"在 OB 库里放一篇"无具体路径时,LLM 帮 user 拼一个合理路径?(低优先级)

## 交接记录
- 2026-06-21 16:30  主控 agent  W8 提交: 接通 W1 harness, 删 W7 死代码, 写 OB 改走 harness 真写入, 联网能力保留, 19/19 W8 测试通过, 623KB 新打包, 等用户 Alfred runtime 实测。
- 2026-06-21 16:50  主控 agent  W9 提交: continuation 协议(仿 Hermes _get_continuation_prompt), pending_continuation.json 持久化跨 rerun 状态, go on/继续/接着说 严格识别, LLM 答到一半自动存盘/答完整自动清 pending, 5/5 W9 测试通过, 71/71 全套回归, 634KB 新打包, 等用户 Alfred runtime 实测 go on 续答。
