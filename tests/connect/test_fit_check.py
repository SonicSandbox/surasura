"""The fit check (P2.4 row 2.4.5; K89): an episode is mined only when its subtitle is known to be timed to its video.

What a wrong answer would cost: a card cut from a subtitle a few seconds off holds the wrong line's audio, and Connect
writes the user's Anki unattended. So only hato's `timed` verdict, or tsubasa's one-segment `CONFIDENT` answer, may
mine; a two-segment timing (it drifts part-way through), a refusal, an error, a garbled answer or no tsubasa at all
must each stop the episode with a plain reason. The program is a stand-in (`run=`): it returns the bytes tsubasa
would print, so no real tsubasa runs and nothing touches a file.
"""
import json
import subprocess
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
    """hato's pairing record as 09-hato-layer v2 writes it: schema 1, `timed`, one segment against a text track, the
    copy's sha256."""
    import hashlib
    record = {"schema": 1, "verdict": "timed", "subtitle_sha256": hashlib.sha256(subtitle_bytes).hexdigest(),
              "timing": {"outcome": "CONFIDENT", "offset_s": -1.24, "segments": 1, "reference": "text-track"}}
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


def _timed_by(reference, tmp_path):
    """`fit` on a hato `timed` record whose timing names `reference` (None: no `reference` at all) -> (its answer, how
    often tsubasa was asked)."""
    body = "1\n00:00:01,000 --> 00:00:02,500\n上層部の決定だ\n".encode("utf-8")
    subtitle = tmp_path / "上層部の話 01.srt"
    subtitle.write_bytes(body)
    timing = {"outcome": "CONFIDENT", "offset_s": -1.24, "segments": 1}
    if reference is not None:
        timing["reference"] = reference
    asked = []

    def tsubasa(command, **kw):
        asked.append(command)
        return SimpleNamespace(stdout=(json.dumps({"outcome": "CONFIDENT", "segments": [
            {"start": 0.0, "end": 1420.5, "offset": 1.24}]}) + "\n").encode("utf-8"))

    got = fit_check.fit(_hato_record(body, timing=timing), VIDEO, str(subtitle), tsubasa="tsubasa", run=tsubasa)
    return got, len(asked)


def test_each_of_tsubasas_three_references_is_hatos_word(tmp_path):
    # 09-hato-layer v2 P13: hato times against a text track, a picture (bitmap) track or a speech mask — each is a
    # real tsubasa check, so the record is mined on hato's word with no second run and no offset
    assert fit_check.REFERENCES == ("text-track", "picture-track", "speech-mask")
    for reference in fit_check.REFERENCES:
        assert _timed_by(reference, tmp_path) == ((fit_check.TIMED, "hato", None, 0.0), 0), reference


def test_a_reference_absent_v1s_subtitle_or_unknown_goes_to_tsubasa(tmp_path):
    # v2: `subtitle` named no tsubasa reference and is dropped; a value this Surasura doesn't know (tsubasa's own
    # spelling "bitmap track", or none at all) means "check it yourself" — never mined on hato's word
    for reference in (None, "subtitle", "bitmap track"):
        assert _timed_by(reference, tmp_path) == ((fit_check.TIMED, "tsubasa", None, 1.24), 1), reference


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
    assert got == (fit_check.NOT_TIMED, None, fit_check.NO_CHECKER)


def test_with_nothing_to_check_it_the_reason_names_the_cause_and_the_switch():
    # Laptop try row 9: every episode said "Not timed" although its subtitles were synced — Connect never looked,
    # because nothing on the PC could check them. The reason must say so (no tsubasa) and name the way out, not read
    # as a verdict on the subtitle.
    got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="", run=None)
    assert got[0] == fit_check.NOT_TIMED
    assert "no tsubasa" in got[2] and "Trust my subtitles’ timing" in got[2]


def test_trusting_your_subtitles_mines_an_unpaired_episode_at_its_own_times_without_a_checker():
    # P-LF-9 (off by default): with the switch on and nothing on this PC to check it, an episode hato never paired
    # (a library folder's, one you placed) mines at its subtitle's own times — no shift, nothing run.
    def must_not_run(*_a, **_kw):
        raise AssertionError("ran with no tsubasa program")

    got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="", run=must_not_run, trust=True)
    assert got == (fit_check.TIMED, "you", None, 0.0)
    assert fit_check.check(None, VIDEO, SUBTITLE, tsubasa="", run=must_not_run, trust=True)[0] == fit_check.TIMED


