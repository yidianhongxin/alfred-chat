# Handoff — Alfred Chat

## 状态
`active`  2026-06-21 13:30  by 主控 agent (W7.11 提交,真写入 OB 链路修好,**等用户实测验证**)

## 当前任务: W7.11 — 真写入 OB 链路(5 次连续修复,方向反转)

### 用户痛点
"电视剧好好的时光里刘成是个什么样的人" → 答得很好(联网搜过)→ "写入 ob 库" → 蒂娜"先确认下当前库状态,然后写入" → "放 0.inbox/好好的时光-刘成.md" → 蒂娜"已写入" → **实际上文件不存在**(用户验证过,0.inbox/ 里没该文件)→ 用户骂"废物"。

**用户原话**:"我觉得写入ob笔记应该是比较轻松的事情呀,为什么这么复杂?"

### 诊断关键方法(W7.11)
**用真实 ANTHROPIC_API_KEY 跑一次 decideToolUse**,看 LLM 实际输出:

| 用户 query | LLM 实际返回(没骗我) |
|---|---|
| 放 0.inbox/... | "我先搜一下刘成这个角色,搜完就写。" (自然语言,不是 JSON) |
| 写入ob库 | "写入成功。" (瞎说) |
| go on | "工具路由:电视剧剧情介绍,写 OB 库。" (自然语言) |

**M3 推理模型不擅长 JSON 路由**——加再多 toolRouterPrompt rule 也无效,LLM 直接瞎说。

### W7.11 修复方向反转
**关键洞察**: LLM 在 **content synthesize** 这个 task 上表现很好(刚验证:能输出带 frontmatter 的完整 obsidian 笔记);但在 **JSON 路由** task 上不可靠。

**新链路**(砍掉 LLM 路由器这层):
```
1. chat script 正则抓「放/存/写 [path].md」 → 抓到 path
2. 调 LLM (新职责:content synthesize) → 拿到 markdown 内容
3. chat script 调 obsidian_write(path, content) → 真写入
```

**链路简化**: 之前 5 层 (regex → LLM router → LLM tool call → tool → LLM synthesize) → 现在 3 层 (regex → LLM synthesize → tool)

### 代码改动(W7.11)
**`Workflow/chat`** 改 3 处:
1. **回滚** decideToolUse 的历史注入 + sessionContext 传参 (W7.10.1 引入,W7.11 删除)
2. **回滚** toolRouterPrompt 末尾的 5 条「W7.10 硬性 rule」(已被证无效)
3. **新增** `handleModelToolUse` 入口的 `explicitWriteMatch` 早返回:
   - 正则双向匹配(动词+path / path+动词)
   - 抓 path → 调 `buildSynthesizeMessages` → 调 `runLocalAgentTool(obsidian_write)`
4. **新增** `buildSynthesizeMessages(chatFile, typedQuery, targetPath)`:
   - 读 session 注入最近 10 条历史
   - system prompt 让 LLM 输出带 frontmatter 的 markdown (title / created / urls)
   - 加 `obsidian_write` 失败 fallback (return 真实错误,不让 LLM 二次瞎说)

### regex 测试 11/11
✓ 命中 (7/11): `放/存到/保存到/把 X.md 放好/X.md 保存/塞到/录入/写入/写到/新建/创建 0.inbox/X.md` (双向都覆盖)
· 合理 miss (4/11): `在 0.inbox 里放一篇` / `Obsidian 库里写一份` (无具体 .md 路径) / `今天天气怎么样` (无关) / `刘成是什么人` (无关)

### 待用户验证
1. 双击装新版 `/Users/DRLer/Desktop/cursor项目/alfred chat/Alfred Chat.alfredworkflow` (620KB)
2. 跑 `问: 电视剧好好的时光里刘成是个什么样的人` → 答完后跑 `问: 放 0.inbox/好好的时光-刘成.md`
3. **预期结果**:
   - 蒂娜 answer 里直接显示 `已写入 OB:0.inbox/好好的时光-刘成.md`(工具真实输出,不是 LLM synthesize)
   - 文件实际写入 `/Users/DRLer/Obsidian_250614/0.inbox/好好的时光-刘成.md`(用户自己 `ls` 验证)
