"""Connect's write and resume paths after the laptop fixes (mining): each test pins a rule the real code holds that no
earlier test did.

- Connect's profile is the first open one that holds every deck you chose for one of your languages
  (`anki_session.waiting` → `_holds_your_decks` → `setup.keep_profile`): a record that couldn't be written names
  none; Anki not answering its decks takes none; one language's decks are enough, one deck of a
  set is not, an empty list chosen counts as none.
- The plug back ends `run`'s pause between looks at its next ask, read from the machine's power state
  (`Steps.on_battery`); on battery, the episodes left after an asked one are looked at again, and an
  unasked one's fill waits for the plug.
- A failed call to Anki is named by the session's look: a verb's `anki-closed` while Anki answers is ANKI_SLOW
 ; the names' tag Anki turns down is *Needs you*, one that times out while Anki answers ANKI_SLOW.
- The run's kept set of Anki Miner look-ups (`verbs._anki_miner_setup`, row 25): read again once 15 minutes old
 , emptied by a failed setup, not used when its export can't be written, the note type still
  checked on it.
- The media rename (`media_names`): a short `multi` reply's missing slots are failed, a name check answers for
  that exact name only, a store never overwrites, a failed name check or delete makes the rename raise
 , an old file another note still plays is never deleted.

Against stand-ins for Anki and `FakeSteps`; never a live Anki, and every setup record in `tmp_path`.
"""
import contextlib
import json
import os
import threading

import pytest

from app import anki_connect
from app.cli import verbs
from app.cli.contract import CliError
from app.connect import anki_session, media_names, power, runner, setup
from app.connect.ledger import Ledger, stamp
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_anki_miner import LAPIS_EXPORT
from tests.connect.fake_steps import FakeSteps
from tests.connect.test_lf_mining import _anki
from tests.connect.test_lf_mining_speed import LOOK_UPS, _Clock, _episode, _steps
from tests.connect.test_media_names import FakeMedia, card_note
from tests.connect.test_media_names_multi import KEY, FailingMedia, _audio, two_lines
from tests.connect.test_pick_cli import library  # noqa: F401  (fixture: a generated Japanese library)


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


@pytest.fixture
def record(monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "record_path", lambda: str(tmp_path / "setup.json"))


# --- the profile Connect makes cards in ---------------------------------------------------------------------------- #
def test_a_record_that_couldnt_be_written_names_no_profile(monkeypatch, record):
    # why: when the record can't be written, keep_profile names no profile, so the session waits and looks
    # again (NO_PROFILE_YET) — Connect never writes to Anki in a profile it couldn't record
    monkeypatch.setattr(setup, "write_record", lambda record: False)
    assert setup.keep_profile("日本語") is None
    _anki(monkeypatch, "日本語")
    assert runner.Steps({"connect_enabled": True}).blocked("ja") == anki_session.NO_PROFILE_YET
    assert setup.anki_profile() is None


def _anki_deck_list_silent(monkeypatch, open_now):
    """Anki names its open profile, but does not answer `deckNames` (AnkiError), as when it is busy with a sync."""
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: False)
    monkeypatch.setattr(anki_session, "look", lambda url: "open")
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: False)

    def invoke(action, url, timeout=30, **params):
        if action == "deckNames":
            raise anki_connect.AnkiError("no answer", kind="offline")
        assert action == "getActiveProfile"
        return open_now
    monkeypatch.setattr(anki_connect, "invoke", invoke)


def test_anki_not_answering_its_decks_takes_no_profile(monkeypatch, record):
    # why: with Anki silent on deckNames the open profile can't be shown to hold the decks you chose, so it is
    # not taken — nothing recorded, and the session waits to look again (NO_PROFILE_DECKS), never a write into it
    _anki_deck_list_silent(monkeypatch, "日本語")
    settings = {"connect_enabled": True, "anki_sync_decks": {"ja": ["日本語::アニメ"]}}
    assert runner.Steps(settings).blocked("ja") == anki_session.NO_PROFILE_DECKS
    assert setup.anki_profile() is None


