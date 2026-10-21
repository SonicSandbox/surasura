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
from tests.connect_helpers import TSUBASA_REAL, tsubasa_answer

VIDEO = "C:/Video/上層部の話 01.mkv"
SUBTITLE = "C:/Subs/上層部の話 01.srt"
# tsubasa's answers are its real `--json` shape, built on one recorded from tsubasa 0.1.10 (`connect_helpers`).
REAL = TSUBASA_REAL
TWO_SEGMENTS = [[None, 0.0], [1420.5, 3.2]]
_answer = tsubasa_answer


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
    # and on a PC with no tsubasa at all (a learner's laptop): hato's verdict alone mines it (mutant LF9-H02)
    assert fit_check.fit(_hato_record(body), VIDEO, str(subtitle), tsubasa="", run=must_not_run) == got
    assert fit_check.fit(_hato_record(body), VIDEO, str(subtitle), tsubasa="", trust=True) == got


def test_a_hato_timed_record_that_fails_the_gate_goes_to_tsubasa(tmp_path):
    # 09-hato-layer's gate: schema 1, one segment and the copy's sha256 all hold, else Connect asks tsubasa itself —
    # a copy edited since hato timed it, or a record of a schema this Surasura doesn't know, is never trusted.
    body = "1\n00:00:01,000 --> 00:00:02,500\n上層部の決定だ\n".encode("utf-8")
    subtitle = tmp_path / "上層部の話 01.srt"
    subtitle.write_bytes(body)
    asked = []

    def tsubasa(command, **kw):
        asked.append(command)
        return SimpleNamespace(stdout=(json.dumps(_answer(segments=[[None, 1.24]])) + "\n").encode("utf-8"))

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
        return SimpleNamespace(stdout=(json.dumps(_answer(segments=[[None, 1.24]])) + "\n").encode("utf-8"))

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
    assert _check(_answer()) == (fit_check.TIMED, "tsubasa", None)


def test_a_confident_answer_with_two_segments_is_not_timed_and_says_why():
    # Two segments means the timing shifts part-way through: a card from it would hold the wrong line's audio.
    got = _check(_answer(segments=TWO_SEGMENTS))
    assert got[0] == fit_check.NOT_TIMED
    assert got[1] == "tsubasa"
    assert "changes part-way" in got[2]


def test_a_confident_answer_with_no_segments_is_not_timed():
    got = _check(_answer(segments=[]))
    assert got[0] == fit_check.NOT_TIMED and got[1] == "tsubasa"


def test_a_refused_answer_is_not_timed_and_carries_tsubasas_reason():
    got = _check(_answer("REFUSED", reason="no speech match"))
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
    # and Settings saves it off for everyone who never touched it (mutant LF9-B30: a True default would mine every
    # unchecked episode unattended)
    from app import settings_manager
    assert settings_manager.get_default_settings()["connect_trust_timing"] is False


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
                            run=_tsubasa(_answer(segments=[[None, 2.5]])))
    assert shifted == (fit_check.TIMED, "tsubasa", None, 2.5)


def test_connects_steps_read_the_switch_from_settings_as_they_are_now(monkeypatch):
    # The runner's real fit step reads `connect_trust_timing` from settings.json at each check, never the snapshot taken
    # when Connect started (review LF-9 #2): turned off mid-run, the signed rule is back for the next episode; turned on
    # mid-run, the next episode mines. Absent or anything but true → off.
    from app.cli import verbs
    from app.connect import runner
    monkeypatch.setattr(fit_check, "find_tsubasa", lambda: None)
    job = {"id": 1, "item_id": 1}
    now = {}
    monkeypatch.setattr(verbs, "settings", lambda: dict(now))
    started_on = runner.Steps({"connect_trust_timing": True})
    assert started_on.fit("ja", job, None, VIDEO, SUBTITLE)[0] == fit_check.NOT_TIMED, "absent in the file: off"
    now["connect_trust_timing"] = "true"
    assert started_on.fit("ja", job, None, VIDEO, SUBTITLE)[0] == fit_check.NOT_TIMED, "only true itself is on"
    now["connect_trust_timing"] = True
    started_off = runner.Steps({"connect_trust_timing": False})
    assert started_off.fit("ja", job, None, VIDEO, SUBTITLE) == (fit_check.TIMED, "you", None, 0.0)


