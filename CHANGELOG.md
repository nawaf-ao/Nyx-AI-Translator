# Changelog

## v0.1.1

### New features

- **Batch folder mode** (`--folder`): process all video files in a directory with one command.
  - `--recursive` flag to include subfolders.
  - Auto-picks subtitle track when only one exists; prompts when multiple are found.
  - **Skip-if-translated**: automatically skips videos that already have a translated subtitle file for the target language. Use `--overwrite` to force re-translation.
  - **Track selection strategy** (`--track-strategy`): control how tracks are picked when videos have multiple subtitles — `ask` (prompt per video, default), `first` (always pick the first track), or `lang:XX` (match by language code, e.g. `lang:en`).
  - Progress display: per-file status, track info, and a summary at the end.
- **Batch folder mode in interactive CLI**: new menu option [3] for folder translation without CLI flags.
- **Bitmap/PGS subtitle OCR**: automatic detection and OCR of image-based subtitle codecs (PGS, VobSub, DVD subtitles) using `pgsrip`.
  - Works seamlessly in both `--video` and `--folder` modes.
  - Detects codecs: `hdmv_pgs_subtitle`, `pgssub`, `dvd_subtitle`, `dvdsub`, `xsub`.
  - Requires `pgsrip` (`pip install "pgsrip[rapidocr]"`) and MKVToolNix.
- Default OpenRouter model: `openai/gpt-4o-mini`.
- Requirement checker (`--check`) now reports `pgsrip` status and bitmap OCR availability.

### Internal

- Added `BITMAP_SUBTITLE_CODECS` constant for codec detection.
- Added helper functions: `is_bitmap_subtitle()`, `find_pgsrip()`, `_find_srt_for_video()`, `ocr_bitmap_subtitle()`, `_format_track_choice()`, `_pick_subtitle_track()`, `process_folder()`.
- Version bumped to 0.1.1.

## v0.1.0

- Initial release. Single-file CLI with structure-preserving subtitle translation.
- Supported formats: SRT, ASS/SSA, VTT/WebVTT.
- Providers: free (deep-translator), OpenRouter, OpenAI, Gemini, DeepL, Google Cloud, Azure, Ollama, custom OpenAI.
- Embedded subtitle extraction via ffprobe + ffmpeg.
- Interactive CLI and direct CLI modes.
- Config persistence, environment variable overrides.
- Arabic quality validation with English-word warnings.
- Validation with smaller-chunk retry on failure.
