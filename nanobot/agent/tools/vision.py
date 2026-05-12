"""Vision tool — describe images using qwen3.5-omni-plus."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.config.schema import VisionToolConfig
from nanobot.utils.helpers import detect_image_mime

if TYPE_CHECKING:
    from nanobot.config.schema import ProvidersConfig


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema(
            "Local filesystem path to the image file to describe.",
        ),
        url=StringSchema(
            "URL of the image to describe.",
        ),
    )
)
class VisionTool(Tool):
    """Describe images using a vision-capable model (qwen3.5-omni-plus)."""

    def __init__(
        self,
        *,
        config: VisionToolConfig,
        providers: ProvidersConfig | None = None,
    ) -> None:
        self._config = config
        provider_config = getattr(providers, config.provider, None) if providers else None
        self._api_key = provider_config.api_key if provider_config else None
        self._api_base = provider_config.api_base if provider_config else None
        logger.info(
            "[vision] VisionTool init: enabled={}, auto_describe={}, provider={}, "
            "has_api_key={}",
            config.enabled,
            config.auto_describe,
            config.provider,
            bool(self._api_key),
        )

    @property
    def name(self) -> str:
        return "describe_image"

    @property
    def description(self) -> str:
        return (
            "Describe the content of an image. "
            "Provide either a local file path or an image URL. "
            "Returns a text description of what the image shows."
        )

    def _api_url(self) -> str:
        base = (self._api_base or "").rstrip("/")
        if base.endswith("/compatible-mode/v1"):
            return f"{base}/chat/completions"
        return f"{base}/chat/completions" if base else "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

    def _build_image_block(self, image_data: bytes, mime: str) -> dict[str, Any]:
        b64 = base64.b64encode(image_data).decode()
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        }

    async def _call_vision_api(self, image_block: dict[str, Any]) -> str:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        image_block,
                        {"type": "text", "text": "请详细描述这张图片的内容。用中文描述。"},
                    ],
                }
            ],
            "max_tokens": 512,
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(self._api_url(), json=payload, headers=headers)
            if response.status_code != 200:
                raise RuntimeError(
                    f"DashScope API returned status {response.status_code}: "
                    f"{response.text[:300]}"
                )
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("DashScope API returned no choices")
            content = (
                choices[0]
                .get("message", {})
                .get("content", "")
            )
            if not content:
                raise RuntimeError("DashScope API returned empty content")
            result = content if isinstance(content, str) else str(content)
            return result[: self._config.max_description_chars].strip()

    async def execute(self, path: str = "", url: str = "", **kwargs: Any) -> str:
        """Describe an image from a local path or URL.

        Returns the text description or an error message.
        """
        if not self._api_key:
            return "Error: DashScope API key is not configured. Set providers.dashscope.apiKey."

        try:
            if url:
                return await self._describe_url(url)
            if path:
                return await self._describe_local(path)
            return (
                "Error: Either 'path' or 'url' must be provided. "
                "Usage: describe_image(path=\"/tmp/photo.jpg\") or describe_image(url=\"https://...\")"
            )
        except Exception as exc:
            return f"Error describing image: {exc}"

    async def _describe_local(self, path_str: str) -> str:
        p = Path(path_str).expanduser()
        if not p.is_file():
            return f"Error: image file not found: {path_str}"
        raw = p.read_bytes()
        mime = detect_image_mime(raw)
        if mime is None:
            return f"Error: unsupported image format: {path_str}"
        block = self._build_image_block(raw, mime)
        return await self._call_vision_api(block)

    async def _describe_url(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                return f"Error: failed to download image from URL (status {resp.status_code})"
            raw = resp.content
            mime = detect_image_mime(raw)
            if mime is None:
                return "Error: unsupported image format from URL"
            block = self._build_image_block(raw, mime)
            return await self._call_vision_api(block)