def test_a_library_folders_own_record_or_a_link_is_not_hatos_so_trust_releases_it():
    # Review LF-9 #1 (blocking): an episode read from a Library folder carries Surasura's origin record (producer
    # "source"), one linked by hand a "surasura" record — neither is a timing hato checked. With the switch on and no
    # tsubasa they mine at their own times; off, the reason names the cause and the switch.
    source = {"producer": "source", "channel_id": 3, "root": 3, "origin": "かぐや荘の日々/第03話.ja.srt",
              "video_path": "D:/Anime/かぐや荘の日々/第03話.mkv", "show": {"title": "かぐや荘の日々"}}
    linked = {"schema": 1, "producer": "surasura", "content_key": "abc", "video_path": VIDEO}
    for record in (source, linked):
        assert fit_check.fit(record, VIDEO, SUBTITLE, tsubasa="", trust=True) == (fit_check.TIMED, "you", None, 0.0)
        off = fit_check.fit(record, VIDEO, SUBTITLE, tsubasa="")
        assert off[0] == fit_check.NOT_TIMED and off[2] == fit_check.NO_CHECKER


def test_a_record_hato_wrote_still_waits_with_or_without_its_producer_named(tmp_path):
    # hato's records name no producer, or "hato": an untimed one is never released by the switch.
    for record in ({"schema": 1, "verdict": "untimed"}, {"schema": 1, "producer": "hato", "verdict": "untimed"},
                   {"schema": 1, "producer": "  hato ", "verdict": "extracted"}):
        got = fit_check.fit(record, VIDEO, SUBTITLE, tsubasa="", trust=True)
        assert got[0] == fit_check.NOT_TIMED and "Trust my subtitles" not in got[2], record


def test_another_programs_untimed_record_waits_and_only_surasuras_own_records_are_released(tmp_path):
    # Delta review LF-9 #1: `surasura-cli connect register` takes any short producer name, so a pairing program other
    # than hato can register an untimed subtitle. Only Surasura's own records — a Library folder's or + Add's origin
    # (`source`), a *Link…* (`surasura`) — are no timing anyone was asked to check; every other record waits, as an
    # empty row does (it exists, so it isn't "no record").
    from app import library_store
    from app.connect import link
    from app.cli import connect_verbs
    assert set(fit_check.OWN_PRODUCERS) == {library_store.SOURCE_PRODUCER, link.PRODUCER, "youtube"}, "one rule"
    assert set(fit_check.OWN_PRODUCERS) <= set(connect_verbs.RESERVED), "no other program can claim one"
    for record in ({"schema": 1, "producer": "sonarr-sync", "verdict": "untimed"}, {}, [], "garbled"):
        got = fit_check.fit(record, VIDEO, SUBTITLE, tsubasa="", trust=True)
        assert got[0] == fit_check.NOT_TIMED, record
        raw = fit_check.fit(record, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(RAW_ERROR), trust=True)
        assert raw[0] == fit_check.NOT_TIMED, record
    assert fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="", trust=True)[0] == fit_check.TIMED, "no record at all"
    # Surasura's own YouTube download: the transcript of that very video (app/qt/windows.youtube_record)
    youtube = {"schema": 1, "producer": "youtube", "media_type": "youtube", "content_key": "youtube:abc123"}
    assert fit_check.fit(youtube, VIDEO, SUBTITLE, tsubasa="", trust=True)[0] == fit_check.TIMED


RAW_ERROR = {"outcome": "ERROR", "segments": [], "offset": None,
             "reason": "第03話.mkv could not be measured: it has no subtitle track to align against. The speech-mask path "
                       "that does not need one lands at RUNBOOK B6 and its band has not been fitted yet, so nothing is "
                       "guessed here."}


