#!/usr/bin/env python3
"""Nyx-AI-Translator: structure-preserving AI subtitle translator.

Single-file v1 CLI. It extracts only subtitle text, translates that text, then
rebuilds the original subtitle timing/style shell.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

APP_NAME = "Nyx-AI-Translator"
VERSION = "0.1.1"
SUPPORTED_SUBTITLES = {".srt", ".ass", ".ssa", ".vtt", ".webvtt"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm"}
BITMAP_SUBTITLE_CODECS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub", "xsub"}
LANG_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,4})?$")
ASS_TAG_RE = re.compile(r"\{[^{}]*\}")
ASS_CONTROL_RE = re.compile(r"\\[Nnh]")
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
ENGLISH_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z']{2,}\b")
QUALITY_STOPWORDS = {
    "the", "and", "for", "you", "your", "are", "was", "were", "with", "that", "this", "from", "here", "next",
    "month", "during", "party", "evil", "slash", "skill", "send", "sends", "attack", "through", "air", "die",
    "earn", "conquered", "all", "get", "of", "to", "by", "in", "on", "at", "it", "is", "be", "have", "has",
}

LANGUAGE_ALIASES = {
    # Full names → ISO 639-1
    "arabic": "ar", "english": "en", "japanese": "ja", "korean": "ko",
    "french": "fr", "spanish": "es", "german": "de", "italian": "it",
    "portuguese": "pt", "turkish": "tr", "chinese": "zh", "russian": "ru",
    "hindi": "hi", "thai": "th", "vietnamese": "vi", "indonesian": "id",
    "malay": "ms", "persian": "fa", "farsi": "fa", "hebrew": "he",
    "polish": "pl", "dutch": "nl", "swedish": "sv", "norwegian": "no",
    "danish": "da", "finnish": "fi", "greek": "el", "czech": "cs",
    "romanian": "ro", "hungarian": "hu", "ukrainian": "uk", "bengali": "bn",
    "tamil": "ta", "urdu": "ur", "swahili": "sw", "filipino": "tl",
    "tagalog": "tl", "catalan": "ca", "croatian": "hr", "serbian": "sr",
    "slovak": "sk", "slovenian": "sl", "bulgarian": "bg", "latvian": "lv",
    "lithuanian": "lt", "estonian": "et", "icelandic": "is",
    # ISO 639-3 (3-letter) → ISO 639-1 (2-letter)
    "ara": "ar", "eng": "en", "jpn": "ja", "kor": "ko", "fra": "fr",
    "fre": "fr", "spa": "es", "deu": "de", "ger": "de", "ita": "it",
    "por": "pt", "tur": "tr", "zho": "zh", "chi": "zh", "rus": "ru",
    "hin": "hi", "tha": "th", "vie": "vi", "ind": "id", "msa": "ms",
    "may": "ms", "fas": "fa", "per": "fa", "heb": "he", "pol": "pl",
    "nld": "nl", "dut": "nl", "swe": "sv", "nor": "no", "dan": "da",
    "fin": "fi", "ell": "el", "gre": "el", "ces": "cs", "cze": "cs",
    "ron": "ro", "rum": "ro", "hun": "hu", "ukr": "uk", "ben": "bn",
    "tam": "ta", "urd": "ur", "swa": "sw", "fil": "tl", "tgl": "tl",
    "cat": "ca", "hrv": "hr", "srp": "sr", "slk": "sk", "slo": "sk",
    "slv": "sl", "bul": "bg", "lav": "lv", "lit": "lt", "est": "et",
    "isl": "is", "ice": "is",
    "auto": "auto",
}

OPENAI_COMPATIBLE_PROVIDERS = {"openrouter", "openai", "custom_openai"}


@dataclass
class TranslationUnit:
    id: str
    text: str
    original_text: str
    line_index: int | None = None
    cue_index: int | None = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class SubtitleDocument:
    format: str
    input_ext: str
    output_ext: str
    original_lines: list[str]
    units: list[TranslationUnit]
    cues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------- config ---------------------------------------

def config_dir() -> Path:
    if platform.system().lower() == "windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "nyx-ai-translator"


def config_path() -> Path:
    return config_dir() / "config.json"


def default_config() -> dict[str, Any]:
    return {
        "general": {
            "default_provider": "free",
            "default_quality": "balanced",
            "default_source_language": "auto",
            "overwrite_existing": False,
            "add_translator_note": False,
        },
        "providers": {
            "free": {"enabled": True, "provider": "deep-translator", "fallback_provider": "mymemory"},
            "openrouter": {"enabled": False, "api_key": "", "model": "openai/gpt-4o-mini", "base_url": "https://openrouter.ai/api/v1"},
            "openai": {"enabled": False, "api_key": "", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
            "gemini": {"enabled": False, "api_key": "", "model": "gemini-1.5-flash"},
            "deepl": {"enabled": False, "api_key": "", "endpoint": "https://api-free.deepl.com/v2/translate"},
            "google_cloud": {"enabled": False, "api_key": ""},
            "azure": {"enabled": False, "api_key": "", "endpoint": "", "region": ""},
            "ollama": {"enabled": False, "base_url": "http://localhost:11434", "model": "llama3.1"},
            "custom_openai": {"enabled": False, "api_key": "", "base_url": "", "model": ""},
        },
    }


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    p = config_path()
    cfg = default_config()
    if p.exists():
        try:
            cfg = deep_merge(cfg, json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    apply_env_overrides(cfg)
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_env_overrides(cfg: dict[str, Any]) -> None:
    mapping = {
        "OPENROUTER_API_KEY": ("openrouter", "api_key"),
        "OPENAI_API_KEY": ("openai", "api_key"),
        "GEMINI_API_KEY": ("gemini", "api_key"),
        "DEEPL_API_KEY": ("deepl", "api_key"),
        "GOOGLE_TRANSLATE_API_KEY": ("google_cloud", "api_key"),
        "AZURE_TRANSLATOR_KEY": ("azure", "api_key"),
        "AZURE_TRANSLATOR_ENDPOINT": ("azure", "endpoint"),
        "AZURE_TRANSLATOR_REGION": ("azure", "region"),
        "OLLAMA_BASE_URL": ("ollama", "base_url"),
    }
    for env, (provider, key) in mapping.items():
        if os.environ.get(env):
            cfg["providers"][provider][key] = os.environ[env]
            cfg["providers"][provider]["enabled"] = True
    if os.environ.get("NYX_TRANSLATOR_PROVIDER"):
        cfg["general"]["default_provider"] = os.environ["NYX_TRANSLATOR_PROVIDER"]
    if os.environ.get("NYX_TRANSLATOR_MODEL"):
        provider = cfg["general"].get("default_provider", "openrouter")
        cfg["providers"].setdefault(provider, {})["model"] = os.environ["NYX_TRANSLATOR_MODEL"]


# --------------------------- subtitle parsing -----------------------------

def normalize_language(value: str | None) -> str:
    if not value:
        return "auto"
    value = value.strip()
    return LANGUAGE_ALIASES.get(value.lower(), value)


def parse_subtitle_text(text: str, ext: str) -> SubtitleDocument:
    ext = ext.lower()
    if ext in {".ass", ".ssa"}:
        return parse_ass(text, ext)
    if ext == ".srt":
        return parse_srt(text, ext)
    if ext in {".vtt", ".webvtt"}:
        return parse_vtt(text, ext)
    raise ValueError(f"Unsupported subtitle format: {ext}")


def protect_ass_tags(text: str) -> tuple[str, dict[str, str]]:
    tags: dict[str, str] = {}
    counter = 1

    def repl(match: re.Match[str]) -> str:
        nonlocal counter
        key = f"<TAG_{counter}>"
        counter += 1
        tags[key] = match.group(0)
        return key

    protected = ASS_TAG_RE.sub(repl, text)

    def control_repl(match: re.Match[str]) -> str:
        nonlocal counter
        key = f"<ASS_BREAK_{counter}>"
        counter += 1
        tags[key] = match.group(0)
        return key

    protected = ASS_CONTROL_RE.sub(control_repl, protected)
    leading_keys: list[str] = []
    while True:
        m = re.match(r"^(<TAG_\d+>)", protected)
        if not m:
            break
        leading_keys.append(m.group(1))
        protected = protected[m.end():]
    if leading_keys:
        tags["__leading__"] = "".join(leading_keys)
    return protected, tags


def restore_tags(text: str, tags: dict[str, str]) -> str:
    leading_keys = re.findall(r"<TAG_\d+>", tags.get("__leading__", ""))
    for key, value in sorted(((k, v) for k, v in tags.items() if not k.startswith("__")), key=lambda kv: len(kv[0]), reverse=True):
        text = text.replace(key, value)
    leading = "".join(tags[key] for key in leading_keys if key in tags and tags[key] not in text)
    if leading:
        text = leading + text
    return text


def parse_ass_dialogue_text(line: str) -> tuple[str, str] | None:
    if not line.startswith("Dialogue:"):
        return None
    # ASS Dialogue has 10 fields; Text is field 10 and may contain commas.
    parts = line.split(",", 9)
    if len(parts) < 10:
        return None
    prefix = ",".join(parts[:9]) + ","
    return prefix, parts[9]


def parse_ass(text: str, ext: str) -> SubtitleDocument:
    lines = text.splitlines()
    units: list[TranslationUnit] = []
    for idx, line in enumerate(lines):
        parsed = parse_ass_dialogue_text(line)
        if not parsed:
            continue
        _prefix, dialogue_text = parsed
        clean, tags = protect_ass_tags(dialogue_text)
        if clean.strip():
            units.append(TranslationUnit(id=str(len(units) + 1), text=clean, original_text=dialogue_text, line_index=idx, tags=tags))
    return SubtitleDocument(format="ass", input_ext=ext, output_ext=".ass", original_lines=lines, units=units)


def srt_time_to_vtt(t: str) -> str:
    return t.replace(",", ".")


def vtt_time_to_srt(t: str) -> str:
    return t.split()[0].replace(".", ",")


def parse_srt_timestamp(line: str) -> tuple[str, str] | None:
    if "-->" not in line:
        return None
    start, end = line.split("-->", 1)
    return start.strip(), end.strip()


def parse_srt(text: str, ext: str) -> SubtitleDocument:
    blocks = re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")) if text.strip() else []
    units: list[TranslationUnit] = []
    cues: list[dict[str, Any]] = []
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        number = lines[0].strip() if lines[0].strip().isdigit() else str(len(cues) + 1)
        ts_idx = 1 if lines[0].strip().isdigit() and len(lines) > 1 else 0
        if ts_idx >= len(lines) or "-->" not in lines[ts_idx]:
            continue
        start, end = parse_srt_timestamp(lines[ts_idx]) or ("", "")
        cue_text = "\n".join(lines[ts_idx + 1:]).strip()
        unit_id = str(len(units) + 1)
        cues.append({"number": number, "start": start, "end": end, "unit_id": unit_id})
        units.append(TranslationUnit(id=unit_id, text=cue_text, original_text=cue_text, cue_index=len(cues) - 1))
    return SubtitleDocument(format="srt", input_ext=ext, output_ext=".srt", original_lines=text.splitlines(), units=units, cues=cues)


def parse_vtt(text: str, ext: str) -> SubtitleDocument:
    cleaned_lines: list[str] = []
    for raw in text.replace("\r\n", "\n").splitlines():
        line = raw.strip("\ufeff")
        if line.strip().upper() == "WEBVTT" or line.strip().startswith("NOTE"):
            continue
        cleaned_lines.append(raw)
    blocks = re.split(r"\n\s*\n", "\n".join(cleaned_lines).strip()) if "\n".join(cleaned_lines).strip() else []
    units: list[TranslationUnit] = []
    cues: list[dict[str, Any]] = []
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        ts_idx = 0
        if "-->" not in lines[0] and len(lines) > 1:
            ts_idx = 1
        if ts_idx >= len(lines) or "-->" not in lines[ts_idx]:
            continue
        start_raw, end_raw = lines[ts_idx].split("-->", 1)
        start = vtt_time_to_srt(start_raw.strip())
        end = vtt_time_to_srt(end_raw.strip())
        cue_text = "\n".join(lines[ts_idx + 1:]).strip()
        unit_id = str(len(units) + 1)
        cues.append({"number": str(len(cues) + 1), "start": start, "end": end, "unit_id": unit_id})
        units.append(TranslationUnit(id=unit_id, text=cue_text, original_text=cue_text, cue_index=len(cues) - 1))
    return SubtitleDocument(format="vtt", input_ext=ext, output_ext=".srt", original_lines=text.splitlines(), units=units, cues=cues)


def rebuild_subtitle(doc: SubtitleDocument, translations: dict[str, str]) -> str:
    if doc.format == "ass":
        lines = list(doc.original_lines)
        for unit in doc.units:
            translated = translations.get(unit.id, unit.original_text)
            translated = restore_tags(translated, unit.tags)
            if unit.line_index is None:
                continue
            parsed = parse_ass_dialogue_text(lines[unit.line_index])
            if not parsed:
                continue
            prefix, _old_text = parsed
            lines[unit.line_index] = prefix + translated
        return "\n".join(lines) + ("\n" if doc.original_lines else "")
    if doc.format in {"srt", "vtt"}:
        blocks: list[str] = []
        for cue in doc.cues:
            unit_id = cue["unit_id"]
            text = translations.get(unit_id, "")
            blocks.append(f"{cue['number']}\n{cue['start']} --> {cue['end']}\n{text}")
        return "\n\n".join(blocks) + ("\n" if blocks else "")
    raise ValueError(f"Unsupported doc format: {doc.format}")


# --------------------------- validation/output -----------------------------

def target_is_arabic(target_language: str) -> bool:
    lang = normalize_language(target_language).lower()
    return lang == "ar" or lang.startswith("ar-") or lang == "arabic"


def suspicious_english_leftovers(doc: SubtitleDocument, output_text: str) -> list[tuple[str, str, list[str]]]:
    """Return Arabic output lines that still contain likely untranslated English words.

    Proper nouns/acronyms can be legitimate in subtitles, so this intentionally
    focuses on common lowercase English words that should normally be translated.
    """
    try:
        parsed = parse_subtitle_text(output_text, doc.output_ext)
    except Exception:
        return []
    leftovers: list[tuple[str, str, list[str]]] = []
    for unit in parsed.units:
        text = re.sub(r"<TAG_\d+>|<ASS_BREAK_\d+>|\{[^{}]*\}", " ", unit.text)
        words = [w for w in ENGLISH_WORD_RE.findall(text) if w.lower() in QUALITY_STOPWORDS]
        if words:
            leftovers.append((unit.id, unit.text, sorted(set(words), key=str.lower)))
    return leftovers


def validate_output(doc: SubtitleDocument, output_text: str, target_language: str = "auto") -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if not output_text.strip():
        errors.append("output is empty")
    try:
        parsed = parse_subtitle_text(output_text, doc.output_ext)
    except Exception as exc:
        errors.append(f"output is not parseable as {doc.output_ext}: {exc}")
        parsed = None
    if parsed is not None and len(parsed.units) != len(doc.units):
        errors.append(f"cue/event count changed: input={len(doc.units)} output={len(parsed.units)}")
    if parsed is not None:
        empty_ids = [source_unit.id for source_unit, output_unit in zip(doc.units, parsed.units) if source_unit.text.strip() and not output_unit.text.strip()]
        if empty_ids:
            sample = ", ".join(empty_ids[:10])
            more = "..." if len(empty_ids) > 10 else ""
            errors.append(f"empty translated cue/event(s): {sample}{more}")
    if any(token in output_text for token in ["```", '"id"', "TRANSLATION_ERROR"]):
        warnings.append("output may contain provider/debug garbage")
    if target_is_arabic(target_language):
        if not ARABIC_RE.search(output_text):
            errors.append("target is Arabic but output has no Arabic characters")
        leftovers = suspicious_english_leftovers(doc, output_text)
        if leftovers:
            sample = "; ".join(f"#{unit_id}: {', '.join(words[:3])}" for unit_id, _text, words in leftovers[:5])
            warnings.append(f"Arabic quality warning: {len(leftovers)} subtitle line(s) still contain likely untranslated English words ({sample})")
    for unit in doc.units:
        # Empty translations are common hard failures.
        if unit.text.strip() and unit.id not in output_text and False:
            pass
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def strip_known_language_suffix(stem: str) -> str:
    parts = stem.split(".")
    if len(parts) > 1 and (LANG_CODE_RE.match(parts[-1]) or parts[-1].lower() in LANGUAGE_ALIASES):
        return ".".join(parts[:-1])
    return stem


def make_output_path(source: Path, target_language: str, output_ext: str, overwrite: bool = False) -> Path:
    code = normalize_language(target_language)
    stem = strip_known_language_suffix(source.stem)
    candidate = source.with_name(f"{stem}.{code}{output_ext}")
    if overwrite or not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = source.with_name(f"{stem}.{code}.{n}{output_ext}")
        if not candidate.exists():
            return candidate
        n += 1


def _language_code_variants(code: str) -> set[str]:
    """Return all known equivalent language codes for a given code.

    For example, 'ar' → {'ar', 'ara'}, 'ja' → {'ja', 'jpn'}, etc.
    This ensures we detect existing translations regardless of which
    code variant was used to create them.
    """
    code = code.lower()
    variants = {code}
    # Collect all aliases that map to the same normalized code
    normalized = LANGUAGE_ALIASES.get(code, code)
    variants.add(normalized)
    for alias, target in LANGUAGE_ALIASES.items():
        if target == normalized and len(alias) <= 3:  # only short codes, not full names
            variants.add(alias)
    return variants


def translation_already_exists(video: Path, target_language: str) -> Path | None:
    """Check if a translated subtitle already exists next to a video file.

    Looks for files like Episode.ar.srt, Episode.ara.ass, and also
    .failed and numbered variants. Handles mismatched language codes
    (ar vs ara) by checking all known equivalent codes.
    Returns the path if found, None otherwise.
    """
    code = normalize_language(target_language)
    stem = strip_known_language_suffix(video.stem)
    codes = _language_code_variants(code)
    # Build pattern matching any code variant, with optional .failed or .N suffix
    code_alt = "|".join(re.escape(c) for c in sorted(codes))
    pattern = re.compile(re.escape(stem) + r"\.(?:" + code_alt + r")(?:\.failed|\.\d+)?\.\w+$", re.IGNORECASE)
    for sibling in video.parent.iterdir():
        if sibling.is_file() and sibling.suffix.lower() in SUPPORTED_SUBTITLES and pattern.match(sibling.name):
            return sibling
    return None


# --------------------------- providers -------------------------------------

def chunk_units(units: list[TranslationUnit], max_chars: int = 3500) -> list[list[TranslationUnit]]:
    chunks: list[list[TranslationUnit]] = []
    current: list[TranslationUnit] = []
    size = 0
    for unit in units:
        add = len(unit.text) + 40
        if current and size + add > max_chars:
            chunks.append(current)
            current = []
            size = 0
        current.append(unit)
        size += add
    if current:
        chunks.append(current)
    return chunks


MAX_CHUNK_RETRIES = 3


def translate_units(units: list[TranslationUnit], source_language: str, target_language: str, provider: str, cfg: dict[str, Any], retry_smaller: bool = False, progress: Callable[[str], None] | None = None) -> dict[str, str]:
    provider = provider or cfg["general"].get("default_provider", "free")
    translations: dict[str, str] = {}
    max_chars = 1800 if retry_smaller else 3500
    chunks = chunk_units(units, max_chars=max_chars)
    for idx, chunk in enumerate(chunks, 1):
        if progress and len(chunks) > 1:
            progress(f"Translating chunk {idx}/{len(chunks)} ({len(chunk)} subtitle text units)")
        last_err: Exception | None = None
        for attempt in range(1, MAX_CHUNK_RETRIES + 1):
            try:
                translations.update(translate_chunk(chunk, source_language, target_language, provider, cfg, progress=progress))
                last_err = None
                break
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                last_err = exc
                if progress:
                    progress(f"  ⟳ Chunk {idx} attempt {attempt}/{MAX_CHUNK_RETRIES} failed ({type(exc).__name__}), retrying…")
        if last_err is not None:
            # Last resort: split the chunk in half and try each piece
            if len(chunk) > 1:
                mid = len(chunk) // 2
                if progress:
                    progress(f"  ⟳ Splitting chunk {idx} into two smaller pieces and retrying…")
                for half in (chunk[:mid], chunk[mid:]):
                    translations.update(translate_chunk(half, source_language, target_language, provider, cfg, progress=progress))
            else:
                raise RuntimeError(f"Chunk {idx} failed after {MAX_CHUNK_RETRIES} retries: {last_err}") from last_err
    return translations


def translate_chunk(units: list[TranslationUnit], source_language: str, target_language: str, provider: str, cfg: dict[str, Any], progress: Callable[[str], None] | None = None) -> dict[str, str]:
    if provider == "auto":
        for candidate in [cfg["general"].get("default_provider", "free"), "free", "openrouter", "openai", "gemini", "ollama"]:
            try:
                return translate_chunk(units, source_language, target_language, candidate, cfg, progress=progress)
            except Exception:
                continue
        raise RuntimeError("No provider succeeded")
    if provider == "free":
        return translate_free(units, source_language, target_language, progress=progress)
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return translate_openai_compatible(units, source_language, target_language, provider, cfg)
    if provider == "gemini":
        return translate_gemini(units, source_language, target_language, cfg)
    if provider == "deepl":
        return translate_deepl(units, source_language, target_language, cfg)
    if provider == "ollama":
        return translate_ollama(units, source_language, target_language, cfg)
    if provider == "google_cloud":
        return translate_google_cloud(units, source_language, target_language, cfg)
    if provider == "azure":
        return translate_azure(units, source_language, target_language, cfg)
    raise ValueError(f"Unsupported provider: {provider}")


def translate_free(units: list[TranslationUnit], source_language: str, target_language: str, progress: Callable[[str], None] | None = None) -> dict[str, str]:
    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator  # type: ignore
    except Exception as exc:
        raise RuntimeError("Free provider requires deep-translator. Install with: python -m pip install deep-translator") from exc
    src = normalize_language(source_language)
    dst = normalize_language(target_language)
    out: dict[str, str] = {}
    errors: list[str] = []
    total = len(units)
    for idx, unit in enumerate(units, 1):
        if not unit.text.strip():
            out[unit.id] = unit.text
            if progress:
                progress(f"free provider: skipped blank line {idx}/{total}")
            continue
        translated = None
        try:
            translated = GoogleTranslator(source="auto" if src == "auto" else src, target=dst).translate(unit.text)
        except Exception as exc:
            errors.append(f"GoogleTranslator failed for unit {unit.id}: {exc}")
        if not translated:
            try:
                # MyMemory does not reliably support source='auto'; English is a safer fallback for public v1.
                fallback_src = "en" if src == "auto" else src
                translated = MyMemoryTranslator(source=fallback_src, target=dst).translate(unit.text)
            except Exception as exc:
                errors.append(f"MyMemoryTranslator failed for unit {unit.id}: {exc}")
        if not translated:
            detail = errors[-1] if errors else "unknown free provider error"
            raise RuntimeError(f"Free provider failed while translating subtitle text. {detail}")
        out[unit.id] = translated
        if progress:
            progress(f"free provider: translated line {idx}/{total}")
    return out


def json_http(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 120) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user-configured provider URLs are intentional
        return json.loads(resp.read().decode("utf-8"))


def repair_invalid_json_escapes(text: str) -> str:
    """Escape non-JSON backslash sequences returned by LLMs.

    Models sometimes return subtitle text containing ASS markers like \\N or \\h
    inside JSON strings. Valid JSON only allows \" \\ / b f n r t u escapes, so
    json.loads raises "Invalid \\escape". Doubling only invalid backslashes keeps
    valid JSON escapes intact and lets us restore the intended subtitle text.
    """
    return re.sub(r"\\(?![\\\"/bfnrtu])", r"\\\\", text)


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences that LLMs sometimes wrap around JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _repair_json(text: str) -> str:
    """Apply progressively aggressive repairs for common LLM JSON mistakes."""
    # 1) Fix invalid backslash escapes (ASS markers like \N, \h)
    text = repair_invalid_json_escapes(text)
    # 2) Remove trailing commas before ] or }
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # 3) Strip control characters that break JSON (except \n \r \t)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def parse_json_mapping(text: str) -> dict[str, str]:
    text = _strip_json_fences(text)
    # Try strict parse first, then repaired parse
    for attempt, src in enumerate([text, _repair_json(text)]):
        try:
            data = json.loads(src)
            break
        except json.JSONDecodeError:
            if attempt == 1:
                raise
    if isinstance(data, list):
        return {str(item["id"]): str(item["text"]) for item in data}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    raise ValueError("provider returned unsupported JSON shape")


def translation_prompt(units: list[TranslationUnit], source_language: str, target_language: str) -> list[dict[str, str]]:
    payload = [{"id": u.id, "text": u.text} for u in units]
    system = (
        "You are a subtitle translation engine. Translate only the text values. "
        "Preserve placeholders like <TAG_1> and <ASS_BREAK_1> exactly. Return ONLY valid JSON as a list of objects "
        "with id and text. Do not add commentary. If the target language is Arabic, produce natural Arabic subtitles, "
        "translate all ordinary English words, and leave only true proper nouns, acronyms, model names, or brand names untranslated. "
        "For game/anime/fantasy subtitles, translate party as فريق/مجموعة (not حفلة), skill as مهارة, dungeon as زنزانة, "
        "Demon Lord as سيد الشياطين, Trial as تجربة/اختبار (not محاكمة unless it is a court trial), "
        "and Air Slash as ضربة هوائية or قَطعة هوائية. Keep Arabic phrasing concise for subtitle readability."
    )
    user = f"Source language: {source_language}\nTarget language: {target_language}\nTranslate all subtitle text:\n{json.dumps(payload, ensure_ascii=False)}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def translate_openai_compatible(units: list[TranslationUnit], source_language: str, target_language: str, provider: str, cfg: dict[str, Any]) -> dict[str, str]:
    pcfg = cfg["providers"][provider]
    api_key = pcfg.get("api_key", "")
    base_url = pcfg.get("base_url", "").rstrip("/")
    model = pcfg.get("model", "")
    if not api_key and provider != "custom_openai":
        raise RuntimeError(f"{provider} API key not configured")
    if not base_url or not model:
        raise RuntimeError(f"{provider} base_url/model not configured")
    response = json_http(
        f"{base_url}/chat/completions",
        {"model": model, "messages": translation_prompt(units, source_language, target_language), "temperature": 0.2},
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
    )
    content = response["choices"][0]["message"]["content"]
    return parse_json_mapping(content)


def translate_gemini(units: list[TranslationUnit], source_language: str, target_language: str, cfg: dict[str, Any]) -> dict[str, str]:
    pcfg = cfg["providers"]["gemini"]
    key = pcfg.get("api_key")
    model = pcfg.get("model", "gemini-1.5-flash")
    if not key:
        raise RuntimeError("Gemini API key not configured")
    prompt = "\n\n".join(m["content"] for m in translation_prompt(units, source_language, target_language))
    response = json_http(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}},
    )
    content = response["candidates"][0]["content"]["parts"][0]["text"]
    return parse_json_mapping(content)


def translate_deepl(units: list[TranslationUnit], source_language: str, target_language: str, cfg: dict[str, Any]) -> dict[str, str]:
    pcfg = cfg["providers"]["deepl"]
    key = pcfg.get("api_key")
    if not key:
        raise RuntimeError("DeepL API key not configured")
    import urllib.parse
    out = {}
    for unit in units:
        data = urllib.parse.urlencode({"auth_key": key, "text": unit.text, "target_lang": normalize_language(target_language).upper()}).encode()
        req = urllib.request.Request(pcfg.get("endpoint"), data=data, method="POST")
        with urllib.request.urlopen(req, timeout=90) as resp:
            js = json.loads(resp.read().decode("utf-8"))
        out[unit.id] = js["translations"][0]["text"]
    return out


def translate_ollama(units: list[TranslationUnit], source_language: str, target_language: str, cfg: dict[str, Any]) -> dict[str, str]:
    pcfg = cfg["providers"]["ollama"]
    base = pcfg.get("base_url", "http://localhost:11434").rstrip("/")
    model = pcfg.get("model", "llama3.1")
    messages = translation_prompt(units, source_language, target_language)
    response = json_http(f"{base}/api/chat", {"model": model, "messages": messages, "stream": False}, timeout=180)
    return parse_json_mapping(response["message"]["content"])


def translate_google_cloud(units: list[TranslationUnit], source_language: str, target_language: str, cfg: dict[str, Any]) -> dict[str, str]:
    key = cfg["providers"]["google_cloud"].get("api_key")
    if not key:
        raise RuntimeError("Google Cloud Translation API key not configured")
    texts = [u.text for u in units]
    payload = {"q": texts, "target": normalize_language(target_language), "format": "text"}
    if normalize_language(source_language) != "auto":
        payload["source"] = normalize_language(source_language)
    response = json_http(f"https://translation.googleapis.com/language/translate/v2?key={key}", payload)
    translated = response["data"]["translations"]
    return {u.id: translated[i]["translatedText"] for i, u in enumerate(units)}


def translate_azure(units: list[TranslationUnit], source_language: str, target_language: str, cfg: dict[str, Any]) -> dict[str, str]:
    pcfg = cfg["providers"]["azure"]
    key, endpoint, region = pcfg.get("api_key"), pcfg.get("endpoint"), pcfg.get("region")
    if not key or not endpoint or not region:
        raise RuntimeError("Azure key/endpoint/region not configured")
    params = f"api-version=3.0&to={normalize_language(target_language)}"
    if normalize_language(source_language) != "auto":
        params += f"&from={normalize_language(source_language)}"
    payload = [{"text": u.text} for u in units]
    response = json_http(
        endpoint.rstrip("/") + "/translate?" + params,
        payload,  # type: ignore[arg-type]
        headers={"Ocp-Apim-Subscription-Key": key, "Ocp-Apim-Subscription-Region": region},
    )
    return {u.id: response[i]["translations"][0]["text"] for i, u in enumerate(units)}


# --------------------------- video helpers --------------------------------

def find_executable(name: str) -> str | None:
    """Find a tool, preferring real media-tool installs over unrelated shims.

    On some Windows machines ImageMagick puts an ffmpeg.exe early in PATH. Prefer
    Scoop/normal FFmpeg paths when available so embedded extraction uses the
    expected binary.
    """
    candidates: list[str] = []
    path = shutil.which(name)
    if path:
        candidates.append(path)
    try:
        shell_cmd = ["where", name] if platform.system().lower() == "windows" else ["which", "-a", name]
        cp = subprocess.run(shell_cmd, capture_output=True, timeout=10, check=False,
                            text=True, encoding="utf-8", errors="replace")
        if cp.returncode == 0:
            candidates.extend([line.strip() for line in cp.stdout.splitlines() if line.strip()])
    except Exception:
        pass
    seen: set[str] = set()
    unique = []
    for candidate in candidates:
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    if not unique:
        return None
    non_imagemagick = [p for p in unique if "imagemagick" not in p.lower()]
    return non_imagemagick[0] if non_imagemagick else unique[0]


def run_command(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, timeout=timeout, check=False,
                          text=True, encoding="utf-8", errors="replace")


REQUIRED_EMBEDDED_TOOLS = ("ffprobe", "ffmpeg")
OPTIONAL_TOOLS = ("mkvextract",)


def system_dependency_commands(include_optional: bool = False) -> list[list[str]]:
    """Return install commands for required external binaries on this OS."""
    sysname = platform.system().lower()
    commands: list[list[str]] = []
    if sysname == "windows":
        winget = find_executable("winget") or "winget"
        commands.append([winget, "install", "--id", "Gyan.FFmpeg", "-e"])
        if include_optional:
            commands.append([winget, "install", "--id", "MoritzBunkus.MKVToolNix", "-e"])
    elif sysname == "darwin":
        brew = find_executable("brew") or "brew"
        commands.append([brew, "install", "ffmpeg"])
        if include_optional:
            commands.append([brew, "install", "mkvtoolnix"])
    else:
        # Debian/Ubuntu friendly default. Other Linux users can copy/adapt the printed command.
        commands.append(["sudo", "apt", "update"])
        commands.append(["sudo", "apt", "install", "-y", "ffmpeg"])
        if include_optional:
            commands.append(["sudo", "apt", "install", "-y", "mkvtoolnix"])
    return commands


def system_dependency_help(include_optional: bool = False) -> str:
    commands = system_dependency_commands(include_optional=include_optional)
    return "\n".join(" ".join(cmd) for cmd in commands)


def install_system_dependencies(assume_yes: bool = False, include_optional: bool = False) -> None:
    """Install required external binaries via the OS package manager when available."""
    commands = system_dependency_commands(include_optional=include_optional)
    print("External binary dependencies needed for embedded subtitle mode:")
    print("- ffprobe (required)")
    print("- ffmpeg  (required)")
    if include_optional:
        print("- mkvextract (optional, from MKVToolNix)")
    print("\nInstall commands:")
    for cmd in commands:
        print("  " + " ".join(cmd))
    if not assume_yes:
        answer = prompt("Run these install commands now?", "n").lower()
        if answer not in {"y", "yes"}:
            print("Install skipped.")
            return
    for cmd in commands:
        print("\nRunning: " + " ".join(cmd))
        cp = run_command(cmd, timeout=600)
        if cp.stdout.strip():
            print(cp.stdout.strip())
        if cp.stderr.strip():
            print(cp.stderr.strip())
        if cp.returncode != 0:
            raise RuntimeError(f"Install command failed ({cp.returncode}): {' '.join(cmd)}")
    print("\nInstall commands finished. Close/reopen PowerShell/Terminal so PATH updates apply, then run --check.")


def check_requirements() -> dict[str, Any]:
    tools = {name: find_executable(name) for name in [*REQUIRED_EMBEDDED_TOOLS, *OPTIONAL_TOOLS]}
    packages = {}
    for package in ["requests", "deep_translator"]:
        try:
            __import__(package)
            packages[package] = True
        except Exception:
            packages[package] = False
    return {"python": sys.version.split()[0], "python_ok": sys.version_info >= (3, 10), "tools": tools, "packages": packages}


def embedded_dependency_error(missing: list[str]) -> str:
    missing_text = ", ".join(missing)
    return (
        f"Embedded subtitle mode requires missing external tool(s): {missing_text}.\n"
        "Install FFmpeg/ffprobe, then close and reopen your terminal.\n\n"
        "Recommended command:\n"
        f"{system_dependency_help(include_optional=False)}"
    )


def ensure_embedded_dependencies(offer_install: bool = False) -> None:
    req = check_requirements()
    missing = [tool for tool in REQUIRED_EMBEDDED_TOOLS if not req["tools"].get(tool)]
    if not missing:
        return
    if offer_install:
        install_system_dependencies(assume_yes=False, include_optional=False)
        req = check_requirements()
        missing = [tool for tool in REQUIRED_EMBEDDED_TOOLS if not req["tools"].get(tool)]
        if not missing:
            return
    raise RuntimeError(embedded_dependency_error(missing))


def print_requirement_report() -> None:
    req = check_requirements()
    print(f"{APP_NAME} requirement check\n")
    print(f"Python: {req['python']} {'OK' if req['python_ok'] else 'missing/too old (requires 3.10+)'}")
    for pkg, ok in req["packages"].items():
        print(f"{pkg}: {'OK' if ok else 'missing'}")
    print()
    for tool in REQUIRED_EMBEDDED_TOOLS:
        path = req["tools"].get(tool)
        print(f"{tool}: {'OK - ' + path if path else 'missing REQUIRED for embedded mode'}")
    for tool in OPTIONAL_TOOLS:
        path = req["tools"].get(tool)
        print(f"{tool}: {'OK - ' + path if path else 'missing optional'}")
    pgsrip_path = shutil.which("pgsrip")
    print(f"pgsrip: {'OK - ' + pgsrip_path if pgsrip_path else 'missing (needed for bitmap/PGS subtitle OCR)'}")
    print("\nModes:")
    print("external subtitle: available")
    embedded_ok = all(req["tools"].get(tool) for tool in REQUIRED_EMBEDDED_TOOLS)
    print(f"embedded subtitle (text): {'available' if embedded_ok else 'unavailable (needs ffprobe + ffmpeg)'}")
    print(f"embedded subtitle (PGS/bitmap OCR): {'available' if pgsrip_path else 'unavailable — install with: pip install \"pgsrip[rapidocr]\"'}")
    if not embedded_ok:
        print("\nInstall embedded-mode dependencies:")
        print(system_dependency_help(include_optional=False))


def ffprobe_subtitle_tracks(video: Path) -> list[dict[str, Any]]:
    ffprobe = find_executable("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found")
    cp = run_command([ffprobe, "-v", "error", "-print_format", "json", "-show_streams", str(video)], timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "ffprobe failed")
    try:
        data = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON: {exc}") from exc
    tracks = []
    subtitle_ord = 0
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "subtitle":
            continue
        tags = stream.get("tags", {}) or {}
        disp = stream.get("disposition", {}) or {}
        tracks.append({
            "subtitle_index": subtitle_ord,
            "stream_index": stream.get("index"),
            "codec": stream.get("codec_name") or stream.get("codec_long_name") or "unknown",
            "language": tags.get("language", "und"),
            "title": tags.get("title", ""),
            "default": bool(disp.get("default")),
            "forced": bool(disp.get("forced")),
        })
        subtitle_ord += 1
    return tracks


def codec_to_ext(codec: str) -> str:
    c = (codec or "").lower()
    if "ass" in c or "ssa" in c:
        return ".ass"
    if "subrip" in c or "srt" in c:
        return ".srt"
    if "webvtt" in c or "vtt" in c:
        return ".vtt"
    return ".srt"


def extract_embedded_subtitle(video: Path, track: dict[str, Any], temp_dir: Path) -> Path:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    ext = codec_to_ext(track.get("codec", ""))
    out = temp_dir / f"{video.stem}.track{track['subtitle_index']}{ext}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    cp = run_command([ffmpeg, "-y", "-i", str(video), "-map", f"0:s:{track['subtitle_index']}", str(out)], timeout=180)
    if cp.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(cp.stderr.strip() or "ffmpeg subtitle extraction failed")
    return out


def is_bitmap_subtitle(track: dict[str, Any]) -> bool:
    """Return True if the track uses a bitmap/image-based subtitle codec (PGS, VobSub, etc.)."""
    codec = (track.get("codec") or "").lower()
    return codec in BITMAP_SUBTITLE_CODECS or "pgs" in codec or "dvd_sub" in codec


def find_pgsrip() -> str | None:
    """Return pgsrip executable path, or None if not installed."""
    return shutil.which("pgsrip")


def _find_srt_for_video(directory: Path, stem: str) -> list[Path]:
    """Find .srt files matching a video stem using plain string matching (not glob).

    Glob breaks on filenames with square brackets, so we iterate the
    directory and match with str.startswith() instead.
    """
    prefix = stem + "."
    results = []
    try:
        for f in directory.iterdir():
            if f.is_file() and f.suffix.lower() == ".srt" and f.name.startswith(prefix):
                results.append(f)
    except OSError:
        pass
    return sorted(results, key=lambda p: p.stat().st_mtime, reverse=True)


def ocr_bitmap_subtitle(video: Path, track: dict[str, Any], progress: Callable[[str], None] | None = None) -> Path:
    """Use pgsrip to OCR a bitmap subtitle track from a video file to SRT.

    pgsrip writes the .srt next to the video file. Returns the path to the generated SRT.
    """
    pgsrip = find_pgsrip()
    if not pgsrip:
        raise RuntimeError(
            "pgsrip is required for bitmap (PGS/VobSub) subtitles but was not found.\n"
            "Install it with:  pip install \"pgsrip[rapidocr]\"\n"
            "Also install MKVToolNix (mkvmerge). See: https://github.com/ratoaq2/pgsrip"
        )
    lang = track.get("language", "und")
    if progress:
        progress(f"Bitmap subtitle detected (codec={track.get('codec')}). Running OCR with pgsrip...")
    # Snapshot existing .srt files before running pgsrip so we can detect new ones
    parent = video.parent
    stem = video.stem
    existing_srts = {f for f in parent.iterdir() if f.is_file() and f.suffix.lower() == ".srt"}
    # pgsrip writes SRT next to the video, e.g. video.en.srt
    args = [pgsrip, "-l", lang, str(video)]
    cp = run_command(args, timeout=600)
    if cp.returncode != 0:
        stderr_msg = cp.stderr.strip() if cp.stderr else ""
        raise RuntimeError(f"pgsrip failed: {stderr_msg or 'unknown error'}")
    # Find the SRT that pgsrip created — uses plain string matching, not glob,
    # because filenames with brackets [] break glob patterns
    candidates = _find_srt_for_video(parent, stem)
    if not candidates:
        # Fallback: detect any brand-new .srt files that appeared after pgsrip ran
        current_srts = {f for f in parent.iterdir() if f.is_file() and f.suffix.lower() == ".srt"}
        new_srts = sorted((current_srts - existing_srts), key=lambda p: p.stat().st_mtime, reverse=True)
        if new_srts:
            candidates = new_srts
    if not candidates:
        # Last resort: check current working directory (pgsrip may write there instead)
        cwd = Path.cwd()
        if cwd != parent:
            candidates = _find_srt_for_video(cwd, stem)
    if not candidates:
        raise RuntimeError(f"pgsrip ran but no .srt file was found next to {video.name}")
    srt_path = candidates[0]
    if progress:
        progress(f"OCR complete: {srt_path.name}")
    return srt_path


# --------------------------- workflow --------------------------------------

def translate_subtitle_file(path: Path, source_language: str, target_language: str, provider: str, cfg: dict[str, Any], output_base: Path | None = None, overwrite: bool | None = None, progress: Callable[[str], None] | None = None) -> Path:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_SUBTITLES:
        raise ValueError(f"Unsupported subtitle file: {path}")
    if progress:
        progress(f"Reading subtitle file: {path}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    doc = parse_subtitle_text(text, ext)
    if progress:
        progress(f"Parsed {len(doc.units)} subtitle text unit(s) from {path.name}")
        progress(f"Translating {len(doc.units)} subtitle text unit(s) with provider '{provider}'")
    translations = translate_units(doc.units, source_language, target_language, provider, cfg, progress=progress)
    output = rebuild_subtitle(doc, translations)
    result = validate_output(doc, output, target_language)
    if not result.ok:
        if progress:
            progress("Validation failed; retrying with smaller chunks")
        translations = translate_units(doc.units, source_language, target_language, provider, cfg, retry_smaller=True, progress=progress)
        output = rebuild_subtitle(doc, translations)
        result = validate_output(doc, output, target_language)
    if progress and result.warnings:
        for warning in result.warnings:
            progress(f"Warning: {warning}")
    base = output_base or path
    out_path = make_output_path(base, target_language, doc.output_ext, overwrite=cfg["general"].get("overwrite_existing", False) if overwrite is None else overwrite)
    if not result.ok:
        out_path = out_path.with_suffix(f".failed{out_path.suffix}")
    out_path.write_text(output, encoding="utf-8")
    if progress:
        progress(f"Saved translated subtitle: {out_path}")
    if not result.ok:
        raise RuntimeError("Validation failed: " + "; ".join(result.errors) + f". Saved failed output: {out_path}")
    return out_path


def prompt(msg: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{msg}{suffix}: ").strip()
    return value if value else (default or "")


def choose_provider(cfg: dict[str, Any]) -> str:
    providers = ["free", "openrouter", "openai", "gemini", "deepl", "google_cloud", "azure", "ollama", "custom_openai", "auto"]
    print("\nChoose provider:")
    for i, p in enumerate(providers, 1):
        print(f"[{i}] {p}")
    choice = prompt("Choice", "1")
    try:
        return providers[int(choice) - 1]
    except Exception:
        return cfg["general"].get("default_provider", "free")


def configure_provider(cfg: dict[str, Any]) -> None:
    providers = ["openrouter", "openai", "gemini", "deepl", "google_cloud", "azure", "ollama", "custom_openai"]
    print("\nConfigure provider:")
    for i, p in enumerate(providers, 1):
        print(f"[{i}] {p}")
    choice = prompt("Choice")
    try:
        name = providers[int(choice) - 1]
    except Exception:
        return
    pcfg = cfg["providers"][name]
    if name == "ollama":
        pcfg["base_url"] = prompt("Ollama base URL", pcfg.get("base_url", "http://localhost:11434"))
        pcfg["model"] = prompt("Ollama model", pcfg.get("model", "llama3.1"))
    elif name == "custom_openai":
        pcfg["base_url"] = prompt("Base URL", pcfg.get("base_url", ""))
        pcfg["api_key"] = prompt("API key", pcfg.get("api_key", ""))
        pcfg["model"] = prompt("Model", pcfg.get("model", ""))
    elif name == "azure":
        pcfg["api_key"] = prompt("Azure key", pcfg.get("api_key", ""))
        pcfg["endpoint"] = prompt("Azure endpoint", pcfg.get("endpoint", ""))
        pcfg["region"] = prompt("Azure region", pcfg.get("region", ""))
    else:
        pcfg["api_key"] = prompt(f"{name} API key", pcfg.get("api_key", ""))
        if "model" in pcfg:
            pcfg["model"] = prompt("Model", pcfg.get("model", ""))
    pcfg["enabled"] = True
    save_config(cfg)
    print(f"Saved config: {config_path()}")


def settings_menu(cfg: dict[str, Any]) -> None:
    while True:
        print("\nProvider settings")
        for name, pcfg in cfg["providers"].items():
            configured = bool(pcfg.get("api_key") or name in {"free", "ollama"})
            print(f"- {name}: {'configured' if configured else 'not configured'}")
        print("\n[1] Add/update provider key")
        print("[2] Choose default provider")
        print("[3] Show config location")
        print("[4] Back")
        choice = prompt("Choice")
        if choice == "1":
            configure_provider(cfg)
        elif choice == "2":
            cfg["general"]["default_provider"] = choose_provider(cfg)
            save_config(cfg)
        elif choice == "3":
            print(config_path())
        elif choice == "4":
            return


def interactive(cfg: dict[str, Any]) -> None:
    while True:
        print(f"\n{APP_NAME} v{VERSION}\n")
        print("[1] Embedded subtitle inside video")
        print("[2] External subtitle file")
        print("[3] Batch folder mode")
        print("[4] Settings / Providers")
        print("[5] Check requirements")
        print("[6] Exit")
        choice = prompt("Choice")
        if choice == "1":
            video = Path(prompt("Enter video file path").strip().strip('"').strip("'"))
            if not video.exists():
                print("Video file not found.")
                continue
            try:
                ensure_embedded_dependencies(offer_install=False)
                tracks = ffprobe_subtitle_tracks(video)
            except Exception as exc:
                print(f"Could not scan embedded subtitles: {exc}")
                if "ffprobe" in str(exc).lower() or "ffmpeg" in str(exc).lower():
                    answer = prompt("Install ffprobe/ffmpeg now using your OS package manager?", "y").lower()
                    if answer in {"y", "yes"}:
                        try:
                            install_system_dependencies(assume_yes=True, include_optional=False)
                        except Exception as install_exc:
                            print(f"Dependency install failed: {install_exc}")
                print("Tip: run `.\\run-windows.bat --check` on Windows (or `py -3 Nyx-AI-Translator.py --check`) after install and reopening PowerShell.")
                continue
            if not tracks:
                print("No embedded subtitle tracks found.")
                continue
            print("\nFound embedded subtitle tracks:")
            for i, t in enumerate(tracks):
                print(f"[{i}] {t['language']} | {t['codec']} | default: {t['default']} | forced: {t['forced']} | title: {t['title']}")
            try:
                idx = int(prompt("Select subtitle track number"))
                if idx < 0 or idx >= len(tracks):
                    raise ValueError(f"track must be between 0 and {len(tracks) - 1}")
            except Exception as exc:
                print(f"Invalid subtitle track selection: {exc}")
                continue
            source = prompt("Source language", cfg["general"].get("default_source_language", "auto"))
            target = prompt("Target language")
            provider = choose_provider(cfg)
            tmp = Path(os.environ.get("TEMP", ".")) / "nyx-ai-translator"
            try:
                extracted = extract_embedded_subtitle(video, tracks[idx], tmp)
                out = translate_subtitle_file(extracted, source, target, provider, cfg, output_base=video, progress=lambda msg: print(msg, flush=True))
            except Exception as exc:
                print(f"Embedded subtitle translation failed: {exc}")
                continue
            print(f"\nDone:\n{out}")
        elif choice == "2":
            sub = Path(prompt("Enter subtitle file path").strip().strip('"').strip("'"))
            if not sub.exists():
                print("Subtitle file not found.")
                continue
            source = prompt("Source language", cfg["general"].get("default_source_language", "auto"))
            target = prompt("Target language")
            provider = choose_provider(cfg)
            try:
                out = translate_subtitle_file(sub, source, target, provider, cfg, progress=lambda msg: print(msg, flush=True))
            except Exception as exc:
                print(f"External subtitle translation failed: {exc}")
                continue
            print(f"\nDone:\n{out}")
        elif choice == "3":
            folder = Path(prompt("Enter folder path").strip().strip('"').strip("'"))
            if not folder.is_dir():
                print("Folder not found.")
                continue
            recursive_answer = prompt("Include subfolders? (recursive)", "n").lower()
            recursive = recursive_answer in {"y", "yes"}
            print("\nTrack selection when a video has multiple subtitle tracks:")
            print("  [1] Ask me per video (default)")
            print("  [2] Always pick the first track")
            print("  [3] Match by language code (e.g. en, ja)")
            strategy_choice = prompt("Track strategy", "1")
            if strategy_choice == "2":
                track_strategy = "first"
            elif strategy_choice == "3":
                lang_code = prompt("Language code to match (e.g. en, ja, es)")
                track_strategy = f"lang:{lang_code.strip().lower()}"
            else:
                track_strategy = "ask"
            source = prompt("Source language", cfg["general"].get("default_source_language", "auto"))
            target = prompt("Target language")
            provider = choose_provider(cfg)
            try:
                failed = process_folder(folder, source, target, provider, cfg,
                                        recursive=recursive, track_strategy=track_strategy)
                if failed:
                    print(f"\n{failed} file(s) failed — see output above for details.")
            except Exception as exc:
                print(f"Batch folder translation failed: {exc}")
                continue
        elif choice == "4":
            settings_menu(cfg)
        elif choice == "5":
            print_requirement_report()
        elif choice == "6":
            return


def install_requirements_prompt() -> None:
    print_requirement_report()
    print("\nEmbedded subtitle mode requires external binaries: ffprobe and ffmpeg.")
    print("This tool does not bundle binaries, but it can install them with your OS package manager.")
    print("\nRequired embedded-mode install command:")
    print(system_dependency_help(include_optional=False))
    print("\nOptional MKVToolNix/mkvextract command:")
    print(system_dependency_help(include_optional=True))
    print("\nPython package command:")
    print("py -3 -m pip install -r requirements.txt" if platform.system().lower() == "windows" else "python -m pip install -r requirements.txt")
    print("\nTo run installer from this tool:")
    print("py -3 Nyx-AI-Translator.py --install-deps --yes" if platform.system().lower() == "windows" else "python Nyx-AI-Translator.py --install-deps --yes")


def _format_track_choice(track: dict[str, Any]) -> str:
    """Format a subtitle track dict as a human-readable label for selection."""
    parts = [f"#{track['subtitle_index']}"]
    parts.append(f"lang={track['language']}")
    if track.get("title"):
        parts.append(f'"{track["title"]}"')
    parts.append(f"codec={track['codec']}")
    flags = []
    if track.get("default"):
        flags.append("default")
    if track.get("forced"):
        flags.append("forced")
    if is_bitmap_subtitle(track):
        flags.append("bitmap/PGS — needs OCR")
    if flags:
        parts.append(f"[{', '.join(flags)}]")
    return " ".join(parts)


def _pick_subtitle_track(tracks: list[dict[str, Any]], video_name: str,
                         strategy: str = "ask") -> dict[str, Any] | None:
    """Pick a subtitle track based on strategy.

    Strategies:
      - 'ask'      : auto-pick if one track, prompt if multiple (default)
      - 'first'    : always pick the first track
      - 'lang:XX'  : pick the track matching language XX, skip if no match
    """
    if not tracks:
        return None
    if len(tracks) == 1:
        return tracks[0]

    # Strategy: first — always pick index 0
    if strategy == "first":
        return tracks[0]

    # Strategy: lang:XX — match by language code
    if strategy.startswith("lang:"):
        target_lang = strategy.split(":", 1)[1].strip().lower()
        for t in tracks:
            if t.get("language", "").lower() == target_lang:
                return t
        # No match — skip this video
        print(f"  ⊘ No track matching language '{target_lang}' — skipping", file=sys.stderr)
        return None

    # Strategy: ask — prompt the user
    print(f"\n  Subtitle tracks in {video_name}:", file=sys.stderr)
    for t in tracks:
        print(f"    [{t['subtitle_index']}] {_format_track_choice(t)}", file=sys.stderr)
    while True:
        try:
            choice = input(f"  Pick track for {video_name} (0-{len(tracks)-1}, or 's' to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if choice.lower() == "s":
            return None
        try:
            idx = int(choice)
            if 0 <= idx < len(tracks):
                return tracks[idx]
        except ValueError:
            pass
        print(f"  Invalid choice. Enter 0-{len(tracks)-1} or 's' to skip.", file=sys.stderr)


def process_folder(folder: Path, source_language: str, target_language: str,
                   provider: str, cfg: dict[str, Any], overwrite: bool = False,
                   recursive: bool = False, track_strategy: str = "ask") -> int:
    """Process all video files in a folder, extracting and translating embedded subtitles.

    Returns the number of files that failed (0 = all succeeded).
    """
    ensure_embedded_dependencies(offer_install=False)

    # Collect video files
    if recursive:
        videos = sorted(f for f in folder.rglob("*") if f.suffix.lower() in VIDEO_EXTENSIONS and f.is_file())
    else:
        videos = sorted(f for f in folder.iterdir() if f.suffix.lower() in VIDEO_EXTENSIONS and f.is_file())

    if not videos:
        print(f"No video files found in {folder}", file=sys.stderr)
        return 0

    print(f"\nFound {len(videos)} video file(s) in {folder}\n", file=sys.stderr)

    tmp = Path(os.environ.get("TEMP", ".")) / "nyx-ai-translator"
    succeeded = 0
    failed = 0
    skipped = 0
    progress = lambda msg: print(f"  {msg}", file=sys.stderr, flush=True)

    for i, video in enumerate(videos, 1):
        header = f"[{i}/{len(videos)}] {video.name}"
        print(f"{header}", file=sys.stderr)
        print(f"{'─' * len(header)}", file=sys.stderr)

        if not overwrite:
            existing = translation_already_exists(video, target_language)
            if existing:
                print(f"  ⊘ Already translated → {existing.name} (use --overwrite to redo)", file=sys.stderr)
                skipped += 1
                continue

        try:
            tracks = ffprobe_subtitle_tracks(video)
        except Exception as exc:
            print(f"  ✗ Could not read tracks: {exc}", file=sys.stderr)
            failed += 1
            continue

        if not tracks:
            print(f"  ✗ No subtitle tracks found — skipping", file=sys.stderr)
            skipped += 1
            continue

        track = _pick_subtitle_track(tracks, video.name, strategy=track_strategy)
        if track is None:
            print(f"  ⊘ Skipped", file=sys.stderr)
            skipped += 1
            continue

        print(f"  Using track {_format_track_choice(track)}", file=sys.stderr)

        try:
            if is_bitmap_subtitle(track):
                # PGS/VobSub — OCR to SRT first, then translate the SRT
                srt_path = ocr_bitmap_subtitle(video, track, progress=progress)
                out = translate_subtitle_file(
                    srt_path, source_language, target_language, provider, cfg,
                    output_base=video, overwrite=overwrite, progress=progress,
                )
            else:
                # Text subtitle — extract with ffmpeg and translate directly
                extracted = extract_embedded_subtitle(video, track, tmp)
                out = translate_subtitle_file(
                    extracted, source_language, target_language, provider, cfg,
                    output_base=video, overwrite=overwrite, progress=progress,
                )
            print(f"  ✓ {out}", file=sys.stderr)
            print(out)
            succeeded += 1
        except Exception as exc:
            print(f"  ✗ Failed: {exc}", file=sys.stderr)
            failed += 1

        print(file=sys.stderr)

    # Summary
    print(f"\n{'═' * 40}", file=sys.stderr)
    print(f"Batch complete: {succeeded} translated, {skipped} skipped, {failed} failed out of {len(videos)} video(s)", file=sys.stderr)
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Structure-preserving AI subtitle translator")
    parser.add_argument("setup", nargs="?", help="Use 'setup' to show setup/install help")
    parser.add_argument("--check", action="store_true", help="Check requirements")
    parser.add_argument("--install-deps", action="store_true", help="Install required external deps for embedded mode: ffprobe/ffmpeg")
    parser.add_argument("--install-optional-deps", action="store_true", help="Also install optional MKVToolNix/mkvextract when used with --install-deps")
    parser.add_argument("--yes", action="store_true", help="Do not prompt during dependency install")
    parser.add_argument("--subtitle", help="External subtitle path")
    parser.add_argument("--video", help="Video path for embedded subtitle mode")
    parser.add_argument("--folder", help="Folder path for batch embedded subtitle translation of all video files")
    parser.add_argument("--recursive", action="store_true", help="Include subfolders when using --folder")
    parser.add_argument("--track", type=int, help="Embedded subtitle track number from subtitle stream list")
    parser.add_argument("--track-strategy", default="ask",
                        help="Track selection for batch mode: 'ask' (prompt per video, default), 'first' (always pick first track), 'lang:XX' (pick track matching language code, e.g. lang:en)")
    parser.add_argument("--from", dest="source_language", default="auto", help="Source language code/name")
    parser.add_argument("--to", dest="target_language", help="Target language code/name")
    parser.add_argument("--provider", default=None, help="Provider: free/openrouter/openai/gemini/deepl/google_cloud/azure/ollama/custom_openai/auto")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output")
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.setup == "setup":
        install_requirements_prompt()
        return 0
    if args.install_deps:
        install_system_dependencies(assume_yes=args.yes, include_optional=args.install_optional_deps)
        return 0
    if args.check:
        print_requirement_report()
        return 0
    provider = args.provider or cfg["general"].get("default_provider", "free")
    if args.subtitle:
        if not args.target_language:
            raise SystemExit("--to is required with --subtitle")
        try:
            out = translate_subtitle_file(Path(args.subtitle), args.source_language, args.target_language, provider, cfg, overwrite=args.overwrite, progress=lambda msg: print(msg, file=sys.stderr, flush=True))
        except Exception as exc:
            print(f"External subtitle translation failed: {exc}", file=sys.stderr)
            print("Tip: run `python Nyx-AI-Translator.py --check` and install missing requirements from README/WINDOWS_QUICK_START.md.", file=sys.stderr)
            return 1
        print(out)
        return 0
    if args.video:
        if args.track is None or not args.target_language:
            raise SystemExit("--video requires --track and --to")
        try:
            video = Path(args.video)
            ensure_embedded_dependencies(offer_install=False)
            tracks = ffprobe_subtitle_tracks(video)
            if args.track < 0 or args.track >= len(tracks):
                raise ValueError(f"track must be between 0 and {len(tracks) - 1}")
            progress_fn = lambda msg: print(msg, file=sys.stderr, flush=True)
            selected_track = tracks[args.track]
            if is_bitmap_subtitle(selected_track):
                srt_path = ocr_bitmap_subtitle(video, selected_track, progress=progress_fn)
                out = translate_subtitle_file(srt_path, args.source_language, args.target_language, provider, cfg, output_base=video, overwrite=args.overwrite, progress=progress_fn)
            else:
                tmp = Path(os.environ.get("TEMP", ".")) / "nyx-ai-translator"
                extracted = extract_embedded_subtitle(video, selected_track, tmp)
                out = translate_subtitle_file(extracted, args.source_language, args.target_language, provider, cfg, output_base=video, overwrite=args.overwrite, progress=progress_fn)
        except Exception as exc:
            print(f"Embedded subtitle translation failed: {exc}", file=sys.stderr)
            print("Tip: run `.\\run-windows.bat --check` on Windows (or `python Nyx-AI-Translator.py --check`) and install missing requirements from README/WINDOWS_QUICK_START.md.", file=sys.stderr)
            return 1
        print(out)
        return 0
    if args.folder:
        if not args.target_language:
            raise SystemExit("--to is required with --folder")
        folder = Path(args.folder)
        if not folder.is_dir():
            raise SystemExit(f"Not a directory: {folder}")
        failures = process_folder(
            folder, args.source_language, args.target_language,
            provider, cfg, overwrite=args.overwrite, recursive=args.recursive,
            track_strategy=args.track_strategy,
        )
        return 1 if failures else 0
    interactive(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
