# SPDX-License-Identifier: GPL-3.0-or-later
"""`auto.reorder` hands its caller's automatic job on as it is (E3.1's line): the run fills in what the caller reads
back — the numbering's kind and tomorrow's front — on the very job the caller holds.

What a wrong answer would cost a learner: `surasura-cli junban --auto` (and `resort`) reporting no numbering — how
many of tomorrow's cards were placed — after a run that placed them, because the run filled in a copy. Against the
fake collection (real Japanese words, never Anki).
"""
from modules.junban import auto, spaced
from modules.junban.tests.test_auto_actions import _auto, _backlog
from modules.junban.tests.test_reposition import _patched


def test_the_callers_automatic_job_is_the_one_the_run_fills_in(tmp_path):
    fake = _backlog(tmp_path)
    job = spaced.Job(automatic=True)
    with _patched(fake):
        done = auto.reorder(_auto(), list_current=True, job=job)
    assert done["outcome"] == "ran", done
    assert job.actions is True, "the run was handed another job than the caller's"
    assert job.kind is not None and job.front_size is not None, "the caller can't read back what the run filled in"


def test_a_changed_later_tag_makes_the_parked_read_key_differ(tmp_path):
    # why: the parked-cards read is cached under its key; if the key ignored the later tag, a job after the tag was
    # changed would reuse the old read and never look at the parked cards under the new tag.
    from unittest import mock
    from modules.junban import reposition
    list_file = tmp_path / "order.csv"
    list_file.write_text("Word,Orth\n勉強,勉強\n", encoding="utf-8")
    settings = {"target_language": "ja"}
    decks = ["Lapis::Vocab"]
    with mock.patch.object(reposition, "order_csv_path", return_value=str(list_file)):
        before = reposition._parked_read_key(settings, decks, "Surasura_later", None)
        after = reposition._parked_read_key(settings, decks, "Surasura_later_v2", None)
        again = reposition._parked_read_key(settings, decks, "Surasura_later", None)
    assert before is not None and after is not None, "the list file was not read, so no key was made"
    assert before == again, "the same tag gave a different key, so the cache could never hit"
    assert before != after, "a changed later tag reused the parked read cached under the old tag"


def test_a_put_back_that_failed_only_on_note_fields_is_reported_as_owed_to_the_next_reorder():
    # why: a Put back that failed only on note fields (no suspend or tag failed) must still leave the run not ok
    # with a problem naming the next re-order, so the plan is not recorded as written and the next look tries again.
    # The owed failure is carried on the report so the next look can see it. GAP, stated on purpose: the public
    # path is not driven here. The caller's record gate (ok = not failures and not note_failures, verbs.py) and the
    # retry on the next run need a fake whose removeTags refuses on note fields alone; the test fake has no such
    # hook (refuse_note_writes refuses field writes, not tags). This pins the helper's report, which the gate reads.
    from modules.junban import reposition

    report = {}
    note = (1712345601, "欄の書き込みに失敗")
    reposition._put_back_owed(report, {"note_failures": [note]})
    assert report.get("ok") is False, report
    assert report.get("note_failures") == [note], report
    assert any("next re-order" in p and "欄の書き込みに失敗" in p for p in report.get("problems", [])), report
