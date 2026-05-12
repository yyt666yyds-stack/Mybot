## 1. Config schema

- [x] 1.1 Add `VisionToolConfig` to `nanobot/config/schema.py` with fields: enabled, auto_describe, model, provider, max_images_per_turn, max_description_chars
- [x] 1.2 Add `vision` field to `ToolsConfig` in `nanobot/config/schema.py`

## 2. VisionTool class

- [x] 2.1 Create `nanobot/agent/tools/vision.py` with `VisionTool` class extending `Tool`
- [x] 2.2 Implement `name` ("describe_image"), `description`, and `parameters` (path or url)
- [x] 2.3 Implement direct HTTP call to DashScope API using `httpx` for vision requests
- [x] 2.4 Implement `execute()`: read local image as base64, send to vision model, return text description
- [x] 2.5 Handle errors: file not found, unsupported format, API key missing, API errors

## 3. Auto pre-call hook

- [x] 3.1 Add auto-describe logic in `AgentLoop._state_build()` (after `_build_initial_messages()`)
- [x] 3.2 Detect images in `ctx.msg.media`, filter to actual image files
- [x] 3.3 Concurrently call VisionTool for each image (respecting `max_images_per_turn`)
- [x] 3.4 Insert descriptions as separate system messages into `ctx.initial_messages`
- [x] 3.5 Fallback to `[image omitted]` placeholder on vision API failure, with user warning

## 4. Integration

- [x] 4.1 Register VisionTool in tool registry (conditional on `vision.enabled`)
- [x] 4.2 Pass VisionTool to AgentLoop for auto pre-call access

## 5. Tests

- [x] 5.1 Write unit tests for VisionTool parameter validation and error handling
- [x] 5.2 Write integration tests for auto-describe flow (mock DashScope API)
