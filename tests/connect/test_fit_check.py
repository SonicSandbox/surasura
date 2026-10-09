"""The fit check (P2.4 row 2.4.5; K89): an episode is mined only when its subtitle is known to be timed to its video.

What a wrong answer would cost: a card cut from a subtitle a few seconds off holds the wrong line's audio, and Connect
writes the user's Anki unattended. So only hato's `timed` verdict, or tsubasa's one-segment `CONFIDENT` answer, may
mine; a two-segment timing (it drifts part-way through), a refusal, an error, a garbled answer or no tsubasa at all
must each stop the episode with a plain reason. The program is a stand-in (`run=`): it returns the bytes tsubasa
would print, so no real tsubasa runs and nothing touches a file.
"""
import json
from types import SimpleNamespace

from app.connect import fit_check

VIDEO = "C:/Video/上層部の話 01.mkv"
SUBTITLE = "C:/Subs/上層部の話 01.srt"
ONE_SEGMENT = {"start": 0.0, "end": 1420.5, "offset": 0.0}
TWO_SEGMENTS = [ONE_SEGMENT, {"start": 1420.5, "end": 1500.0, "offset": 3.2}]


def _tsubasa(answer, stdout=None):
    """A stand-in for `subprocess.run`: prints one JSON line, the way tsubasa does with --json."""
    body = stdout if stdout is not None else json.dumps(answer) + "\n"
    data = body.encode("utf-8") if isinstance(body, str) else body
    return lambda command, **kw: SimpleNamespace(stdout=data)


def _check(answer=None, stdout=None, pairing=None):
    return fit_check.check(pairing, VIDEO, SUBTITLE, tsubasa="tsubasa",
                           run=_tsubasa(answer, stdout))


def _hato_record(subtitle_bytes, **over):
    """hato's pairing record as 09-hato-layer writes it: schema 1, `timed`, one segment, the copy's sha256."""
    import hashlib
    record = {"schema": 1, "verdict": "timed", "subtitle_sha256": hashlib.sha256(subtitle_bytes).hexdigest(),
              "timing": {"outcome": "CONFIDENT", "offset_s": -1.24, "segments": 1}}
    record.update(over)
    return record


def test_hatos_timed_verdict_mines_without_running_tsubasa(tmp_path):
    # hato already paired it as timed, and the library's copy is the file it timed: tsubasa must not be asked again (a
    # second run costs about a second an episode), and no offset is applied (hato's copy is already shifted).
    def must_not_run(*_a, **_kw):
        raise AssertionError("tsubasa ran although hato said timed")

    body = "1\n00:00:01,000 --> 00:00:02,500\n上層部の決定だ\n".encode("utf-8")
    subtitle = tmp_path / "上層部の話 01.srt"
    subtitle.write_bytes(body)
    got = fit_check.fit(_hato_record(body), VIDEO, str(subtitle), tsubasa="tsubasa", run=must_not_run)
    assert got == (fit_check.TIMED, "hato", None, 0.0)


def test_a_hato_timed_record_that_fails_the_gate_goes_to_tsubasa(tmp_path):
    # 09-hato-layer's gate: schema 1, one segment and the copy's sha256 all hold, else Connect asks tsubasa itself —
    # a copy edited since hato timed it, or a record of a schema this Surasura doesn't know, is never trusted.
    body = "1\n00:00:01,000 --> 00:00:02,500\n上層部の決定だ\n".encode("utf-8")
    subtitle = tmp_path / "上層部の話 01.srt"
    subtitle.write_bytes(body)
    asked = []

    def tsubasa(command, **kw):
        asked.append(command)
        return SimpleNamespace(stdout=(json.dumps({"outcome": "CONFIDENT", "segments": [
            {"start": 0.0, "end": 1420.5, "offset": 1.24}]}) + "\n").encode("utf-8"))

    for record in (_hato_record(body, schema=2), _hato_record(body, timing={"segments": 2}),
                   _hato_record(body, timing=None), _hato_record("別のファイル".encode("utf-8"))):
        got = fit_check.fit(record, VIDEO, str(subtitle), tsubasa="tsubasa", run=tsubasa)
        assert got == (fit_check.TIMED, "tsubasa", None, 1.24)      # tsubasa's one segment: its offset is cut by
    assert len(asked) == 4


def test_a_confident_answer_with_exactly_one_segment_is_timed():
    assert _check({"outcome": "CONFIDENT", "segments": [ONE_SEGMENT]}) == (fit_check.TIMED, "tsubasa", None)


def test_a_confident_answer_with_two_segments_is_not_timed_and_says_why():
    # Two segments means the timing shifts part-way through: a card from it would hold the wrong line's audio.
    got = _check({"outcome": "CONFIDENT", "segments": TWO_SEGMENTS})
    assert got[0] == fit_check.NOT_TIMED
    assert got[1] == "tsubasa"
    assert "changes part-way" in got[2]


def test_a_confident_answer_with_no_segments_is_not_timed():
    got = _check({"outcome": "CONFIDENT", "segments": []})
    assert got[0] == fit_check.NOT_TIMED and got[1] == "tsubasa"


def test_a_refused_answer_is_not_timed_and_carries_tsubasas_reason():
    got = _check({"outcome": "REFUSED", "segments": [ONE_SEGMENT], "reason": "no speech match"})
    assert got[0] == fit_check.NOT_TIMED
    assert "refused" in got[2] and "no speech match" in got[2]


def test_a_garbled_answer_with_no_json_line_is_not_timed():
    got = _check(stdout=b"tsubasa: unexpected crash\n")
    assert got == (fit_check.NOT_TIMED, "tsubasa", "tsubasa gave no answer, so no cards.")


def test_an_absent_tsubasa_program_is_not_timed_without_running_anything():
    # "" means no program: the check must stop before any command is built or run.
    def must_not_run(*_a, **_kw):
        raise AssertionError("ran with no tsubasa program")

    got = fit_check.check(None, VIDEO, SUBTITLE, tsubasa="", run=must_not_run)
    assert got == (fit_check.NOT_TIMED, None, "Not timed to its video, so no cards.")
