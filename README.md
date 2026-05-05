# mcp-subtitle-burner

MCP server for subtitle transcription and hard-burning using FFmpeg and Whisper.cpp. Generate SRT files from audio, burn styled captions onto video, and create timing-estimated captions from scripts — all locally.

## Tools

| Tool | Description |
|------|-------------|
| `transcribe_to_srt` | Transcribe audio/video to SRT using Whisper.cpp |
| `burn_subtitles` | Hard-burn SRT onto video with custom font/style |
| `generate_captions` | Convert a script text file to timed SRT |
| `translate_srt` | Prepare SRT for translation (extracts text lines) |

## Free Tier Limits

| Component | Cost |
|-----------|------|
| FFmpeg | **Free, open source** |
| Whisper.cpp | **Free, open source, fully local** |
| Cloud API usage | **None — 100% offline** |

No subscriptions, no per-minute charges. Transcribe unlimited hours of video locally.

## Prerequisites

### FFmpeg
```bash
brew install ffmpeg   # macOS
sudo apt install ffmpeg  # Ubuntu
```

### Whisper.cpp
```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp && make
bash ./models/download-ggml-model.sh base.en   # or small, medium
make whisper-cli
```

**Recommended models by use case:**
| Model | Speed | Accuracy | VRAM |
|-------|-------|----------|------|
| `tiny.en` | Fastest | Low | 0.4GB |
| `base.en` | Fast | Good | 0.7GB |
| `small.en` | Medium | Better | 1.5GB |
| `medium.en` | Slow | Best | 3GB |
| `large-v3` | Slowest | Best multi-lang | 6GB |

## Environment Variables

```bash
FFMPEG_PATH=ffmpeg
WHISPER_CPP_PATH=whisper-cli
WHISPER_MODEL_PATH=/path/to/whisper.cpp/models/ggml-base.en.bin
```

## Install

```bash
cd mcp-subtitle-burner
pip install -e .
```

## Claude Code `.mcp.json` Config

```json
{
  "mcpServers": {
    "subtitle-burner": {
      "command": "python",
      "args": ["/absolute/path/to/mcp-subtitle-burner/src/server.py"],
      "env": {
        "FFMPEG_PATH": "ffmpeg",
        "WHISPER_CPP_PATH": "/path/to/whisper.cpp/whisper-cli",
        "WHISPER_MODEL_PATH": "/path/to/whisper.cpp/models/ggml-base.en.bin"
      }
    }
  }
}
```

## Example Prompts

```
Transcribe /Videos/interview.mp4 to SRT using the base.en model, save to /Subs/interview.srt
```

```
Burn subtitles from interview.srt onto interview.mp4, use yellow font size 28, bold, save to interview_captioned.mp4
```

```
Generate a timed SRT from my script at /Scripts/ep12_script.txt, 8 words per caption, 180 WPM
```

## Subtitle Style Parameters

```json
{
  "font": "Arial",
  "fontsize": 24,
  "color": "white",
  "outline": 2,
  "shadow": 1,
  "bold": false,
  "margin_v": 40,
  "alignment": 2
}
```

**Available colors:** white, yellow, cyan, red, green, blue

**Alignment values (ASS standard):**
- `2` = bottom center (default, most common)
- `8` = top center
- `5` = center screen

## Shorts Caption Style (Recommended)

```json
{
  "font": "Arial",
  "fontsize": 48,
  "color": "yellow",
  "outline": 3,
  "bold": true,
  "margin_v": 120,
  "alignment": 2
}
```

Larger font + yellow + high margin works best for vertical 9:16 Shorts.

## `generate_captions` Use Case

If you write scripts before recording:
1. Export script as plain text
2. Use `generate_captions` to create a rough SRT with estimated timing
3. Record video following the script
4. Fine-tune timestamps in a subtitle editor (Subtitle Edit — free)
5. Burn with `burn_subtitles`

This workflow is faster than transcribing ad-lib recordings.

## Translation Workflow

`translate_srt` extracts the text lines from an SRT and returns them for translation. The recommended workflow:
1. Call `translate_srt` to extract text
2. Send the text lines to Claude (or any translation tool) for translation
3. Reconstruct the SRT preserving original timestamps
4. Burn the translated SRT onto the video

## How I Built This — Channel 1 Angle

**Video idea:** *"Free AI subtitles in any language — my local Whisper + FFmpeg workflow"*

The cost comparison is stark: commercial caption services charge $1-3/minute. This pipeline transcribes with Whisper.cpp locally, runs on a Mac with Metal acceleration at roughly 10x realtime speed (1 hour of audio transcribed in 6 minutes), and burns the result with FFmpeg in one FFmpeg command. The entire workflow costs $0 and runs without internet.

The Shorts caption style (large yellow font, bold) is specifically tuned for vertical videos — tested against the YouTube Shorts algorithm's requirement that key text appear within the safe area. The `margin_v: 120` setting keeps captions above the UI elements that YouTube overlays on Shorts.

## License

MIT — see [LICENSE](LICENSE)
