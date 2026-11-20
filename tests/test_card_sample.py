"""Mado-EZC (SPEC-r2 §0.3, lane 3's gate): *Which words get a card?*'s picture is Connect's picker's own answer.

`card_sample.sample` draws the mine line's first episode for each choice of `connect_mine_words`. Its numbers and its
marks must be exactly `pick.pick()`'s on the same episode — the card's span (`others()`), one card per word, the list —
so the picture can never promise a card Connect won't make. *From another episode* (only *Only one-new-word
sentences*) is drawn only for a word another episode of the mine line has alone on a line.

The view is built in a child process, as the warm arrivals worker builds it (the analyzer's and the names' globals stay
out of this process), over the real known words of `tests/Test Resources`, on real episodes: the shipped 喫茶店の朝 and
the zh night-market episode.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from app.services import card_sample

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPISODES = {"ja": os.path.join(REPO, "samples", "ja", "HighPriority", "喫茶店の朝.srt"),
            "zh": os.path.join(REPO, "tests", "Test Resources", "zh", "night_market.srt")}
KNOWN = {"ja": ("ja", "KnownWord.json"), "zh": ("zh", "KnownWords.json")}

# The child: the bare view (no plan: the worker's view before a first Generate), every new word of the episode read by
# the picker, a list made of them (two words with no other new word left off: rarer than the Level), the picture, and
# each mode's pick() over the same cues and list — the oracle.
_CHILD = r"""
import json, os, sys
from app import analyzer, arrivals, cues, plan_engine
from app.services import card_sample
language, first, others, learn = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4] == "1"
args = analyzer.parse_analysis_args([f"--language={language}"])
bare = plan_engine.Plan({"floor": 0, "run_signature": None, "phrase_entries": []}, [], [], [], [], [])
view = arrivals.View.build(language, bare, None, args)
read = cues.read(first, language)
every = arrivals.pick_cues(view, read, None, mode="unknown")["words"]
if learn:
    # a learner who knows most of this episode: every word known but one on each even line and two on each odd one
    lines = []
    for w in every:
        if w["line_start"] not in lines:
            lines.append(w["line_start"])
    new, per_line = set(), {}
    for w in every:
        k = lines.index(w["line_start"])
        if per_line.get(k, 0) < 1 + k % 2:
            per_line[k] = per_line.get(k, 0) + 1
            new.add((w["word"], w["reading"]))
    from app.path_utils import get_user_files_path
    path = os.path.join(get_user_files_path(language), "KnownWord.json")
    with open(path, encoding="utf-8") as f:
        known = json.load(f)
    known["words"] += [{"dictForm": w["word"], "secondary": w["reading"] or "", "partOfSpeech": "",
                        "language": language, "knownStatus": "KNOWN"} for w in every
                       if (w["word"], w["reading"]) not in new]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(known, f, ensure_ascii=False)
    view = arrivals.View.build(language, bare, None, args, tokenizer=view.tokenizer)
    every = arrivals.pick_cues(view, read, None, mode="unknown")["words"]
if others == ["halves"]:
    # another episode: each line holding two new words cut between them (each half alone), 10 s apart
    by_line = {}
    for w in every:
        by_line.setdefault((w["line_start"], w["line_text"]), []).append(w)
    parts = []
    for (_at, text), ws in sorted(by_line.items()):
        cuts = sorted({text.find(w["surface"]) + len(w["surface"]) for w in ws if text.find(w["surface"]) >= 0})
        start = 0
        for cut in cuts[:-1]:
            parts.append(text[start:cut])
            start = cut
        parts.append(text[start:])
    others = [os.path.join(os.path.dirname(os.path.dirname(first)), "halves.srt")]
    with open(others[0], "w", encoding="utf-8", newline="\n") as f:
        for n, text in enumerate(p for p in parts if p.strip()):
            f.write(f"{n + 1}\n00:{n * 10 // 60:02d}:{n * 10 % 60:02d},000 --> 00:{n * 10 // 60:02d}:"
                    f"{n * 10 % 60:02d},900\n{text.strip()}\n\n")
alone = [(w["word"], w["reading"]) for w in every if not w["other_new"]]
rare = set(alone[1::2][:2])
listed = {(w["word"], w["reading"]): n for n, w in enumerate(every) if (w["word"], w["reading"]) not in rare}
oracle = {m: arrivals.pick_cues(view, read, listed, mode=m)["words"] for m in card_sample.MODES}
away = {}
for path in others:
    away[path] = arrivals.pick_cues(view, cues.read(path, language), listed, mode="i1")["words"]
out = {"rare": sorted(rare), "oracle": oracle, "away": away, "others": others,
       "picture": card_sample.sample(view, [first] + others, listed, carded=set()),
       "alone": card_sample.sample(view, [first], listed, carded=set())}
