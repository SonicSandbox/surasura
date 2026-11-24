"""E-JOURNEY (part 1): the young words reach the list — at release 2 the list's first sentence for a word is the one its
card gets, Anki's young cards included (SPEC § 10.3 *E-JOURNEY*, its addendum; the e-build card § E-JOURNEY 1).

The young words are the ones Connect's Anki sync already keeps (`anki_sync.sync_young` -> `User Files/<lang>/
anki_young.json`); the card reads them through `connect.sentences.young_weights`, and so now does the list
(`analyzer.ListSentences`). What these prove, on RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py),
each through a full Generate at level 2 in a child process as the dashboard runs it:
  - a word whose card takes another sentence because a young word sits in it: the list's first sentence is that one;
  - no young file (never synced, Anki absent): the list's answer is the one it gave before (no young words);
  - the redraw marker names the young words it was drawn with, and a sync since that changed them owes the journey one
    redraw (as a new day does); no young words at all is the marker of before (no redraw owed);
  - below level 2 nothing of it is asked.
"""
import json
import os
import subprocess
import sys
import types

import pytest

from app import analyzer, plan_engine, plan_rules
from tests import plan_file_cases as cases

LEVEL_2 = {"SURASURA_SENTENCE_TABLE": "2"}


def _env(root):
    env = cases.child_env(root)
    env.update(LEVEL_2)
    return env


def _child(root, script, *args):
    p = subprocess.run([sys.executable, "-c", script, *args], cwd=cases.REPO, env=_env(root), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


# The card's first sentence (Connect's maker: `connect.sentences.choose`, Best) and the list's (`ListSentences`, the
# redraw's and the level-2 Generate's chooser) for each key, as (Src, Context) — the list's columns' own shape
_FIRSTS = r"""
import json, os, sys
from app import analyzer
from app.connect import sentences as S
from app.path_utils import get_data_path
language, results, keys, young = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), json.loads(sys.argv[4])
keys = [tuple(k) for k in keys]
young = None if young is None else dict(young)        # None: each reads the young file, as in the app
base = os.path.join(get_data_path(language), "")
tagger = analyzer._LazyTagger() if language == "ja" else None
out = {}
listed = analyzer.ListSentences(language, 3, results_dir=results, **({} if young is None else {"young": young}))(
    keys, None) or {}
for key in keys:
    card = S.choose(language, [key], dial=S.BEST, young=young).get(key) or []
    c = card[0] if card else None
    out[json.dumps(list(key), ensure_ascii=False)] = {
        "card": None if c is None else [c.file[len(base):].replace(os.sep, "/") if c.file.startswith(base) else c.file,
                                        analyzer.strip_verse_number(c.text, tagger) if tagger else c.text],
        "list": [listed[key][1], listed[key][0]] if listed.get(key) else None}     # [Src 1, Context 1]
print(json.dumps(out, ensure_ascii=False))
"""

# Words whose card's first sentence moves when one word of another of its lines is young: (key, the young word)
_FIND = r"""
import json, os, sys
from app import analyzer, sentence_score
from app.connect import sentences as S
language, results = sys.argv[1], sys.argv[2]
with open(os.path.join(results, "priority_learning_list.csv"), encoding="utf-8-sig") as f:
    import csv
    keys = [(r["Word"], r["Reading"]) for r in csv.DictReader(f)][:80]
store = sentence_score._tokens(language)
found = []
for key in keys:
    card = S.choose(language, [key], dial=S.BEST, young={}).get(key) or []
    if len(card) < 2 or card[0].number is None:
        continue
    def lemmas(c):
        held = store.file_tokens(c.file)
        return {t[0] for t in held[c.number][1] if t} if 0 <= c.number < len(held) else set()
    first = lemmas(card[0]) | {key[0]}
    for other in card[1:4]:
        if other.number is None:
            continue
        for word in sorted(lemmas(other) - first):
            moved = S.choose(language, [key], dial=S.BEST, young={word: 1.0}).get(key) or []
            if moved and (moved[0].file, moved[0].number) != (card[0].file, card[0].number):
                found.append([list(key), word])
                break
        if found and found[-1][0] == list(key):
            break
    if len(found) >= 3:
        break
store.close()
print(json.dumps(found, ensure_ascii=False))
"""


def _young_file(root, language, words):
    """`User Files/<lang>/anki_young.json` as Connect's sync writes it (`anki_sync.sync_young`), each word a card in
    its first learning step (interval 0: weight 1)."""
    path = os.path.join(root, "User Files", language, "anki_young.json")
    notes = {str(1700000000000 + i): {"word": w, "interval": 0} for i, w in enumerate(words)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "synced_at": "2026-11-23T21:00:00Z", "decks": ["Mining"], "fields": ["Word"],
                   "notes": notes}, f, ensure_ascii=False)
    return path


