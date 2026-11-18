# Nyx-AI-Translator

<p align="center">
  <img src="assets/logo.png" alt="Nyx-AI-Translator logo" width="180">
</p>

Structure-preserving AI subtitle translator in a single Python script.

Nyx-AI-Translator does **not** ask a model to rewrite your whole subtitle file. It parses subtitles, extracts only the visible text, translates that text, then rebuilds the original subtitle shell with timing and styling preserved.

## How it works

Nyx-AI-Translator keeps subtitle structure local. Only clean dialogue text is sent to the selected translator/provider.

![Nyx-AI-Translator workflow](assets/workflow.svg)

## Structure-preserving translation

Instead of sending the whole subtitle file to the AI, the tool separates subtitle structure from dialogue.

![Subtitle parse and rebuild example](assets/parse-rebuild-example.svg)

### SRT example

Original subtitle:

```srt
1
00:00:01,000 --> 00:00:03,000
Hello, world!

2
00:00:04,000 --> 00:00:05,500
How are you?
```

Nyx-AI-Translator extracts only the dialogue text:

```json
[
  {"id": "1", "text": "Hello, world!"},
  {"id": "2", "text": "How are you?"}
]
```

The translator returns:

```json
[
  {"id": "1", "text": "مرحباً بالعالم!"},
  {"id": "2", "text": "كيف حالك؟"}
]
```

Rebuilt subtitle:

```srt
1
00:00:01,000 --> 00:00:03,000
مرحباً بالعالم!

2
00:00:04,000 --> 00:00:05,500
كيف حالك؟
```

Cue numbers and timestamps stay exactly where they belong.

### ASS example

Example ASS subtitle line:

```ass
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\an8}Hello, {\i1}friend{\i0}!
```

The tool extracts only the dialogue text and protects style tags as placeholders:

```json
[{"id": "1", "text": "Hello, <TAG_2>friend<TAG_3>!"}]
```

The translator returns:

```json
[{"id": "1", "text": "مرحباً، <TAG_2>صديقي<TAG_3>!"}]
```

Then Nyx-AI-Translator rebuilds the original subtitle line:

```ass
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\an8}مرحباً، {\i1}صديقي{\i0}!
```

Timing, style, font, ASS tags, and subtitle structure stay in the correct place.

## Features

- Interactive CLI for normal users.
- External subtitle translation: `.srt`, `.ass`, `.ssa`, `.vtt`, `.webvtt`.
- Embedded subtitle extraction from video files with `ffprobe` + `ffmpeg`.
- **Bitmap/PGS subtitle OCR**: automatic OCR of image-based subtitles (PGS, VobSub) via `pgsrip`, then translation of the resulting text.
- **Batch folder mode** (`--folder`): process all video files in a directory in one command. Auto-picks single subtitle tracks; prompts when multiple exist.
- Manual embedded subtitle track selection.
- Translate from/to any language supported by the selected provider.
- ASS/SSA preservation: timing, styles, fields, and override tags are kept.
- SRT preservation: cue numbers and timestamps are kept.
- VTT/WebVTT input is converted to SRT output by default.
- Same-folder output using language suffix naming, e.g. `Episode 01.ar.ass`.
- Free/default provider via `deep-translator` for rough/testing translations with no API key.
- Recommended quality provider: OpenRouter/OpenAI/Gemini-style LLMs.
- Default OpenRouter model: `openai/gpt-4o-mini`.
- Requirement checker.
- Validation and smaller-chunk retry on failure.

## Requirements

- **Python 3.10+** — required to run the script.
- Python packages from `requirements.txt`:
  - `requests`
  - `deep-translator`
- **Required for embedded subtitle mode:**
  - `ffprobe`
  - `ffmpeg`
  - Install with the tool: `run-windows.bat --install-deps --yes`, or the OS command printed by `--check`.
- **Required for bitmap/PGS subtitle OCR:**
  - `pgsrip` — `pip install "pgsrip[rapidocr]"`
  - `mkvmerge` from MKVToolNix
- Optional but recommended for future robust MKV extraction:
  - `mkvextract` from MKVToolNix

## Install

### Windows quick start

If you are on Windows, read [`WINDOWS_QUICK_START.md`](WINDOWS_QUICK_START.md).

Fast path from PowerShell in this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
.\run-windows.bat --check
.\run-windows.bat
```

The `run-windows.bat` launcher tries `py -3` first, then `python`, so it avoids the common Microsoft Store `python was not found` problem.

### Manual install

First install Python 3.10+:

- Windows: <https://www.python.org/downloads/windows/> or `winget install Python.Python.3.11`
- macOS: <https://www.python.org/downloads/macos/> or `brew install python`
- Linux: use your distro package manager, e.g. `sudo apt install python3 python3-pip`

Then install Python packages:

```bash
python -m pip install -r requirements.txt
```

For embedded subtitles, install FFmpeg:

### Windows

```powershell
winget install Gyan.FFmpeg
winget install MoritzBunkus.MKVToolNix
```

### macOS

```bash
brew install ffmpeg mkvtoolnix
```

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install ffmpeg mkvtoolnix
```

`mkvextract` / MKVToolNix is optional for future robust MKV handling. v1 uses ffmpeg extraction.

## Running the tool

All examples below use `run-windows.bat`. On macOS/Linux, replace it with `python Nyx-AI-Translator.py` — all flags and arguments are the same.

## Check requirements

```bash
run-windows.bat --check
```

## Interactive use

```bash
run-windows.bat
```

Menu:

