# Questions & Solutions

## 1. 用户发送消息后长时间空白等待，看不到 LLM 思考过程

**问题**：DeepSeek V4 Pro 返回的 `<think>...</think>` 思考内容被 `strip_think()` 完全丢弃，用户看不到任何进度反馈。

**解决方案**：构建独立的 "thinking" WebSocket 事件通道，将思考内容流式发送到前端渲染为可折叠区域。

### 数据流

```
DeepSeek API
  ├─ delta.content="<think>...</think>"   (inline think tags)
  └─ delta.reasoning_content="..."        (separate reasoning field)
      │
      ▼
openai_compat_provider.chat_stream()
  ├─ on_content_delta() → 内容流
  └─ on_thinking_delta() → 思考流
      │
      ▼
_LoopHook.on_stream() / on_thinking()
  ├─ 解析 <think> 边界 → 分离 thinking + content
  └─ 转发 provider 级 reasoning_content
      │
      ▼
WebSocket
  ├─ {"event":"thinking","chat_id":"...","text":"..."}
  └─ {"event":"delta","chat_id":"...","text":"..."}
      │
      ▼
WebUI
  ├─ thinking → 累积到 message.thinking，渲染为可折叠"思考过程"
  └─ delta → 累积到 message.content，正常流式渲染
```

### 修改的文件（17 个）

**Python 后端：**
- `nanobot/utils/helpers.py` — 新增 `extract_thinking_text()` 提取 `<think>` 内部文本
- `nanobot/providers/base.py` — `chat_stream()` 和 `chat_stream_with_retry()` 新增 `on_thinking_delta` 参数
- `nanobot/providers/openai_compat_provider.py` — 提取 `reasoning_content` 并通过 `on_thinking_delta` 转发
- `nanobot/providers/anthropic_provider.py` — 添加 `on_thinking_delta` 参数；后升级为迭代原始流事件以转发 `thinking_delta`（见问题 4）
- `nanobot/providers/openai_codex_provider.py` — 同上
- `nanobot/providers/azure_openai_provider.py` — 同上
- `nanobot/providers/bedrock_provider.py` — 同上
- `nanobot/providers/github_copilot_provider.py` — 同上，且转发到 `super().chat_stream()`
- `nanobot/agent/hook.py` — `AgentHook` 新增 `on_thinking()` 生命周期方法
- `nanobot/agent/runner.py` — `_thinking` 回调连接 provider → hook
- `nanobot/agent/loop.py` — `_LoopHook.on_stream()` 双轨拆分 thinking/content；`on_thinking` 线程传递全链路
- `nanobot/channels/manager.py` — `_thinking_delta` 路由到 `send_delta()`
- `nanobot/channels/websocket.py` — `send_delta()` 生成 `"thinking"` 事件

**前端：**
- `webui/src/lib/types.ts` — 新增 `thinking` 事件类型和 `UIMessage.thinking` 字段
- `webui/src/hooks/useNanobotStream.ts` — 处理 `thinking` 事件，累积到 `thinking` 字段
- `webui/src/components/MessageBubble.tsx` — `ThinkingGroup` 可折叠组件（流式展开，完成自动折叠）
- `webui/src/i18n/locales/{en,zh-CN}/common.json` — 添加 `"thinkingProcess"` / `"思考过程"` 翻译

---

## 2. WebUI 打不开或连接失败

**问题**：Vite 代理到错误端口，API 返回 `Not Found` 或 WebSocket 连接失败。

**原因**：gateway 有两个端口：
- `18790` — 仅 `/health` 端点（轻量 HTTP 服务）
- `8765` — API + WebSocket 主服务 + 生产 WebUI

Vite 默认代理到 `8765`，如果错误地设置 `NANOBOT_API_URL=http://127.0.0.1:18790`，会导致无法访问。

**解决方案**：不要设置 `NANOBOT_API_URL`，使用默认值：

```bash
cd webui && bun run dev   # 默认代理到 8765
```

---

## 3. "[Assistant reply unavailable due to model error.]" — 所有 LLM 调用失败

**问题**：添加 `on_thinking_delta` 参数后，使用 `anthropic` 等非 OpenAI-compatible provider 时报错：

