"""WP-Z1: the Chinese script converter (app/zh_script.py) and its table builder.

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md. What these pin down:

- the conversions a learner actually meets, in both directions, on real text (§7);
- LENGTH PRESERVATION (I3) on every fixture. The tokenizer's segment-in-Simplified trick and the
  report's deep links both index the converted text with offsets from the original, so one
  length-changing mapping would silently shift every token after it;
- "asis" is a true no-op returning the very same string (I2);
- Traditional goes through Simplified, so a word lands on ONE spelling whichever script it came from;
- the tables stay lazy (I4) and a missing table degrades to "read as written" instead of crashing;
- the build script drops and counts unequal-length entries and emits a module that decodes.
"""

import os
import subprocess
import sys
import time
import importlib.util

import pytest

from app import zh_script

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = ("chinese_text_1.txt", "context_test.txt", "traditional_news.txt",
            "mixed_script_transcript.txt")


def _read(zh_resources_dir, name):
    with open(os.path.join(zh_resources_dir, name), encoding="utf-8") as f:
        return f.read()


# ---- conversions ------------------------------------------------------------------------------ #

@pytest.mark.parametrize("simplified, traditional", [
    ("学习", "學習"),
    ("这个", "這個"),
    ("头发", "頭髮"),      # 发 is 髮 here...
    ("发现", "發現"),      # ...and 發 here: the context pass has to pick between them
    ("干净", "乾淨"),      # 干 has three Traditional forms (乾 / 幹 / 干)
    ("后来", "後來"),
    ("经济关系", "經濟關係"),
])
def test_known_pairs_convert_both_ways(simplified, traditional):
    assert zh_script.convert(simplified, "t") == traditional
    assert zh_script.convert(traditional, "s") == simplified


def test_shared_characters_keep_their_traditional_meaning():
    """里 and 准 are ordinary Traditional characters too (里長 = village chief, 准許 = permit). Read
    straight from the Traditional original, OpenCC's Simplified phrase keys never matched them and
    they were "corrected" into 裏長 / 準許. Going through Simplified gives the phrases their context."""
    assert zh_script.convert("一位里長說", "t") == "一位里長說"
    assert zh_script.convert("希望政府准許延長", "t") == "希望政府准許延長"


def test_a_word_from_either_script_lands_on_one_spelling(zh_resources_dir):
    """The whole point of the setting: the transcript writes 牛肉麵 in a Traditional line and 牛肉面 in
    a Simplified one. Both must come out identical in each target script, or they count as two words."""
    text = _read(zh_resources_dir, "mixed_script_transcript.txt")
    assert "牛肉麵" in text and "牛肉面" in text
    for script in ("s", "t"):
        out = zh_script.convert(text, script)
        variants = {out[i:i + 3] for i in range(len(text)) if text[i:i + 3] in ("牛肉麵", "牛肉面")}
        assert len(variants) == 1, f"{script}: {variants}"


def test_non_chinese_text_passes_through_untouched():
    """Kana, Latin, digits, punctuation and CRLF line ends are not OpenCC's business."""
    text = "ラーメン ramen 2026年\r\n牛肉面。\r\n"
    out = zh_script.convert(text, "t")
    assert out == "ラーメン ramen 2026年\r\n牛肉麪。\r\n"


def test_empty_text_is_returned_as_is():
    assert zh_script.convert("", "t") == ""
    assert zh_script.convert("", "s") == ""


def test_asis_returns_the_very_same_string(zh_resources_dir):
    """I2: as-is must cost nothing and change nothing — not even produce an equal copy."""
    text = _read(zh_resources_dir, "chinese_text_1.txt")
    assert zh_script.convert(text, "asis") is text
    assert zh_script.convert(text, "bogus") is text      # a hand-edited setting reads as as-is


@pytest.mark.parametrize("script", ["s", "t"])
@pytest.mark.parametrize("name", FIXTURES)
def test_every_fixture_keeps_its_length_and_converting_twice_changes_nothing(zh_resources_dir,
                                                                             name, script):
    """I3 on real files, plus idempotence: known words are converted on their own and must agree with
    content converted inside the tokenizer, so a second pass may not move anything."""
    text = _read(zh_resources_dir, name)
    once = zh_script.convert(text, script)
    assert len(once) == len(text)
    assert zh_script.convert(once, script) == once