print("OUT " + json.dumps(out, ensure_ascii=False))
"""


def _env(root):
    env = dict(os.environ, SURASURA_TEST_ROOT=str(root), PYTHONIOENCODING="utf-8")
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _child(root, language, first, others=(), learn=False):
    p = subprocess.run([sys.executable, "-c", _CHILD, language, first, json.dumps(list(others)), "1" if learn else "0"],
                       cwd=REPO,
                       env=_env(root), capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-4000:]
    return json.loads(next(line for line in p.stdout.splitlines() if line.startswith("OUT "))[4:])


def _root(tmp_path, language):
    """A user root holding the real known words of `tests/Test Resources` (never the developer's)."""
    root = tmp_path / "root"
    folder, name = KNOWN[language]
    user = root / "User Files" / language
    user.mkdir(parents=True)
    shutil.copy(os.path.join(REPO, "tests", "Test Resources", folder, name), str(user / "KnownWord.json"))
    return root


def _clauses(src, dst, language):
    """Another episode made of `src`'s own lines cut at each clause (、 。 ， … and the like), one cue each, 10 s apart
    (no card's lines reach the next: gaps over 2 s): a word that shared its sentence with another new word may stand
    alone on a line here — real text, the way a later episode says the same words again."""
    from app import cues
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    parts = []
    for cue in cues.read(src, language):
        for piece in re.split(r"(?<=[、。，,！？!?])", cue.text or ""):
            if piece.strip() and not piece.startswith("♪"):
                parts.append(piece.strip())
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        for n, text in enumerate(parts):
            start = n * 10
            f.write(f"{n + 1}\n00:{start // 60:02d}:{start % 60:02d},000 --> 00:{start // 60:02d}:"
                    f"{start % 60:02d},900\n{text}\n\n")
    return dst


def _key(w):
    return (w["word"], w["reading"])


def _episode(tmp_path, language):
    """(the child's answer) for `language`'s case. Japanese: the shipped café episode as it is, under the fixture
    learner's own known words, and the same episode cut at each clause as another episode of the mine line. Chinese:
    the night-market episode cut at each clause (the fixture's 10 known words know none of it, so the learner here
    knows all of it but one word on every other line and two on the rest), and another episode of its two-new-word
    lines cut between the two words."""
    root = _root(tmp_path, language)
    if language == "ja":
        other = _clauses(EPISODES["ja"], str(tmp_path / "later.ja.srt"), "ja")
        return _child(root, "ja", EPISODES["ja"], [other])
    first = _clauses(EPISODES["zh"], str(tmp_path / "data" / "ep01.zh.srt"), "zh")
    return _child(root, "zh", first, ["halves"], learn=True)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_picture_counts_each_choice_exactly_as_connects_picker_does(tmp_path, language):
    # Why: the picker must never promise a card Connect won't make — every number and mark is pick()'s own answer on
    # the same episode, for all three choices, its "N new" the card's span (others()), never the sentence alone.
    out = _episode(tmp_path, language)
    pic, oracle = out["picture"], out["oracle"]
    assert pic is not None and not pic["sample"] and pic["elsewhere_exact"]
    assert 2 <= len(pic["lines"]) <= card_sample.LINES
    assert any(line["new"] > 1 for line in pic["lines"]) and any(line["new"] == 1 for line in pic["lines"])
    rare = {tuple(k) for k in out["rare"]}
    for mode in card_sample.MODES:
        picked = {_key(w): w for w in oracle[mode]}
        assert pic["counts"][mode]["here"] == len(picked), mode
        for line in pic["lines"]:
            for w in line["words"]:
                got, key = w["outcome"][mode], _key(w)
                if key in picked:
                    assert got == ("amber" if picked[key]["other_new"] else "card"), (mode, key)
                else:
                    assert got in ("rare", "other", "none"), (mode, key)
                    assert (got == "rare") == (mode == "list" and key in rare), (mode, key)
    # the line a word is drawn on is the line the list's pick cuts its card from, its count that card's span
    by_list = {_key(w): w for w in oracle["list"]}
    for line in pic["lines"]:
        for w in line["words"]:
            if _key(w) in by_list:
                assert line["text"] == by_list[_key(w)]["line_text"]
                assert line["new"] == 1 + by_list[_key(w)]["other_new"]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_another_episode_only_when_one_of_the_mine_line_has_the_word_alone(tmp_path, language):
    # Why: *Only one-new-word sentences* gives a word with no such line here its card from another episode — but only
    # when another episode Connect reaches really has a line where it is the only new word; else it gets none.
    out = _episode(tmp_path, language)
    here = {_key(w) for w in out["oracle"]["i1"]}
    lost = {_key(w) for w in out["oracle"]["unknown"]} - here
    expected = lost & {_key(w) for w in out["away"][out["others"][0]]}
    assert expected, "the clause-cut episode should hold some lost word alone (the case under test)"
    pic = out["picture"]
    assert pic["counts"]["i1"]["elsewhere"] == len(expected)
    drawn = [w for line in pic["lines"] for w in line["words"]]
    for w in drawn:
        assert (w["outcome"]["i1"] == "other") == (_key(w) in expected), _key(w)
        assert all(w["outcome"][m] != "other" for m in ("list", "unknown"))
    # The same episode with no other episode on the mine line: nothing comes from elsewhere
    alone = out["alone"]
    assert alone["counts"]["i1"]["elsewhere"] == 0
    assert all(w["outcome"]["i1"] != "other" for line in alone["lines"] for w in line["words"])
    assert {m: alone["counts"][m]["here"] for m in card_sample.MODES} == \
        {m: pic["counts"][m]["here"] for m in card_sample.MODES}       # another episode never changes what's here


def test_the_bundled_picture_is_the_specs_four_lines_with_your_list_first():
    # Why: with no library yet the picker still teaches the difference (SPEC-r2 §0.3): 香り is on the list and gets its
    # card; モカブレンド, rarer than the Level, gets none under Your list; the two-new-word line is two amber cards, and
    # under Only one-new-word sentences each comes from another episode ("up to": nothing was read).
    pic = card_sample.fallback("ja")
    assert pic["sample"] and not pic["elsewhere_exact"] and pic["source"] == "喫茶店の朝"
    assert [line["new"] for line in pic["lines"]] == [1, 2, 1, 1]
    words = {w["word"]: w["outcome"] for line in pic["lines"] for w in line["words"]}
    assert words["香り"] == {"list": "card", "unknown": "card", "i1": "card"}
    assert words["モカブレンド"] == {"list": "rare", "unknown": "card", "i1": "card"}
    assert words["出てくる"] == words["調べる"] == {"list": "amber", "unknown": "amber", "i1": "other"}
    assert {m: (c["here"], c["elsewhere"]) for m, c in pic["counts"].items()} == \
        {"list": (4, 0), "unknown": (5, 0), "i1": (3, 2)}
    zh = card_sample.fallback("zh")
    assert zh["source"] == "孔乙己" and [line["new"] for line in zh["lines"]] == [1, 2, 1, 1]
    assert {m: (c["here"], c["elsewhere"]) for m, c in zh["counts"].items()} == \
        {"list": (4, 0), "unknown": (5, 0), "i1": (3, 2)}
    assert card_sample.fallback("ko") == card_sample.fallback("ja")       # any other language: the Japanese one


def test_an_episode_without_a_two_new_word_line_is_drawn_as_the_bundled_sample():
    # Why: the picture exists to show one new word vs two; an episode whose list words all sit alone can't show it,
    # so the window draws the bundled sample (named a sample) instead of a picture that teaches nothing.
    alone = [{"word": "急に", "reading": "キュウニ", "surface": "急に", "listed": True, "other_new": 0,
              "line_start": 17.6, "line_text": "ええ、駅まで歩いてきたら、急に雨が降ってきて。"}]
    assert card_sample.picture({"list": alone, "unknown": alone, "i1": alone}) is None
    assert card_sample.picture({"list": [], "unknown": [], "i1": []}) is None       # an empty episode, no list


def test_the_worker_answers_no_picture_without_a_list_and_reads_nothing_twice(tmp_path, monkeypatch):
    # Why: before a first Generate there is no list — the window draws the bundled sample, never a picture of an
    # empty list; and the same files asked again are never read again (S19).
    from app import arrivals_worker
    worker = arrivals_worker.Worker.__new__(arrivals_worker.Worker)
    worker.language, worker.send_grammar, worker.known_sig = "ja", True, "k"
    worker.answers = arrivals_worker.OrderedDict()
    warm = {"view": object(), "order": None, "listed": {}, "signature": None}
    worker.current = lambda force=False: warm
    calls = []
    monkeypatch.setattr(card_sample, "sample", lambda *a, **k: calls.append(a) or {"lines": []})
    monkeypatch.setattr(card_sample, "top_paths", lambda language: [EPISODES["ja"]])
    assert worker.answer({"id": 1, "op": "sample"})["picture"] is None and not calls       # no plan: no list
    warm.update(order=object(), listed={("急に", "キュウニ"): 0}, signature="s1")
    first = worker.answer({"id": 2, "op": "sample"})
    assert first["picture"] == {"lines": []} and not first["cached"] and len(calls) == 1
    assert worker.answer({"id": 3, "op": "sample"})["cached"] and len(calls) == 1
    gone = str(tmp_path / "gone.srt")                                     # a file gone since: never read
    assert worker.answer({"id": 4, "op": "sample", "paths": [gone]})["picture"] is None and len(calls) == 1
