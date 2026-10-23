"""Finished content is reference, like a watched episode (W-1b; Sonic 2026-10-23, one rule with W-1).

Sonic's ask: "When I put in all my content, it accurately gets the words, order, etc without inflating counts by doing
it wrong (such as including finished content) but also provides and enriches based on all the content (such as with
finished content)". So a Finished show is set aside, exactly as a watched episode is: never a list use — no count,
Score, order, tier count, phrase, one-kanji piece, Rarity number or mine line — but the name tables' evidence (a name
met in the show stays whole in the episodes ahead) and a sentence source (例文, the sentence dictionary). New arrivals
and removed items stay kept (text only).

What a wrong answer would cost a learner:
  * a finished show's words counted again — inflated counts, words he has already met pushed up the list;
  * a finished show's character name splitting into fake words in the sequel he is watching now;
  * a word whose only good sentences are in a finished show getting none on its card;
  * a show moved into Finished (or back, or the move undone) being read all over again, or its names forgotten;
  * a finished show whose files he deleted losing its sentences and names at the next rebuild of the token store.

Real Japanese and Chinese text (testing.md): the six real files of the token store's tests in NOW, Soon and 6+ Months,
Finished shows cut from tests/Test Resources/, and — for the names — the made-up recurring katakana name of
tests/test_token_store_aside.py (メロン + ベンチ: two common words, a name only through the library's table), all
under the per-test SURASURA_TEST_ROOT; Generate runs as the dashboard runs it (a child process).
"""
import os
import shutil
from unittest.mock import patch

import pytest

from app import analyzer, library_store as ls, sentence_corpus as sc, token_index as ti
from tests.test_generate_missing_item import _generate
from tests.test_library_store_support import LANGUAGES, entry, roots, write_manifest
from tests.test_token_store_aside import NAME, _cues, _names_bytes, _show, _srt, _surfaces
from tests.test_token_store_kept import _everything_counted, _kept_text, _lemmas, _library, _run_indexer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# A finished show of real text no NOW / Soon / 6+ Months file holds (the six are tests/test_token_store_kept's).
FINISHED = {"ja": ["tests/Test Resources/ja/placed_episode.srt", "tests/Test Resources/ja/runaway_transcript.txt"],
            "zh": ["tests/Test Resources/zh/mixed_script_transcript.txt",
                   "tests/Test Resources/zh/traditional_news.txt"]}


def _finished_show(language, show="終わった作品", season="第1期", sources=None):
    """The real files of FINISHED copied into Graduated/<show>/<season>/ (nested, as the Finished importer copies a
    folder): their paths."""
    data_dir, _u = roots(language)
    out = []
    for source in sources or FINISHED[language]:
        path = os.path.join(data_dir, ls.GRADUATED_FOLDER, show, season, os.path.basename(source))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy2(os.path.join(REPO, *source.split("/")), path)
        out.append(path)
    return out


def _keys(paths):
    return {ti._norm(p) for p in paths}


def _counts(store, language):
    """Every count the list and the Rarity slider read: `_everything_counted` less the name tables (their evidence
    is the point of the rule)."""
    counted = _everything_counted(store, language)
    counted.pop("names")
    return counted


def _library_frequency(root):
    """Generate's whole-library word map (`results/library_frequency.json`), as written: what Junban reads for a word
    below the list's cut-off — a word absent from it and from the list is "not on your list"."""
    with open(os.path.join(root, "results", "library_frequency.json"), encoding="utf-8") as f:
        return f.read()


def _library_words(root, language):
    """{(lemma, reading): uses} of that map (`analyzer.library_counts`)."""
    counts, _floor = analyzer.library_counts(os.path.join(root, "results", "library_frequency.json"), language)
    return counts


def _spy_tokenizing():
    """Every file the token store tokenizes, in the pool or by hand: (patcher, the list)."""
    seen, real_pool = [], ti._tokenized

    def pool(paths, tokenize_file, workers):
        seen.extend(paths)
        return real_pool(paths, tokenize_file, workers)
    return patch.object(ti, "_tokenized", pool), seen


