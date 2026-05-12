## Why

nanobot's main LLM (DeepSeek V4 Pro) has no vision capability, so images sent by users are replaced with `[image omitted]` placeholder text before reaching the model — the assistant is effectively blind to user images. Adding a vision tool that auto-describes images before the LLM turn solves this without requiring the main model to support vision natively.

## What Changes

- New `vision_tool` registered as a standard Tool: calls `qwen3.5-omni-plus-2026-03-15` via DashScope API to describe images, available for both automatic pre-call and on-demand LLM invocation
- Auto pre-call hook in `AgentLoop._state_build`: detects images in user messages, calls vision_tool for each image, injects descriptions as system messages before the LLM sees the message
- New `VisionToolConfig` in config schema: controls auto-describe toggle, model selection, per-turn image limit, description max length
- Failure fallback: if vision API call fails, system falls back to existing `[image omitted]` placeholder and warns the user

## Capabilities

### New Capabilities

- `vision-tool`: A tool that receives image file paths or URLs and returns text descriptions by calling a vision-capable model (qwen3.5-omni-plus). Supports both automatic pre-call (images auto-described before reaching main LLM) and on-demand invocation (main LLM can call `describe_image` tool directly).

### Modified Capabilities

<!-- No existing capabilities modified -->

## Impact

- New file: `nanobot/agent/tools/vision.py` (VisionTool class)
- Modified: `nanobot/config/schema.py` (VisionToolConfig + ToolsConfig field)
- Modified: `nanobot/agent/loop.py` (auto pre-call logic in `_state_build`)
- Modified: `nanobot/agent/tools/__init__.py` (export VisionTool, if needed)
- New dependency: DashScope API (`DASHSCOPE_API_KEY` env var, already supported in provider registry)
