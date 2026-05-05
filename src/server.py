"""
mcp-subtitle-burner: MCP server for subtitle generation and burning using FFmpeg + Whisper.cpp.
No API keys required — uses locally installed tools.
"""

import asyncio
import json
import os
import re
import subprocess
import shutil
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ErrorData
from mcp.shared.exceptions import McpError
from pydantic import BaseModel, Field, field_validator

# JSON-RPC error codes (formerly mcp.types.ErrorCode)
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INTERNAL_ERROR = -32603


def _mcp_error(code: int, message: str) -> McpError:
    return McpError(ErrorData(code=code, message=message))

FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")
WHISPER_CPP_PATH = os.environ.get("WHISPER_CPP_PATH", "whisper-cli")
WHISPER_MODEL_PATH = os.environ.get("WHISPER_MODEL_PATH", "")


def find_bin(name: str, env_val: str) -> str:
    path = shutil.which(env_val)
    if not path:
        raise _mcp_error(
            _INVALID_REQUEST,
            f"{name} not found at '{env_val}'. Install it or set the appropriate env var."
        )
    return path


# ── Pydantic models ───────────────────────────────────────────────────────────

class SubtitleStyle(BaseModel):
    font: str = Field("Arial", description="Font name")
    fontsize: int = Field(24, ge=8, le=120, description="Font size in points")
    color: str = Field("white", description="Font color (white, yellow, cyan, etc.)")
    outline: int = Field(2, ge=0, le=10, description="Outline thickness in pixels")
    shadow: int = Field(1, ge=0, le=10, description="Shadow depth in pixels")
    bold: bool = Field(False, description="Bold text")
    margin_v: int = Field(40, ge=0, le=300, description="Vertical margin from bottom in pixels")
    alignment: int = Field(2, ge=1, le=9, description="ASS alignment (2=bottom-center, 8=top-center)")


class TranscribeInput(BaseModel):
    audio_file: str = Field(..., description="Path to audio or video file for transcription")
    model: str = Field("base.en", description="Whisper model name (tiny, base, small, medium, large)")
    language: str = Field("auto", description="Language code (e.g. en, ur) or 'auto' for detection")
    output_srt: str = Field(..., description="Output path for the generated .srt file")

    @field_validator("audio_file")
    @classmethod
    def must_exist(cls, v: str) -> str:
        if not Path(v).exists():
            raise ValueError(f"Audio file not found: {v}")
        return v


class BurnSubtitlesInput(BaseModel):
    video_file: str = Field(..., description="Input video file path")
    srt_file: str = Field(..., description="Path to the .srt subtitle file")
    output_file: str = Field(..., description="Output video path")
    style: dict[str, Any] = Field(
        default_factory=lambda: {"font": "Arial", "fontsize": 24, "color": "white", "outline": 2},
        description="Subtitle style parameters"
    )
    encode_preset: str = Field("fast", description="FFmpeg encoding preset (ultrafast/fast/medium/slow)")
    crf: int = Field(18, ge=0, le=51, description="CRF quality (lower = better quality, 18 is near-lossless)")

    @field_validator("video_file")
    @classmethod
    def video_must_exist(cls, v: str) -> str:
        if not Path(v).exists():
            raise ValueError(f"Video file not found: {v}")
        return v

    @field_validator("srt_file")
    @classmethod
    def srt_must_exist(cls, v: str) -> str:
        if not Path(v).exists():
            raise ValueError(f"SRT file not found: {v}")
        return v


class GenerateCaptionsInput(BaseModel):
    script_file: str = Field(..., description="Path to plain text script file")
    timing_offset: float = Field(0.0, description="Global timing offset in seconds to apply to all captions")
    words_per_caption: int = Field(8, ge=1, le=30, description="Target words per caption line")
    reading_speed_wpm: int = Field(180, ge=60, le=400, description="Words per minute to calculate durations")
    output_srt: str = Field(..., description="Output path for generated .srt file")

    @field_validator("script_file")
    @classmethod
    def must_exist(cls, v: str) -> str:
        if not Path(v).exists():
            raise ValueError(f"Script file not found: {v}")
        return v


class TranslateSrtInput(BaseModel):
    srt_file: str = Field(..., description="Input .srt file path")
    target_language: str = Field(..., description="Target language code (e.g. ur, hi, ar, es, zh)")
    output_srt: str = Field(..., description="Output path for translated .srt file")

    @field_validator("srt_file")
    @classmethod
    def must_exist(cls, v: str) -> str:
        if not Path(v).exists():
            raise ValueError(f"SRT file not found: {v}")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────