# --------------------------------------------------------------------------- #
# 1. Never inflates
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_show_never_counts_in_generate_the_rarity_slider_or_the_mine_line(language):
    """The six real files, Generated; then a finished show of other real text is added (the Finished importer's
    command) and indexed. Generate's lists — every word's count, Score and order, the tier counts — and its
    whole-library word map are byte for byte as before; the Rarity slider's counts, the bound and phrase tables are as
    before; the show is set aside in the token store (reference), never counted, never on the mine line. Not vacuous:
    the show holds words no other file does (absent everywhere) and words the others hold too (their counts unchanged)."""
    root = os.environ["SURASURA_TEST_ROOT"]
    store, data_dir, ids = _library(language)
    store.close()
    before = _generate(root, language)
    words_before = _library_frequency(root)
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        counts_before = _counts(tokens, language)

    show = _finished_show(language)
    store = ls.open_store(language, data_dir, roots(language)[1])
    store.import_finished(show)
    assert all(store.item(store.item_id(os.path.relpath(p, data_dir).replace("\\", "/")))["tier"] == "graduated"
               for p in show)
    assert not {store.item(i)["rel_path"] for i in store._mine_ids(50)} & {
        os.path.relpath(p, data_dir).replace("\\", "/") for p in show}, "never on the mine line"
    store.close()
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        assert set(tokens.aside_files()) == _keys(show), "Finished is set aside: reference, never kept only"
        assert not set(tokens.counted_files()) & _keys(show)
        assert _counts(tokens, language) == counts_before, "the Rarity slider counts what it counted before"
        mine = set().union(*(_lemmas(tokens, p) for p in ids))
        theirs = set().union(*(_lemmas(tokens, p) for p in show))
    after = _generate(root, language)
    assert after == before, "Generate's lists: every count, Score, order and tier count as before"
    assert _library_frequency(root) == words_before, "and the whole-library map Junban reads"
    only_finished = {w for w in theirs - mine if analyzer.has_target_language(w, language)}
    # Not vacuous: the show holds words the list and the map lack — and, the lists unchanged, still lack.
    assert only_finished - {lemma for lemma, _r in _library_words(root, language)}, "a word only in Finished: absent"
    assert theirs & mine, "words in both: counted with their own files' uses only (the lists are unchanged)"


# --------------------------------------------------------------------------- #
# 2. Enriches
# --------------------------------------------------------------------------- #
def _name_library():
    """The six real Japanese files, a NOW episode holding the recurring name once, and a three-episode finished show
    holding it once an episode (Graduated/<show>/<season>/, imported as the Finished importer does): (store,
    data_dir, now episode, show)."""
    store, data_dir, _ids = _library("ja")
    store.close()
    show = _show(folder=f"{ls.GRADUATED_FOLDER}/空の庭/第1期")
    now_ep = os.path.join(data_dir, "HighPriority", "空の庭 続", "空の庭 続 第1話.srt")
    os.makedirs(os.path.dirname(now_ep), exist_ok=True)
    with open(now_ep, "w", encoding="utf-8", newline="\n") as f:
        f.write(_srt(_cues("phrases_sample.srt")[8:12] + ["メロンベンチでまた会おうね。"]))
    store = ls.open_store("ja", data_dir, roots("ja")[1])
    store.insert([now_ep], "now")
    store.import_finished(show)
    return store, data_dir, now_ep, show