def test_one_languages_decks_are_enough_when_the_other_languages_decks_live_elsewhere(monkeypatch, record):
    # why: a profile holding every deck chosen for ONE language is Connect's; zh's decks may sit in another
    # profile, so a rule that needs every language's decks at once would wrongly refuse 日本語
    _anki(monkeypatch, "日本語", decks=["Default", "日本語::アニメ"])
    steps = runner.Steps({"connect_enabled": True,
                          "anki_sync_decks": {"ja": ["日本語::アニメ"], "zh": ["中文::电视"]}})
    assert steps.blocked("ja") is None
    assert setup.anki_profile() == "日本語"


def test_a_profile_holding_only_one_of_a_languages_decks_is_not_taken(monkeypatch, record):
    # why: a language's deck set is all-or-nothing; a test profile that shares one deck name with the set is
    # never recorded as Connect's
    settings = {"connect_enabled": True, "anki_sync_decks": {"ja": ["日本語::アニメ", "日本語::文"]}}
    _anki(monkeypatch, "DevTest", decks=["Default", "日本語::アニメ"])
    assert runner.Steps(settings).blocked("ja") == anki_session.NO_PROFILE_DECKS
    assert setup.anki_profile() is None


def test_a_language_with_no_chosen_decks_does_not_make_every_profile_its_own(monkeypatch, record):
    # why: an empty deck list chosen for one language (zh: []) never counts as "holds every deck chosen" — a
    # profile without the Japanese deck is never taken as Connect's
    _anki(monkeypatch, "DevTest", decks=["Default"])
    steps = runner.Steps({"connect_enabled": True, "anki_sync_decks": {"ja": ["日本語::アニメ"], "zh": []}})
    assert steps.blocked("ja") == anki_session.NO_PROFILE_DECKS
    assert setup.anki_profile() is None


# --- the plug back ends the pause (row 34) ------------------------------------------------------------------------ #
class _PlugBack(FakeSteps):
    """On battery until the first ask for a language's blocked state; that ask puts the plug back in."""

    def __init__(self, folder, plan):
        super().__init__(folder, plan)
        self.plugged = False

    def blocked(self, lang):
        self.log.append(("blocked", lang))
        if not self.plugged:
            self.plugged = True
            return runner.ON_BATTERY
        return None

    def on_battery(self):
        return not self.plugged


def test_the_plug_back_ends_run_pause_at_its_next_look_ask(tmp_path, ledger, monkeypatch):
    # why (the wiring in run): the plug comes back during the pause between looks; run ends it at the next
    # UPDATE_LOOK_S ask so the second look mines episode 1 at once, not after the whole LOOK_EVERY_S
    monkeypatch.setattr(runner, "LOOK_EVERY_S", 30)
    monkeypatch.setattr(runner, "UPDATE_LOOK_S", 0.01)
    steps = _PlugBack(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    cancel = threading.Event()
    timer = threading.Timer(10, cancel.set)     # the safety net: a pause the plug didn't end is cancelled at 10 s
    timer.start()
    try:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, cancel=cancel, looks=2)
    finally:
        timer.cancel()
    assert "stopped" not in summary, "the pause ran on until the safety net cancelled it"
    assert [e[1] for e in steps.log if e[0] == "mine"] == [1]


def test_steps_on_battery_reports_the_machine_power_state(monkeypatch):
    # why: Steps.on_battery hands back the machine's power state; a stub that always says False would end the
    # pause on every ask while the laptop is still on battery
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: True)
    assert runner.Steps({}).on_battery() is True
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: False)
    assert runner.Steps({}).on_battery() is False


# --- on battery with an ask (M-3) ---------------------------------------------------------------------------------- #
def _asked(ledger, item):
    with ledger.transaction():
        ledger.ask("ja", item, stamp(), store_id="store-1")


