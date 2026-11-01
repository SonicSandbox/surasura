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


def _anki_entries(rec, cards_on=True):
    return [e for e in service.entries(None, connect=rec, cards_on=cards_on) if e.kind == service.ANKI_WAIT]


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
    entry_again, = [e for e in service.entries(None, connect=closed, seen=service.read_seen("ja"), cards_on=True)
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
    kicked = []
    monkeypatch.setattr(open_anki, "start", lambda profile=None: started.append(profile) or object())
    monkeypatch.setattr(setup, "anki_profile", lambda: "日本語")
    monkeypatch.setattr(open_anki, "running", lambda: False)
    assert open_anki.for_you({}, after=kicked.append) is True and started == ["日本語"]
    import time
    deadline = time.time() + 5
    while not kicked and time.time() < deadline:
        time.sleep(0.01)
    assert kicked == [{}], "started: a thread waits for it, then kicks Connect"
    monkeypatch.setattr(open_anki, "running", lambda: True)
    assert open_anki.for_you({}, after=kicked.append) == "running" and started == ["日本語"], "already running"
    monkeypatch.setattr(open_anki, "running", lambda: False)
    monkeypatch.setattr(open_anki, "start", lambda profile=None: None)
    assert open_anki.for_you({}, after=kicked.append) is False and kicked == [{}], "couldn't start: said so, no kick"


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


# --- the review's fixes (reviews/alpha3-needs-adversary.md) ------------------------------------------------------- #
def test_a3_the_line_counts_what_the_strip_counts_never_a_refusal_a_blanket_wait_reached():
    rec = _record(runner.ANKI_CLOSED, runner.ANKI_CLOSED, runner.ANKI_CLOSED, openable=True)
    rec["needs"] = [{"id": 1, "kind": "not-timed", "say": "x", "item": 101}]
    rec["skipped"] = [102]
    entry, = _anki_entries(rec)
    assert entry.title == "Anki isn't open: 1 episode waits for it"


def test_a4_seen_in_one_run_counts_again_in_the_next(monkeypatch):
    first, = _anki_entries(_record(runner.ANKI_CLOSED, openable=True))
    monkeypatch.setattr(service, "_SESSION", "another-run")
    again, = [e for e in service.entries(None, connect=_record(runner.ANKI_CLOSED, openable=True),
                                         seen=frozenset({first.key}), cards_on=True) if e.kind == service.ANKI_WAIT]
    assert again.key != first.key and again.unseen


def test_a5_no_line_while_connect_may_not_run():
    assert _anki_entries(_record(runner.ANKI_CLOSED, openable=True), cards_on=False) == []


def test_a6_kicks_connect_once_anki_answers_and_never_when_it_doesnt():
    clock = {"t": 0.0}
    answers = iter(["closed", "closed", "open"])
    kicked = []

    def sleep(s):
        clock["t"] += s
    from app.connect import open_anki
    assert open_anki.kick_when_open({}, sleep=sleep, clock=lambda: clock["t"], look=lambda url: next(answers),
                                    kick=kicked.append) is True and kicked == [{}]
    clock["t"] = 0.0
    assert open_anki.kick_when_open({}, sleep=sleep, clock=lambda: clock["t"], look=lambda url: "closed",
                                    kick=kicked.append) is False and kicked == [{}]


@pytest.mark.parametrize("kind, reason", [(feed.BATTERY, runner.ON_BATTERY), (feed.ANKI_WAIT, runner.REVIEWING),
                                          (feed.ANKI, runner.ANKI_CLOSED)])
def test_a_waits_hover_names_its_click_once_whatever_its_colour(kind, reason):
    """Intent keeper (A3W-5): a battery or reviewing wait is plain now; its row's button still says its click once."""
    from app.qt import rows
    item = feed.Item(kind, feed.WORDS[kind], reason, 7, 0, 0)
    st = vr._connected(vr.Status("waiting", vr.STRINGS["waiting"], "", "dim"), item, "video")
    ep = vr.Episode(id=7, label="Ep 1", number=1, title="Ep 1", watched=False, cards=0, mining=False, missing=False,
                    removed=False, in_top=True, pct=None, n_new=None, status=st, mark=None,
                    rel_path="HighPriority/x.srt", play_tip="", can_play=True)
    name, tip, ask = rows.action_of(st, (ep,))
    assert name == "mine-now" and tip.count("Click") == 1, tip


def test_open_anki_still_starts_anki_on_its_own_choice_when_the_profile_lookup_fails(monkeypatch):
    # why: Open Anki is the user's press; a profile lookup that raises must fall back to no profile, not stop the start.
    from app.connect import open_anki, setup
    started = []

    def broken_lookup():
        raise RuntimeError("profile file unreadable")
    monkeypatch.setattr(open_anki, "start", lambda profile=None: started.append(profile) or object())
    monkeypatch.setattr(setup, "anki_profile", broken_lookup)
    monkeypatch.setattr(open_anki, "running", lambda: False)
    assert open_anki.for_you({}, after=lambda settings: None) is True and started == [None], \
        "a failed profile lookup starts Anki with no profile"


def test_with_anki_closed_the_line_gives_the_closed_reason_even_when_another_wait_is_commoner():
    # why: with Anki closed the amber line keeps Anki's closed reason, not the commonest wait (a permission prompt here)
    entry, = _anki_entries(_record(anki_session.UNUSABLE, anki_session.UNUSABLE, runner.ANKI_CLOSED, openable=True))
    assert entry.title == "Anki isn't open: 3 episodes wait for it"
    assert entry.data["reason"] == runner.ANKI_CLOSED != anki_session.UNUSABLE, entry.data


# --- Mado-N (Sonic 2026-10-31, MA-1 / MA-2): AnkiConnect missing on the Anki line, Mado-A's one rule and words ------ #
def _closed_with(running, n=19):
    rec = _record(*[runner.ANKI_CLOSED] * n, openable=True)
    if running != "unlooked":
        rec["anki_running"] = running
    return rec


def test_anki_open_without_ankiconnect_says_so_with_the_steps_and_offers_no_open_anki():
    # why: the stuck case (IK-4) — *Open Anki* answered "already open" and the line said Anki wasn't open
    from app import ankiconnect_addon as A
    entry, = _anki_entries(_closed_with(True))
    assert entry.title == f"{A.NO_CONNECT}: 19 episodes wait for it"
    assert entry.data["steps"] == "no_addon" and entry.actions == ()
    assert entry.data["running"] is True and entry.data["closed"]


def test_a_look_that_cant_tell_says_both_and_keeps_open_anki_with_open_anki_first_in_the_steps():
    from app import ankiconnect_addon as A
    entry, = _anki_entries(_closed_with(None, n=1))
    assert entry.title == f"{A.UNSURE}: 1 episode waits for it"
    assert entry.data["steps"] == "unsure" and entry.actions == ("open_anki",)


@pytest.mark.parametrize("running", [False, "unlooked"])
def test_anki_seen_closed_or_not_looked_for_is_the_plain_line_with_no_steps(running):
    entry, = _anki_entries(_closed_with(running))
    assert entry.title == "Anki isn't open: 19 episodes wait for it"
    assert entry.data["steps"] is None and entry.actions == ("open_anki",) and entry.data["running"] is False


def test_the_words_changing_keep_the_lines_key_so_it_never_counts_again():
    # why: Anki opened without AnkiConnect changes the words, not the trouble — a seen line stays seen
    keys = {_anki_entries(_closed_with(r))[0].key for r in (True, None, False)}
    assert len(keys) == 1


def test_a_permission_prompt_never_shows_the_steps_whatever_the_process_list_says():
    rec = _record(anki_session.UNUSABLE, openable=True)
    rec["anki_running"] = True
    entry, = _anki_entries(rec)
    assert entry.title == "Anki needs you: 1 episode waits for it" and entry.data["steps"] is None


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_read_connect_looks_for_an_anki_process_only_while_the_closed_line_needs_it(monkeypatch, language):
    from app import ankiconnect_addon
    from app.connect import open_anki, status
    asked = []
    monkeypatch.setattr(open_anki, "find", lambda: None)
    monkeypatch.setattr(ankiconnect_addon, "running", lambda: asked.append(1) or True)
    for reasons, want in (([runner.ANKI_CLOSED], True), ([runner.REVIEWING], "absent"),
                          ([anki_session.UNUSABLE], "absent")):
        asked.clear()
        rec = {"languages": {language: _record(*reasons)}}
        monkeypatch.setattr(status, "read", lambda languages=None, path=None, rec=rec: rec)
        got = service.read_connect(language)
        assert got.get("anki_running", "absent") == want and len(asked) == (1 if want is True else 0)
