import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Nyx-AI-Translator.py"


def load_module():
    spec = importlib.util.spec_from_file_location("nyx_ai_translator", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_srt_roundtrip_translates_only_text_and_preserves_timing():
    nyx = load_module()
    source = """1\n00:00:01,000 --> 00:00:03,000\nHello, world!\n\n2\n00:00:04,000 --> 00:00:05,500\nHow are you?\n"""
    doc = nyx.parse_subtitle_text(source, ".srt")
    assert [u.text for u in doc.units] == ["Hello, world!", "How are you?"]

    rebuilt = nyx.rebuild_subtitle(doc, {doc.units[0].id: "مرحبا بالعالم!", doc.units[1].id: "كيف حالك؟"})

    assert "00:00:01,000 --> 00:00:03,000" in rebuilt
    assert "00:00:04,000 --> 00:00:05,500" in rebuilt
    assert "مرحبا بالعالم!" in rebuilt
    assert "كيف حالك؟" in rebuilt
    assert "Hello, world!" not in rebuilt


def test_ass_roundtrip_preserves_dialogue_shell_and_inline_tags():
    nyx = load_module()
    source = """[Script Info]\nTitle: Test\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour\nStyle: Default,Arial,20,&H00FFFFFF\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an8}Hello, {\\i1}friend{\\i0}!\n"""
    doc = nyx.parse_subtitle_text(source, ".ass")
    assert len(doc.units) == 1
    assert doc.units[0].text == "Hello, <TAG_2>friend<TAG_3>!"
    assert doc.units[0].tags["<TAG_1>"] == "{\\an8}"

    rebuilt = nyx.rebuild_subtitle(doc, {doc.units[0].id: "مرحبا، <TAG_2>صديقي<TAG_3>!"})

    assert "[Script Info]" in rebuilt
    assert "0:00:01.00,0:00:03.00,Default" in rebuilt
    assert "{\\an8}مرحبا، {\\i1}صديقي{\\i0}!" in rebuilt
    assert "Hello" not in rebuilt


def test_ass_control_sequences_are_protected_and_restored():
    nyx = load_module()
    source = """[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Come here\\Nnext month and stay\\hclose\n"""
    doc = nyx.parse_subtitle_text(source, ".ass")

    assert "\\N" not in doc.units[0].text
    assert "\\h" not in doc.units[0].text
    assert "<ASS_BREAK_" in doc.units[0].text

    rebuilt = nyx.rebuild_subtitle(doc, {doc.units[0].id: "تعال هنا<ASS_BREAK_1>الشهر القادم وابق<ASS_BREAK_2>قريبًا"})

    assert "تعال هنا\\Nالشهر القادم وابق\\hقريبًا" in rebuilt


def test_vtt_is_parsed_and_rebuilt_as_srt():
    nyx = load_module()
    source = """WEBVTT\n\n00:00:01.000 --> 00:00:03.000 line:90%\nHello there\n"""
    doc = nyx.parse_subtitle_text(source, ".vtt")
    assert doc.output_ext == ".srt"
    assert [u.text for u in doc.units] == ["Hello there"]

    rebuilt = nyx.rebuild_subtitle(doc, {doc.units[0].id: "أهلا"})
    assert "1\n00:00:01,000 --> 00:00:03,000\nأهلا" in rebuilt
    assert "WEBVTT" not in rebuilt


def test_validate_warns_on_suspicious_english_leftovers_for_arabic():
    nyx = load_module()
    source = """1\n00:00:01,000 --> 00:00:03,000\nHello\n"""
    doc = nyx.parse_subtitle_text(source, ".srt")
    output = nyx.rebuild_subtitle(doc, {doc.units[0].id: "هذا evil كبير"})

    result = nyx.validate_output(doc, output, target_language="ar")

    assert result.ok
    assert any("likely untranslated English words" in warning for warning in result.warnings)


def test_translate_units_uses_large_chunks_first_then_smaller_retry():
    nyx = load_module()
    units = [nyx.TranslationUnit(id=str(i), text="x" * 100, original_text="x" * 100) for i in range(40)]
    normal_chunks = nyx.chunk_units(units, max_chars=3500)
    smaller_chunks = nyx.chunk_units(units, max_chars=1800)

    assert len(normal_chunks) < len(smaller_chunks)


def test_output_path_uses_language_suffix_and_avoids_overwrite(tmp_path):
    nyx = load_module()
    src = tmp_path / "Episode 01.en.ass"
    src.write_text("dummy", encoding="utf-8")
    existing = tmp_path / "Episode 01.ar.ass"
    existing.write_text("existing", encoding="utf-8")

    out = nyx.make_output_path(src, "ar", ".ass", overwrite=False)

    assert out.name == "Episode 01.ar.2.ass"


def test_validate_rejects_empty_output_cues_when_source_has_text():
    nyx = load_module()
    source = """1\n00:00:01,000 --> 00:00:03,000\nHello\n\n2\n00:00:04,000 --> 00:00:05,000\nWorld\n\n3\n00:00:06,000 --> 00:00:07,000\nAgain\n"""
    doc = nyx.parse_subtitle_text(source, ".srt")
    bad = """1\n00:00:01,000 --> 00:00:03,000\nمرحبا\n\n2\n00:00:04,000 --> 00:00:05,000\n\n3\n00:00:06,000 --> 00:00:07,000\nمرة أخرى\n"""

    result = nyx.validate_output(doc, bad, target_language="ar")

    assert not result.ok
    assert any("empty translated cue/event(s)" in error for error in result.errors)


def test_validate_rejects_empty_or_missing_translations():
    nyx = load_module()
    source = """1\n00:00:01,000 --> 00:00:03,000\nHello\n"""
    doc = nyx.parse_subtitle_text(source, ".srt")
    bad = nyx.rebuild_subtitle(doc, {doc.units[0].id: ""})
    result = nyx.validate_output(doc, bad, target_language="ar")
    assert not result.ok


def test_interactive_embedded_scan_error_does_not_crash(tmp_path, monkeypatch, capsys):
    nyx = load_module()
    video = tmp_path / "demo.mkv"
    video.write_text("not a real video", encoding="utf-8")
    answers = iter(["1", str(video), "n", "6"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(nyx, "ffprobe_subtitle_tracks", lambda _video: (_ for _ in ()).throw(RuntimeError("ffprobe failed badly")))

    nyx.interactive(nyx.default_config())

    output = capsys.readouterr().out
    assert "Could not scan embedded subtitles" in output
    assert "ffprobe failed badly" in output


def test_find_executable_prefers_non_imagemagick_path(monkeypatch):
    nyx = load_module()
    monkeypatch.setattr(nyx.shutil, "which", lambda _name: r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\ffmpeg.EXE")

    class Result:
        returncode = 0
        stdout = "C:\\Program Files\\ImageMagick-7.1.1-Q16-HDRI\\ffmpeg.EXE\nC:\\Tools\\scoop\\shims\\ffmpeg.EXE\n"

    monkeypatch.setattr(nyx.subprocess, "run", lambda *args, **kwargs: Result())

    assert nyx.find_executable("ffmpeg") == r"C:\Tools\scoop\shims\ffmpeg.EXE"


def test_interactive_external_provider_error_does_not_crash(tmp_path, monkeypatch, capsys):
    nyx = load_module()
    sub = tmp_path / "demo.en.srt"
    sub.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    answers = iter(["2", str(sub), "en", "ar", "1", "6"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(nyx, "translate_subtitle_file", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("free provider exploded")))

    nyx.interactive(nyx.default_config())

    output = capsys.readouterr().out
    assert "External subtitle translation failed" in output
    assert "free provider exploded" in output


def test_translation_prompt_includes_arabic_quality_and_placeholder_rules():
    nyx = load_module()
    prompt = nyx.translation_prompt([nyx.TranslationUnit(id="1", text="Air <ASS_BREAK_1> Slash", original_text="")], "en", "ar")[0]["content"]
    assert "<ASS_BREAK_1>" in prompt and "translate all ordinary English words" in prompt
    assert "party as فريق/مجموعة" in prompt
    assert "Air Slash as ضربة هوائية" in prompt


def test_parse_json_mapping_repairs_invalid_backslash_escapes_from_llm():
    nyx = load_module()
    raw = r'''[
      {"id": "1", "text": "تعال هنا\Nالشهر القادم"},
      {"id": "2", "text": "ابق\hقريبًا"}
    ]'''

    parsed = nyx.parse_json_mapping(raw)

    assert parsed == {"1": r"تعال هنا\Nالشهر القادم", "2": r"ابق\hقريبًا"}


def test_free_provider_falls_back_to_mymemory_with_auto_source(monkeypatch):
    nyx = load_module()

    class BadGoogle:
        def __init__(self, source, target):
            self.source = source
            self.target = target
        def translate(self, text):
            raise RuntimeError("google down")

    class GoodMemory:
        seen_source = None
        def __init__(self, source, target):
            GoodMemory.seen_source = source
            self.target = target
        def translate(self, text):
            return "مرحبا"

    import types
    fake = types.ModuleType("deep_translator")
    fake.GoogleTranslator = BadGoogle
    fake.MyMemoryTranslator = GoodMemory
    monkeypatch.setitem(sys.modules, "deep_translator", fake)

    unit = nyx.TranslationUnit(id="1", text="Hello", original_text="Hello")
    assert nyx.translate_free([unit], "auto", "ar") == {"1": "مرحبا"}
    assert GoodMemory.seen_source == "en"


def test_translate_subtitle_file_reports_progress_before_provider_work(tmp_path, monkeypatch):
    nyx = load_module()
    sub = tmp_path / "demo.en.srt"
    sub.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    messages = []

    def fake_translate_units(units, source_language, target_language, provider, cfg, retry_smaller=True, progress=None):
        messages.append("provider-called")
        return {units[0].id: "مرحبا"}

    monkeypatch.setattr(nyx, "translate_units", fake_translate_units)

    nyx.translate_subtitle_file(sub, "en", "ar", "free", nyx.default_config(), overwrite=True, progress=messages.append)

    assert messages[0].startswith("Reading subtitle file")
    assert messages[1].startswith("Parsed 1 subtitle text unit")
    assert "Translating 1 subtitle text unit(s) with provider 'free'" in messages[2]
    assert messages[-1].startswith("Saved translated subtitle")


def test_free_provider_reports_per_line_progress(monkeypatch):
    nyx = load_module()
    seen = []

    class GoodGoogle:
        def __init__(self, source, target):
            pass
        def translate(self, text):
            return "مرحبا"

    class GoodMemory:
        def __init__(self, source, target):
            pass
        def translate(self, text):
            return "ذاكرة"

    import types
    fake = types.ModuleType("deep_translator")
    fake.GoogleTranslator = GoodGoogle
    fake.MyMemoryTranslator = GoodMemory
    monkeypatch.setitem(sys.modules, "deep_translator", fake)

    units = [nyx.TranslationUnit(id="1", text="Hello", original_text="Hello"), nyx.TranslationUnit(id="2", text="World", original_text="World")]
    result = nyx.translate_free(units, "en", "ar", progress=seen.append)

    assert result == {"1": "مرحبا", "2": "مرحبا"}
    assert seen == ["free provider: translated line 1/2", "free provider: translated line 2/2"]


def test_embedded_dependencies_report_ffprobe_and_ffmpeg_as_required(monkeypatch, capsys):
    nyx = load_module()
    monkeypatch.setattr(nyx, "find_executable", lambda _name: None)

    nyx.print_requirement_report()

    output = capsys.readouterr().out
    assert "ffprobe: missing REQUIRED for embedded mode" in output
    assert "ffmpeg: missing REQUIRED for embedded mode" in output
    assert "embedded subtitle (text): unavailable" in output or "embedded subtitle: unavailable" in output


def test_install_system_dependencies_installs_ffmpeg_with_winget(monkeypatch):
    nyx = load_module()
    calls = []

    class Result:
        returncode = 0
        stdout = "installed"
        stderr = ""

    monkeypatch.setattr(nyx.platform, "system", lambda: "Windows")
    monkeypatch.setattr(nyx, "find_executable", lambda name: "C:/Windows/System32/winget.exe" if name == "winget" else None)
    monkeypatch.setattr(nyx, "run_command", lambda args, timeout=120: calls.append(args) or Result())

    nyx.install_system_dependencies(assume_yes=True, include_optional=False)

    assert ["C:/Windows/System32/winget.exe", "install", "--id", "Gyan.FFmpeg", "-e"] in calls


def test_ensure_embedded_dependencies_raises_actionable_install_message(monkeypatch):
    nyx = load_module()
    monkeypatch.setattr(nyx, "find_executable", lambda _name: None)

    try:
        nyx.ensure_embedded_dependencies(offer_install=False)
    except RuntimeError as exc:
        msg = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "ffprobe" in msg
    assert "ffmpeg" in msg
    # Install hint is platform-specific (winget on Windows, apt on Linux)
    assert "ffmpeg" in msg.lower()


# --- skip-if-translated and track strategy tests ---


def test_translation_already_exists_finds_srt(tmp_path):
    nyx = load_module()
    video = tmp_path / "Episode 01.mkv"
    video.write_text("fake", encoding="utf-8")
    existing = tmp_path / "Episode 01.ar.srt"
    existing.write_text("1\n00:00:01,000 --> 00:00:02,000\nمرحبا\n", encoding="utf-8")

    result = nyx.translation_already_exists(video, "ar")
    assert result is not None
    assert result.name == "Episode 01.ar.srt"


def test_translation_already_exists_returns_none_when_missing(tmp_path):
    nyx = load_module()
    video = tmp_path / "Episode 01.mkv"
    video.write_text("fake", encoding="utf-8")

    result = nyx.translation_already_exists(video, "ar")
    assert result is None


def test_translation_already_exists_finds_failed_variant(tmp_path):
    nyx = load_module()
    video = tmp_path / "Episode 01.mkv"
    video.write_text("fake", encoding="utf-8")
    # Simulates validation-failed output: Episode 01.ar.failed.ass
    failed = tmp_path / "Episode 01.ar.failed.ass"
    failed.write_text("failed output", encoding="utf-8")

    result = nyx.translation_already_exists(video, "arabic")
    assert result is not None
    assert result.name == "Episode 01.ar.failed.ass"


def test_translation_already_exists_matches_alternate_codes(tmp_path):
    """'ar' and 'ara' should be treated as the same language."""
    nyx = load_module()
    video = tmp_path / "Episode 01.mkv"
    video.write_text("fake", encoding="utf-8")
    # First run used 'ara' (ISO 639-3)
    existing = tmp_path / "Episode 01.ara.srt"
    existing.write_text("subtitle", encoding="utf-8")

    # Second run uses 'ar' (ISO 639-1) — should still detect it
    result = nyx.translation_already_exists(video, "ar")
    assert result is not None
    assert result.name == "Episode 01.ara.srt"

    # And vice versa: file is .ar.ass, user passes 'ara'
    existing2 = tmp_path / "Episode 01.ar.ass"
    existing2.write_text("subtitle", encoding="utf-8")
    existing.unlink()  # remove the .ara.srt so only .ar.ass remains
    result2 = nyx.translation_already_exists(video, "ara")
    assert result2 is not None
    assert result2.name == "Episode 01.ar.ass"


def test_pick_subtitle_track_strategy_first():
    nyx = load_module()
    tracks = [
        {"subtitle_index": 0, "language": "eng", "codec": "subrip", "default": True, "forced": False, "title": "English"},
        {"subtitle_index": 1, "language": "jpn", "codec": "ass", "default": False, "forced": False, "title": "Japanese"},
    ]
    picked = nyx._pick_subtitle_track(tracks, "test.mkv", strategy="first")
    assert picked["language"] == "eng"


def test_pick_subtitle_track_strategy_lang_match():
    nyx = load_module()
    tracks = [
        {"subtitle_index": 0, "language": "eng", "codec": "subrip", "default": True, "forced": False, "title": "English"},
        {"subtitle_index": 1, "language": "jpn", "codec": "ass", "default": False, "forced": False, "title": "Japanese"},
    ]
    picked = nyx._pick_subtitle_track(tracks, "test.mkv", strategy="lang:jpn")
    assert picked["language"] == "jpn"


def test_pick_subtitle_track_strategy_lang_no_match():
    nyx = load_module()
    tracks = [
        {"subtitle_index": 0, "language": "eng", "codec": "subrip", "default": True, "forced": False, "title": "English"},
        {"subtitle_index": 1, "language": "jpn", "codec": "ass", "default": False, "forced": False, "title": "Japanese"},
    ]
    picked = nyx._pick_subtitle_track(tracks, "test.mkv", strategy="lang:kor")
    assert picked is None


def test_parse_json_mapping_repairs_trailing_comma():
    nyx = load_module()
    raw = '[{"id": "1", "text": "مرحبا"}, {"id": "2", "text": "وداعا"},]'
    parsed = nyx.parse_json_mapping(raw)
    assert parsed == {"1": "مرحبا", "2": "وداعا"}


def test_translate_units_retries_on_json_error(monkeypatch):
    """translate_units retries a chunk up to MAX_CHUNK_RETRIES on JSON errors."""
    nyx = load_module()
    import json as json_mod

    call_count = 0

    def flaky_chunk(units, src, tgt, prov, cfg, progress=None):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise json_mod.JSONDecodeError("Expecting ',' delimiter", "", 123)
        return {u.id: f"translated-{u.id}" for u in units}

    monkeypatch.setattr(nyx, "translate_chunk", flaky_chunk)

    units = [nyx.TranslationUnit(id="1", text="hello", original_text="hello")]
    result = nyx.translate_units(units, "en", "ar", "openrouter",
                                  {"general": {"default_provider": "openrouter"}})
    assert result == {"1": "translated-1"}
    assert call_count == 3  # failed twice, succeeded on third