def test_on_battery_after_the_asked_episode_the_run_pauses_and_looks_again(tmp_path, ledger):
    # why: once the asked episode is mined, the rest wait on battery with a look outside — the run pauses and
    # looks again so the plug back mines them; a run that ended there would leave 1 and 2 until the next start
    plan = {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}, "blocked": runner.ON_BATTERY}
    runner.run({}, ["ja"], steps=FakeSteps(str(tmp_path), plan), ledger=ledger, sleep=lambda s: None, looks=1)
    _asked(ledger, 3)
    pauses = []
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: pauses.append(s), looks=2)
    assert [e[1] for e in steps.log if e[0] == "pick"] == [3], "the unasked ones are never picked on battery"
    assert summary["looks"] == 2, "the run looks again after the asked episode instead of ending"
    assert pauses == [runner.LOOK_EVERY_S]
    assert summary["languages"]["ja"]["waiting"] == {1: runner.ON_BATTERY, 2: runner.ON_BATTERY}


class _UnpluggedAfterMining(FakeSteps):
    """Plugged in while the episode is picked and mined, then on battery from the moment its mine is logged."""

    def blocked(self, lang):
        self.log.append(("blocked", lang))
        return runner.ON_BATTERY if any(e[0] == "mine" for e in self.log) else None


def test_an_unasked_episode_unplugged_after_mining_never_fills_and_waits_for_the_plug(tmp_path, ledger):
    # why: nobody asked for this episode on battery, so its fill (a write to the cards) waits; the job resumes
    # at "filling", so the plug back finishes the fill, never the mine that already happened
    steps = _UnpluggedAfterMining(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ("mine", 1) in [e[:2] for e in steps.log], "the episode was mined before the battery"
    assert not any(e[0] == "fill" for e in steps.log), "an unasked episode's fill never runs on battery"
    job = [j for j in ledger.jobs("ja") if j["item_id"] == 1][0]
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.ON_BATTERY, "filling")


# --- a failed call to Anki, named (row 26) ------------------------------------------------------------------------- #
@pytest.mark.parametrize("state, reason", [("open", runner.ANKI_SLOW), ("closed", runner.ANKI_CLOSED)])
def test_a_verbs_anki_closed_is_named_by_the_look_now(monkeypatch, state, reason):
    # why: a verb's `anki-closed` is only a failed probe; Anki answering is the episode's own slow wait, and
    # only a refused port (closed) holds every episode
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_session, "look", lambda url: state)
    wait = runner._wait_or_needs(CliError("anki-closed", "Anki didn't answer"), "mining", "http://127.0.0.1:8765")
    assert isinstance(wait, runner.Wait)
    assert (wait.reason, wait.resume) == (reason, "mining")


@pytest.fixture
def anki_writer(monkeypatch):
    monkeypatch.setattr(anki_connect, "writer", lambda verb, wait=0.0, **kw: contextlib.nullcontext())
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: False)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)


def test_anki_refusing_the_name_tag_is_needs_you_not_a_wait(monkeypatch, anki_writer):
    # why: Anki answered and refused addTags for good (kind "action", a note gone) — *Needs you*, never a
    # silent wait for Anki to open
    def refuse(action, url, **kw):
        raise anki_connect.AnkiError("Anki refused 'addTags': Note was not found: 5", kind="action")
    monkeypatch.setattr(anki_connect, "invoke", refuse)
    with pytest.raises(runner.Needs) as got:
        runner.Steps({"connect_enabled": True}).tag_names("ja", [5])
    assert got.value.kind == "anki-refused"


def test_a_name_tag_timeout_while_anki_answers_is_slow_not_closed(monkeypatch, anki_writer):
    # why: the call timed out but Anki's port still answers — Anki is slow (the episode's own wait), not closed
    def time_out(action, url, **kw):
        raise anki_connect.AnkiError("timed out", kind="offline")
    monkeypatch.setattr(anki_connect, "invoke", time_out)
    monkeypatch.setattr(anki_session, "look", lambda url: "open")
    with pytest.raises(runner.Wait) as got:
        runner.Steps({"connect_enabled": True}).tag_names("ja", [5])
    assert got.value.reason == runner.ANKI_SLOW


