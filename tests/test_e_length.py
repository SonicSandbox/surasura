"""E-LENGTH: *Length*'s default becomes 14–25 once the sentence table is on (plan_rules.SENTENCE_TABLE >= 1).

The rule (the sentence choice's spec § 4.6): *Length* (logic.context min_chars / preferred_max_chars) is the length a
learner likes best. At level 0 every saved settings.json reads exactly as today and the row shows 10–50. At level 1 and
above the default is 14–25, and a learner who never changed Length moves to it: a first save wrote every default into
settings.json, so a saved pair of exactly 10 and 50 with no `sentence_length_chosen` mark is the old default, never a
choice, and reads as 14–25. Any other pair is the learner's own and is kept; a 10–50 set from the Settings row once the
table is on carries the mark and is kept too. The load reads so and never writes.

What a wrong answer would cost: a learner's own Length silently replaced (their sentences change under them), or the
new default never reaching the learners who never touched it. Real ja + zh libraries' settings, in the test's own root
(conftest's SURASURA_TEST_ROOT); never a user's settings.json.
"""
import json
import os
import subprocess
import sys

import pytest

from app import plan_rules, run_args, sentence_corpus, settings_manager, settings_placement
from app.cli import verbs
from app.path_utils import get_settings_path
from app.qt import settings_catalog as catalog
from app.services import settings_io
from app.services.settings import freeze

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = catalog.ROW["sentence_length"]
LOW, HIGH = "logic.context.min_chars", "logic.context.preferred_max_chars"


@pytest.fixture
def level(monkeypatch):
    """Set the sentence table's level for this process (a child process takes SURASURA_SENTENCE_TABLE instead)."""
    def to(n):
        monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", n)
    return to


def _write(data, bom=False):
    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="\r\n" if bom else "\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _saved(language, low, high, **extra):
    """A settings.json as a first save writes it: the language, the pair, and whatever else the learner set."""
    return dict({"target_language": language, "logic": {"context": {"min_chars": low, "preferred_max_chars": high,
                                                                    "max_chars": 150}}}, **extra)


def _length(settings=None):
    context = (settings or settings_manager.load_settings())["logic"]["context"]
    return context["min_chars"], context["preferred_max_chars"]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_file_that_never_held_length_reads_the_default_of_its_level(level, language):
    """No settings.json, and one that names only the language: 10–50 at level 0 (today), 14–25 at level 1 and 2."""
    level(0)
    assert _length() == (10, 50)
    _write({"target_language": language})
    assert _length() == (10, 50)
    for n in (1, 2):
        level(n)
        assert _length() == (14, 25)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_an_unmarked_saved_10_50_moves_to_14_25_only_once_the_table_is_on(level, language):
    """The old default saved by a first save, never a choice: today's at level 0, 14–25 from level 1."""
    _write(_saved(language, 10, 50))
    level(0)
    assert _length() == (10, 50)
    level(1)
    assert _length() == (14, 25)
    assert settings_manager.load_settings()["logic"]["context"]["max_chars"] == 150      # *Never longer than* kept


@pytest.mark.parametrize("pair", [(12, 40), (10, 40), (14, 50), (5, 80), (14, 25)])
def test_a_learners_own_pair_is_kept_at_every_level(level, pair):
    """Any pair but exactly 10 and 50 is the learner's (one end at the old default too): never moved."""
    _write(_saved("ja", *pair))
    for n in (0, 1, 2):
        level(n)
        assert _length() == pair


def test_a_10_50_set_with_the_mark_is_kept(level):
    """A learner who set 10–50 from the Settings row once the table was on: the mark says it is theirs."""
    _write(_saved("zh", 10, 50, sentence_length_chosen=True))
    level(1)
    assert _length() == (10, 50)


def test_one_end_held_reads_the_other_from_the_default(level):
    """A hand-edited file holding only the low end: it is kept, the high end is the level's default."""
    _write({"target_language": "ja", "logic": {"context": {"min_chars": 10}}})
    level(1)
    assert _length() == (10, 25)
    level(0)
    assert _length() == (10, 50)


def test_one_end_held_never_reads_a_pair_upside_down(level):
    """A held end past the default's (14–25 is narrower than 10–50: a held low end of 26–50 sat above the high end):
    the default's end follows it. A value that isn't a number is left to today's readers, as before."""
    level(1)
    _write({"target_language": "ja", "logic": {"context": {"min_chars": 30}}})
    assert _length() == (30, 30)
    _write({"target_language": "zh", "logic": {"context": {"preferred_max_chars": 12}}})
    assert _length() == (12, 12)
    _write({"target_language": "ja", "logic": {"context": {"min_chars": "30"}}})
    assert _length() == ("30", 25)


