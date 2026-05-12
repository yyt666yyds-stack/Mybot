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

### 修改的文件（12 个）

**Python 后端：**
- `nanobot/utils/helpers.py` — 新增 `extract_thinking_text()` 提取 `<think>` 内部文本
- `nanobot/providers/base.py` — `chat_stream()` 新增 `on_thinking_delta` 参数
- `nanobot/providers/openai_compat_provider.py` — 提取 `reasoning_content` 并转发
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

## 2. WebUI 报 "Error calling LLM: Connection error"

**问题**：gateway 重启后，WebUI 连接模型失败。

**原因**：Vite 开发服务器默认代理到 `http://127.0.0.1:8765`（vite.config.ts 默认值），但 gateway 实际运行在端口 `18790`。

**解决方案**：启动 Vite 时设置环境变量：

```bash
NANOBOT_API_URL=http://127.0.0.1:18790 bun run dev
```

---

## 3. 端口冲突导致重启失败

**问题**：重启 gateway 或 Vite 时报错 `[Errno 10048]` 端口已被占用。

**原因**：旧进程未完全清理，端口 `8765`、`18790`、`5173` 被残留进程占用。

**解决方案**：彻底清理后重启：

```bash
# 强制终止所有残留进程
for port in 8765 18790 5173; do
  for pid in $(netstat -ano | grep ":$port " | awk '{print $NF}' | sort -u); do
    taskkill /F /PID $pid
  done
done

# 然后重新启动
python -m nanobot gateway &
NANOBOT_API_URL=http://127.0.0.1:18790 bun run dev
```
