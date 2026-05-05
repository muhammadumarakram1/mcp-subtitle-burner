# mcp-subtitle-burner — Research Report
**Date:** 2026-05-05

## Dependencies (verified)
- `mcp>=1.0.0`: unpinned floor; current MCP Python SDK is 1.x — MATCH
- `pydantic>=2.0.0`: unpinned floor; Pydantic 2.x stable — MATCH
- `pydantic-settings>=2.0.0`: unpinned floor; 2.x stable — MATCH
- `ffmpeg` (system): flags used are stable — MATCH
- `whisper-cli` (system binary): renamed from `main` to `whisper-cli` in PR #2648 (late 2024); code already uses `whisper-cli` — MATCH

## Tool/API State (verified)
- **whisper-cli flags used**: `-f <audio>`, `-osrt`, `--output-file <stem>`, `-m <model_path>`, `-l <lang>`. All flags confirmed stable in whisper.cpp 1.7.x. ([whisper.cpp GitHub](https://github.com/ggml-org/whisper.cpp))
- **whisper-cli binary rename**: old binary was `main`; renamed to `whisper-cli` in late 2024. Code correctly defaults `WHISPER_CPP_PATH = "whisper-cli"`. ([rename PR #2648](https://github.com/ggml-org/whisper.cpp/pull/2648))
- **ffmpeg `subtitles=` filter with `force_style`**: stable, no breaking changes in 2025–2026. ([ffmpeg subtitles filter docs](https://ffmpeg.org/ffmpeg-filters.html#subtitles))

## Code vs tool delta
- `-osrt` flag to output SRT: MATCH (confirmed still valid flag name)
- `--output-file <stem>` (no extension): MATCH — whisper-cli appends `.srt` automatically; code handles this with rename logic on lines 292–294
- `language="auto"` maps to omitting `-l` flag: MATCH — no `-l` flag passed when `auto`
- ffmpeg `subtitles='<path>':force_style='...'` filter: MATCH — syntax valid

## Fixes required
- NONE

## Confidence
HIGH

## Sources
1. https://github.com/ggml-org/whisper.cpp/pull/2648
2. https://github.com/ggml-org/whisper.cpp
3. https://ffmpeg.org/ffmpeg-filters.html#subtitles