def test_a_name_met_in_a_finished_show_stays_whole_in_the_episode_ahead_and_counts_only_there(tmp_path):
    """The name is met three times across the finished show and once in the NOW episode: the name tables join it, so
    the NOW episode reads it whole — one word, counted once (its NOW use alone), in the Rarity slider and in Generate's
    whole-library map. The same NOW episode without the finished show reads it in pieces: the show is what holds it."""
    root = os.environ["SURASURA_TEST_ROOT"]
    store, _data_dir, now_ep, show = _name_library()
    store.close()
    _run_indexer("ja")
    with ti.open_store("ja") as tokens:
        assert NAME in tokens.names_tables()["k"], "the finished show is the names' evidence"
        assert NAME in _surfaces(tokens, now_ep), "the episode ahead reads the name whole"
        assert tokens.word_counts()[0].get((NAME, "")) == 1, "counted once: its NOW use, never the show's three"
    _generate(root, "ja")
    assert {uses for (lemma, _r), uses in _library_words(root, "ja").items() if lemma == NAME} == {1},         "Generate lists the name as one word, its NOW use alone"

    alone = ti.open_store("ja", path=str(tmp_path / "alone.db"))
    alone.reconcile([now_ep], ti.make_tokenizer("ja"), ti.build_signature("ja"))
    assert NAME not in alone.names_tables()["k"] and NAME not in _surfaces(alone, now_ep), \
        "without the finished show the name is in pieces (the test can fail)"
    alone.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_shows_sentences_go_to_examples_and_the_sentence_dictionary(language, tmp_path):
    """A word met only in the finished show gets its 例文 from the show (`best_for`), and the sentence dictionary
    (`build`) holds the show's sentences — with nothing tokenized again; the list's own example sentences (Generate's
    contexts) still come from the counted files alone."""
    root = os.environ["SURASURA_TEST_ROOT"]
    store, data_dir, ids = _library(language)
    show = _finished_show(language)
    store.import_finished(show)
    store.close()
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        cached = {p: tokens.file_tokens(p) for p in list(ids) + show}
    others = {s for p in ids for s, _t in cached[p]}
    show_only = {s for p in show for s, _t in cached[p]} - others
    wanted = {(t[0], t[1]) for p in show for _s, toks in cached[p] for t in toks}
    picked = {text for found in sc.best_for(language, wanted).values() for _o, text, _s, _f in found}
    assert show_only & picked, "例文 picks a finished show's sentence"

    dictionary = []
    real_export = sc.export_dictionary

    def export(words, sources, *args, **kwargs):
        dictionary.extend(text for w in words.values() if w.best is not None for _r, text, _f, _s in w.best.result())
        return real_export(words, sources, *args, **kwargs)

    spy, tokenized = _spy_tokenizing()
    with patch.object(sc, "export_dictionary", export), spy:
        assert sc.build(language, str(tmp_path / "corpus.zip"), progress=lambda message: None)
    assert show_only & set(dictionary), "the sentence dictionary holds a finished show's sentences"
    assert tokenized == [], "nothing read again"

    _generate(root, language)
    with open(os.path.join(root, "results", "priority_learning_list.csv"), encoding="utf-8-sig") as f:
        contexts = f.read()
    assert not any(s.strip() and s.strip() in contexts for s in show_only if len(s.strip()) > 6), \
        "the list's own example sentences never come from Finished"


# --------------------------------------------------------------------------- #
# 3. Into Finished and back
# --------------------------------------------------------------------------- #
def test_a_show_moved_into_finished_and_back_and_undone_moves_its_counts_keeps_its_names_and_reads_nothing(tmp_path):
    """The name show in NOW (three episodes) and a fourth NOW episode holding the name: indexed, every count and the
    name tables are the reference. Finished: the counts are the fourth episode's alone, the name tables byte for byte
    the reference (still evidence), the fourth episode still reads the name whole. Put back: every count as at first.
    Undo: Finished again. No step tokenizes anything."""
    data_dir, user_files_dir = roots("ja")
    eps = _show(folder="HighPriority/空の庭")
    fourth = os.path.join(data_dir, "HighPriority", "空の庭", "空の庭 第4話.srt")
    with open(fourth, "w", encoding="utf-8", newline="\n") as f:
        f.write(_srt(_cues("phrases_sample.srt")[8:12] + ["メロンベンチでまた会おうね。"]))
    write_manifest(user_files_dir, {"schedule": {"PHASE_1_NOW": [entry(_rel(data_dir, p)) for p in eps + [fourth]],
                                                 "PHASE_2_SOON": [], "PHASE_3_LATER": []}})
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store("ja", data_dir, user_files_dir)
    show_ids = [store.item_id(_rel(data_dir, p)) for p in eps]
    _run_indexer("ja")
    with ti.open_store("ja") as tokens:
        reference, names = _everything_counted(tokens, "ja"), _names_bytes(tokens)
    assert NAME in reference["names"]["k"]
    sig = ti.build_signature("ja")
    fourth_alone = ti.open_store("ja", path=str(tmp_path / "fourth.db"))
    fourth_alone.reconcile([fourth], ti.make_tokenizer("ja"), sig, aside=eps)

    spy, tokenized = _spy_tokenizing()
    with spy:
        store.finish(show_ids)
        _run_indexer("ja")
        with ti.open_store("ja") as tokens:
            assert set(tokens.aside_files()) == _keys(eps)
            assert _counts(tokens, "ja") == _counts(fourth_alone, "ja"), "the fourth episode's counts alone"
            assert _names_bytes(tokens) == names, "the name tables keep the show as evidence, byte for byte"
            assert NAME in _surfaces(tokens, fourth)
        change = store.put_back_finished(show_ids)
        _run_indexer("ja")
        with ti.open_store("ja") as tokens:
            assert _everything_counted(tokens, "ja") == reference and tokens.aside_files() == []
        store.undo(change)
        assert all(store.item(i)["tier"] == "graduated" for i in show_ids)
        _run_indexer("ja")
        with ti.open_store("ja") as tokens:
            assert _counts(tokens, "ja") == _counts(fourth_alone, "ja") and _names_bytes(tokens) == names
    assert tokenized == [], "no move reads a file again"
    fourth_alone.close()
    store.close()