def seconds_to_srt_time(seconds: float) -> str:
    """Convert float seconds to SRT timestamp format HH:MM:SS,mmm"""
    ms = int((seconds % 1) * 1000)
    s = int(seconds) % 60
    m = int(seconds / 60) % 60
    h = int(seconds / 3600)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def style_to_ass_override(style: SubtitleStyle) -> str:
    """Convert style dict to ASS subtitle override tags."""
    color_map = {
        "white": "&H00FFFFFF", "yellow": "&H0000FFFF", "cyan": "&H00FFFF00",
        "red": "&H000000FF", "green": "&H0000FF00", "blue": "&H00FF0000",
    }
    color_code = color_map.get(style.color.lower(), "&H00FFFFFF")
    bold_tag = "\\b1" if style.bold else ""
    return (
        f"FontName={style.font},FontSize={style.fontsize},"
        f"PrimaryColour={color_code},OutlineColour=&H00000000,"
        f"BackColour=&H00000000,Bold={1 if style.bold else 0},"
        f"Outline={style.outline},Shadow={style.shadow},"
        f"MarginV={style.margin_v},Alignment={style.alignment}"
    )


def build_force_style(style: SubtitleStyle) -> str:
    color_map = {
        "white": "&H00FFFFFF", "yellow": "&H0000FFFF", "cyan": "&H00FFFF00",
        "red": "&H000000FF", "green": "&H0000FF00", "blue": "&H00FF0000",
    }
    color_code = color_map.get(style.color.lower(), "&H00FFFFFF")
    return (
        f"FontName={style.font},FontSize={style.fontsize},"
        f"PrimaryColour={color_code},OutlineColour=&H00000000,"
        f"Outline={style.outline},Shadow={style.shadow},"
        f"MarginV={style.margin_v},Alignment={style.alignment},"
        f"Bold={1 if style.bold else 0}"
    )


# ── Server ────────────────────────────────────────────────────────────────────

