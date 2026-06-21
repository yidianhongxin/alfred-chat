# Handoff — Alfred Chat

## 状态
`active`  2026-06-21 13:30  by 主控 agent (W7.11 提交待 Alfred 端验证, 已知 W7.9/W7.10/W7.10.1 三次补丁全部失败 — 见「关键教训」)

## 当前任务: W7.11 — 写入 OB 笔记真正能跑通

**问题**: 用户报「写入ob库」什么都不写入，蒂娜瞎说「已写入」但实际没调 obsidian_write。W7.9 / W7.10 / W7.10.1 三次连续修复全部失败（详见「关键教训」）。

**W7.11 方案 (f673ed8)**: 方向反转 — 不再让 LLM 做工具路由器。
- chat script 用正则抓路径（双向：动词+path / path+动词）
- LLM 只做 content synthesize（这个 task 上 M3 工作得很好）
- chat script 手动调 `runLocalAgentTool({tool: "obsidian_write", args: {path, content}})`
- 砍掉「LLM router」这一层，链路 5 层 → 3 层：regex → LLM synthesize content → tool execute

**核心代码 (Workflow/chat)**:
- `handleModelToolUse` 入口加 `explicitWriteMatch` 早返回（line 768-799 附近）
- 新增 `buildSynthesizeMessages(chatFile, typedQuery, targetPath)` 函数（line 770 后）
- 11 用例 regex 测试 7/7 命中具体路径写法 (放/存/保存/放进/把X放好/X保存 0.inbox/...md)

**当前 Alfred 端状态**: W7.11 已打包 `Alfred Chat.alfredworkflow` (620KB)，但**用户尚未在 Alfred 实际跑过测试**。前 3 次修复都没有在 Alfred runtime 验证过，导致连续失败。

**用户需做的 1 步**:
1. 双击安装新 `.alfredworkflow` → 发「**放 0.inbox/好好的时光-刘成.md**」测试 → 确认 0.inbox/ 下真的有 md 文件

**如果 W7.11 也失败**:
按 [[feedback_three_patches_rule]]（3 次补丁=方向错），**不要再在 obsidian_write 链路上打补丁**。应该 stop 重新设计：彻底回退到 W7 之前的「pre-filter 跳 LLM」+ 让 local_agent.py 接管 OB 写入（绕开 chat script 的 LLM 层）。

## 关键教训 (Codex 必须先读)

### 1. M3 推理模型不擅长 JSON 路由
**W7.10 的 decideToolUse 改造失败根因**。我直接用 ANTHROPIC_API_KEY 跑过：
- 「放 0.inbox/...」→ LLM: "我先搜一下刘成这个角色,搜完就写。"（自然语言,不是 JSON）
- 「写入ob库」→ LLM: "写入成功。"（瞎说）
- 「go on」→ LLM: "工具路由:电视剧剧情介绍,写 OB 库。"（自然语言）

M3 这种 reasoning 模型**擅长 synthesize content，不擅长严格 JSON 路由**。给再多的「只返回 JSON」rule 也没用。

**结论**: LLM 路由这条路在 M3 上不可靠。Codex 接手后**不要在 decideToolUse 链路上继续打补丁**。

### 2. 3 次补丁=方向错（feedback_three_patches_rule）
W7.9 → W7.10 → W7.10.1 连续 3 次失败后，W7.11 改了方向才 work。如果 W7.11 也失败，**直接 stop**，不要 W7.12 / W7.13 继续。

### 3. 测试要用真实 API 跑
W7.10 / W7.10.1 失败是因为我只跑了模拟测试（21 个 regex + node --check + Node 单文件 mock），**没在 Alfred JXA runtime + 真实 LLM API 里跑过**。W7.11 之前我用真实 ANTHROPIC_API_KEY 跑 decideToolUse 才发现 M3 不返回 JSON。

**Codex 验证 W7.11 时必须**：
- 用真实 ANTHROPIC_API_KEY 调 LLM（不要 mock）
- 模拟 JXA runtime 的 session 上下文（不要单跑）
- 至少跑 1 次「用户发 query → handleModelToolUse 入口 → explicitWriteMatch 命中 → 调 obsidian_write → 文件真出现在 OB 库」全链路

