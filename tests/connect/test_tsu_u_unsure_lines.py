"""Tsu-U (completes the part of Mattias's #364 that Michi-NT2 left out; based on his Tsubasa-sync #2): a card is never
cut from a line where tsubasa can't say which side of a cut it sits on.

Mattias's field report: Re:Zero S04E18, a Netflix subtitle on the AT-X broadcast — tsubasa found the two parts, but
the break lies somewhere inside a stretch it calls undetermined, and a card cut from 力を貸して！ (inside it) played
the next scene. tsubasa 0.1.12 says where (`undetermined`, `[[lo, hi], ...]` in video seconds, in its `--json`) and
places most breaks in the silence between two lines. When Connect has tsubasa re-time a copy in parts (Michi-NT2),
the spans it answered are kept with the job (its run folder, tied to the re-timed copy as written), and the next
pick from that copy cuts no card holding a line that starts inside one: the word takes another line, or waits.

What a wrong answer would cost: a card whose audio plays another scene (the report's), or — the other way — every
card of a re-timed episode held back for a span that names no line, or a span kept for a copy since replaced.

Real Japanese subtitles (`tests/Test Resources/ja/airing/`, as Michi-NT2's tests); tsubasa stood in for at
`fit_check._run`, never the machine's.
"""
import json
import os
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.connect import fit_check, runner
from app.connect import pick as picking
from tests.connect.test_nt2_retime import Tsubasa, _steps, library   # noqa: F401  (fixture)


# --- fit_check.retime: the spans tsubasa answered ------------------------------------------------------------- #

def _answer(**kw):
    return dict({"outcome": "CONFIDENT", "segments": [[272.5, 0.25], [None, -9.75]]}, **kw)   # a -10 s jump


@pytest.mark.parametrize("given, kept", [
    ([[228.4, 322.2]], [(228.4, 322.2), (218.4, 312.2)]),          # the span, and the span moved by the jump
    (None, []),                                          # tsubasa 0.1.11: no such field
    ([], []),
    ([[228.4]], []), ([["a", "b"]], []), ([[300.0, 200.0]], []), ("228.4-322.2", []), ([[True, 3.0]], []),
])
def test_retime_keeps_the_spans_tsubasa_answered_and_nothing_malformed(tmp_path, monkeypatch, library, given,
                                                                       kept):
    _data, full = library
    Tsubasa(monkeypatch, answer=_answer(**({} if given is None else {"undetermined": given})))
    made = fit_check.retime("video.mkv", full, str(tmp_path / "out"))
    assert made is not None and made.undetermined == pytest.approx(kept)


def test_each_span_is_also_kept_moved_by_its_cuts_jump():
    """Tsu-U review: a line given the other part's offset is written at the span moved by the jump — on a +40 s jump
    a subtitle line at 101 s, given +40, is written at 141 s, outside tsubasa's 98-115 s. Both stretches are unsure."""
    answer = {"segments": [[98.0, 0.0], [None, 40.0]], "undetermined": [[98.0, 115.0]]}
    assert fit_check.unsure_in_written(answer) == [(98.0, 115.0), (138.0, 155.0)]
    three = {"segments": [[98.0, 0.0], [500.0, 40.0], [None, 30.0]], "undetermined": [[98.0, 115.0], [480.0, 520.0]]}
    assert fit_check.unsure_in_written(three) == [(98.0, 115.0), (138.0, 155.0), (480.0, 520.0), (470.0, 510.0)]
    # segments that don't line up with the spans: the spans alone, never a guess
    assert fit_check.unsure_in_written({"segments": [[98.0, 0.0]], "undetermined": [[98.0, 115.0]]}) == [
        (98.0, 115.0)]
    assert fit_check.unsure_in_written({"undetermined": [[98.0, 115.0]]}) == [(98.0, 115.0)]


# --- Steps: kept with the job, read back for the very copy ------------------------------------------------------ #

def test_the_spans_of_a_retime_are_kept_with_its_job_for_that_copy(tmp_path, monkeypatch, library):
    _data, full = library
    Tsubasa(monkeypatch, answer=_answer(undetermined=[[228.4, 322.2]]))
    steps = _steps(tmp_path, monkeypatch)
    assert steps.retime("ja", {"id": 7}, "video.mkv", full) is True
    assert steps.unsure({"id": 7}, full) == pytest.approx([(228.4, 322.2), (218.4, 312.2)])
    assert steps.unsure({"id": 8}, full) == [], "another job's pick never reads them"
    assert steps.unsure({"id": 7}, full + ".other") == [], "only the copy tsubasa re-timed"