def test_trust_mines_a_raw_video_tsubasa_has_nothing_to_time_against():
    # Sonic's follow-up (P-LF-9, 2026-10-21 "yes, go ahead and mine it"): tsubasa's ERROR for a video with no subtitle
    # track inside (P0.2: "it has no subtitle track to align against") is "nothing can check it" — with the switch on it
    # mines at the subtitle's own times; off, it waits and the reason names the switch.
    on = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(RAW_ERROR), trust=True)
    assert on == (fit_check.TIMED, "you", None, 0.0)
    off = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(RAW_ERROR))
    assert off[0] == fit_check.NOT_TIMED and fit_check.TRUST_LABEL in off[2]


def test_trust_never_mines_past_tsubasas_refusal_or_another_error():
    # REFUSED is tsubasa finding the subtitle doesn't fit (the wrong cut, the wrong episode); any other ERROR isn't
    # "no track". Both still wait with the switch on, and neither points at it.
    # (mutant LF9-B11: a REFUSED whose reason happens to hold the raw's words is still a refusal)
    for answer in ({"outcome": "REFUSED", "reason": "no speech match", "segments": []},
                   {"outcome": "REFUSED", "reason": "no subtitle track matched its speech", "segments": []},
                   {"outcome": "ERROR", "reason": "the video could not be read", "segments": []}):
        got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(answer), trust=True)
        assert got[0] == fit_check.NOT_TIMED and fit_check.TRUST_LABEL not in got[2], answer


def test_trust_never_mines_a_raw_video_hato_paired_untimed(tmp_path):
    # A raw with hato's own untimed record: hato said it isn't checked, so it waits even when tsubasa can't time it.
    record = {"schema": 1, "verdict": "untimed"}
    got = fit_check.fit(record, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(RAW_ERROR), trust=True)
    assert got[0] == fit_check.NOT_TIMED


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
        return SimpleNamespace(stdout=(json.dumps(_answer()) + "\n").encode())

    fit_check.check(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=run)
    assert "--dry-run" in seen[0]
    assert "--json" in seen[0]
    assert seen[0][:4] == ["tsubasa", "--pair", VIDEO, SUBTITLE]


def test_the_reason_names_the_switch_by_the_label_settings_shows():
    # The reason sends you to a Settings row: its name must be the row's own, or the pointer leads nowhere.
    from app.qt import settings_strings
    assert settings_strings.ROWS["connect_trust_timing"][0] == fit_check.TRUST_LABEL
    assert fit_check.TRUST_LABEL in fit_check.NO_CHECKER


# --- T1 (Sonic 2026-10-21, B): 3.0 ships tsubasa.exe in Surasura's own bundle, beside Surasura.exe and
# surasura-cli.exe. Connect must find that one first — a learner has no PATH entry for it — and only then a
# developer's tsubasa on PATH. A frozen build is faked by `path_utils.is_frozen` and `sys.executable`, as
# tests/test_tools_entry.py does.

def _bundle(tmp_path, monkeypatch, frozen=True, ship=True):
    """A program folder with Surasura.exe (running) and, when `ship`, tsubasa.exe beside it; PATH holds another."""
    import sys
    from app import path_utils
    folder = tmp_path / "Surasura 3.0 (テスト)"           # a space and Japanese, as install paths have
    folder.mkdir()
    (folder / "Surasura.exe").write_bytes(b"MZ")
    if ship:
        (folder / "tsubasa.exe").write_bytes(b"MZ")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(folder / "Surasura.exe"))
    monkeypatch.setattr(path_utils, "is_frozen", lambda: frozen)
    monkeypatch.setattr(fit_check.shutil, "which", lambda name: "C:/dev/Scripts/tsubasa.exe" if name == "tsubasa"
                        else None)
    return folder


def test_a_frozen_surasura_finds_the_tsubasa_its_bundle_ships_before_one_on_path(tmp_path, monkeypatch):
    folder = _bundle(tmp_path, monkeypatch)
    assert fit_check.find_tsubasa() == str(folder / "tsubasa.exe")