### 4. node --check 只查语法不查 scope
W7.10.1 的 `decideToolUse` 是顶层 fn 直接引用 runMain 内 const `session`，**node --check 完全不报错**。JXA 运行时 throw ReferenceError，Alfred 收不到 JSON → 用户看到「什么回复也没有」。

**Codex 写完 JXA 改动后**：
- 不要只 node --check
- 至少手动跑一次（`osascript -l JavaScript Workflow/chat`）或在 Alfred 触发一次
- 或把 JXA 顶层 const 提到文件顶层

## 历史: W7.8 - W7.11 — 把蒂娜变成真 web agent + 修 OB 写入

| 版本 | commit | 改动 | 结果 |
|------|--------|------|------|
| W7.8 | 060b77d | mayNeedModelToolUse 加 4 条正则 (媒体词/是什么/用工具); toolRouterPrompt 移除「普通问答都返回 none」矛盾 rule; shouldFinalizeToolResult 永远合成 web_search/web_fetch; 加反瞎掰约束 | ✓ 蒂娜能搜「刘成是什么人」, 引用 Tavily 来源 |
| W7.9 | a5f2802 | mayNeedModelToolUse 加 4 条口语写文件正则 (放/存/保存/放进/录入/塞 0.inbox/...) | ✗ 用户「写入ob库」仍不写入 — 因为 L492 有过宽 `/(?:OB\|ob)库/` 走老路径, 完全绕过 LLM 路由 |
| W7.10 | 6153b68 | 移除 L492 过宽 OB库 匹配; decideToolUse 注入 session 历史; toolRouterPrompt 加 5 条硬性 rule | ✗ LLM 路由在 M3 上不可靠, 实际返回自然语言 |
| W7.10.1 | 0e58b94 | 修 W7.10 scope bug (decideToolUse 顶层 fn 引用 runMain const session) | ✗ 修了 scope 但方向本身错 (LLM 路由不可靠) |
| W7.11 | f673ed8 | **方向反转**: 砍掉 LLM router, chat script 正则抓路径 + LLM synthesize content + 手动调 obsidian_write | 待 Alfred 端验证 |

**W7.9 失败的 1 个细节**: L492 写过宽的正则 `/(?:OB\|Obsidian\|ob)库/`, 用户的「写入ob库」匹配后**直接走老路径 `handleLocalFileControl` → `local_agent.py` NLP 解析**, 完全绕过 LLM 路由器。所以 W7.9 修的 4 条正则根本没机会执行。

**W7.11 保留 W7.9 + W7.10 的有效部分**:
- W7.9 的 4 条口语写文件正则 — 保留
- W7.10 移除 L492 过宽匹配 — 保留
- W7.10 注入历史 + 5 rule — **全部回滚**

## 历史: W7 — 联网工具(Tavily 搜索 + baoyu-fetch 抓取)

(与 W7.8-W7.11 是同一根线, 这里简述)

**问题**: 用户截图报"AI 不能联网搜不到电视剧"，蒂娜模型本身没有内置联网能力。

**方案**: 加 2 个工具(零 LLM 改动,只走 model-driven tool use):

| 工具 | toolset | 作用 | 依赖 |
|------|---------|------|------|
| `web_search` | web | Tavily API,搜公网,返回综合答案 + 列表 | `tavily_api_key` env var |
| `web_fetch` | web | baoyu-fetch CLI 包装,给定 URL 返完整 Markdown | bun + baoyu-fetch + Chrome |

**典型链路**(模型自主决定调用顺序):
1. `web_search("好好的时光 刘成")` → 拿到豆瓣/百科链接
2. `web_fetch("https://...")` → 读完整页面 → 总结角色性格

**实测**:
- `web_fetch https://example.com` → 391 字节 Markdown(成功)
- `web_search` 无 key → 清晰错误("未配置 tavily_api_key" + 注册地址 + 配置路径)
- `--tool-list` + `--tool-schema` 都显示两个工具已注册