def test_the_load_writes_nothing(level):
    """Read so, never written (settings criteria 11): the file's bytes and time are the same after every load."""
    path = _write(_saved("ja", 10, 50))
    before = open(path, "rb").read(), os.stat(path).st_mtime_ns
    for n in (0, 1, 2):
        level(n)
        settings_manager.load_settings()
    assert (open(path, "rb").read(), os.stat(path).st_mtime_ns) == before


def test_a_hand_edited_file_with_a_bom_and_crlf_reads_the_same(level):
    """Notepad's BOM and CRLF: the old default still reads as 14–25 (path_utils.read_text), a learner's pair kept."""
    _write(_saved("ja", 10, 50), bom=True)
    level(1)
    assert _length() == (14, 25)
    _write(_saved("ja", 12, 40), bom=True)
    assert _length() == (12, 40)


def test_a_broken_context_or_file_never_raises(level):
    """A hand-broken context (not a mapping) or a file that isn't JSON: the load goes on as before."""
    level(1)
    _write({"target_language": "ja", "logic": {"context": "short"}})
    settings_manager.load_settings()
    path = get_settings_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert _length() == (14, 25)


def test_the_mark_is_placed_neither_and_export_import_carry_it():
    """The mark moves no signature (test_settings_signatures flips it) and a settings export / import keeps it."""
    assert settings_placement.PLACED["sentence_length_chosen"] == "neither"
    assert settings_manager.DEFAULT_SETTINGS["sentence_length_chosen"] is False
    assert settings_io.known("sentence_length_chosen")
    kept, dropped = settings_io._clean(_saved("ja", 10, 50, sentence_length_chosen=True))
    assert kept["sentence_length_chosen"] is True and not dropped
    assert "sentence_length_chosen" in catalog.NOT_SHOWN


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_row_shows_what_the_reader_uses(level, language):
    """The Settings row reads the loaded settings: an unmarked 10–50 shows 14–25 at level 1, 10–50 at level 0."""
    _write(_saved(language, 10, 50))
    level(0)
    assert catalog.value(ROW, freeze(settings_manager.load_settings()), language) == {LOW: 10, HIGH: 50}
    level(1)
    assert catalog.value(ROW, freeze(settings_manager.load_settings()), language) == {LOW: 14, HIGH: 25}


def test_the_row_writes_the_pair_and_the_mark_only_once_the_table_is_on(level):
    """Level 1: any change writes both ends and the mark (one end changed must not leave the file's other end on an
    old default) — and the same value writes nothing (S19). Level 0: today's write, one key, no mark."""
    _write(_saved("ja", 10, 50))
    level(1)
    shown = freeze(settings_manager.load_settings())
    assert catalog.change(ROW, shown, "ja", (14, 25)) == ({}, None)
    assert catalog.change(ROW, shown, "ja", (12, 25))[0] == {LOW: 12, HIGH: 25, "sentence_length_chosen": True}
    assert catalog.change(ROW, shown, "ja", (10, 50))[0] == {LOW: 10, HIGH: 50, "sentence_length_chosen": True}
    level(0)
    shown = freeze(settings_manager.load_settings())
    assert catalog.change(ROW, shown, "ja", (12, 50))[0] == {LOW: 12}


def test_the_fall_backs_read_the_one_default(level):
    """A settings dict without the pair: the run's args, a book's pick (surasura-cli) and 例文's range read the level's
    default from settings_manager, never their own 10 / 50."""
    for n, (low, high) in ((0, (10, 50)), (1, (14, 25))):
        level(n)
        args = run_args.analyzer_args({"target_language": "ja", "logic": {"context": {}}}, "ja")
        assert f"--context-min={low}" in args and f"--context-max={high}" in args
        assert verbs._sentence_length({}) == (low, high, 150)
        lead = sentence_corpus.LENGTH_LEEWAY
        assert sentence_corpus.length_range({}) == (max(1, low - lead), min(150, high + lead), low, high)


@pytest.mark.parametrize("n, pair, line", [
    ("0", (10, 50), "Shorter or longer ones are still used, just later"),
    ("1", (14, 25), "The sentence length you like best. Others are still used, a little later."),
])
def test_a_child_process_takes_the_default_and_the_words_of_its_level(n, pair, line):
    """A Generate is a subprocess: SURASURA_SENTENCE_TABLE sets DEFAULT_SETTINGS (the changed dot's default) and the
    row's words at import."""
    code = ("from app import settings_manager as m; from app.qt import settings_catalog as c, settings_strings as s;"
            "x = m.DEFAULT_SETTINGS['logic']['context'];"
            "print(x['min_chars'], x['preferred_max_chars'], c.default_value(c.ROW['sentence_length'], 'ja'));"
            "print(s.ROWS['sentence_length'][1])")
    env = dict(os.environ, SURASURA_SENTENCE_TABLE=n)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr
    first, second = out.stdout.strip().splitlines()[-2:]
    assert first == f"{pair[0]} {pair[1]} {pair}"          # the default, and the row's default (its changed dot)
    assert second == line