def test_a_copy_changed_since_its_retime_has_no_spans(tmp_path, monkeypatch, library):
    # the library copied its original over it again (S5): that text is checked again, with no old span
    _data, full = library
    Tsubasa(monkeypatch, answer=_answer(undetermined=[[228.4, 322.2]]))
    steps = _steps(tmp_path, monkeypatch)
    assert steps.retime("ja", {"id": 7}, "video.mkv", full) is True
    with open(full, "a", encoding="utf-8") as f:
        f.write("\n")
    assert steps.unsure({"id": 7}, full) == []


def test_a_retime_with_no_spans_leaves_none_from_before(tmp_path, monkeypatch, library):
    _data, full = library
    steps = _steps(tmp_path, monkeypatch)
    Tsubasa(monkeypatch, answer=_answer(undetermined=[[228.4, 322.2]]))
    assert steps.retime("ja", {"id": 7}, "video.mkv", full) is True
    Tsubasa(monkeypatch, answer=_answer(undetermined=[]))
    assert steps.retime("ja", {"id": 7}, "video.mkv", full) is True
    assert steps.unsure({"id": 7}, full) == []


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"copy": 3}), json.dumps({"spans": "x"})])
def test_a_record_that_cant_be_read_is_no_span_and_no_crash(tmp_path, monkeypatch, library, text):
    _data, full = library
    steps = _steps(tmp_path, monkeypatch)
    folder = steps.run_dir({"id": 7})
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, runner.UNSURE_FILE), "w", encoding="utf-8") as f:
        f.write(text)
    assert steps.unsure({"id": 7}, full) == []


def test_steps_pick_hands_the_spans_to_the_pick(tmp_path, monkeypatch, library):
    _data, full = library
    steps = _steps(tmp_path, monkeypatch)
    Tsubasa(monkeypatch, answer=_answer(undetermined=[[228.4, 322.2]]))
    assert steps.retime("ja", {"id": 7}, "video.mkv", full) is True
    seen = []

    def pick(ns):
        seen.append(ns.unsure)
        return {"words": [], "subtitle": None}
    monkeypatch.setattr(verbs, "pick", pick)
    monkeypatch.setattr(steps, "_plan_now", lambda lang: None)
    monkeypatch.setattr(steps, "_anki_miner_held", lambda lang: {})
    from app.connect import library as connect_library
    monkeypatch.setattr(connect_library, "made_words_for", lambda store, job: set())

    class _Store:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(steps, "_open", lambda lang: _Store())
    steps.pick("ja", {"id": 7, "item_id": 1}, "video.mkv", subtitle=full)
    steps.pick("ja", {"id": 9, "item_id": 1}, "video.mkv", subtitle=full)
    assert seen[0] == pytest.approx([(228.4, 322.2), (218.4, 312.2)]) and seen[1] == []


# --- verbs.pick: the spans reach the choosing ------------------------------------------------------------------ #

class _Chosen(Exception):
    pass


def test_verbs_pick_hands_the_spans_to_the_choosing_and_none_from_the_command_line(tmp_path, monkeypatch):
    subtitle = tmp_path / "話1.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,500\n約束だよ\n", encoding="utf-8")
    monkeypatch.setattr(verbs, "settings", lambda: {"target_language": "ja"})
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(verbs, "_listed", lambda args, lang: {("約束", "ヤクソク"): 0})
    monkeypatch.setattr(verbs, "_level_job", lambda job, lang: None)
    monkeypatch.setattr(verbs, "_connect_folder", lambda: str(tmp_path / "connect"))
    monkeypatch.setattr(picking, "carded", lambda *a, **k: (set(), "anki"))
    got = []

    def choose(*a, **kw):
        got.append(kw.get("unsure"))
        raise _Chosen()
    monkeypatch.setattr(picking, "pick", choose)
    base = dict(lang="ja", file=str(subtitle), video=None, words="list", job="8", wait=0.0)
    for ns in (SimpleNamespace(**base, unsure=[(1.5, 9.0)]), SimpleNamespace(**base)):
        with pytest.raises(_Chosen):
            verbs.pick(ns)
    assert got == [[(1.5, 9.0)], ()]