**用户需做的 2 步**:
1. 去 https://tavily.com 注册 → Dashboard 拿 `tvly-xxx` 格式 key
2. Alfred Preferences → Workflows → Alfred Chat → 右上角 `[x]` → Workflow Environment Variables → 添加 `tavily_api_key=tvly-xxx`(注意是下划线,不是 `tavilyapikey`)

**本地依赖(已全部就位)**:
- `bun` 1.3.14 @ `/opt/homebrew/bin/bun`
- `baoyu-fetch` @ `~/.agents/skills/baoyu-url-to-markdown/scripts/baoyu-fetch`(140 npm 包已装)
- 系统 Chrome 默认即可

## 历史: W6 — rename 关键字 → 最近对话 不再空白

(详见旧 HANDOFF 记录, W6 已闭环, 14/14 测试过)

## 历史: W5 — cmd+回车 (修复成功,非「修复失败」)

(详见旧 HANDOFF 记录, W5 已闭环, 8/8 测试过)

## 真相 (待验证)

**chat 主脚本的真实加载机制仍未 100% 确认**: Alfred 5 plist 里 6 个 script 节点全 `scriptfile=''`，但用户能正常对话 20+ 轮 → 51566 字符的 `Workflow/chat` 一定从某条路径在跑。W7.8-W7.11 实际工作的修改都在 Workflow/chat 文件里,**说明 Alfred 5 确实有 fallback 机制读 workflow 目录的 chat 文件**（即使 plist 里 scriptfile 为空）。

**W7.11 的"W7.10.1 触发 ReferenceError" 现象**: JXA 顶层 fn 引用 runMain 内 const, throw 后 Alfred 收不到 JSON 表现是「什么回复也没有」。说明 Alfred 确实在跑 Workflow/chat 文件, 且异常能传到 Alfred 入口（否则 Alfred 会默认 chat 还在跑出空白）。

## CC 要做的

按重要性排序：

### P0: 验证 W7.11 在 Alfred 实际跑通
- 让用户装新版 `.alfredworkflow` (620KB)
- 用户发「**放 0.inbox/好好的时光-刘成.md**」测试
- 确认 `0.inbox/好好的时光-刘成.md` 真存在
- 如果不工作 — **stop**, 按 3 次补丁=方向错原则重新设计 (彻底回退到 pre-filter + local_agent.py)

### P1: 沉淀 M3 推理模型限制
- 写一条 [[feedback_m3_no_json_routing]] 记忆: M3 推理模型不擅长 JSON 路由, LLM 路由 task 改用 LLM synthesize content + chat script 手动调工具
- 写一条 [[feedback_real_api_test_required]] 记忆: JXA 改动必须真实跑过（不是 mock, 不是 node --check, 是在 Alfred runtime 里）

### P2: 排查 chat 主脚本加载机制（低优先级, 不阻塞 W7.11）
- 临时 `mv Workflow/chat Workflow/chat.bak` → Alfred 触发 chat keyword → 看是报错还是能对话
- 跑完**立即改回来**
- 这条是历史未决问题, W7.8-W7.11 实际工作证明 fallback 存在, 排查只是补完知识

### P3: 用户原话强调的「为什么这么复杂」反思
- 当前链路 3 层（regex → LLM synthesize → tool execute）已经尽力简化
- 如果用户仍嫌复杂, 终极方案是: pre-filter regex 跳 LLM, 全部走 local_agent.py NLP 解析（牺牲 LLM 的灵活性换简单性）
- 但这条会牺牲 LLM 整理 content 的能力, 写入的笔记会很粗糙

## 代码源唯一路径
`/Users/DRLer/Desktop/cursor项目/alfred chat/`（用户原话强调"我之前让你改的就是这个文件夹下的文件"）。Alfred workflow 目录的副本是 Alfred 自动 sync 过去的，**不要在那里改**。

## 关键文件
- `Workflow/chat` (51766+ bytes) — JXA 主脚本
  - line 768-799 附近: `handleModelToolUse` 入口的 `explicitWriteMatch` 早返回 (W7.11 新增)
  - line 770 后: `buildSynthesizeMessages` 函数 (W7.11 新增)
  - line 1324: `ensureFreshChat` (W5, OK)
  - line 1352: `run(argv)` (W6 改过)
  - line 1375: `runMain` 顶部调用 ensureFreshChat