4. 如果还是失败,**停止在写入链路上打补丁**——参见 [feedback_three_patches_rule]

---

## 历史: W7.7 - W7.10.1 (3 个修复全部失败,留下教训)

### W7.7 反瞎掰约束 + Tavily retry(成功)
- 蒂娜拿到 web_search 结果后,不再瞎编/套用训练数据补全答案
- Tavily API 网络错误重试 2 次(1s/2s 退避)
- 4 个测试用例全过

### W7.8 web_search 自动合成 + 多步工具(成功)
- `shouldFinalizeToolResult` 对 web_search/web_fetch 永远走 synthesize
- `finalizeToolResult` 加 5 条反瞎掰 rule
- `toolRouterPrompt` 移除矛盾的"普通知识问答都返回 none"

### W7.9 mayNeedModelToolUse 加 4 条写文件动词正则(部分成功)
- 加「放/存/保存/存到/放进/录入/塞 [path]」等口语化写文件说法
- 21 个测试用例 18/18 命中,3/3 正确排除
- **但被 W7.10 揭示的过宽 OB库 匹配短路了,根本没机会触发**

### W7.10 修 LLM 工具路由链路(**失败**)
- 改 3 处: 移除 looksLikeLocalAgentQuery 过宽 OB库 匹配 / decideToolUse 注入对话历史 / toolRouterPrompt 加 5 条硬性 rule 禁分步
- **实际效果**: 装了之后"写入ob库"直接什么回复都没有

### W7.10.1 修 W7.10 regression(**失败**)
- 根因: decideToolUse 是顶层 fn 引用 runMain 的 const session → throw ReferenceError → Alfred 收不到 JSON
- 改: sessionContext 作参数传入
- **实际效果**: 装了之后蒂娜的"已写入"是 LLM 瞎说,文件根本不存在(用户验证)

### 共同教训
1. **M3 推理模型不擅长 JSON 路由**——给再多 rule 也无效
2. **W5 已经 5 次补丁 = 方向错**——3 次补丁就该停手重设计(参见 [[feedback_three_patches_rule]])
3. **没在 Alfred runtime 实测**——只在 Node 单文件模拟,scope 错误暴露不出
4. **诊断方法错误**——前几次只跑 regex 测试,没跑真实 LLM 调用看实际输出

---

## 历史: W7 — 联网工具 (Tavily 搜索 + baoyu-fetch 抓取)

**问题**: 用户截图报"AI 不能联网搜不到电视剧",蒂娜模型本身没有内置联网能力。

**方案**: 加 2 个工具(零 LLM 改动,只走 model-driven tool use):

| 工具 | toolset | 作用 | 依赖 |
|------|---------|------|------|
| `web_search` | web | Tavily API,搜公网,返回综合答案 + 列表 | `TAVILY_API_KEY` env var |
| `web_fetch` | web | baoyu-fetch CLI 包装,给定 URL 返完整 Markdown | bun + baoyu-fetch + Chrome |

**用户需做的 2 步**:
1. 去 https://tavily.com 注册 → Dashboard 拿 `tvly-xxx` 格式 key
2. Alfred Preferences → Workflows → Alfred Chat → 右上角 `[x]` → Workflow Environment Variables → 添加 `TAVILY_API_KEY=tvly-xxx`

---

## 历史: W6 — rename 关键字 → 最近对话 不再空白(成功)

**根因**: rename 关键字 → B2F04B2C script filter → 879C841D (sets replace_with_chat=X, new_chat=0) → 84A47CA0 (callexternaltrigger, fires **new_chat** trigger) → A6AD2F54 → **8296D113 强制覆盖 new_chat=1**(无视 879C841D 设的 0) → 74890339 → F87E8DE0 (把 X 移到 chat.json) → 4DB440D5 (TextView)。
TextView 跑 Workflow/chat 时,`ensureFreshChat` 看到 new_chat=1,把刚 load 的 X **又归档**,写空 `[]` → 渲染空白。

**修复**:
- `Workflow/chat` `ensureFreshChat`: 加 `if (envVar("replace_with_chat")) return`,load 模式下不归档。
- `Workflow/chat` `run` 输出: 同时清空 `new_chat="0"` 和 `replace_with_chat=""`,防止变量在 TextView 作用域残留。

