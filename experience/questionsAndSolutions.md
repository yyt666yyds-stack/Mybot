# Vision Tool 实践教训

## 背景

为 nanobot 添加 vision_tool，自动调用 qwen3.5-omni-plus 描述用户图片，让不具备视觉能力的 DeepSeek V4 Pro 能"看到"图片。

## 问题 1：描述注入方式错误

### 初始设计

图片描述以独立 system 消息注入：

```
[system] nanobot 系统提示词...
[system] [图片 1/1 描述]: 景元，银灰长发，黑金铠甲...
[user]   [image omitted] 图中的人是谁
```

### 现象

- DeepSeek 看到 user 消息里的 `[image omitted]` 占位符后，**仍然调用 `describe_image` 工具**
- 相当于同一张图片被 vision API 调了两次（auto-describe 一次 + DeepSeek 手动调一次）
- 总延迟：13s(首次) + 7s(思考) + 28s(二次) = **49秒**
- 有时 DeepSeek 完全忽略 system 消息中的描述，直接回复"无法查看图片"

### 根因

DeepSeek V4 Pro 不信任孤立的 system 描述消息。它的推理链路是：

> 用户消息里有个我看不到的图片（[image omitted]），虽然 system 消息里有段描述，但那不一定是用户发的。我应该调用 describe_image 工具亲自看看。

### 修复

直接将 user 消息中的 `image_url` 块替换为文字描述块：

```
[user] [图片 1/1 描述]: 景元，银灰长发，黑金铠甲...  图中的人是谁
```

DeepSeek 在用户消息上下文里直接看到描述，不会再调用工具。

## 问题 2：图片检测路径错误

### 初始设计

`_auto_describe_images()` 只检查 `ctx.msg.media`（本地文件路径列表）。

### 现象

某些场景下 auto-describe 完全不触发。

### 原因

图片可能以 `image_url` 块形式直接嵌入在消息 content 中（base64 data URI），而不是作为 `media` 列表。仅检查 `media` 字段会漏掉这些图片。

### 现状

目前仍只检查 `media`，因为 websocket channel 会将图片保存到磁盘后放入 `media`。但如果未来有其他 channel 直接嵌入 image_url 块，需要同时检查 content。

## 问题 3：速度

### 现象

qwen3.5-omni-plus 单次调用耗时 13-19 秒。

### 分析

- qwen3.5-omni-plus 是大模型，推理本身需要时间
- DashScope API 网络延迟
- 提示词要求中文详细描述，生成的 token 较多（当前 max_tokens=512）

### 可能的优化方向

- 换更小的视觉模型
- 减少 max_tokens
- 流式返回（streaming），让用户看到"正在识别图片..."的进度
- 并发多图时已经用 `asyncio.gather`，无明显优化空间

## 问题 4：config.json 缺少 vision 字段

### 现象

如果用户 config.json 中没有 `tools.vision` 配置，Pydantic 会使用 `VisionToolConfig` 的默认值（`enabled=True, auto_describe=True`），行为正常。

但如果 `providers.dashscope` 未配置 API key，vision tool 会返回错误并降级到占位符。

### 教训

关键配置项需要显式文档说明依赖关系（vision tool 依赖 dashscope provider 的 API key）。

## 总结

| 教训 | 影响 | 修复 |
|------|------|------|
| 描述应替换 image_url 块，而非插入 system 消息 | DeepSeek 重复调用工具，延迟翻倍 | 重构注入方式 |
| 工具注册为 Tool 后 LLM 也会调用，需避免与 auto 路径冲突 | 同一图片被描述两次 | 替换 user content 后 LLM 不再看到占位符 |
| 视觉模型调用是瓶颈（13-19s） | 用户体验差 | 暂无明显优化，后续考虑更快模型或流式 |
| 日志对排查关键 | 没有日志时完全不知道 auto-describe 是否触发 | 保留 loguru 关键日志 |