def test_a_frozen_bundle_without_tsubasa_falls_back_to_path(tmp_path, monkeypatch):
    # an older bundle, or tsubasa removed from it: a developer's install still counts
    _bundle(tmp_path, monkeypatch, ship=False)
    assert fit_check.find_tsubasa() == "C:/dev/Scripts/tsubasa.exe"


def test_from_source_a_tsubasa_beside_python_is_never_taken_for_the_bundles(tmp_path, monkeypatch):
    # from source sys.executable is python.exe: a file beside it isn't Surasura's bundle, so PATH decides
    _bundle(tmp_path, monkeypatch, frozen=False)
    assert fit_check.find_tsubasa() == "C:/dev/Scripts/tsubasa.exe"


def test_with_no_tsubasa_anywhere_nothing_is_found(tmp_path, monkeypatch):
    _bundle(tmp_path, monkeypatch, ship=False)
    monkeypatch.setattr(fit_check.shutil, "which", lambda name: None)
    assert fit_check.find_tsubasa() is None


def test_programs_beside_the_exe_are_named_without_exe_off_windows(tmp_path, monkeypatch):
    # macOS / Linux bundles ship `tsubasa`, `surasura-cli` (no .exe): one rule names every program beside the exe
    import sys
    from app import path_utils
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Surasura"))
    monkeypatch.setattr(sys, "platform", "linux")
    assert path_utils.program_beside("tsubasa") == str(tmp_path / "tsubasa")
    monkeypatch.setattr(sys, "platform", "win32")
    assert path_utils.program_beside("surasura-cli") == str(tmp_path / "surasura-cli.exe")


def test_tsubasas_real_answer_for_a_shifted_pair_is_timed_with_its_own_offset():
    # Minato's proof (T1, 2026-10-21): tsubasa 0.1.10 on a pair shifted +2.4 s answers CONFIDENT, segments
    # [[null, -2.4]], offset -2.4. Anki Miner adds `subtitle_offset` to every subtitle time, so -2.4 is the shift its
    # cards must be cut by; 0.0 would cut every card 2.4 s off its line.
    got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(None, stdout=json.dumps(
        REAL, ensure_ascii=False) + "\n"))
    assert got[:3] == (fit_check.TIMED, "tsubasa", None)
    assert abs(got[3] - (-2.4)) < 1e-9


def test_a_confident_answer_whose_offset_cant_be_read_waits_rather_than_cut_at_zero():
    # One segment but no number to cut by (a shape Connect doesn't know, a null): mining at 0.0 could be seconds off,
    # so it waits with a reason, as tsubasa's own unreadable answer does.
    for answer in (dict(REAL, segments=[[None, None]], offset=None), dict(REAL, segments=[{"offset": -2.4}], offset=None),
                   dict(REAL, segments=[[None]], offset="-2.4"), dict(REAL, segments=[[None, True]], offset=True)):
        got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(answer))
        assert got[0] == fit_check.NOT_TIMED and got[2], answer


def test_the_top_level_offset_is_read_first_and_the_first_segments_offset_without_it():
    got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(dict(REAL, segments=[[None, 1.0]],
                                                                                   offset=1.5)))
    assert got[0] == fit_check.TIMED and got[3] == 1.5
    got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(dict(REAL, segments=[[None, 1.0]],
                                                                                   offset=None)))
    assert got[0] == fit_check.TIMED and got[3] == 1.0


def test_an_error_with_no_reason_or_another_kind_of_reason_waits_and_never_raises():
    # tsubasa's ERROR carries defaults in its other fields (P0.2): a missing, null or non-text reason is no raw, with
    # the switch on or off — it waits, it never crashes the look (mutant LF9-H05)
    for reason in (None, 3, ["no subtitle track"]):
        answer = dict(REAL, outcome="ERROR", segments=[], offset=None, reason=reason)
        for trust in (False, True):
            got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(answer), trust=trust)
            assert got[0] == fit_check.NOT_TIMED, (reason, trust)
    answer = dict(REAL, outcome="ERROR", segments=[], offset=None)
    del answer["reason"]
    assert fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=_tsubasa(answer), trust=True)[0] ==         fit_check.NOT_TIMED
