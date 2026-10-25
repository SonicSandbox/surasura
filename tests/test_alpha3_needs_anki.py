"""Alpha 3's A3W-5 / A3W-6 (Sonic took both leans, 2026-10-24 night; QUESTIONS.md *A3W-5, A3W-6 …*).

- A3W-6: amber means "needs you", so a wait on Anki only you can end — Anki closed, a permission prompt, another profile
  or none — with episodes queued is ONE *Needs you* line: "Anki isn't open: 19 episodes wait for it", with *Open Anki*
  where Surasura can start it. It is gone by itself once Anki opens (it is read from Connect's record, never written).
- A3W-5: on battery is a still arc on the rows as on the strip (never amber); Anki Miner's own window open stays plain.

What a wrong answer would cost: the star amber and Needs you empty (Sonic's T6 question: "I would expect it to show
up in needs me right?"); a line that stays after Anki opened; an *Open Anki* that can't open it; a laptop unplugged
lighting every row amber.

Connect's record as `needs.read_connect` returns it (the runner's own reasons); real ja / zh titles.
"""
import pytest

from app.connect import anki_session, feed, runner
from app.services import needs as service
from app.services import view_rows as vr


def _record(*reasons, openable=None):
    jobs = [{"item": 100 + n, "job": n, "state": "waiting", "reason": r, "kind": "mine"} for n, r in enumerate(reasons)]
    rec = {"jobs": jobs, "needs": [], "gaps": []}
    if openable is not None:
        rec["anki_openable"] = openable
    return rec


def _anki_entries(rec):
    return [e for e in service.entries(None, connect=rec) if e.kind == service.ANKI_WAIT]


@pytest.mark.parametrize("openable, actions", [(True, ("open_anki",)), (False, ())])
def test_anki_closed_with_work_queued_is_one_needs_you_line_with_open_anki_where_it_can(openable, actions):
    got = _anki_entries(_record(*[runner.ANKI_CLOSED] * 19, openable=openable))
    assert len(got) == 1
    entry = got[0]
    assert entry.title == "Anki isn't open: 19 episodes wait for it"
    assert entry.actions == actions and entry.unseen
    assert "dismiss" not in entry.actions, "it goes by itself once Anki opens"


@pytest.mark.parametrize("reason", [anki_session.UNUSABLE, anki_session.OTHER_PROFILE.format("日本語", "User 1"),
                                    anki_session.NO_PROFILE_YET, anki_session.NO_PROFILE_DECKS])
def test_a_permission_prompt_or_another_profile_is_the_same_one_line_saying_why(reason):
    entry, = _anki_entries(_record(reason, reason, openable=True))
    assert entry.title == "Anki needs you: 2 episodes wait for it"
    assert entry.say == reason
    assert entry.actions == (), "Anki is open: there's nothing to open"


def test_one_episode_is_said_as_one():
    entry, = _anki_entries(_record(runner.ANKI_CLOSED, openable=False))
    assert entry.title == "Anki isn't open: 1 episode waits for it"


@pytest.mark.parametrize("reasons", [
    (runner.REVIEWING, anki_session.BUSY, runner.WRITER_BUSY, runner.ANKI_SLOW),     # clears by itself
    (runner.ON_BATTERY, runner.ANKI_MINER_OPEN, runner.TURN, runner.CHINESE),        # not Anki's
    ()])
def test_no_line_while_nothing_waits_on_you_in_anki(reasons):
    assert _anki_entries(_record(*reasons, openable=True)) == []


def test_the_line_goes_by_itself_once_anki_opens_and_its_seen_key_is_pruned(monkeypatch, tmp_path):
    """Opened: Connect's next look gives its episodes another reason (or none) — the line is gone, and its seen key
    leaves the seen file, so the next time Anki is closed it counts again."""
    import types
    monkeypatch.setattr(service, "seen_path", lambda language: str(tmp_path / f"needs_seen_{language}.json"))
    closed = _record(*[runner.ANKI_CLOSED] * 3, openable=True)
    entry, = _anki_entries(closed)
    service.mark_seen("ja", [entry.key])
    assert entry.key in service.read_seen("ja")
    entry_again, = [e for e in service.entries(None, connect=closed, seen=service.read_seen("ja"))
                    if e.kind == service.ANKI_WAIT]
    assert not entry_again.unseen and entry_again.key == entry.key, "seen: stays listed, stops counting"
    opened = _record(runner.TURN, None, None, openable=True)
    assert _anki_entries(opened) == []
    view = types.SimpleNamespace(mode="store", rows=())
    service.prune("ja", view, connect=opened)
    assert entry.key not in service.read_seen("ja")


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_read_connect_asks_whether_anki_can_be_opened_only_while_a_line_needs_it(monkeypatch, language):
    """`open_anki.find` looks at the disk and the registry: asked only when there is a line to offer it on."""
    from app.connect import open_anki, status
    asked = []
    monkeypatch.setattr(open_anki, "find", lambda: asked.append(1) or ["C:/Anki/anki.exe"])
    for reasons, want in (([runner.ANKI_CLOSED, runner.ANKI_CLOSED], True), ([runner.REVIEWING], None)):
        asked.clear()
        rec = {"languages": {language: _record(*reasons)}}
        monkeypatch.setattr(status, "read", lambda languages=None, path=None, rec=rec: rec)
        got = service.read_connect(language)
        assert got.get("anki_openable") is want and len(asked) == (1 if want else 0)


def test_open_anki_starts_it_on_connects_profile_and_never_a_second_one(monkeypatch):
    from app.connect import open_anki, setup
    started = []
    monkeypatch.setattr(open_anki, "start", lambda profile=None: started.append(profile) or object())
    monkeypatch.setattr(setup, "anki_profile", lambda: "日本語")
    monkeypatch.setattr(open_anki, "running", lambda: False)
    assert open_anki.for_you() is True and started == ["日本語"]
    monkeypatch.setattr(open_anki, "running", lambda: True)
    assert open_anki.for_you() == "running" and started == ["日本語"], "already running: nothing started"
    monkeypatch.setattr(open_anki, "running", lambda: False)
    monkeypatch.setattr(open_anki, "start", lambda profile=None: None)
    assert open_anki.for_you() is False, "couldn't start: said so"


# --- A3W-5: on battery is a still arc on the rows too ------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_on_battery_is_a_plain_waiting_on_its_row_with_its_mine_now_hover(language):
    item = feed.Item(feed.BATTERY, feed.WORDS[feed.BATTERY], runner.ON_BATTERY, 7, 0, 0)
    st = vr._connected(vr.Status("waiting", vr.STRINGS["waiting"], "", "dim"), item, "video")
    assert (st.kind, st.tone) == ("waiting", "dim")
    assert st.tip == vr.STRINGS["tip_ask_battery"].format(tip=runner.ON_BATTERY)


def test_anki_miners_window_open_stays_plain_on_its_row():
    item = feed.Item(feed.WAITING, feed.WORDS[feed.WAITING], runner.ANKI_MINER_OPEN, 7, 0, 0)
    st = vr._connected(vr.Status("waiting", vr.STRINGS["waiting"], "", "dim"), item, "video")
    assert (st.tone, st.tip) == ("dim", runner.ANKI_MINER_OPEN)