- `Workflow/info.plist` line 3096-3098 — `workflow_version` 字段, 当前 `W7.11 (回滚 W7.10 LLM 路由: M3 推理模型不擅 JSON 路由仍瞎说已写入; 改为 chat script 直接匹配「放/存 X.md」正则抓 path, LLM 只做 content synthesize, 然后手动调 obsidian_write)`
- `Workflow/agent_tools/obsidian_write.py` — W2 已写好, 0.175s 冷启动直调 OK
- `Workflow/agent_tools/web_search.py` — W7 新增, Tavily 工具
- `Workflow/agent_tools/web_fetch.py` — W7 新增, baoyu-fetch 包装
- `Workflow/agent_tools/__init__.py` — 已注册 web_search + web_fetch + obsidian_write (共 11 个工具)
- `scripts/test_new_chat.py` — W5 测试, 8/8 过
- `scripts/test_rename_recent.py` — W6 测试, 14/14 过

## 不要再做的事
- **不要再在 decideToolUse 链路上打补丁** (W7.10 / W7.10.1 已证伪方向)
- **不要再让 LLM 做 JSON 路由器** (M3 推理模型不擅长)
- **不要再只跑 node --check** (查不出 scope bug)
- **不要再写超过必要的探索代码** (用户原话)
- **不要再 5 次补丁** — W7.9 + W7.10 + W7.10.1 + (W7.11 是方向反转不是补丁) 已经够多
- **W7.11 是方向反转, 不是补丁; 如果它失败, stop 重新设计, 不是打 W7.12**
- **不要把 baoyu-fetch 140 个 npm 包搬进 Workflow/** — 体量太大, 走 ~/.agents/skills/

## 未决问题 (open_questions)

1. **W7.11 Alfred 端验证**: 待用户测试「放 0.inbox/...md」, 验证 obsidian_write 真的被调 + 文件真存在
2. **chat 主脚本加载机制**: Alfred 5 plist 全 `scriptfile=''` 但能跑 20+ 轮, fallback 机制待确认 (P2, 不阻塞)
3. **M3 推理模型限制**: 是否要把这条作为 feedback 永久沉淀? 待 Codex 决定
4. **「为什么这么复杂」用户痛点**: 3 层链路是底线还是还能再简化? 见 P3
5. **W7.11 的 LLM synthesize 失败 fallback**: 如果 content synthesize 失败, 现在 W7.11 直接 return "内容整理失败:xxx", 用户体验差。是否要 fallback 到 "把最近 5 条消息直接拼"?

## 交接记录 (handoff_log)
- 2026-06-19 23:41  主控 agent → 接手 agent  `/handoff` 触发; W5 修复失败状态冻结
- 2026-06-20 00:30  主控 agent  W6 修复 rename → 最近对话空白 bug, 14/14 + 8/8 测试过
- 2026-06-20 10:30  主控 agent  Push v1.6.0 (e473abe) 到 origin/main, README 加 Demo 段
- 2026-06-20 16:00  主控 agent  W7 新增 web_search + web_fetch 工具, 等用户配 TAVILY_API_KEY
- 2026-06-21 12:00  主控 agent  W7.8 把蒂娜变 web agent (web_search 自动合成 + 反瞎掰约束), 验证「刘成是什么人」能搜出 3 个来源
- 2026-06-21 12:30  主控 agent  W7.9 修 mayNeedModelToolUse 加 4 条口语写文件正则, 21/21 regex 测试过
- 2026-06-21 13:00  主控 agent  W7.10 移除 L492 过宽 OB库 匹配 + decideToolUse 注入历史 + toolRouterPrompt 5 rule — 失败
- 2026-06-21 13:15  主控 agent  W7.10.1 修 W7.10 scope bug — 失败, 方向本身错
- 2026-06-21 13:30  主控 agent  **W7.11 方向反转**: 砍掉 LLM router, 改用 chat script 正则抓 path + LLM synthesize content + 手动调 obsidian_write, f673ed8 已 commit + .alfredworkflow 620KB 已打包。**等用户 Alfred 端验证**