```text
[1] Embedded subtitle inside video
[2] External subtitle file
[3] Batch folder mode
[4] Settings / Providers
[5] Check requirements
[6] Exit
```

## External subtitle example

```bash
run-windows.bat --subtitle "Episode 01.en.srt" --from en --to ar --provider free
```

Output:

```text
Episode 01.ar.srt
```

## Embedded subtitle example

First check tracks interactively:

```bash
run-windows.bat
```

Or direct mode if you know the subtitle track index:

```bash
run-windows.bat --video "Episode 01.mkv" --track 0 --from en --to ar --provider free
```

Output:

```text
Episode 01.ar.ass
```

## Batch folder mode

Translate all video files in a folder at once. The tool scans each video for embedded subtitle tracks, auto-picks when there is a single track, and prompts if there are multiple.

```bash
run-windows.bat --folder "C:\Anime\Season 1" --from en --to ar --provider openrouter
```

Recursive mode (includes subfolders):

```bash
run-windows.bat --folder "C:\Anime" --from en --to ar --provider openrouter --recursive
```

Translated subtitles are saved next to each video file.

### Skip already-translated files

Batch mode automatically skips videos that already have a translated subtitle for the target language (e.g. `Episode 01.ar.srt`). To force re-translation, add `--overwrite`.

### Track selection strategy

When videos have multiple subtitle tracks, use `--track-strategy` to control how tracks are picked:

| Strategy | Behavior |
|---|---|
| `ask` | Prompt per video (default) |
| `first` | Always pick the first track |
| `lang:XX` | Pick the track matching language code XX, skip if no match |

Example — translate only English tracks unattended:

```bash
run-windows.bat --folder "C:\Anime" --from en --to ar --provider openrouter --track-strategy lang:eng
```

## Bitmap/PGS subtitle OCR

Blu-ray rips often use PGS (image-based) subtitles that cannot be extracted as text. Nyx-AI-Translator detects bitmap subtitle codecs (PGS, VobSub) and automatically uses `pgsrip` to OCR them into SRT text before translation.

Install the OCR dependencies:

```bash
pip install "pgsrip[rapidocr]"
```

Also install MKVToolNix (provides `mkvmerge`):

### Windows

```powershell
winget install MoritzBunkus.MKVToolNix
```

### macOS

```bash
brew install mkvtoolnix
```

### Ubuntu/Debian

```bash
sudo apt install mkvtoolnix
```

Then use normally — PGS tracks are handled automatically:

```bash
run-windows.bat --video "bluray-episode.mkv" --track 0 --from en --to ar --provider openrouter
```

## Provider configuration

Run the interactive settings menu:

```bash
run-windows.bat
```

Then choose:

```text
[3] Settings / Providers
```

Config is stored at:

- Windows: `%APPDATA%\\Nyx-AI-Translator\\config.json`
- macOS/Linux: `~/.config/nyx-ai-translator/config.json`

Environment variables override config:

```text
OPENROUTER_API_KEY
OPENAI_API_KEY
GEMINI_API_KEY
DEEPL_API_KEY
GOOGLE_TRANSLATE_API_KEY
AZURE_TRANSLATOR_KEY
AZURE_TRANSLATOR_ENDPOINT
AZURE_TRANSLATOR_REGION
OLLAMA_BASE_URL
NYX_TRANSLATOR_PROVIDER
NYX_TRANSLATOR_MODEL
```

## Provider notes

Default provider is `free`, using `deep-translator` GoogleTranslator with MyMemory fallback. It is useful for testing and quick rough translations, but it is **not publish-quality**, especially for Arabic subtitles with jokes, fantasy terms, or long ASS lines.

Recommended quality path:

- `openrouter` — easiest API-key workflow; recommended for real episodes.
- `openai` / `gemini` — good direct API options if you already use them.
- `ollama` / `custom_openai` — local or custom OpenAI-compatible servers; quality depends on the model.
- `deepl`, `google_cloud`, `azure` — stable machine-translation APIs, usually weaker than LLMs for subtitle context.
- `auto` — fallback testing only; for serious output pick one provider directly.

For Arabic output, the tool warns if likely untranslated English words remain, for example ordinary words like `evil`, `next`, or `during`. Proper nouns/acronyms can still be valid and may remain untranslated.

## Provider quality guide

| Provider | API key needed | Best for | Quality |
|---|---:|---|---|
| `free` | No | Testing, quick rough subtitles | Basic |
| `openrouter` | Yes | Real subtitle translation | Recommended |
| `openai` | Yes | High-quality subtitle translation | Recommended |
| `gemini` | Yes | High-quality subtitle translation | Recommended |
| `ollama` | Local server | Private/local workflows | Depends on model |
| `deepl` / `google_cloud` / `azure` | Yes | Stable machine translation | Good, less context-aware |

For publish-quality Arabic subtitles, use `openrouter`, `openai`, or `gemini`. The `free` provider is useful for testing but may produce awkward or literal translations.

AI/provider options:

- `openrouter`
- `openai`
- `gemini`
- `deepl`
- `google_cloud`
- `azure`
- `ollama`
- `custom_openai`
- `auto`

## Test

```bash
python -m pytest tests -q
```

## Status

v0.1.1 adds batch folder processing, bitmap/PGS subtitle OCR, and improved defaults. It has working parsers/rebuilders, provider plumbing, config, CLI, and batch mode. Next recommended work:

- Better provider integration testing with real API keys.
- Add mkvextract-first fallback for MKV subtitle extraction.
- Add more subtitle edge-case tests.
- Add optional translator note.

## License

MIT
