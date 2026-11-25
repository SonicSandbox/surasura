"""DSA-CONNECT (G6, the DSA audit of 2026-11-25): Best's mine picks once more in every other episode a word's line is
cut from (`runner._borrow` → `Steps.pick` with `only` → `verbs.pick`), and each of those picks read again what the
episode's own pick had just read for the same job — the settings, the tokenizer, the known test, the phrases, Anki
Miner's look-ups and the note type (two Anki calls), the carded set (a probe, findNotes and KnownWord.json), the
learning view, the young words — and looked each other episode's video up again and again (`_best`'s reach, its loop
and `_borrow`: up to 60 look-ups for 11 episodes, each a store open and the pairing). The DevTest split (Bocchi ep 01,
10 other episodes): ~2.4 s of Best's 4.2 s pick was that.

The standard choice: one pick context a job (`verbs.pick`'s `context`, started by the episode's own pick in
`Steps.pick`, read by its borrows) and each video looked up once a pick step (`runner._VideosOnce`). What each test
holds: the counters (red on the code before), and the same answer as a pick that reads everything itself.

Real subtitles (lines as `tests/Test Resources/ja|zh` write them), the cue reader and the tokenizer as a mine runs them.
"""
import contextlib
import os
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.connect import pick, runfile, sentences
from app.connect.ledger import Ledger

LINES = {"ja": ["約束だよ、明日の朝に駅で会おうね。", "その約束、ちゃんと覚えてる？"],
         "zh": ["我们明天早上在车站见面吧。", "你还记得那个约定吗？"]}
WORD = {"ja": "約束", "zh": "约定"}


def _srt(path, lines):
    path.write_text("".join(f"{n}\n00:00:0{n},000 --> 00:00:0{n},900\n{t}\n\n" for n, t in enumerate(lines, 1)),
                    encoding="utf-8")
    return str(path)


@pytest.fixture
def counted(monkeypatch, tmp_path):
    """`verbs.pick` with every per-job read counted: {name: calls}. The episode files and a video stand-in in
    tmp_path; Anki Miner's look-ups answer as an installed one would (its deck), nothing reaches Anki."""
    calls = {}

    def counting(owner, name, fn=None):
        real = fn or getattr(owner, name)

        def counted_call(*a, **k):
            calls[name] = calls.get(name, 0) + 1
            return real(*a, **k)
        monkeypatch.setattr(owner, name, counted_call)

    counting(verbs, "settings", lambda: {"target_language": "ja", "exclude_single": True})
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(verbs, "_level_job", lambda job, lang: None)
    monkeypatch.setattr(verbs, "_swap_spec", lambda job, lang: None)
    monkeypatch.setattr(verbs, "_connect_folder", lambda: str(tmp_path / "connect"))
    counting(verbs, "_reading")
    counting(verbs, "_known_test", lambda lang, tokenizer, script: (lambda key: key[0] != WORD[lang]))
    counting(verbs, "_phrase_set", lambda loaded, lang: None)
    mapping = SimpleNamespace(deck="Mining", own_deck=None)
    counting(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir, held=None: ({"app": "3.13.0", "features": []},
                                                                                 "p1", mapping))
    counting(pick, "carded", lambda language, settings, decks=(): ({"既に"}, "anki"))
    counting(verbs, "_counted", lambda lang: (None, 0))
    counting(sentences, "young_weights", lambda language: {})
    monkeypatch.setattr(sentences, "lines_in", lambda *a, **k: None)      # (the score's lines: not this test's)
    for name in ("episode", "word_requests", "config", "build"):          # (the run file: not this test's)
        monkeypatch.setattr(runfile, name, lambda *a, **k: {})
    monkeypatch.setattr(runfile, "write", lambda path, data: path)
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"")
    return calls, str(video)


def _ns(lang, subtitle, video, job="12", context=None, only=None):
    ns = dict(lang=lang, file=subtitle, video=video, words="unknown", job=job, wait=0.0, made=set(), listed={},
              reading=None)
    if only:
        ns.update(only=only, aside="from-3")
    if context is not None:
        ns["context"] = context
    return SimpleNamespace(**ns)