# --- the run's kept set of Anki Miner look-ups (row 25) ------------------------------------------------------------ #
def test_a_kept_set_is_read_again_once_fifteen_minutes_and_one_second_old(library, fake_miner, monkeypatch):  # noqa: F811
    # why: the rule is 15 minutes; a set one second past that is read again. 15 * 60 is written out, not
    # verbs.SETUP_FOR_S, so a changed constant fails here
    subtitle, video = library
    clock = _Clock()
    monkeypatch.setattr(verbs, "time", clock)
    steps = _steps(fake_miner)
    _episode(steps, {"id": 1, "item_id": 1}, subtitle, video)
    clock.now += 15 * 60 + 1
    _episode(steps, {"id": 2, "item_id": 2}, subtitle, video)
    assert fake_miner.commands() == LOOK_UPS + ["check", "mine"] + LOOK_UPS + ["check", "mine"]


def _note_type_lacks_a_field(loaded, mapping, info=None):
    raise CliError("needs-you", "the note type lacks a field")


def test_a_failed_setup_empties_the_kept_set_so_the_next_call_reads_anki_miner_again(fake_miner, monkeypatch, tmp_path):
    # why: a set kept across a failure may describe an Anki Miner or a note type that has since changed
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    loaded = verbs.settings()
    held = {}
    verbs._anki_miner_setup(loaded, "ja", str(tmp_path / "run-1"), held=held)
    assert held, "the first real call fills the set, or the failing call below proves nothing"
    monkeypatch.setattr(verbs, "_check_note_type", _note_type_lacks_a_field)
    with pytest.raises(CliError):
        verbs._anki_miner_setup(loaded, "ja", str(tmp_path / "run-2"), held=held)
    assert held == {}, "the failure emptied the set"


def test_a_kept_set_whose_export_cannot_be_written_is_not_used_and_anki_miner_is_read_again(
        library, fake_miner, monkeypatch):  # noqa: F811
    # why: the kept export is written into the job's run folder; when that write fails the set is dropped and
    # Anki Miner read again (it writes the file itself), so the job's folder always holds its export
    subtitle, video = library
    steps = _steps(fake_miner)
    _episode(steps, {"id": 1, "item_id": 1}, subtitle, video)
    real_dump, armed = json.dump, [True]

    def dump_failing_the_kept_export_once(obj, fp, *args, **kwargs):
        if armed[0] and os.path.basename(getattr(fp, "name", "")) == "settings-export.json":
            armed[0] = False
            raise OSError("the export could not be written (the test's failure)")
        return real_dump(obj, fp, *args, **kwargs)

    monkeypatch.setattr(json, "dump", dump_failing_the_kept_export_once)
    _episode(steps, {"id": 2, "item_id": 2}, subtitle, video)
    assert armed[0] is False, "the kept set's export write was attempted and failed"
    assert fake_miner.commands() == LOOK_UPS + ["check", "mine"] + LOOK_UPS + ["check", "mine"]
    with open(os.path.join(steps.run_dir({"id": 2}), "settings-export.json"), encoding="utf-8") as f:
        assert json.load(f) == LAPIS_EXPORT


def test_a_kept_set_still_checks_the_note_type(fake_miner, tmp_path, monkeypatch):
    # why: a note type edited mid-run is seen at the next episode, so a kept set is checked too
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    loaded = verbs.settings()
    run_dir = str(tmp_path / "run")
    held = {}
    assert verbs._anki_miner_setup(loaded, "ja", run_dir, held=held) is not None
    monkeypatch.setattr(verbs, "_check_note_type", _note_type_lacks_a_field)
    with pytest.raises(CliError, match="the note type lacks a field"):
        verbs._anki_miner_setup(loaded, "ja", run_dir, held=held)
    assert fake_miner.commands() == LOOK_UPS, "the second call used the kept set: Anki Miner was not started again"


# --- the media rename's requests (row 25) -------------------------------------------------------------------------- #
def test_a_multi_reply_shorter_than_the_actions_reads_the_missing_slots_as_failed(monkeypatch):
    # why: a missing slot in AnkiConnect's answer is a failed one, never an IndexError
    sent = []

    def short_multi(actions, url, timeout=60):
        sent.append(actions)
        return [{"result": None, "error": None}]   # one reply for three actions

    monkeypatch.setattr(anki_connect, "multi", short_multi)
    out = media_names.AnkiConnectMedia("http://127.0.0.1:8765").many("delete", [("a.mp3",), ("b.mp3",), ("c.mp3",)])
    assert len(sent) == 1 and len(sent[0]) == 3, "the three deletes went out as one multi, so the short reply is real"
    assert out == [(True, None), (False, None), (False, None)]