def test_trust_is_off_by_default():
    # The signed rule (K16 / G1.3-6) holds until the switch is turned on: no checker, no pairing → not timed.
    assert fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="")[0] == fit_check.NOT_TIMED
    assert fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="", trust=False)[0] == fit_check.NOT_TIMED


def test_trust_never_overrules_hatos_own_untimed_or_extracted_verdict(tmp_path):
    # hato placed these by name only (untimed) or took the video's own track out unchecked (extracted): a pairing
    # that says it isn't checked still waits for *Mine anyway*, switch or not.
    body = "1\n00:00:01,000 --> 00:00:02,500\n上層部の決定だ\n".encode("utf-8")
    subtitle = tmp_path / "上層部の話 01.srt"
    subtitle.write_bytes(body)
    for verdict in ("untimed", "extracted", "forced", "timed"):
        record = _hato_record(body, verdict=verdict, subtitle_sha256="0" * 64)    # "timed" here fails the sha256
        got = fit_check.fit(record, VIDEO, str(subtitle), tsubasa="", trust=True)
        assert got[0] == fit_check.NOT_TIMED, verdict
        assert "Trust my subtitles" not in got[2], "the switch can't release it: don't point at it"


def test_trust_leaves_an_installed_tsubasa_in_charge():
    # tsubasa on this PC is a real check: its refusal still stops the episode, its one segment's offset still cuts.
    refused = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", trust=True,
                            run=_tsubasa({"outcome": "REFUSED", "reason": "no speech match"}))
    assert refused[0] == fit_check.NOT_TIMED and refused[1] == "tsubasa"
    shifted = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", trust=True,
                            run=_tsubasa({"outcome": "CONFIDENT", "segments": [dict(ONE_SEGMENT, offset=2.5)]}))
    assert shifted == (fit_check.TIMED, "tsubasa", None, 2.5)


def test_connects_steps_read_the_switch_from_settings(monkeypatch):
    # The runner's real fit step hands `connect_trust_timing` to the check: absent or false → the signed rule; true →
    # an unpaired episode with no checker mines.
    from app.connect import runner
    monkeypatch.setattr(fit_check, "find_tsubasa", lambda: None)
    job = {"id": 1, "item_id": 1}
    assert runner.Steps({}).fit("ja", job, None, VIDEO, SUBTITLE)[0] == fit_check.NOT_TIMED
    assert runner.Steps({"connect_trust_timing": False}).fit("ja", job, None, VIDEO, SUBTITLE)[0] == fit_check.NOT_TIMED
    assert runner.Steps({"connect_trust_timing": True}).fit("ja", job, None, VIDEO, SUBTITLE) == (
        fit_check.TIMED, "you", None, 0.0)


def test_a_tsubasa_run_that_fails_to_start_or_times_out_is_retried_not_refused():
    # A file read whole over a slow share, or a program that won't start, is no answer about the timing: the runner
    # must ask again (RETRY), never mark the episode as not timed.
    for err in (OSError("not a program"), subprocess.TimeoutExpired(["tsubasa"], 120)):
        def run(command, **kw):
            raise err

        got = fit_check.check(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=run)
        assert got[0] == fit_check.RETRY
        assert got[1] == "tsubasa"


def test_tsubasa_is_always_run_dry_and_json_so_it_never_retimes_the_file():
    # --dry-run keeps tsubasa from re-timing (writing) the file; --json is what the answer parser reads.
    seen = []

    def run(command, **kw):
        seen.append(command)
        return SimpleNamespace(stdout=(json.dumps({"outcome": "CONFIDENT", "segments": [ONE_SEGMENT]}) + "\n").encode())

    fit_check.check(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=run)
    assert "--dry-run" in seen[0]
    assert "--json" in seen[0]
    assert seen[0][:4] == ["tsubasa", "--pair", VIDEO, SUBTITLE]


def test_the_reason_names_the_switch_by_the_label_settings_shows():
    # The reason sends you to a Settings row: its name must be the row's own, or the pointer leads nowhere.
    from app.qt import settings_strings
    assert settings_strings.ROWS["connect_trust_timing"][0] == fit_check.TRUST_LABEL
    assert fit_check.TRUST_LABEL in fit_check.NO_CHECKER
