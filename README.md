# Alfred Chat

Alfred 5 对话框聊天 Workflow，支持 **DeepSeek** 与 **MiniMax**，架构参考 [alfredapp/openai-workflow](https://github.com/alfredapp/openai-workflow)。

## 安装

1. 下载 [`Alfred Chat.alfredworkflow`](Alfred%20Chat.alfredworkflow) 并双击安装。
2. 打开 Alfred Preferences → Workflows → **Alfred Chat** → **Configure**。
3. 填入两个 API Key（默认使用 MiniMax）。

## 切换模型

在 **Alfred Preferences → Workflows → Alfred Chat → Configure** 里操作：

1. **换服务商**：改 **Provider**
   - `MiniMax` → 走 MiniMax API
   - `DeepSeek` → 走 DeepSeek API
2. **换具体模型**：改对应下拉框
   - MiniMax：**MiniMax Model**（如 `MiniMax-M2.7-highspeed`、`MiniMax-M3`）
   - DeepSeek：**DeepSeek Model**（如 `deepseek-v4-flash`、`deepseek-v4-pro`）
3. **MiniMax 国内/国际**：改 **MiniMax Region**（国内 Key 通常选 `China`）

改完保存即可，下次 `chat` 提问立即生效。建议切换后按 **⌘↩** 开新对话，避免旧上下文混淆。

## 配置

| 选项 | 说明 |
|------|------|
| **Chat Keyword** | 触发关键词，默认 `chat` |
| **Provider** | 默认 `MiniMax`；可改选 `DeepSeek` |
| **DeepSeek API Key** | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| **DeepSeek Model** | 默认 `deepseek-v4-flash` |
| **MiniMax API Key** | [platform.minimax.io](https://platform.minimax.io/user-center/basic-information/interface-key) |
| **MiniMax Region** | 默认国内 `api.minimaxi.com`；国际 Key 改选 International |
| **MiniMax Model** | 默认 `MiniMax-M2.7-highspeed` |
| **Keep History** | 新对话时归档当前会话 |
| **Context** | 发送给 API 的最近消息条数 |
| **Timeout** | 流式连接超时（秒） |
| **System Prompt** | 系统提示词 |

### 高级：Environment Variables

在 Workflow 右上角 `[x]` → **Workflow Environment Variables** 可覆盖端点：

- `deepseek_api_endpoint` — 默认 `https://api.deepseek.com/chat/completions`
- `minimax_api_endpoint` — 默认由 Region 决定

## 使用

### 触发方式

- 关键词：`chat 你的问题`
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
| MiniMax 国际 | `https://api.minimax.io/v1/chat/completions` | `MiniMax-M2.7-highspeed` |
| MiniMax 国内 | `https://api.minimaxi.com/v1/chat/completions` | 同上 |

文档：[DeepSeek API](https://api-docs.deepseek.com/) · [MiniMax OpenAI API](https://platform.minimax.io/docs/api-reference/text-openai-api)

## 开发

```bash
# 从参考仓库改造后重新打包
cd Workflow && zip -r "../Alfred Chat.alfredworkflow" .
```

源码结构：

- `Workflow/chat` — 主 JXA 脚本（流式 API 调用）
- `Workflow/info.plist` — Workflow 对象与配置
- `scripts/transform_plist.py` — 从 openai-workflow 迁移用的 plist 转换脚本

## 致谢

基于 [alfredapp/openai-workflow](https://github.com/alfredapp/openai-workflow) 的 Text View + curl 流式架构改造。
