# Alfred Chat

Alfred 5 对话框聊天 Workflow，支持 **DeepSeek** 与 **MiniMax**，架构参考 [alfredapp/openai-workflow](https://github.com/alfredapp/openai-workflow)。

## 安装

1. 下载 [`Alfred Chat.alfredworkflow`](Alfred%20Chat.alfredworkflow) 并双击安装。
2. 打开 Alfred Preferences → Workflows → **Alfred Chat** → **Configure**。
3. 选择 **Provider**（MiniMax 或 DeepSeek），填入对应 API Key。

## 切换模型

在 **Alfred Preferences → Workflows → Alfred Chat → Configure** 里操作：

1. **换服务商**：改 **Provider**
   - `MiniMax` → 走 MiniMax API
   - `DeepSeek` → 走 DeepSeek API
2. **换具体模型**：改对应下拉框
   - MiniMax：**MiniMax Model**（默认 `MiniMax-M3`）
   - DeepSeek：**DeepSeek Model**（如 `deepseek-v4-flash`、`deepseek-v4-pro`）
3. **MiniMax 国内/国际**：改 **MiniMax Region**（国内 Key 通常选 `China`）

改完保存即可，下次 `chat` 提问立即生效。建议切换后按 **⌘↩** 开新对话，避免旧上下文混淆。

## 配置

| 选项 | 说明 |
|------|------|
| **Chat Keyword** | 触发关键词，默认 `chat` |
| **Provider** | `MiniMax` / `DeepSeek` |
| **DeepSeek API Key** | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| **DeepSeek Model** | 默认 `deepseek-v4-flash` |
| **MiniMax API Key** | [platform.minimax.io](https://platform.minimax.io/user-center/basic-information/interface-key) |
| **MiniMax Region** | 默认国内 `api.minimaxi.com`；国际 Key 改选 International |
| **MiniMax Model** | 默认 `MiniMax-M3` |
| **Keep History** | 新对话时归档当前会话 |
| **Context** | 发送给 API 的最近消息条数 |
| **Timeout** | 流式连接超时（秒） |
| **Your Name** | 对话里你的称呼，默认 `You` |
| **Assistant Name** | 对话里 AI 的称呼，默认 `Assistant` |
| **Obsidian Vault Path** | OB 库根目录，供 `/export` 使用 |
| **Obsidian Export Folder** | 导出子文件夹，默认 `0.inbox` |
| **System Prompt** | 系统提示词 |

### 对话排版说明

- **你和 AI 的称呼**使用一级标题（`#`），最醒目。
- **AI 回复里的标题**（如 `#`、`##`）会自动降 3 级显示，避免和称呼抢字号。
- **字体颜色**：Alfred Text View 只支持标准 Markdown，**不支持**自定义颜色（HTML 标签会原样显示）。可在 Text View 右上角 `···` 调整全局字号。

### 高级：Environment Variables

在 Workflow 右上角 `[x]` → **Workflow Environment Variables** 可覆盖端点：

- `deepseek_api_endpoint` — 默认 `https://api.deepseek.com/chat/completions`
- `minimax_api_endpoint` — 默认由 Region 决定

## 使用

### 触发方式

- 关键词：`chat 你的问题`
- 快捷键：**⌘3** — 打开最近一次对话（当前会话优先，否则加载最新归档）
- Universal Action：**Ask AI**
- Fallback Search：**Ask AI '{query}'**

### 对话框快捷键

| 快捷键 | 功能 |
|--------|------|
| ↩ | 发送新问题 |
| ⌘↩ | 新对话（可选归档当前会话） |
| ⌥↩ | 复制最后回答 |
| ⌃↩ | 复制全文 |
| ⇧↩ | 停止生成 |

### 重命名当前会话

在**对话框**里输入（不会发给 AI）：

```text
/rename 项目讨论
```

- 顶部会显示 `⌖ 项目讨论`
- 历史列表里也会用这个名称（优先于第一条问题）
- 只输入 `/rename` 会提示用法

### 回退对话片段（/rewind）

类似 Claude Code 的 `/rewind`，在对话框输入（不会发给 AI）：

| 命令 | 作用 |
|------|------|
| `/rewind` 或 `/rewind list` | 列出当前会话各轮编号 |
| `/rewind 1` | 删除最近 1 轮（一问一答） |
| `/rewind 3` | 删除最近 3 轮 |
| `/rewind to 2` | 只保留前 2 轮，后面全部删掉 |

适合答错方向时回退上下文，再继续问。

### 导出到 Obsidian（/export）

在对话框输入（不会发给 AI）：

| 命令 | 作用 |
|------|------|
| `/export` | 导出当前整段对话到 OB 库 |
| `/export 笔记标题` | 指定笔记标题（文件名）后导出 |

也支持自然语言（不会发给 AI），例如：

- `导出当前对话`
- `导出当前对话，命名为：哮喘与运动`
- `导出对话到 obsidian，标题：项目讨论`
- `export this conversation, named: Weekly review`

**注意**：需包含「导出 + 对话/聊天/会话」或 `/export`，避免和普通聊天里的「导出」一词混淆。

- 默认保存到 **Obsidian Vault Path** / **Obsidian Export Folder**（默认 `0.inbox/`）
- 文件名即笔记标题，如 `螨虫导致的哮喘用药.md`（同名时自动加 `-2`、`-3`）
- 导出成功后对话框回复 **已存入 done**

首次使用请在 Configure 里确认 **Obsidian Vault Path** 指向你的库根目录。

### 本机文件控制（自然语言）

支持在对话框直接用自然语言执行本机文件操作（不会发给 AI）。这部分由 `Workflow/local_agent.py` 处理，Alfred 负责展示对话，本地 Agent 负责解析、权限检查和真实文件操作：

- `创建文件 /Users/DRLer/tmp/note.md 内容：今天完成了复盘`
- `写入123.txt`
- `桌面写入123.txt`
- `在桌面新建123.txt`
- `在桌面新建123.txt 内容：hello`
- `追加 /Users/DRLer/tmp/note.md 内容：\n- 明天继续`
- `替换 /Users/DRLer/tmp/note.md 中 复盘 为 周复盘`
- `删除 /Users/DRLer/tmp/note.md`
- `列出桌面所有txt文件`
- `把桌面所有txt移动到 Desktop/txt归档`
- `读取123.txt`
- `搜索OB哮喘`
- `读下ob库今日日记`
- `今天日记 内容：今天完成 Alfred Chat 升级`
- `新增任务：整理桌面`
- `早上9点30提醒我打卡`（写入 macOS **提醒事项**）
- `明天下午3点提醒开会`
- `提醒我18:30取快递`
- `列出任务`
- `完成任务 1`
- `记住 资料库 是 /Users/DRLer/Obsidian_250614/3.wiki资料`
- `你记住以下内容：OB 指 Obsidian；CC 指 Claude Code`
- `列出记忆`
- `运行命令：ls Desktop`
- `撤销上一步`

规则：

- 仅允许操作 `/Users/DRLer` 目录内文件
- 普通写入/追加/替换：直接执行
- 危险操作（删除文件、覆盖已存在文件）：会先提示，需输入 **确认执行**
- 输入 `取消` 可取消待执行危险操作
- 裸文件名默认指向桌面，例如 `写入123.txt` / `删除123.txt`
- 批量移动会先展示计划，确认后执行
- 每次写入/追加/替换/删除/批量移动会写操作日志，支持 `撤销上一步`
- Shell 仅允许白名单命令：`ls`、`pwd`、`mkdir`
- **提醒事项**：支持自然语言时间，写入系统「提醒事项」App（首次使用需授权）
- `memory.json` 会自动注入后续 AI 请求，模型会带着长期记忆回答

### 模型驱动 Tool Use

普通请求会先由模型判断是否需要本地工具。模型只输出结构化 tool call，`Workflow/local_agent.py` 负责真实执行。例如：

- `帮我总结今日日记` → 模型选择 `obsidian_daily_read` → 读取本地 OB 日记 → 再由模型总结
- `帮我看看桌面123.txt写了什么` → 模型选择 `read_file`
- `把这个偏好记住：OB 就是 Obsidian` → 模型选择 `memory_append`

### 聊天历史

输入 **`rename`** 直接浏览最近对话（可在 Configure 里改 **History Keyword**）。

- 列表顶部 **Current** = 当前进行中的会话
- 其余为已归档历史（⌘↩ 新对话时自动保存）
- 选中后 **↩** 加载该会话继续聊
- **⌘↩** 删除选中项（**Current** = 清空当前会话；已归档 = 移入废纸篓）

仍可用 `chat` + **⌥↩** 打开同一列表。

## API 对照

| Provider | Endpoint | 默认模型 |
|----------|----------|----------|
| DeepSeek | `https://api.deepseek.com/chat/completions` | `deepseek-v4-flash` |
| MiniMax 国际 | `https://api.minimax.io/v1/chat/completions` | `MiniMax-M3` |
| MiniMax 国内 | `https://api.minimaxi.com/v1/chat/completions` | `MiniMax-M3` |

文档：[DeepSeek API](https://api-docs.deepseek.com/) · [MiniMax OpenAI API](https://platform.minimax.io/docs/api-reference/text-openai-api)

## 开发

```bash
# 从参考仓库改造后重新打包
cd Workflow && zip -r "../Alfred Chat.alfredworkflow" .
```

源码结构：

- `Workflow/chat` — 主 JXA 脚本（流式 API 调用）
- `Workflow/local_agent.py` — 本地文件 Agent（工具解析、权限、执行）
- `Workflow/info.plist` — Workflow 对象与配置
- `scripts/transform_plist.py` — 从 openai-workflow 迁移用的 plist 转换脚本

## 致谢

基于 [alfredapp/openai-workflow](https://github.com/alfredapp/openai-workflow) 的 Text View + curl 流式架构改造。
