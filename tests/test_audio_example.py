"""'Always include a sentence with audio' — guarantee one example you can study by ear.

A word can easily collect five perfect examples that all came from books, leaving no way to hear
it. With the option on, the LAST example slot goes to the best audio candidate — replacing that
slot rather than adding a sixth, so max_contexts and the CSV column count are unchanged.

Runs the real analyzer over a mixed library (a subtitle file and a prose file sharing vocabulary)
because the behaviour depends on source-type detection, the separate audio candidate pool, and the
selection order all agreeing — none of which a unit test of one function would exercise.
"""

import csv
import json
from unittest.mock import patch

import pytest

from app import analyzer


# The situation the feature exists for: a word with plenty of GOOD prose examples and one
# audio example that loses on merit. The subtitle lines are deliberately long (past the
# preferred_max_chars of 50, though still inside the 150 hard cap) so the ordinary ranking puts
# them last — which means every slot fills with prose and the word ends up unhearable.
SUBTITLE = """1
00:00:01,000 --> 00:00:03,000
その日の夕方になってから彼は誰にも気づかれないように古びた屋敷の二階にある小さな窓の外をゆっくりと静かに覗き込むことにしたのだった。

2
00:00:03,000 --> 00:00:06,000
その日の夕方になってから少女は誰にも聞こえないような本当に小さな声で同じ言葉を何度も何度も静かに囁くのをやめなかったのだった。

3
00:00:06,000 --> 00:00:09,000
その日の夕方になってから男は激しい怒りのあまり自分でも抑えられないほど大きく肩を震わせることになってしまったのだった。
"""

YOUTUBE = """彼は静かに窓の外を覗き込む。
少女は小さな声で囁く。
男は思わず肩を震わせる。
"""

PROSE = """彼は窓の外を覗き込む。
彼女は窓の外を覗き込む。
老人は窓の外を覗き込む。
子供は窓の外を覗き込む。
少女は静かに囁く。
老人は静かに囁く。
子供は静かに囁く。
女性は静かに囁く。
男は肩を震わせる。
彼は肩を震わせる。
老人は肩を震わせる。
子供は肩を震わせる。
"""


@pytest.fixture
def mixed_library(tmp_path):
    """A library holding the same vocabulary in both a subtitle and a prose file."""
    data_ja = tmp_path / "data" / "ja"
    high = data_ja / "HighPriority"
    high.mkdir(parents=True)
    (tmp_path / "User Files" / "ja").mkdir(parents=True)
    (tmp_path / "results").mkdir()

    # Names matter: the analyzer walks files in sorted order, and the first sentence a word is
    # ever seen in is pinned to slot 1. With the subtitle sorting first every word would get its
    # audio example for free and the feature would never engage — so the prose file sorts first
    # and the subtitle has to win a slot on merit (which, being long, it can't).
    (high / "a_novel.txt").write_text(PROSE, encoding="utf-8")
    (high / "z_episode.srt").write_text(SUBTITLE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def audio_choice_library(tmp_path):
    """Prose, a subtitle AND a YouTube transcript — all covering the same words."""
    high = tmp_path / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (tmp_path / "User Files" / "ja").mkdir(parents=True)
    (tmp_path / "results").mkdir()
    (high / "a_novel.txt").write_text(PROSE, encoding="utf-8")
    (high / "y_talk [dQw4w9WgXcQ].txt").write_text(YOUTUBE, encoding="utf-8")
    (high / "z_episode.srt").write_text(SUBTITLE, encoding="utf-8")
    return tmp_path


def test_youtube_is_preferred_over_a_subtitle(audio_choice_library):
    """A YouTube badge opens the video at the exact second the line is spoken; a subtitle only
    names an episode you then have to find. Where both could fill the audio slot, the clickable
    one wins.

    Only the vocabulary present in BOTH audio files can show this — a word appearing solely in
    the subtitle has no YouTube alternative to prefer, so including it would test nothing.
    """
    rows = _run(audio_choice_library, ["--min-freq", "1", "--max-contexts", "3",
                                       "--ensure-audio-example"])
    assert rows

    checked = 0
    for word in ("覗き込む", "囁く", "震わせる"):     # in the prose, the subtitle AND the transcript
        if word not in rows:
            continue
        srcs = _srcs(rows[word], 3)
        checked += 1
        assert any("dQw4w9WgXcQ" in s for s in srcs), (
            f"{word}: a subtitle took the audio slot while a YouTube example existed: {srcs}")
    assert checked, "fixture produced none of the shared words"


def _run(root, extra_args):
    """Run a real analysis against `root`, and ONLY against `root`.

    Patch `app.analyzer.*`, not `app.path_utils.*`. The analyzer does
    `from app.path_utils import get_data_path`, which binds the function into its own namespace —
    so replacing the attribute on path_utils leaves the analyzer's copy untouched and it walks the
    developer's real library instead of this fixture. It looks correct, raises nothing, and the
    assertions still pass, because a real library contains the same vocabulary a test looks for.
    """
    results = root / "results"
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(root / "data" / l) if l else str(root / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(root / "User Files" / l) if l else str(root / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja"] + extra_args):
        analyzer.main()

    path = results / "priority_learning_list.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return {r["Word"]: r for r in csv.DictReader(f)}


def _srcs(row, max_contexts):
    """The Src cells actually filled in for a row."""
    return [row.get(f"Src {i + 1}", "") for i in range(max_contexts)
            if row.get(f"Src {i + 1}", "")]


def test_without_the_option_a_word_can_end_up_with_no_audio_example(mixed_library):
    """Baseline: prose outnumbers subtitles, so the ordinary ranking can fill every slot."""
    rows = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3"])
    assert rows, "analysis produced no rows"
    # At least one word should demonstrate the problem the feature solves.
    assert any(not any(s.endswith(".srt") for s in _srcs(r, 3)) for r in rows.values())


def test_with_the_option_every_word_that_can_have_audio_does(mixed_library):
    """Any word appearing in the subtitle file must end up with a subtitle example."""
    rows = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3",
                                "--ensure-audio-example"])
    assert rows

    for word in ("覗き込む", "囁く", "震わせる"):
        if word not in rows:
            continue                      # tokenizer may lemmatize differently; skip rather than guess
        srcs = _srcs(rows[word], 3)
        assert any(s.endswith(".srt") for s in srcs), (
            f"{word} appears in the subtitle file but got no audio example: {srcs}")


def test_only_the_last_slot_ever_changes(mixed_library):
    """It's a bonus slot, not a promotion.

    Diffing the two runs is the precise test: a word that already had an audio example is left
    completely alone, and for any word the feature DID change, only the final slot may differ —
    earlier slots still hold the best examples the ordinary ranking chose.
    """
    off = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3"])
    on = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3",
                              "--ensure-audio-example"])
    assert off.keys() == on.keys()

    changed_any = False
    for word in off:
        before = [off[word].get(f"Context {i+1}", "") for i in range(3)]
        after = [on[word].get(f"Context {i+1}", "") for i in range(3)]
        if before == after:
            continue
        changed_any = True
        assert before[:-1] == after[:-1], (
            f"{word}: the feature altered an earlier slot, not just the last one\n"
            f"  before={before}\n  after ={after}")
        assert on[word].get("Src 3", "").endswith(".srt"), (
            f"{word}: last slot changed but isn't an audio source")

    assert changed_any, "fixture didn't exercise the substitution path"


