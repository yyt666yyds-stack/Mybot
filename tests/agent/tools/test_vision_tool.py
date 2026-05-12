"""Tests for VisionTool — describe images via qwen3.5-omni-plus."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.tools.vision import VisionTool
from nanobot.config.schema import VisionToolConfig

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdacd\xfc\xff\x1f\x00\x03\x03"
    b"\x02\x00\xef\xbf\xa7\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)

_DASHSCOPE_RESULT = {
    "choices": [{"message": {"content": "这是一张橘色猫咪的图片。"}}],
}


def _make_vision_tool(**overrides) -> VisionTool:
    config = VisionToolConfig()
    for k, v in overrides.items():
        if hasattr(config, k):
            setattr(config, k, v)
    providers = MagicMock()
    providers.dashscope = MagicMock()
    providers.dashscope.api_key = "sk-test-key"
    providers.dashscope.api_base = None
    return VisionTool(config=config, providers=providers)


def _make_vision_tool_no_key() -> VisionTool:
    config = VisionToolConfig()
    providers = MagicMock()
    providers.dashscope = MagicMock()
    providers.dashscope.api_key = None
    providers.dashscope.api_base = None
    return VisionTool(config=config, providers=providers)


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


class TestParameterValidation:
    def test_missing_both_path_and_url(self):
        tool = _make_vision_tool()
        errors = tool.validate_params({})
        assert len(errors) == 0  # both are optional, handled in execute

    def test_path_is_string(self):
        tool = _make_vision_tool()
        errors = tool.validate_params({"path": "/tmp/test.png"})
        assert len(errors) == 0

    def test_path_rejects_integer(self):
        tool = _make_vision_tool()
        errors = tool.validate_params({"path": 123})
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestVisionToolErrors:
    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        tool = _make_vision_tool_no_key()
        result = await tool.execute(path="/tmp/test.png")
        assert "API key is not configured" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        tool = _make_vision_tool()
        result = await tool.execute(path="/nonexistent/image.png")
        assert "file not found" in result

    @pytest.mark.asyncio
    async def test_neither_path_nor_url(self):
        tool = _make_vision_tool()
        result = await tool.execute()
        assert "Either 'path' or 'url' must be provided" in result

    @pytest.mark.asyncio
    async def test_unsupported_format(self, tmp_path: Path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not an image")
        tool = _make_vision_tool()
        result = await tool.execute(path=str(txt_file))
        assert "unsupported image format" in result


# ---------------------------------------------------------------------------
# Happy path (with mocked HTTP)
# ---------------------------------------------------------------------------


class TestVisionToolHappyPath:
    @pytest.mark.asyncio
    async def test_describe_local_png(self, tmp_path: Path):
        png_file = tmp_path / "test.png"
        png_file.write_bytes(PNG_BYTES)

        tool = _make_vision_tool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _DASHSCOPE_RESULT

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await tool.execute(path=str(png_file))
            assert "橘色猫咪" in result

    @pytest.mark.asyncio
    async def test_describe_url(self):
        tool = _make_vision_tool()

        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.content = PNG_BYTES

        mock_post_response = MagicMock()
        mock_post_response.status_code = 200
        mock_post_response.json.return_value = _DASHSCOPE_RESULT

        with (
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
            patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
        ):
            mock_get.return_value = mock_get_response
            mock_post.return_value = mock_post_response

            result = await tool.execute(url="https://example.com/cat.png")
            assert "橘色猫咪" in result

    @pytest.mark.asyncio
    async def test_truncate_long_description(self, tmp_path: Path):
        png_file = tmp_path / "test.png"
        png_file.write_bytes(PNG_BYTES)

        tool = _make_vision_tool(max_description_chars=50)

        long_desc = "这是一张图片。" * 100
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": long_desc}}],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await tool.execute(path=str(png_file))
            assert len(result) <= 50

    @pytest.mark.asyncio
    async def test_api_error_returns_error_string(self, tmp_path: Path):
        png_file = tmp_path / "test.png"
        png_file.write_bytes(PNG_BYTES)

        tool = _make_vision_tool()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await tool.execute(path=str(png_file))
            assert result.startswith("Error")

    @pytest.mark.asyncio
    async def test_url_fetch_error(self):
        tool = _make_vision_tool()

        mock_get_response = MagicMock()
        mock_get_response.status_code = 404

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_get_response

            result = await tool.execute(url="https://example.com/missing.png")
            assert "failed to download" in result


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------


class TestVisionToolSchema:
    def test_name(self):
        tool = _make_vision_tool()
        assert tool.name == "describe_image"

    def test_description(self):
        tool = _make_vision_tool()
        assert "Describe" in tool.description
        assert "image" in tool.description.lower()

    def test_to_schema(self):
        tool = _make_vision_tool()
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "describe_image"
        props = schema["function"]["parameters"]["properties"]
        assert "path" in props
        assert "url" in props