def test_exists_is_true_only_when_anki_lists_that_exact_name(monkeypatch):
    # why: getMediaFilesNames takes a pattern, so Anki can list another file it matches; a wrong True would
    # point a note at a file never stored
    replies = [{"result": ["other_clip.mp3"], "error": None}, {"result": ["clip.mp3", "other_clip.mp3"], "error": None},
               {"result": [], "error": None}, {"result": None, "error": None}]
    monkeypatch.setattr(anki_connect, "multi", lambda actions, url, timeout=30: replies)
    media = media_names.AnkiConnectMedia("http://127.0.0.1:8765")
    assert media.many("exists", [("clip.mp3",)] * 4) == [(True, False), (True, True), (True, False), (True, False)]


def test_a_store_never_overwrites_a_file_already_in_anki(monkeypatch):
    # why: a file of that name another note plays is never replaced
    sent = []

    def fake_multi(actions, url, timeout=None):
        sent.extend(actions)
        return [{"result": None, "error": None} for _ in actions]

    monkeypatch.setattr(anki_connect, "multi", fake_multi)
    media = media_names.AnkiConnectMedia("http://127.0.0.1:8765")
    assert media.many("store", [("sl-x.mp3", "ZGF0YQ==")]) == [(True, None)]
    assert len(sent) == 1 and sent[0]["action"] == "storeMediaFile"
    assert sent[0]["params"]["deleteExisting"] is False


def test_a_failed_name_check_leaves_its_notes_as_they_are_and_the_rename_raises():
    # why: a failed name check says nothing about the file, so its line is left and the job waits for the next
    # look — a silent success would leave the card on its old name for good
    notes, files, made = two_lines()
    new = media_names.line_name(KEY, made[0][1], made[0][2], media_names.fingerprint(made[0][3]), ".mp3")
    media = FailingMedia(notes, files, fail={("exists", new)})
    with pytest.raises(anki_connect.AnkiError):
        media_names.rename(media, made, KEY, "SentenceAudio", "Picture")
    assert _audio(media, 1) == "演奏_12400_1_ab12.mp3" and _audio(media, 2) == "ライブハウス_12400_2_ab12.mp3"
    assert new not in media.files, "nothing stored under the name that could not be checked"
    assert _audio(media, 3).startswith("sl-") and _audio(media, 3) == _audio(media, 4), "the other line is still done"


def test_an_old_file_another_note_still_plays_is_never_deleted():
    # why: a card outside this batch (another episode's) still names note 1's old clip; deleting it would
    # silence that card
    notes, files, made = two_lines()
    notes.append(card_note(99, "演奏_12400_1_ab12.mp3", "演奏_12400_1_ab12.jpg"))
    media = FakeMedia(notes, files)
    media_names.rename(media, made, KEY, "SentenceAudio", "Picture")
    assert "演奏_12400_1_ab12.mp3" in media.files, "kept: note 99 still plays it"
    assert media.note_map[99]["fields"]["SentenceAudio"]["value"] == "[sound:演奏_12400_1_ab12.mp3]"
    assert "結束_31000_3_ab12.mp3" not in media.files, "control: an old file no note uses is still deleted"


def test_a_failed_delete_makes_the_rename_raise_and_the_rest_is_done():
    # why: a delete that failed is counted, so the job waits for the next look; never a silent success
    notes, files, made = two_lines()
    media = FailingMedia(notes, files, fail={("delete", "演奏_12400_1_ab12.mp3")})
    with pytest.raises(anki_connect.AnkiError):
        media_names.rename(media, made, KEY, "SentenceAudio", "Picture")
    assert all(_audio(media, n).startswith("sl-") for n in (1, 2, 3, 4)), "every note was pointed"
    assert "演奏_12400_1_ab12.mp3" in media.files, "the file whose delete failed is still there"
    assert "ライブハウス_12400_2_ab12.mp3" not in media.files, "the other deletes went through"
