"""DashScope multimodal image generation client."""

from __future__ import annotations

from typing import Any

import httpx

from nanobot.providers.image_generation import (
    _DEFAULT_TIMEOUT_S,
    _download_image_data_url,
    _provider_base_url,
    GeneratedImageResponse,
    ImageGenerationError,
    image_path_to_data_url,
)

_DASHSCOPE_ASPECT_RATIO_SIZES = {
    "1:1": "1024*1024",
    "3:4": "1024*1536",
    "9:16": "1024*1536",
    "4:3": "1536*1024",
    "16:9": "1536*1024",
}


def _dashscope_image_base_url(api_base: str | None) -> str:
    """Build the DashScope image generation endpoint from the chat API base."""
    base = _provider_base_url(
        "dashscope",
        api_base,
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    if "://" in base:
        scheme, rest = base.split("://", 1)
        host = rest.split("/")[0]
        return f"{scheme}://{host}/api/v1/services/aigc/multimodal-generation/generation"
    return "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


def _dashscope_size(aspect_ratio: str | None, image_size: str | None) -> str | None:
    """Convert aspect ratio / size hint to DashScope ``W*H`` format."""
    if image_size and "*" in image_size:
        return image_size
    if image_size and "x" in image_size.lower():
        return image_size.replace("x", "*").replace("X", "*")
    if aspect_ratio in _DASHSCOPE_ASPECT_RATIO_SIZES:
        return _DASHSCOPE_ASPECT_RATIO_SIZES[aspect_ratio]
    return None


class DashScopeImageGenerationClient:
    """Async client for DashScope multimodal image generation."""

    def __init__(
        self,
        *,
        api_key: str | None,
        api_base: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        timeout: float = _DEFAULT_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = _dashscope_image_base_url(api_base)
        self.extra_headers = extra_headers or {}
        self.extra_body = extra_body or {}
        self.timeout = timeout
        self._client = client

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> GeneratedImageResponse:
        if not self.api_key:
            raise ImageGenerationError(
                "DashScope API key is not configured. Set providers.dashscope.apiKey."
            )

        content: list[dict[str, Any]] = []
        for path in list(reference_images or []):
            content.append({"image": image_path_to_data_url(path)})
        content.append({"text": prompt})

        body: dict[str, Any] = {
            "model": model,
            "input": {
                "messages": [
                    {"role": "user", "content": content}
                ]
            },
            "parameters": {
                "n": 1,
            },
        }

        size = _dashscope_size(aspect_ratio, image_size)
        if size:
            body["parameters"]["size"] = size
        body["parameters"].update(self.extra_body)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        if self._client is not None:
            response = await self._client.post(self.api_base, headers=headers, json=body)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.api_base, headers=headers, json=body)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise ImageGenerationError(
                f"DashScope image generation failed: {detail}"
            ) from exc

        data = response.json()

        if "code" in data and data.get("code") != "" and "output" not in data:
            raise ImageGenerationError(
                f"DashScope image generation failed: {data.get('message', data.get('code'))}"
            )

        images: list[str] = []
        text_parts: list[str] = []

        output = data.get("output") or {}
        for choice in output.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            for item in message.get("content") or []:
                if not isinstance(item, dict):
                    continue
                if "image" in item:
                    url = str(item["image"])
                    if url.startswith("data:image/"):
                        images.append(url)
                    elif url.startswith(("http://", "https://")):
                        dl = self._client
                        if dl is not None:
                            images.append(await _download_image_data_url(dl, url))
                        else:
                            async with httpx.AsyncClient(timeout=self.timeout) as dl:
                                images.append(await _download_image_data_url(dl, url))
                if "text" in item:
                    text_parts.append(str(item["text"]))

        if not images:
            raise ImageGenerationError(
                "DashScope returned no images for this request"
            )

        return GeneratedImageResponse(
            images=images,
            content="\n".join(part for part in text_parts if part).strip(),
            raw=data,
        )