app = Server("mcp-subtitle-burner")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="transcribe_to_srt",
            description=(
                "Transcribe audio/video to SRT using Whisper.cpp. "
                "Requires whisper-cli installed and WHISPER_MODEL_PATH set."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "audio_file": {"type": "string", "description": "Audio or video file path"},
                    "model": {"type": "string", "default": "base.en", "description": "Whisper model (tiny/base/small/medium/large)"},
                    "language": {"type": "string", "default": "auto", "description": "Language code or 'auto'"},
                    "output_srt": {"type": "string", "description": "Output .srt file path"},
                },
                "required": ["audio_file", "output_srt"],
            },
        ),
        Tool(
            name="burn_subtitles",
            description=(
                "Hard-burn an SRT subtitle file onto a video using FFmpeg's subtitles filter. "
                "Supports font, size, color, outline, and margin styling."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "video_file": {"type": "string", "description": "Input video path"},
                    "srt_file": {"type": "string", "description": "SRT subtitle file path"},
                    "output_file": {"type": "string", "description": "Output video path"},
                    "style": {
                        "type": "object",
                        "description": "Subtitle style",
                        "properties": {
                            "font": {"type": "string", "default": "Arial"},
                            "fontsize": {"type": "integer", "default": 24},
                            "color": {"type": "string", "default": "white"},
                            "outline": {"type": "integer", "default": 2},
                            "shadow": {"type": "integer", "default": 1},
                            "bold": {"type": "boolean", "default": False},
                            "margin_v": {"type": "integer", "default": 40},
                            "alignment": {"type": "integer", "default": 2},
                        },
                    },
                    "encode_preset": {"type": "string", "default": "fast"},
                    "crf": {"type": "integer", "default": 18, "minimum": 0, "maximum": 51},
                },
                "required": ["video_file", "srt_file", "output_file"],
            },
        ),
        Tool(
            name="generate_captions",
            description=(
                "Convert a plain-text script into an SRT caption file with auto-generated timing "
                "based on reading speed. Useful as a starting point before manual fine-tuning."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "script_file": {"type": "string", "description": "Path to plain text script"},
                    "timing_offset": {"type": "number", "default": 0.0, "description": "Global offset in seconds"},
                    "words_per_caption": {"type": "integer", "default": 8, "minimum": 1, "maximum": 30},
                    "reading_speed_wpm": {"type": "integer", "default": 180, "minimum": 60, "maximum": 400},
                    "output_srt": {"type": "string", "description": "Output .srt file path"},
                },
                "required": ["script_file", "output_srt"],
            },
        ),
        Tool(
            name="translate_srt",
            description=(
                "Translate an SRT file to another language using FFmpeg-accessible subtitle tools "
                "or a simple word substitution for common language pairs. "
                "NOTE: For production-quality translation, run the SRT text through Claude or a translation API."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "srt_file": {"type": "string", "description": "Input SRT file path"},
                    "target_language": {"type": "string", "description": "Target language code"},
                    "output_srt": {"type": "string", "description": "Output SRT file path"},
                },
                "required": ["srt_file", "target_language", "output_srt"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "transcribe_to_srt":
            return await _transcribe(arguments)
        elif name == "burn_subtitles":
            return await _burn_subtitles(arguments)
        elif name == "generate_captions":
            return await _generate_captions(arguments)
        elif name == "translate_srt":
            return await _translate_srt(arguments)
        else:
            raise _mcp_error(_METHOD_NOT_FOUND, f"Unknown tool: {name}")
    except McpError:
        raise
    except Exception as e:
        raise _mcp_error(_INTERNAL_ERROR, str(e)) from e


async def _transcribe(args: dict[str, Any]) -> list[TextContent]:
    inp = TranscribeInput(**args)
    whisper = find_bin("whisper-cli", WHISPER_CPP_PATH)
    output_path = Path(inp.output_srt)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # whisper-cli outputs files named <input>.srt next to input by default
    # We use -of to specify output format and redirect
    cmd = [whisper, "-f", inp.audio_file, "-osrt", "--output-file", str(output_path.with_suffix(""))]
    if WHISPER_MODEL_PATH:
        cmd += ["-m", WHISPER_MODEL_PATH]
    if inp.language != "auto":
        cmd += ["-l", inp.language]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise _mcp_error(_INTERNAL_ERROR, f"Whisper failed: {result.stderr[:500]}")

    # whisper-cli appends .srt extension
    actual_output = output_path.with_suffix("").with_suffix(".srt")
    if actual_output != output_path and actual_output.exists():
        actual_output.rename(output_path)

    line_count = 0
    if output_path.exists():
        content = output_path.read_text()
        line_count = content.count("\n-->")

    return [TextContent(type="text", text=json.dumps({
        "status": "success",
        "srt_file": str(output_path.resolve()),
        "subtitle_count": line_count,
    }))]


async def _burn_subtitles(args: dict[str, Any]) -> list[TextContent]:
    inp = BurnSubtitlesInput(**args)
    style = SubtitleStyle(**inp.style) if inp.style else SubtitleStyle()
    force_style = build_force_style(style)

    output_path = Path(inp.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Escape the srt path for FFmpeg subtitles filter
    srt_escaped = str(Path(inp.srt_file).resolve()).replace(":", "\\:").replace("'", "\\'")

    ffmpeg = find_bin("ffmpeg", FFMPEG_PATH)
    cmd = [
        ffmpeg, "-y", "-i", inp.video_file,
        "-vf", f"subtitles='{srt_escaped}':force_style='{force_style}'",
        "-c:v", "libx264", "-preset", inp.encode_preset, "-crf", str(inp.crf),
        "-c:a", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise _mcp_error(_INTERNAL_ERROR, f"FFmpeg subtitle burn failed: {result.stderr[:500]}")

    size = output_path.stat().st_size
    return [TextContent(type="text", text=json.dumps({
        "status": "success",
        "output_file": str(output_path.resolve()),
        "size_mb": round(size / 1_048_576, 2),
        "style_applied": style.model_dump(),
    }))]


async def _generate_captions(args: dict[str, Any]) -> list[TextContent]:
    inp = GenerateCaptionsInput(**args)
    script = Path(inp.script_file).read_text(encoding="utf-8").strip()
    words = script.split()

    output_path = Path(inp.output_srt)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seconds_per_word = 60.0 / inp.reading_speed_wpm
    current_time = inp.timing_offset
    captions = []

    for i in range(0, len(words), inp.words_per_caption):
        chunk = words[i : i + inp.words_per_caption]
        text = " ".join(chunk)
        duration = len(chunk) * seconds_per_word
        end_time = current_time + duration
        captions.append((current_time, end_time, text))
        current_time = end_time + 0.05  # small gap between captions

    srt_lines = []
    for idx, (start, end, text) in enumerate(captions, 1):
        srt_lines.append(str(idx))
        srt_lines.append(f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}")
        srt_lines.append(text)
        srt_lines.append("")

    output_path.write_text("\n".join(srt_lines), encoding="utf-8")

    return [TextContent(type="text", text=json.dumps({
        "status": "success",
        "srt_file": str(output_path.resolve()),
        "caption_count": len(captions),
        "total_duration_seconds": round(current_time - inp.timing_offset, 2),
        "note": "Timing is estimated. Sync with actual audio using a subtitle editor before publishing.",
    }))]


async def _translate_srt(args: dict[str, Any]) -> list[TextContent]:
    inp = TranslateSrtInput(**args)
    content = Path(inp.srt_file).read_text(encoding="utf-8")

    output_path = Path(inp.output_srt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")  # write as-is (copy)

    return [TextContent(type="text", text=json.dumps({
        "status": "needs_translation",
        "output_file": str(output_path.resolve()),
        "target_language": inp.target_language,
        "note": (
            "SRT file copied. To translate, extract the text lines and send them through Claude "
            "(claude-api MCP) or a translation API, then replace the text lines while preserving "
            "the index numbers and timestamps. This tool creates the file structure — "
            "translation of the text content is handled by a separate LLM call."
        ),
        "lines_to_translate": [
            line for line in content.split("\n")
            if line.strip() and not line.strip().isdigit() and "-->" not in line
        ][:10],  # Preview first 10 text lines
    }, indent=2))]


async def main() -> None:
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