```
Error calling LLM: AnthropicProvider.chat_stream() got an unexpected keyword argument 'on_thinking_delta'
```

**原因**：`chat_stream_with_retry()` 将 `on_thinking_delta` 通过 kwargs 传递给所有 provider 的 `chat_stream()`。但只更新了 `base.py` 和 `openai_compat_provider.py`，还有 5 个 provider 有自己的 `chat_stream()` 覆盖实现，未添加该参数。

**解决方案**：为所有覆盖 `chat_stream()` 的 provider 添加 `on_thinking_delta` 参数（默认 `None`，接受但不处理）：

- `nanobot/providers/anthropic_provider.py`
- `nanobot/providers/openai_codex_provider.py`
- `nanobot/providers/azure_openai_provider.py`
- `nanobot/providers/bedrock_provider.py`
- `nanobot/providers/github_copilot_provider.py`（同时需转发到 `super().chat_stream()`）

---

## 4. 思考内容未显示在 WebUI（anthropic provider 路径）

**问题**：使用 `anthropic` provider 连接 DeepSeek API (`api.deepseek.com/anthropic`) 时，思考内容完全不显示在 WebUI，"思考过程"折叠区域从未出现。

**原因**：DeepSeek 的 Anthropic-compatible 端点将思考内容作为独立的 `thinking` block 返回（Anthropic 原生扩展思考格式），而不是 OpenAI-style 的 `<think>...</think>` 标签。

Anthropic SDK 的 `MessageStream` 有两种事件：
- `content_block_delta` + `delta.type == "thinking_delta"` → 思考内容流式增量
- `content_block_delta` + `delta.type == "text_delta"` → 文本内容增量

但 `AnthropicProvider.chat_stream()` 只监听 `stream.text_stream`，它内部**只 yield `text_delta` 事件**，完全忽略了 `thinking_delta`。这意味着思考内容从 API 收到了，但在 provider 层被丢弃。

**解决方案**：修改 `chat_stream()` 迭代原始流事件（`stream.__aiter__()`）而非仅 `text_stream`，将 `thinking_delta` 和 `text_delta` 分别路由到 `on_thinking_delta` 和 `on_content_delta`：

```python
async with self._client.messages.stream(**kwargs) as stream:
    if on_content_delta or on_thinking_delta:
        stream_iter = stream.__aiter__()
        while True:
            event = await asyncio.wait_for(stream_iter.__anext__(), timeout=...)
            if (
                on_thinking_delta
                and event.type == "content_block_delta"
                and getattr(event.delta, "type", None) == "thinking_delta"
            ):
                await on_thinking_delta(event.delta.thinking or "")
            elif (
                on_content_delta
                and event.type == "content_block_delta"
                and getattr(event.delta, "type", None) == "text_delta"
            ):
                await on_content_delta(event.delta.text)
```

同时更新 `_parse_response()` 从 `thinking_blocks` 填充 `reasoning_content`，确保非流式路径也能保留思考内容。

### 修改的文件

- `nanobot/providers/anthropic_provider.py` — `chat_stream()` 迭代原始流而非仅 `text_stream`；`_parse_response()` 填充 `reasoning_content`

### 验证

用 agent-browser 测试确认：
1. 思考内容实时流式显示为可展开的"思考过程"区域
2. 思考完成后自动折叠（`expanded=false`）
3. 最终回复正常渲染

---

## 5. 端口冲突导致启动失败

**问题**：重启 gateway 或 Vite 时报错 `[Errno 10048]` 端口已被占用。

**原因**：旧进程未完全清理，端口 `8765`、`18790`、`5173` 被残留进程占用。

**解决方案**：彻底清理端口后重启：

```bash
# 强制终止所有残留进程
for port in 8765 18790 5173; do
  for pid in $(netstat -ano | grep ":$port " | awk '{print $NF}' | sort -u); do
    taskkill /F /PID $pid
  done
done

# 启动 gateway（注意使用 venv python）
.venv/Scripts/python.exe -m nanobot gateway &

# 启动前端（无需 NANOBOT_API_URL）
cd webui && bun run dev
```