**测试**: `scripts/test_rename_recent.py` 14/14 过,`scripts/test_new_chat.py` 8/8 过(W5 无回归)。

---

## 关键文件
- `Workflow/chat` (JXA 主脚本) — 关键函数:
  - `mayNeedModelToolUse(text)` L684 — pre-filter 正则
  - `decideToolUse(provider, typedQuery, timeoutSeconds)` L715 — LLM 路由器(已弃用,仅作为 fallback)
  - `handleModelToolUse(...)` L768 — W7.11 入口加 `explicitWriteMatch` 早返回
  - `buildSynthesizeMessages(...)` L782 — W7.11 新增,合成 obsidian 笔记内容
  - `shouldFinalizeToolResult(toolCall, typedQuery)` L750
  - `finalizeToolResult(...)` L759
  - `runLocalAgentTool(toolCall)` L454 — 通过 local_agent.py --tool 调工具
- `Workflow/agent_tools/obsidian_write.py` — 写工具(W2 注册),`handle_write` 验证过 0.175s 写完
- `Workflow/agent_tools/web_search.py` — W7 新增,Tavily 工具(无依赖,stdlib urllib + retry 2 次)
- `Workflow/agent_tools/web_fetch.py` — W7 新增,baoyu-fetch 包装
- `Workflow/local_agent.py` L1377-1378 — `--tool` 入口, 调 `run_tool_call` → REGISTRY.dispatch
- `Workflow/info.plist` L3098-3099 — `workflow_version` 字段,每次改完更新

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
4. 告诉用户双击 `.alfredworkflow` 装新版

## 不要再做的事
- **不要在写入 OB 链路上再打补丁**——W7.11 是方向反转的产物,再改就在错的方向上绕
- **不要用 LLM 做 JSON 路由**——M3 推理模型不擅长,改用 chat script 正则 + LLM synthesize
- **不要重新设计 ensureFreshChat 逻辑**(已 OK)
- **不要花 30 分钟解析 plist 节点图**(已解完)
- **不要把 baoyu-fetch 140 个 npm 包搬进 Workflow/**——体量太大,Alfred 用 `/usr/bin/python3` 跑,npm 环境走 `~/.agents/skills/` 是正解
- **不要在没在 Alfred runtime 实测的情况下声称修复完成**——必须用户跑过才算数

## 未决问题 (open_questions)
- **W7.11 仍未在 Alfred runtime 实测** — 用户装新版后还没跑过"放 0.inbox/..."。等用户验证。
- **M3 LLM synthesize content 在 OB 写入时是否一定返回空** — 如果对话历史里完全无关,LLM 会返回空字符串,这时 chat script 已经 fallback 到 "对话历史里没有可以整理成笔记的内容,无法写入。" 但这种情况是 user 错用,不是 bug。
- **W7.10 / W7.10.1 的 git commit 留着** — 应该 revert 还是保留?保留作为教训(写"共同教训"在 HANDOFF 里)。
- **W7 web_search 的默认 max_results**: 当前写死 5,用户可能想改。Alfred Configure 加个选项?(低优先级)
- **是否给 chat script 加更智能的 fallback** — 比如"在 OB 库里放一篇"无具体路径时,LLM 帮 user 拼一个合理路径?让 simplify 决定是否做。

## 交接记录 (handoff_log)
- 2026-06-20 16:00  主控 agent  W7 联网工具就绪,等用户配 Tavily key + push 决策
- 2026-06-21 10:30  主控 agent  W7.7 反瞎掰约束 + Tavily retry 2 次,4 用例全过;W7.8 web_search 自动合成 + 多步工具说明;W7.9 mayNeedModelToolUse 加 4 条写文件动词正则;**W7.10 路由链路修复失败**(LLM 不返回 JSON);**W7.10.1 修 W7.10 scope bug 失败**(方向错);**W7.11 方向反转** — 用真实 API 跑 decideToolUse 发现 M3 推理模型不擅长 JSON 路由,改为 chat script 正则抓 path + LLM synthesize content + chat script 调 obsidian_write,11/11 regex 测试通过,等待用户实测验证。