@pytest.mark.parametrize("language, script, expected", [
    ("zh", "s", "s"),
    ("zh", "t", "t"),
    ("zh", "asis", "asis"),
    ("zh", None, "asis"),          # key missing from an older settings.json
    ("zh", "tw", "asis"),          # a value this version doesn't know
    ("ja", "t", "asis"),           # the setting belongs to Chinese; a Japanese run never converts
])
def test_effective_script(language, script, expected):
    assert zh_script.effective(language, script) == expected


def test_missing_tables_degrade_to_reading_text_as_written(monkeypatch):
    """A build that lost the generated module must still analyse — unconverted, never crashed."""
    import app
    monkeypatch.setattr(zh_script, "_converters", {})
    # Both halves, or `from app import zh_script_data` still finds the already-imported attribute.
    monkeypatch.setitem(sys.modules, "app.zh_script_data", None)    # import now raises ImportError
    monkeypatch.delattr(app, "zh_script_data", raising=False)
    assert zh_script.convert("学习头发", "t") == "学习头发"
    assert zh_script.convert("學習頭髮", "s") == "學習頭髮"


def test_conversion_speed(zh_resources_dir):
    """Target ≥ 5 MB/s (measured ~9 MB/s to Traditional). The bound is generous so a busy machine
    can't fail it; a real regression — the phrase pass going quadratic — is orders slower."""
    text = _read(zh_resources_dir, "chinese_text_1.txt") * 100
    zh_script.convert("学习", "t")                                    # decode outside the timing
    start = time.perf_counter()
    zh_script.convert(text, "t")
    rate = len(text.encode("utf-8")) / (time.perf_counter() - start) / 1e6
    assert rate >= 1.0, f"{rate:.2f} MB/s"


# ---- laziness (I4) ---------------------------------------------------------------------------- #

def _loaded_after(code):
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT, "PYTHONIOENCODING": "utf-8"}
    probe = code + "; import sys; print('app.zh_script_data' in sys.modules)"
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip() == "True"


def test_importing_the_analyzer_does_not_load_the_tables():
    """A 'nothing changed' Generate imports the analyzer and nothing else; 170 KB of tables must
    not ride along."""
    assert not _loaded_after("import app.analyzer, app.zh_script")


def test_asis_tokenizing_never_loads_the_tables():
    assert not _loaded_after(
        "import app.analyzer as a; list(a.ChineseTokenizer().tokenize_sentences('冒险。'))")


# ---- the build script ------------------------------------------------------------------------- #

def _load_build_script():
    path = os.path.join(PROJECT_ROOT, "scripts", "build_zh_script_data.py")
    spec = importlib.util.spec_from_file_location("build_zh_script_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_script_drops_unequal_length_entries_and_writes_a_decodable_module(tmp_path, capsys):
    """Real OpenCC lines. `U盘 隨身碟` is a real Taiwan-phrasing entry whose target is longer than its
    key; it has to be dropped (and counted) or every offset after it shifts (I3). `一个` converts the
    same character by character, so it carries no information and is omitted."""
    src = tmp_path / "opencc"
    src.mkdir()
    (src / "SOURCE_TAG.txt").write_text("ver.test\n", encoding="utf-8")
    (src / "STCharacters.txt").write_text(
        "# Format: key\tvalue(s)\n个\t個\n发\t發 髮\n头\t頭\n", encoding="utf-8")
    (src / "STPhrases.txt").write_text(
        "一个\t一個\n头发\t頭髮\nU盘\t隨身碟\n", encoding="utf-8")
    (src / "TSCharacters.txt").write_text("個\t个\n發\t发\n髮\t发\n頭\t头\n", encoding="utf-8")
    (src / "TSPhrases.txt").write_text("", encoding="utf-8")
    out = tmp_path / "zh_script_data_test.py"

    build = _load_build_script()
    summary = build.main(opencc_dir=str(src), output=str(out))
    assert summary["s2t"] == (3, 1, 1)          # 3 chars, 1 phrase kept (头发), 1 dropped (U盘)
    assert "1 dropped, unequal length" in capsys.readouterr().out

    spec = importlib.util.spec_from_file_location("zh_script_data_test", out)
    data = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(data)
    assert data.OPENCC_TAG == "ver.test"
    assert data.s2t() == {"chars": {"个": "個", "发": "發", "头": "頭"}, "phrases": {"头发": "頭髮"}}
    assert data.t2s()["chars"]["髮"] == "发"