@pytest.fixture(scope="module", params=["ja", "zh"])
def run(request, tmp_path_factory):
    """One case's library and its Generate at level 2 (no young file), and the words a young card moves."""
    language = request.param
    case = f"rp2-{language}"
    root = str(tmp_path_factory.mktemp(f"e-journey-{language}"))
    cases.build(root, case)
    cases.generate(root, case, extra_env=LEVEL_2)
    results = os.path.join(root, "results")
    found = _child(root, _FIND, language, results)
    return types.SimpleNamespace(language=language, root=root, results=results,
                                 found=[(tuple(k), w) for k, w in found])


def _firsts(run, keys, young=None):
    got = _child(run.root, _FIRSTS, run.language, run.results, json.dumps([list(k) for k in keys], ensure_ascii=False),
                 json.dumps(young, ensure_ascii=False))
    return {tuple(json.loads(k)): v for k, v in got.items()}


def test_the_lists_first_sentence_is_the_cards_when_a_young_card_sits_in_another_line(run):
    # why: SPEC § 1 "the journey and the card: the same answer" — the card weighs Anki's young cards (a line holding a
    # word you are still learning costs less), so the list must too, from the same file, or a word's first sentence
    # on the page is not the one its card is cut from
    assert run.found, f"{run.language}: no word whose card a young card moves in RP-2's library (the case is gone)"
    keys = [k for k, _w in run.found]
    young = _young_file(run.root, run.language, [w for _k, w in run.found])
    try:
        got = _firsts(run, keys)
    finally:
        os.remove(young)
    for key, word in run.found:
        assert got[key]["card"] is not None, key
        # (Src, Context): the card's line is the list's first, the young word weighed by both
        assert got[key]["list"] == got[key]["card"], (run.language, key, word, got[key])


def test_with_no_young_file_the_list_is_todays_answer(run):
    # why: Anki absent, never synced, or every card mature: no young words — the list's first sentence is the one it
    # showed before this lane (the reader with no young words), and still the card's
    keys = [k for k, _w in run.found]
    assert not os.path.exists(os.path.join(run.root, "User Files", run.language, "anki_young.json"))
    none = _firsts(run, keys)
    before = _firsts(run, keys, young={})
    for key in keys:
        assert none[key]["list"] == before[key]["list"] == none[key]["card"], (run.language, key, none[key])


def test_a_young_word_the_list_does_not_hold_changes_nothing(run):
    # why: edge case — a young card whose word is in no line of the library (another deck's word, a name) weighs
    # nothing: the same first sentences as with no young file
    keys = [k for k, _w in run.found]
    young = _young_file(run.root, run.language, ["ＺＺＺ存在しない語" if run.language == "ja" else "不存在的词语甲乙"])
    try:
        got = _firsts(run, keys)
    finally:
        os.remove(young)
    before = _firsts(run, keys, young={})
    for key in keys:
        assert got[key]["list"] == before[key]["list"], (run.language, key)


# --- the staleness rule: the marker names the young words it drew with ---

def test_the_young_stamp_names_the_words_and_their_weights_and_none_for_no_young_words():
    # why: a sync that changed nothing the list weighs (the same words, the same intervals) owes no redraw; one that
    # did (a new young card, an interval moved) does; no young words at all is the marker of before (no key)
    assert analyzer.young_stamp({}) is None and analyzer.young_stamp(None) is None
    a = analyzer.young_stamp({"食べる": 1.0, "走る": 0.5})
    assert a == analyzer.young_stamp({"走る": 0.5, "食べる": 1.0})          # order-free
    assert a != analyzer.young_stamp({"食べる": 1.0, "走る": 0.45})         # an interval moved
    assert a != analyzer.young_stamp({"食べる": 1.0})                      # a card grew mature
    assert analyzer.young_stamp({"学习": 1.0}) != analyzer.young_stamp({"学生": 1.0})