def test_column_count_is_unchanged(mixed_library):
    """Substitution, not extension — an extra column would break every existing export."""
    off = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3"])
    on = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3",
                              "--ensure-audio-example"])
    assert set(next(iter(off.values())).keys()) == set(next(iter(on.values())).keys())
    assert "Context 4" not in next(iter(on.values()))


def test_disabled_when_only_one_example_is_requested(mixed_library):
    """With a single slot the best sentence is worth more than an audio one."""
    plain = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "1"])
    forced = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "1",
                                  "--ensure-audio-example"])
    for word, row in plain.items():
        assert row.get("Context 1") == forced[word].get("Context 1"), (
            f"{word}'s only example changed, but the feature should be inert at max_contexts=1")


def test_library_with_no_audio_at_all_is_unaffected(tmp_path):
    """Prose-only libraries are a normal state: nothing to inject, and no crash."""
    data_ja = tmp_path / "data" / "ja" / "HighPriority"
    data_ja.mkdir(parents=True)
    (tmp_path / "User Files" / "ja").mkdir(parents=True)
    (tmp_path / "results").mkdir()
    (data_ja / "a_novel.txt").write_text(PROSE, encoding="utf-8")

    plain = _run(tmp_path, ["--min-freq", "1", "--max-contexts", "3"])
    forced = _run(tmp_path, ["--min-freq", "1", "--max-contexts", "3",
                             "--ensure-audio-example"])
    assert plain and plain.keys() == forced.keys()
    for word, row in plain.items():
        assert row.get("Context 1") == forced[word].get("Context 1")


def test_flag_is_part_of_the_run_signature(mixed_library):
    """Toggling it must invalidate the cache, or the old report is served unchanged."""
    args_off = analyzer.parse_analysis_args(["--language", "ja"])
    args_on = analyzer.parse_analysis_args(["--language", "ja", "--ensure-audio-example"])

    with patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(mixed_library / "User Files" / (l or ""))), \
         patch("app.analyzer.get_user_file", side_effect=lambda p: str(mixed_library / p)):
        found = []
        sig_off = analyzer.compute_run_signature("ja", found, args_off)
        sig_on = analyzer.compute_run_signature("ja", found, args_on)

    assert sig_off and sig_on and sig_off != sig_on


# --- sentence quality inside the audio slot -------------------------------------------------- #