def _rel(data_dir, path):
    return os.path.relpath(path, data_dir).replace("\\", "/")


# --------------------------------------------------------------------------- #
# 4. Edges
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_an_empty_finished_file_is_set_aside_and_changes_no_count(language):
    """An empty subtitle and an empty text file in Finished: listed aside, cached with nothing in them, every count as
    before; no error."""
    store, data_dir, _ids = _library(language)
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        before = _everything_counted(tokens, language)
    folder = os.path.join(data_dir, ls.GRADUATED_FOLDER, "空っぽ")
    os.makedirs(folder)
    empty = [os.path.join(folder, "第1話.srt"), os.path.join(folder, "メモ.txt")]
    for path in empty:
        open(path, "w", encoding="utf-8").close()
    store.import_finished(empty)
    assert {_rel(data_dir, p) for p in empty} <= set(store.text_lists()[2])
    store.close()
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        assert _keys(empty) <= set(tokens.aside_files())
        assert _everything_counted(tokens, language) == before


def _forget_the_token_store(language):
    """The token store deleted, as a schema change or a damaged file deletes it (the kept text, its own file, stays)."""
    path = ti.store_path_for(language)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


def test_a_finished_file_deleted_from_the_disk_keeps_its_sentences_and_names_through_a_rebuilt_token_store(tmp_path):
    """The name show is finished (imported into Finished, indexed once), then its files are deleted from the disk and
    the token store is rebuilt from nothing before any index sees them gone: its text was kept when it was first read,
    so the rebuilt store reads it back — still set aside, still the names' evidence (the NOW episode reads the name
    whole), still a sentence source; never counted."""
    store, data_dir, now_ep, show = _name_library()
    store.close()
    _run_indexer("ja")
    with ti.open_store("ja") as tokens:
        names, counts = _names_bytes(tokens), _counts(tokens, "ja")
        held = set(_kept_text(tokens).held())
    assert _keys(show) <= held, "a finished file's text is kept at its first read"
    for path in show:
        os.remove(path)
    _forget_the_token_store("ja")
    _run_indexer("ja")
    with ti.open_store("ja") as tokens:
        assert set(tokens.aside_files()) == _keys(show) and _names_bytes(tokens) == names
        assert NAME in _surfaces(tokens, now_ep) and _counts(tokens, "ja") == counts
        assert all(tokens.file_tokens(p) for p in show), "its sentences are read back from the kept text"
    store = ls.open_store("ja", data_dir, roots("ja")[1])
    assert {_rel(data_dir, p) for p in show} <= set(store.text_lists()[2]), "the library still lists them aside"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_episode_also_watched_is_set_aside_once_with_the_option_on_or_off(language):
    """A finished episode that is also watched is one reference file: in the set-aside list only, whatever Keep
    studying watched episodes says — never counted, never kept only."""
    store, data_dir, _ids = _library(language)
    show = _finished_show(language)
    store.import_finished(show)
    first = store.item_id(_rel(data_dir, show[0]))
    store.set_watched([first])
    for keep in (False, True):
        store.set_library_options(keep_watched=keep)
        counted, kept, aside = store.text_lists()
        assert {_rel(data_dir, p) for p in show} <= set(aside), keep
        assert not {_rel(data_dir, p) for p in show} & set(counted + kept), keep
    store.close()


