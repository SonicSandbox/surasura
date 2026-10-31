"""AnkiConnect missing (alpha 8, Mado-A): the one rule and the one set of words setup's Anki step, Settings' Connection
row and Connect's setup check read (`app/ankiconnect_addon.py`)."""
from app import anki_connect
from app import ankiconnect_addon as A


def test_the_three_steps_read_as_one_line_with_the_code_only_where_no_button_copies_it():
    assert A.CODE == "2055492159"
    assert A.steps_line() == "In Anki: Tools › Add-ons › Get Add-ons… → paste the code → restart Anki"
    assert A.steps_line(code=True) == ("In Anki: Tools › Add-ons › Get Add-ons… → paste the code 2055492159 → "
                                       "restart Anki")
    assert A.steps_line(unsure=True) == ("Open Anki. If it's open already: Tools › Add-ons › Get Add-ons… → "
                                         "paste the code → restart Anki")


def test_the_steps_show_only_when_an_anki_may_be_open_and_nothing_answered():
    # a probe's report (Settings) and the wizard's look (`anki_look`) are read by the same rule
    refused = {"ok": False, "version": None, "error": "refused"}
    assert A.needs_addon(dict(refused, running=True))
    assert A.needs_addon(dict(refused, running=None))           # can't tell: the steps, with Open Anki first
    assert not A.needs_addon(dict(refused, running=False))      # no Anki running: it's closed, nothing to install
    assert not A.needs_addon(refused)                           # no process looked for: never guessed
    assert not A.needs_addon({"ok": False, "timed_out": True, "running": True})       # open but busy
    assert not A.needs_addon({"ok": False, "version": 6, "running": True})            # answered, kept Surasura out
    assert not A.needs_addon({"ok": True, "running": True})
    assert not A.needs_addon({"open": True, "running": True})
    assert not A.needs_addon({"open": False, "say": None, "decks": [], "preselected": []})
    assert A.needs_addon({"open": False, "say": None, "decks": [], "preselected": [], "running": True})
    assert not A.needs_addon(None)


def test_the_light_look_asks_once_with_a_short_wait_and_counts_any_answer(monkeypatch):
    asked = []
    answer = {}

    def probe(url, required=(), timeout=5):
        asked.append((url, tuple(required), timeout))
        return dict(answer)
    monkeypatch.setattr(anki_connect, "probe", probe)
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")             # the suites' guard: a live Anki is never asked
    assert A.answers("http://127.0.0.1:8765") is False and asked == []
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC")
    answer.update(ok=False, version=None, error="refused")
    assert A.answers("http://127.0.0.1:8765") is False
    answer.update(ok=False, version=6, error="Anki did not grant access")             # a permission prompt: answered
    assert A.answers("http://127.0.0.1:8765") is True
    answer.update(ok=True, version=6, error="")
    assert A.answers("http://127.0.0.1:8765") is True
    assert asked == [("http://127.0.0.1:8765", (), A.LOOK_TIMEOUT)] * 3


def test_running_is_none_when_the_process_list_cant_be_read(monkeypatch):
    from app.connect import open_anki

    def broken():
        raise OSError("tasklist missing")
    monkeypatch.setattr(open_anki, "running", broken)
    assert A.running() is None
    monkeypatch.setattr(open_anki, "running", lambda: True)
    assert A.running() is True


def test_settings_check_looks_for_an_anki_process_only_when_nothing_answered(monkeypatch):
    from app.qt import settings_live as live
    looked = []
    monkeypatch.setattr(A, "running", lambda: looked.append(1) or True)
    for report, runs in (({"ok": False, "version": None, "error": "refused"}, True),
                         ({"ok": False, "version": None, "error": "slow", "timed_out": True}, False),
                         ({"ok": False, "version": 6, "error": "Anki did not grant access"}, False),
                         ({"ok": True, "version": 6}, False)):
        monkeypatch.setattr(anki_connect, "probe", lambda url, timeout=5, r=report: dict(r))
        looked.clear()
        out = live.probe_anki({})
        assert bool(looked) == runs and ("running" in out) == runs