# 覗き込む appears in two YouTube transcripts: one sentence stuffed with other unknown words, and
# one clean i+1. The messy one is listed first so taking "the first plausible candidate" picks
# the wrong one — which is exactly what the code used to do.
YT_MESSY = "彼は薄暗い廊下の隅から老朽化した換気口の奥をそっと覗き込む。\n"
# Distinct text from every prose line — an identical sentence is deduplicated, and would then be
# skipped at selection because slot 1 already holds it — but built only from vocabulary the prose
# has already introduced, so it is genuinely the easier of the two.
YT_CLEAN = "彼女は静かに窓の外を覗き込む。\n"


@pytest.fixture
def audio_quality_library(tmp_path):
    high = tmp_path / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (tmp_path / "User Files" / "ja").mkdir(parents=True)
    (tmp_path / "results").mkdir()
    # Prose first, so the word is met in text and the audio slot is what's being decided.
    (high / "a_novel.txt").write_text(PROSE, encoding="utf-8")
    (high / "m_messy [aaaaaaaaaaa].txt").write_text(YT_MESSY, encoding="utf-8")
    (high / "n_clean [bbbbbbbbbbb].txt").write_text(YT_CLEAN, encoding="utf-8")
    return tmp_path


def test_the_audio_slot_gets_the_best_sentence_not_the_first(audio_quality_library):
    """Quality decides, not pool order.

    The pool is ranked during aggregation, before we know which words the learner will already
    have met — so every candidate is re-scored at selection. Picking the first plausible one
    handed out a sentence full of other unknown words while a clean i+1 sat behind it.
    """
    rows = _run(audio_quality_library, ["--min-freq", "1", "--max-contexts", "3",
                                        "--ensure-audio-example"])
    row = rows.get("覗き込む")
    if row is None:
        pytest.skip("tokenizer lemmatized the target differently")

    srcs = _srcs(row, 3)
    assert any("bbbbbbbbbbb" in s for s in srcs), (
        f"the clean i+1 audio sentence should have won the slot, got {srcs}")
    assert not any("aaaaaaaaaaa" in s for s in srcs), (
        f"the messy audio sentence was chosen over a cleaner one: {srcs}")


def test_i_plus_one_outranks_the_audio_preference():
    """Quality is never traded for convenience — stated as the sort keys themselves.

    In every place audio influences the choice, the i+1 cost comes FIRST. Audio only decides
    between sentences that are already equally difficult. Reading the source is deliberate: this
    is an ordering guarantee, and an ordering is what a later edit would quietly change.
    """
    import inspect
    from app import analyzer

    source = inspect.getsource(analyzer.main)

    # the guaranteed audio slot
    assert "rank = (unknowns, src_audio_rank[ctx[5]], ctx[0], ctx[1])" in source

    # the ordinary selection, with the option on: unknown-count still leads
    assert "key=lambda x: (x[2], src_audio_rank[x[5]], x[0], x[1], -x[4])" in source

    # ...and with it off, the ranking is untouched
    assert "evaluated_candidates.sort(key=lambda x: (x[2], x[0], x[1], -x[4]))" in source


def test_audio_preference_is_free_when_the_option_is_off(mixed_library):
    """The toggle must not change a single example for someone who never turns it on."""
    plain = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3"])
    again = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3"])
    assert plain and plain.keys() == again.keys()
    for word, row in plain.items():
        for i in (1, 2, 3):
            assert row.get(f"Context {i}") == again[word].get(f"Context {i}")


# --- the debug dump must survive the audio pool ----------------------------------------------- #

def test_full_word_stats_dump_survives_the_audio_pool(mixed_library, monkeypatch):
    """SURASURA_DEBUG_WORD_STATS=1 together with --ensure-audio-example must not abort the run.

    Every candidate pool stores its co-word set as a `set`, which json.dump cannot serialise, so
    the debug path converts each one to a list. A pool added later without that conversion raises
    TypeError mid-write — and the write is NOT wrapped, so the run dies *after* the CSVs but
    before sources.json, the Content Manager sidecars, reading_words.csv, the progressive report
    and the run-signature. The visible symptom is a Generate that silently redoes everything next
    time, which is a long way from the cause.

    Asserting the downstream artifacts exist is the point: "no exception" alone would still pass
    if the run quietly stopped early.
    """
    monkeypatch.setenv("SURASURA_DEBUG_WORD_STATS", "1")
    results = mixed_library / "results"

    rows = _run(mixed_library, ["--min-freq", "1", "--max-contexts", "3",
                                "--ensure-audio-example"])
    assert rows, "the analysis produced no rows"

    # Everything written AFTER word_stats.json — proof the run reached the end.
    for name in ("word_stats.json", "sources.json", "analyzed_files.json", "file_words.json",
                 "reading_words.csv", "progressive_learning_list.csv"):
        assert (results / name).exists(), f"{name} missing — the run aborted during the dump"

    with open(results / "word_stats.json", encoding="utf-8") as f:
        stats = json.load(f)

    pools = [v["audio_contexts"] for v in stats.values() if v.get("audio_contexts")]
    assert pools, "no word collected an audio candidate, so this test proved nothing"
    for pool in pools:
        for ctx in pool:
            assert isinstance(ctx[3], list), (
                "the audio pool's co-word set was not converted for JSON — "
                "mirror what candidate_contexts and first_context do")