def test_the_set_aside_rule_holds_finished_watched_and_the_option():
    """The truth table beside `counts`: Finished is set aside always; an analysed tier only when it doesn't count;
    New arrivals never (kept only); nothing both counts and is set aside."""
    for watched in (0, 1):
        for keep in (False, True):
            assert ls.sets_aside("graduated", watched, keep)
            assert not ls.sets_aside("arrivals", watched, keep)
            for tier in ls.ANALYSED:
                assert ls.sets_aside(tier, watched, keep) == (not ls.counts(tier, watched, keep))
            for tier in ls.TIERS:
                assert not (ls.sets_aside(tier, watched, keep) and ls.counts(tier, watched, keep))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_file_with_crlf_and_mixed_scripts_gives_clean_sentences(language):
    """A finished text with Windows line ends and mixed scripts (kana, kanji or hanzi, Latin letters, digits, a
    full-width number): set aside, its sentences offered to 例文 without a stray carriage return, its words in no
    count."""
    store, data_dir, ids = _library(language)
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        before = _counts(tokens, language)
    lines = {"ja": ["昨日はＡＩの講演を聞きに行った。", "スピーカーはTokyo大学の先生で、話は2時間も続いた。",
                    "帰りにコンビニで新しいノートを３冊買った。"],
             "zh": ["昨天我去听了一个AI讲座。", "演讲者是Beijing大学的老师，讲了2个小时。", "回家的路上我买了３本新笔记本。"]}[language]
    path = os.path.join(data_dir, ls.GRADUATED_FOLDER, "雑記", "講演メモ.txt")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    store.import_finished([path])
    store.close()
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        assert ti._norm(path) in tokens.aside_files() and _counts(tokens, language) == before
        sentences = [s for s, _t in tokens.file_tokens(path)]
        wanted = {(t[0], t[1]) for _s, toks in tokens.file_tokens(path) for t in toks}
    assert sentences and not any("\r" in s for s in sentences)
    picked = {text for found in sc.best_for(language, wanted).values() for _o, text, _s, _f in found}
    assert picked & set(sentences) and not any("\r" in s for s in picked)


# --------------------------------------------------------------------------- #
# Drill A1 (the lead's confidence audit, 2026-10-23): all my content, counted right — a real Generate
# --------------------------------------------------------------------------- #
W_ONLY, W_SHARED = "蜃気楼", "灯台"
ONLY_LINES = ("遠くの道に蜃気楼が見えた。", "あれは本当に蜃気楼だったのかな。", "蜃気楼みたいに消えちゃった。")
SHARED_A = ("岬の灯台まで歩いて行こう。", "灯台の光が海を照らしている。")
SHARED_B = ("灯台の下で待ってるね。", "古い灯台はもう使われていない。", "夜になると灯台が光り始める。")
DRILL_NAME = ("メロンベンチで待ち合わせよう。", "メロンベンチの前に集合ね。", "今日もメロンベンチに座った。",
              "メロンベンチでまた会おうね。")