@pytest.mark.parametrize("level, drawn_with, now, state", [
    (2, "same", "same", "drawn"),           # nothing synced since that the list weighs
    (2, "same", "other", "owed"),           # a sync since changed the young words: redrawn once
    (2, None, "same", "owed"),              # drawn with no young words, a young card since
    (2, "same", None, "owed"),              # every young card grew mature since (or Anki's file gone)
    (2, None, None, "drawn"),               # no Anki at all: the marker of before, nothing owed (today's)
    (0, "same", "other", "drawn"),          # below release 2 the young words are not asked
])
def test_a_sync_since_that_changed_the_young_words_owes_the_journey_a_redraw(monkeypatch, level, drawn_with, now,
                                                                             state):
    # why: the staleness rule — the list's young words are the ones of its draw; a sync since that changed them makes
    # the page's first sentence no longer the card's, so the journey is owed one redraw (as a new day is: § 7 row 36)
    from app import library_store, plan_rules as rules
    from app.connect import sentences as S
    from app.services import journey as J, moves

    class Store:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    weights = {"same": {"食べる": 1.0}, "other": {"食べる": 1.0, "走る": 0.5}, None: {}}
    monkeypatch.setattr(rules, "SENTENCE_TABLE", level)
    monkeypatch.setattr(plan_engine, "read_header", lambda path: {"run_signature": "plan"})
    monkeypatch.setattr(library_store, "open_store", lambda *a, **k: Store())
    monkeypatch.setattr(moves, "plan_inputs", lambda *a: (None, None, "parts"))
    monkeypatch.setattr(rules, "signature_digest", lambda parts: "moved")
    monkeypatch.setattr(plan_engine, "only_order", lambda header, language, *inputs: True)
    monkeypatch.setattr(S, "young_weights", lambda language, read=None: dict(weights[now]))
    marker = {"plan": "plan", "run": "moved", "day": analyzer.drawn_day()}
    stamp = analyzer.young_stamp(weights[drawn_with])
    if stamp is not None:
        marker["young"] = stamp
    monkeypatch.setattr(analyzer, "redrawn_for", lambda results: marker)
    assert J.moved_state({}, "ja", "plan.json.gz") == state


def test_the_redraw_marker_names_the_young_words_it_drew_with(monkeypatch, tmp_path):
    # why: the marker is the redraw's record of its moment — written with the chooser's own stamp (what it weighed,
    # read once), never the file read again after (a sync between the two would be missed); no young words: no key,
    # the marker of before; below release 2: today's marker, nothing new
    monkeypatch.setattr(analyzer, "RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 2)
    analyzer._write_redraw_marker("plan", "run", young="abc123")
    assert analyzer.redrawn_for(str(tmp_path)) == {"plan": "plan", "run": "run", "day": analyzer.drawn_day(),
                                                   "young": "abc123"}
    analyzer._write_redraw_marker("plan", "run")
    assert "young" not in analyzer.redrawn_for(str(tmp_path))
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 0)
    analyzer._write_redraw_marker("plan", "run", young="abc123")
    assert analyzer.redrawn_for(str(tmp_path)) == {"plan": "plan", "run": "run"}


def test_the_chooser_reads_the_young_words_once_and_keeps_their_stamp(monkeypatch):
    # why: the list reads the card's own young words (`young_weights`: one source) once a call, and the stamp the
    # marker takes is of exactly those; handed in (`young=`), the file is not read
    from app.connect import sentences as S
    from app import sentence_score, sentence_corpus, sentence_table, settings_manager
    reads, asked = [], {}
    monkeypatch.setattr(S, "young_weights", lambda language, read=None: reads.append(language) or {"食べる": 1.0})
    monkeypatch.setattr(S, "_dates", lambda language, ai: ({}, {}))
    monkeypatch.setattr(S, "ai_voice", lambda settings, language: None)
    monkeypatch.setattr(settings_manager, "load_settings", lambda: {})
    monkeypatch.setattr(sentence_corpus, "length_range", lambda settings: (14, 25, 14, 25))

    def choose(language, keys, **kw):
        asked["young"] = kw["moment"].young
        return {}
    monkeypatch.setattr(sentence_score, "choose", choose)
    table = types.SimpleNamespace(head={"run_signature": "run"})
    chooser = analyzer.ListSentences("ja", 3, table=table)
    assert chooser([("食事", "しょくじ")], None) == {}
    assert reads == ["ja"] and asked["young"] == {"食べる": 1.0}
    assert chooser.young_at == analyzer.young_stamp({"食べる": 1.0})
    given = analyzer.ListSentences("ja", 3, table=table, young={})
    given([("食事", "しょくじ")], None)
    assert reads == ["ja"] and asked["young"] == {} and given.young_at is None


def test_the_redraw_after_a_move_shows_the_cards_sentence_and_marks_the_young_words_it_drew_with(run):
    # why: end to end, as the window runs it — a move, then the keeper's redraw (`--from-plan`) with Anki's young
    # file there: the list it writes shows the card's first sentence for each word a young card moves, and its marker
    # names those young words (so `moved_state` reads it as drawn until a sync moves them). Last in the module: it
    # moves the fixture's library.
    from tests.test_e_redraw import _columns, _move, _redraw
    words = [w for _k, w in run.found]
    young = _young_file(run.root, run.language, words)
    try:
        _move(run.root, run.language, "top")
        out = _redraw(run.root, run.language)
        assert "Redrew the journey" in out, out[-1500:]
        marker = analyzer.redrawn_for(run.results)
        assert marker.get("young") == analyzer.young_stamp({w: 1.0 for w in words}), marker
        listed = _columns(run.results)
        cards = _firsts(run, [k for k, _w in run.found])
    finally:
        os.remove(young)
    for key, _word in run.found:
        assert listed[key][1::-1] == cards[key]["card"], (run.language, key, listed[key][:2], cards[key])
