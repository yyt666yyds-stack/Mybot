## ADDED Requirements

### Requirement: Vision tool describes images via qwen3.5-omni-plus

The system SHALL provide a `describe_image` tool that accepts an image path or URL and returns a text description by calling the qwen3.5-omni-plus-2026-03-15 model via DashScope API.

#### Scenario: Describe a local image file

- **WHEN** the tool is called with `path="/tmp/photo.jpg"` and the file exists and is a valid image
- **THEN** the system reads the file, encodes it as base64, sends it to qwen3.5-omni-plus, and returns a text description of the image content

#### Scenario: Describe an image URL

- **WHEN** the tool is called with `url="https://example.com/photo.jpg"` and the URL is reachable
- **THEN** the system fetches the image, sends it to qwen3.5-omni-plus, and returns a text description

#### Scenario: Image file not found

- **WHEN** the tool is called with a path that does not exist
- **THEN** the system returns an error message: "Error: image file not found: <path>"

#### Scenario: API key not configured

- **WHEN** the tool is called but `DASHSCOPE_API_KEY` is not set
- **THEN** the system returns an error message: "Error: DashScope API key is not configured. Set DASHSCOPE_API_KEY."

### Requirement: Automatic image pre-description

When `tools.vision.enabled` and `tools.vision.auto_describe` are both true, the system SHALL automatically describe user-uploaded images before the main LLM processes the message.

#### Scenario: Single image auto-described

- **WHEN** a user sends a message with one image attachment
- **THEN** the system calls `describe_image` for that image before the main LLM turn, and injects the description as a system message: `[system] [图片 1/1 描述]: <description>`

#### Scenario: Multiple images auto-described concurrently

- **WHEN** a user sends a message with three image attachments
- **THEN** the system calls `describe_image` for all three images concurrently, and injects three system messages: `[图片 1/3 描述]`, `[图片 2/3 描述]`, `[图片 3/3 描述]`

#### Scenario: Auto-describe disabled

- **WHEN** `tools.vision.auto_describe` is false and the main LLM calls `describe_image` directly
- **THEN** the tool SHALL still work and return the description to the LLM

#### Scenario: Exceeds max images per turn

- **WHEN** a user sends more images than `tools.vision.max_images_per_turn` allows
- **THEN** the system describes only up to the limit and appends a note: "[剩余 N 张图片超出单轮上限，已跳过]"

### Requirement: Graceful fallback on vision API failure

The system SHALL fall back to the existing `[image omitted]` placeholder text when the vision API call fails during auto-describe.

#### Scenario: Vision API network error during auto-describe

- **WHEN** the vision API call fails due to network error during auto-describe
- **THEN** the system inserts the `[image omitted]` placeholder for that image and adds a warning: "[图片描述生成失败: connection error]"

#### Scenario: Vision API returns non-success status

- **WHEN** the vision API returns a 4xx or 5xx status
- **THEN** the system falls back to `[image omitted]` and logs the error

### Requirement: Vision tool configuration

The system SHALL support configuration via `ToolsConfig.vision` with the following fields:

- `enabled` (bool, default true): Whether the vision tool is registered
- `auto_describe` (bool, default true): Whether to auto-describe images before main LLM turn
- `model` (str, default "qwen3.5-omni-plus-2026-03-15"): Vision model to use
- `provider` (str, default "dashscope"): Provider name for API key lookup
- `max_images_per_turn` (int, default 8): Maximum images to describe per turn
- `max_description_chars` (int, default 1000): Maximum characters per description

#### Scenario: Config validation

- **WHEN** `max_images_per_turn` is set to 0
- **THEN** no images are auto-described (effectively disables auto-describe via count)