def _ass_parts(name):
    """(header, events) of a real .ass in tests/Test Resources/ja: the header through `Format:` of [Events], and its
    Dialogue / Comment lines."""
    with open(os.path.join(REPO, "tests", "Test Resources", "ja", name), encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    cut = next(i for i, line in enumerate(lines) if line.startswith(("Dialogue:", "Comment:")))
    return lines[:cut], [line for line in lines[cut:] if line.startswith(("Dialogue:", "Comment:"))]


def _said(texts, minute):
    return [f"Dialogue: 0,0:{minute:02d}:{n * 3:02d}.00,0:{minute:02d}:{n * 3 + 2:02d}.50,Default,,0,0,0,,{text}"
            for n, text in enumerate(texts)]


def _drill_library():
    """Show A (Ep01–04, cut from library_episode.ass and tv_captions.ass) and Show B (Ep01–03, from placed_episode.srt
    and phrases_sample.srt) in NOW, Book C (runaway_transcript.txt) in Soon. W_ONLY only in A-Ep01; W_SHARED in A-Ep01
    and B-Ep02; the name in A-Ep01..03 and B-Ep01, once each. Returns (store, data_dir, {"A": [...], "B": [...],
    "C": [...]})."""
    data_dir, user_files_dir = roots("ja")
    lib_head, lib_events = _ass_parts("library_episode.ass")
    tv_head, tv_events = _ass_parts("tv_captions.ass")
    a_parts = [(lib_head, lib_events[:8] + _said(ONLY_LINES + SHARED_A + DRILL_NAME[:1], 5)),
               (lib_head, lib_events[8:] + _said(DRILL_NAME[1:2], 5)),
               (tv_head, tv_events[:5] + _said(DRILL_NAME[2:3], 5)),
               (tv_head, tv_events[5:])]
    shows = {"A": [], "B": [], "C": []}
    for n, (head, events) in enumerate(a_parts, 1):
        path = os.path.join(data_dir, "HighPriority", "図書館の午後", f"図書館の午後 第{n:02d}話.ass")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(head + events) + "\n")
        shows["A"].append(path)
    placed, phrases = _cues("placed_episode.srt"), _cues("phrases_sample.srt")
    for n, cues in enumerate((placed[:5] + list(DRILL_NAME[3:]), placed[5:] + list(SHARED_B), phrases), 1):
        path = os.path.join(data_dir, "HighPriority", "海辺の町", f"海辺の町 第{n:02d}話.srt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_srt(cues))
        shows["B"].append(path)
    book = os.path.join(data_dir, "LowPriority", "本", "runaway_transcript.txt")
    os.makedirs(os.path.dirname(book), exist_ok=True)
    shutil.copy2(os.path.join(REPO, "tests", "Test Resources", "ja", "runaway_transcript.txt"), book)
    shows["C"].append(book)
    write_manifest(user_files_dir, {"schedule": {
        "PHASE_1_NOW": [entry(_rel(data_dir, p)) for p in shows["A"] + shows["B"]],
        "PHASE_2_SOON": [entry(_rel(data_dir, book))], "PHASE_3_LATER": []}})
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    return ls.open_store("ja", data_dir, user_files_dir), data_dir, shows


def _rows(root, name):
    import csv
    with open(os.path.join(root, "results", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_drill_a1_finishing_a_show_counts_right_and_keeps_its_names_and_sentences():
    """Drill A1: Show A and Show B in NOW, Book C in Soon, Generated; Show A finished, Generated again. Every word's
    Occurrences and tier counts are those of B and C alone, computed independently (each file tokenized on its own),
    W_ONLY is gone, W_SHARED counts its B-Ep02 uses alone, the progressive list follows `schedule()`'s order; the name
    is still read whole in B-Ep01 (one use, B's) and a sentence of Show A can still be picked for 例文."""
    root = os.environ["SURASURA_TEST_ROOT"]
    store, data_dir, shows = _drill_library()
    _generate(root, "ja")
    first = {(r["Word"], r["Reading"]): r for r in _rows(root, "priority_learning_list.csv")}
    assert {W_ONLY, W_SHARED, NAME} <= {w for w, _r in first}, "step 1: every seeded word is on the list"

    store.set_tier([store.item_id(_rel(data_dir, p)) for p in shows["A"]], "graduated")
    # The tiers as the list reads them now (the Soon line moves with Current: Book C may be NOW once A has left).
    schedule = store.schedule()
    order = [os.path.join(data_dir, *e["physical_path"].split("/")) for rows in schedule.values() for e in rows]
    phase = {ti._norm(os.path.join(data_dir, *e["physical_path"].split("/"))): key
             for key, rows in schedule.items() for e in rows}
    tier_files = {k: [p for p in shows["B"] + shows["C"] if phase.get(ti._norm(p)) == k] for k in ls.PHASES}
    assert sum(map(len, tier_files.values())) == len(shows["B"] + shows["C"]), "B and C alone are listed"
    store.close()
    _generate(root, "ja")
    after = {(r["Word"], r["Reading"]): r for r in _rows(root, "priority_learning_list.csv")}

    tokenize = ti.make_tokenizer("ja")
    raw = {p: tokenize(p)["counts"] for k in shows for p in shows[k]}

    def uses(key, paths):
        return sum(raw[p].get(f"{key[0]}|{key[1]}", 0) for p in paths)

    assert W_ONLY not in {w for w, _r in after}, "a word only in the finished show is gone"
    shared = next(r for (w, _r), r in after.items() if w == W_SHARED)
    assert int(shared["Occurrences"]) == len(SHARED_B) == uses((W_SHARED, shared["Reading"]), shows["B"][1:2])
    pieces = {w for w, _r in first if w and w in NAME and w != NAME}      # the name's pieces, read whole by its table
    checked = 0
    for key, row in after.items():
        if key[0] == NAME or key[0] in pieces or not any(f"{key[0]}|{key[1]}" in c for c in raw.values()):
            continue                                    # the name, read through the library's table (below)
        high, low, goal = (uses(key, tier_files[k]) for k in ls.PHASES)
        assert (int(row["Occurrences"]), int(row["Count (High)"]), int(row["Count (Low)"]),
                int(row["Count (Goal)"])) == (high + low + goal, high, low, goal), key
        if key in first:
            assert int(row["Occurrences"]) == int(first[key]["Occurrences"]) - uses(key, shows["A"]), key
        checked += 1
    assert checked > 20
    files = []
    for r in _rows(root, "progressive_learning_list.csv"):
        if r["Source File"] not in files:
            files.append(r["Source File"])
    # The progressive list names each file by its name: in schedule()'s order, Show A in none of it.
    assert files == [os.path.basename(p) for p in order], "the progressive list follows schedule()'s order"
    assert not {os.path.basename(p) for p in shows["A"]} & set(files)

    assert {uses_ for (w, _r), uses_ in _library_words(root, "ja").items() if w == NAME} == {1},         "the name: one word, B-Ep01's one use"
    _run_indexer("ja")
    with ti.open_store("ja") as tokens:
        assert NAME in _surfaces(tokens, shows["B"][0]), "still read whole in B-Ep01"
        wanted = {(t[0], t[1]) for _s, toks in tokens.file_tokens(shows["A"][0]) for t in toks}
        a_sentences = {s for s, _t in tokens.file_tokens(shows["A"][0])}
    picked = {text for found in sc.best_for("ja", wanted).values() for _o, text, _s, _f in found}
    assert picked & a_sentences, "a finished Show A sentence can be picked for 例文"


def test_a_new_arrival_and_a_removed_item_stay_kept_no_names_evidence_and_no_examples(tmp_path):
    """Only reference is set aside. A New arrival (not placed yet) and a removed item whose sentences weren't forgotten
    stay kept — text only: each holds the name twice, the NOW episode once, so either one read as evidence would lift
    the name to the floor; it stays in pieces, and neither file's sentences reach 例文. The same two files in Finished
    join the name (the test can fail)."""
    from tests.test_token_store_kept import _remove
    store, data_dir, _ids = _library("ja")
    folder = os.path.join(data_dir, "HighPriority", "空の庭")
    os.makedirs(folder)
    cues = _cues("placed_episode.srt")
    paths = {}
    for name, part, lines in (("now", cues[:3], ["メロンベンチでまた会おうね。"]),
                              ("arrival", cues[3:6], ["メロンベンチで待ち合わせよう。", "メロンベンチの前に集合ね。"]),
                              ("removed", cues[6:], ["今日もメロンベンチに座った。", "明日もメロンベンチに行こう。"])):
        paths[name] = os.path.join(folder, f"空の庭 {name}.srt")
        with open(paths[name], "w", encoding="utf-8", newline="\n") as f:
            f.write(_srt(part + lines))
    ids = {name: store.insert([path], "now").added[0] for name, path in paths.items()}
    store.set_tier([ids["arrival"]], "arrivals")
    _remove(store, data_dir, ids["removed"], paths["removed"])
    counted, kept, aside = store.text_lists()
    assert {_rel(data_dir, paths["arrival"]), _rel(data_dir, paths["removed"])} <= set(kept)
    assert not {_rel(data_dir, paths["arrival"]), _rel(data_dir, paths["removed"])} & set(aside + counted)
    store.close()
    _run_indexer("ja")
    with ti.open_store("ja") as tokens:
        assert set(tokens.kept_files()) >= {ti._norm(paths["arrival"]), ti._norm(paths["removed"])}
        assert NAME not in tokens.names_tables()["k"] and NAME not in _surfaces(tokens, paths["now"])
        theirs = {s for p in (paths["arrival"],) for s, _t in tokens.file_tokens(p)}
        wanted = {(t[0], t[1]) for _s, toks in tokens.file_tokens(paths["arrival"]) for t in toks}
    picked = {text for found in sc.best_for("ja", wanted).values() for _o, text, _s, _f in found}
    assert theirs and not picked & {s for s in theirs if "メロン" in s}, "no 例文 from kept text"
    assert not {f for found in sc.best_for("ja", wanted).values() for _o, _t, _s, f in found} & {
        ti._norm(paths["arrival"]), ti._norm(paths["removed"]), paths["arrival"], paths["removed"]}

    reference = ti.open_store("ja", path=str(tmp_path / "finished.db"))
    trashed = [os.path.join(dp, f) for dp, _d, fs in os.walk(os.path.join(data_dir, ".trash")) for f in fs]
    reference.reconcile([paths["now"]], ti.make_tokenizer("ja"), ti.build_signature("ja"),
                        aside=[paths["arrival"]] + trashed)
    assert NAME in reference.names_tables()["k"], "as Finished, the same text joins the name"
    reference.close()