PER_JOB = ("settings", "_reading", "_known_test", "_phrase_set", "_anki_miner_setup", "carded", "_counted",
           "young_weights")


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_one_jobs_own_pick_and_its_borrowed_picks_read_the_jobs_context_once(counted, tmp_path, monkeypatch, lang):
    # why: G6 — every borrowed pick read the job's settings, tokenizer, known test, phrases, Anki Miner's look-ups and
    # the note type, the carded set and the view again (DevTest: the carded set alone 1.05 s over 10 episodes)
    calls, video = counted
    own = _srt(tmp_path / "ep01.srt", LINES[lang])
    other = _srt(tmp_path / "ep02.srt", LINES[lang][::-1])
    key = next((w["word"], w["reading"]) for w in verbs.pick(_ns(lang, own, video))["words"])
    calls.clear()
    context = {}
    mine = verbs.pick(_ns(lang, own, video, context=context))
    borrowed = [verbs.pick(_ns(lang, other, video, context=context, only=[key])) for _ in range(2)]
    assert {name: calls.get(name, 0) for name in PER_JOB} == {name: 1 for name in PER_JOB}, \
        "the episode's own pick reads the job's context; its borrowed picks read none of it again"
    # the same answers as picks that read everything themselves
    calls.clear()
    assert verbs.pick(_ns(lang, own, video)) == mine
    assert [verbs.pick(_ns(lang, other, video, only=[key])) for _ in range(2)] == borrowed
    assert borrowed[0]["words"] and borrowed[0]["words"][0]["word"] == key[0]
    # the command line's pick (no context) reads everything at every call, as before
    assert {name: calls.get(name, 0) for name in PER_JOB} == {name: 3 for name in PER_JOB}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_another_job_in_the_same_context_reads_everything_again(counted, tmp_path, lang):
    # why: the context is one job's: a card made by the job before it (the carded set), a deck switched, settings
    # changed between jobs — the next job reads them itself
    calls, video = counted
    own = _srt(tmp_path / "ep01.srt", LINES[lang])
    context = {}
    verbs.pick(_ns(lang, own, video, job="12", context=context))
    verbs.pick(_ns(lang, own, video, job="13", context=context))
    assert {name: calls.get(name, 0) for name in PER_JOB} == {name: 2 for name in PER_JOB}
    assert context["job"] == "13"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_steps_pick_hands_a_borrow_its_jobs_context_and_anything_else_a_new_one(monkeypatch, tmp_path, lang):
    # why: the runner's half — `_borrow`'s picks (`only`, the same job) read the context the episode's own pick
    # started; the next episode's pick, another job, and any pick after a failure start a new one
    from app.connect import library, runner
    steps = runner.Steps({"target_language": lang})
    subtitle = _srt(tmp_path / "ep01.srt", LINES[lang])
    steps.subtitle = lambda lang, job: subtitle
    steps._open = lambda lang: contextlib.nullcontext(None)
    steps._plan_now = lambda lang: None
    steps.unsure = lambda job, subtitle: []
    monkeypatch.setattr(library, "made_words_for", lambda store, job: set())
    seen, fail = [], []

    def picked(ns):
        seen.append(ns.context)
        if fail:
            raise KeyError(fail.pop())
        ns.context.setdefault("job", ns.job)
        return {"words": []}
    monkeypatch.setattr(verbs, "pick", picked)
    job = {"id": 12, "item_id": 1}
    steps.pick(lang, job, None)
    steps.pick(lang, dict(job, item_id=3, only=[(WORD[lang], "")]), None)
    steps.pick(lang, dict(job, item_id=4, only=[(WORD[lang], "")]), None)
    assert seen[1] is seen[0] and seen[2] is seen[0], "a borrow reads its job's context"
    steps.pick(lang, job, None)
    assert seen[3] is not seen[0], "the episode's own pick again: a new context"
    steps.pick(lang, {"id": 13, "item_id": 3, "only": [(WORD[lang], "")]}, None)
    assert seen[4] is not seen[3], "another job's borrow never reads this one's"
    fail.append("a pick that failed part way")
    with pytest.raises(KeyError):
        steps.pick(lang, dict(job, item_id=3, only=[(WORD[lang], "")]), None)
    steps.pick(lang, dict(job, item_id=3, only=[(WORD[lang], "")]), None)
    assert seen[6] is not seen[5], "after a failure the next pick reads everything again"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_best_pick_step_looks_each_other_episodes_video_up_once(tmp_path, monkeypatch, lang):
    # why: G6 — `_best`'s reach, its loop (once a word) and `_borrow` each asked `steps.video` of the same episode:
    # 60 look-ups for 11 episodes on DevTest, each a store open and the pairing
    from app.connect import runner
    from tests.connect.test_kantan_ma_left_out import WORDS, _run, _steps
    monkeypatch.setattr(runfile.time, "sleep", lambda s: None)
    home, away = WORDS[lang]
    steps = _steps(tmp_path, lang)
    steps.plan["words"]["2"] = [home, away]
    steps._settings = lambda lang: {"connect_sentence_dial": sentences.BEST}
    asked = []
    real = steps.video
    steps.video = lambda lang, job: asked.append(job["item_id"]) or real(lang, job)
    here = "/library/1.ja.srt"
    better = sentences.Choice("/library/2.ja.srt", 2, LINES[lang][0], 0, 0.5, False, True)
    own = sentences.Choice(here, 1, LINES[lang][1], 2, 0.5, True, True)

    def choose(lang, keys, **kw):
        assert kw["here"] == here and kw["reach"](2)
        return {key: [better, own] for key in keys}
    monkeypatch.setattr(sentences, "choose", choose)
    jobs = _run(steps, str(tmp_path / "ledger.sqlite"), lang)
    assert [(kind, state) for _id, kind, state in jobs] == [("mine", "done")]
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        picked = ledger.picked(jobs[0][0])
    assert sorted(w.get("from") for w in picked["words"]) == [2, 2], "both words cut from episode 2's lines"
    assert asked.count(2) == 1, f"episode 2's video looked up {asked.count(2)} times in one pick step"
