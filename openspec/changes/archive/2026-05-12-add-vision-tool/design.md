## Context

nanobot currently strips image content before it reaches the main LLM (`LLMProvider._strip_image_content()` in `providers/base.py:442`), replacing it with `[image omitted]` placeholder text. The main model (DeepSeek V4 Pro) has no vision capability. Qwen3.5-Omni-Plus supports vision and is accessible via DashScope's OpenAI-compatible API, which is already registered as a provider (`dashscope` in `providers/registry.py`).

The project's design constraints (`.agent/design.md`) emphasize: extend at the edges (channels/tools), keep core small, prefer simple code over framework layers.

## Goals / Non-Goals

**Goals:**
- Provide a `describe_image` tool that calls qwen3.5-omni-plus to return text descriptions of images
- Auto-describe user-uploaded images before the main LLM sees them (configurable)
- Gracefully fall back to `[image omitted]` if the vision call fails

**Non-Goals:**
- Support for multiple vision models (DashScope/qwen3.5-omni-plus only, for now)
- Image generation or editing (that's already handled by `image_generation.py`)
- Video or audio description
- Caching of descriptions (can be added later if needed)
- Changing the main LLM selection logic

## Decisions

### 1. Auto pre-call hook in `_state_build`, not in ContextBuilder

**Choice**: Add auto-describe logic in `AgentLoop._state_build()` (after `_build_initial_messages()` but before `_state_run()`).

**Alternatives considered**:
- *ContextBuilder._build_user_content()*: Clean semantically but ContextBuilder has no access to the vision provider or config — would require threading dependencies through layers.
- *_state_restore*: Too early; session isn't fully loaded yet.

**Rationale**: `_state_build` is the natural assembly point — it has access to the msg, config, tools registry, and is where initial messages are prepared for the LLM.

### 2. Descriptions injected as separate system messages, not merged into user content

**Choice**: Each image description becomes a standalone system message: `[system] [图片 N/M 描述]: <description>`.

**Rationale**: Clean separation between user intent and machine-generated description. Doesn't pollute the user message. The main LLM can clearly distinguish "what the user said" from "what the vision model saw."
> "Separate system message for each image keeps user intent clean and gives the main LLM clear provenance for each description."

### 3. Vision API called via direct HTTP, not through LLMProvider

**Choice**: VisionTool uses `httpx` directly to call DashScope's chat completions endpoint (OpenAI-compatible), rather than going through `LLMProvider.chat()`.

**Alternatives considered**:
- *Reuse OpenAICompatProvider*: Would need a second provider instance with different model settings. Adds complexity and couples the tool to the provider abstraction.
- *Use LLMProvider factory*: Heavy for a single API call with a fixed model.

**Rationale**: Direct HTTP is simpler, has no retry/complexity overhead, and the vision API shape is well-known (OpenAI-compatible). Keep it self-contained in the tool file.

### 4. Images sent to vision model as base64 data URIs

**Choice**: Read local image files, encode as base64 `data:<mime>;base64,<data>` URIs in the vision API request.

**Rationale**: DashScope's OpenAI-compatible endpoint accepts this format natively. No need for multipart uploads or file hosting.

### 5. Concurrent vision calls for multiple images

**Choice**: When a user sends N images, fire N concurrent vision API calls via `asyncio.gather()`.

**Rationale**: Images are independent — no reason to serialize. Concurrent calls minimize user-facing latency.

### 6. Config structure: top-level `vision` key under tools

**Choice**:
```python
class VisionToolConfig(Base):
    enabled: bool = True
    auto_describe: bool = True
    model: str = "qwen3.5-omni-plus-2026-03-15"
    provider: str = "dashscope"
    max_images_per_turn: int = 8
    max_description_chars: int = 1000
```

Added as a field in `ToolsConfig`.

**Rationale**: Matches the existing pattern of `ImageGenerationToolConfig`. Provider config reuses existing `dashscope` provider's API key.

## Risks / Trade-offs

- **Latency**: Each vision call adds ~1-3 seconds. For 3+ images, concurrent calls keep this bounded. → Mitigation: `max_images_per_turn` cap + concurrency.
- **DashScope API key requirement**: Users need a separate API key for vision. → Mitigation: auto-describe is configurable; failure falls back to `[image omitted]`.
- **Context window cost**: Each description is up to `max_description_chars` characters of system message. For many images this adds up. → Mitigation: configurable `max_description_chars` cap.
- **Vision model errors**: qwen3.5-omni-plus may be unavailable. → Mitigation: fallback to existing placeholder + user warning.
