"""The Anki window in Qt (W3.4 row 3; `app/qt/anki_window.py`, its rules in `app/anki_window.py`): the port of the Tk
`AnkiSyncGui`, every control of its inventory (§1) and both confirmations (§2), its data-safety contract (§4) and the
fixes of its latent defects (§9).

What a wrong answer would cost: known words appended twice at once (the window's sync beside the automatic one), read
by merely opening the window (S16), or read while an update waits; a Replace that writes numbers the user never saw,
or that a stray Esc / Enter confirms; the words dismissed in Migaku brought back by a Replace (W3.4-1); a Restore that
puts back something else than it says; a window still writing the old language's file after a switch, or a job's
result lost when the window switched or closed; a dead or untipped control.

Anki is the suite's fake collection behind a patched `urllib.request.urlopen` (loopback-only; never live Anki); real
Japanese and Chinese words from `tests/Test Resources/`; a temp `SURASURA_TEST_ROOT`, offscreen.
"""
import json
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import anki_sync, settings_manager
from app.path_utils import get_user_files_path
from app.qt import anki_window as QAW
from app.qt import confirm, shell, strings, windows
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems
from tests.test_anki_window import FakeAnki

WORDS = ["冒険", "準備", "危険", "価値", "冒険家", "有名", "素晴らしい", "求める"]


@pytest.fixture
def main(qapp, ja_resources_dir):
    with open(os.path.join(ja_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    assert all(w[:2] in text for w in WORDS), "real words from the shared Japanese resources"
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


@pytest.fixture
def anki(monkeypatch):
    fake = FakeAnki([{"word": w, "deck": "TheBank"} for w in WORDS[:3]], decks=["Grammar"])
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


def _choose(main, language="ja", decks=("TheBank",), **extra):
    """Choices already saved (a returning user), written before the window opens."""
    changes = {"anki_sync_decks": {language: list(decks)}}
    changes.update(extra)
    main.services.settings.set(changes, now=True)


def _open(main, connect=True):
    w = windows.show(main, QAW.NAME, QAW.AnkiWindow)
    if connect:
        w.refresh_connection()
        assert wait_until(lambda: not w._probing)
    assert wait_until(lambda: w._known is not None)
    return w


def _idle(main, w):
    assert wait_until(lambda: not w.busy() and not main.services.registry.live("anki-sync"), 10)
    QApplication.processEvents()


def _file(language="ja"):
    return os.path.join(get_user_files_path(language), "KnownWord.json")


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _words(language="ja"):
    with open(_file(language), encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data["words"]


def _trash(language="ja"):
    folder = os.path.join(get_user_files_path(language), ".trash")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def _migaku(ja_resources_dir):
    """A real Migaku export slice: KNOWN, LEARNING, UNKNOWN and IGNORED entries."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        data = json.load(f)
    picked = [w for w in data["words"] if w["knownStatus"] == "KNOWN"][:20]
    for status in ("LEARNING", "UNKNOWN", "IGNORED"):
        picked += [w for w in data["words"] if w["knownStatus"] == status][:3]
    data["words"] = picked
    os.makedirs(os.path.dirname(_file()), exist_ok=True)
    with open(_file(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _saved(main):
    assert main.services.settings.flush(5)
    return settings_manager.load_settings()


def _say_no_with(key):
    QTest.keyClick(QApplication.focusWidget(), key)
    QApplication.processEvents()


class _Gate:
    """Holds `anki_sync.sync` mid-way, as a slow Anki would."""

    def __init__(self, monkeypatch):
        self.event, self.modes = threading.Event(), []
        real = anki_sync.sync

        def held(*args, **kw):
            self.modes.append("full" if kw.get("full") else "delta")
            self.event.wait(10)
            return real(*args, **kw)
        monkeypatch.setattr(anki_sync, "sync", held)


# --- every control, wired (inv §1) ------------------------------------------------------------------------------ #
def test_every_control_is_wired_tipped_and_named_with_both_doors(main, anki, monkeypatch):
    opened = []
    doors = [windows.Opener("backfill", "Backfill", "x", windows.always, lambda s: opened.append("backfill")),
             windows.Opener("apkg", "Import .apkg", "x", windows.always, lambda s: opened.append("apkg"))]
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + doors)
    _choose(main)
    w = _open(main)
    assert w.windowTitle() == "Anki known words — Surasura"
    assert not w.btn_backfill.isHidden() and not w.btn_apkg.isHidden()
    assert w.deck_list.count() == 1
    found, walked = problems(w)
    assert found == [] and walked >= 9      # ⟳, Backfill, ✕, .apkg, Restore, Replace, Sync, three switches


def test_the_anki_door_is_on_the_settings_tab_and_opens_one_window(main):
    op = next(o for o in windows.OPENERS if o.name == "anki")
    assert not main.launchers.buttons["anki"].isHidden()
    a = windows.launch(main, op)
    b = windows.launch(main, op)
    assert a is b and isinstance(a, QAW.AnkiWindow)


def test_not_connected_says_so_plainly_and_only_the_recheck_works(main, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", FakeAnki(offline=True))
    _choose(main)
    w = _open(main)
    assert w.state.text() == strings.ANKI_STATE_CLOSED and w.status.text() == strings.ANKI_CLOSED_LINE
    assert w.btn_recheck.isEnabled()
    assert not any(b.isEnabled() for b in (w.btn_sync, w.btn_replace, w.add_box, w.box_field1, w.box_field2))


def test_a_permission_prompt_is_shown_as_anki_wrote_it(main, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", FakeAnki(permission="denied"))
    w = _open(main)
    assert "permission" in w.status.text() and w.state.text() == strings.ANKI_STATE_CLOSED


def test_connected_it_shows_the_studied_counts_the_fields_and_the_known_total(main, anki, ja_resources_dir):
    _migaku(ja_resources_dir)
    _choose(main)
    w = _open(main)
    assert w.state.text() == strings.ANKI_STATE_CONNECTED and "AnkiConnect 6" in w.state.toolTip()
    row = w.deck_list.itemWidget(w.deck_list.item(0))
    assert strings.ANKI_STUDIED.format(n=3) in [lab.text() for lab in row.findChildren(type(w.total))]
    assert w.resolved.text() == "Lapis → Expression" and w.skipped.isHidden()
    assert w.total.text() == f"{anki_sync.count_known('ja'):,}"
    assert [w.add_box.itemText(i) for i in range(w.add_box.count())] == ["Grammar"]


def test_a_deck_removed_while_anki_is_checked_never_leaves_the_check_again_off(main, anki, monkeypatch):
    """A scope read asked during the probe makes the probe's answer stale; the window must still know the probe ended
    (else ⟳ stays off for good)."""
    from app import anki_window as AW
    _choose(main, decks=("TheBank", "Grammar"))
    w = _open(main)
    gate, real = threading.Event(), AW.read_probe
    monkeypatch.setattr(AW, "read_probe", lambda *a: (gate.wait(10), real(*a))[1])
    w.refresh_connection()
    assert not w.btn_recheck.isEnabled()
    w.remove_deck("Grammar")
    gate.set()
    assert wait_until(lambda: w.btn_recheck.isEnabled())
    assert w.decks == ["TheBank"]
    assert w.state.text() == strings.ANKI_STATE_CONNECTED, "never left saying checking…"


def test_a_named_field_that_a_note_type_lacks_is_named_as_skipped(main, anki):
    anki.add(WORDS[4], deck="TheBank", model="Migaku Japanese", fields=[("Target Word", WORDS[4])])
    _choose(main, **{"anki_sync_fields": {"ja": ["Expression"]}})
    w = _open(main)
    assert w.resolved.text() == "Lapis → Expression"
    assert w.skipped.text() == strings.ANKI_SKIPPED.format(model="Migaku Japanese") and not w.skipped.isHidden()
    assert w.box_field2.isEnabled(), "Also read waits for a named word field: here there is one"


# --- nothing written by opening (S16, IK-13) ------------------------------------------------------------------- #
def test_the_first_open_pick_is_shown_and_saved_only_on_the_first_action(main, anki):
    w = _open(main)
    assert w.decks == ["TheBank"] and w.status.text() == strings.ANKI_PICKED
    assert (_saved(main).get("anki_sync_decks") or {}).get("ja") is None, "opening the window wrote nothing"
    w.btn_sync.click()
    _idle(main, w)
    assert _saved(main)["anki_sync_decks"]["ja"] == ["TheBank"]
    assert [x["dictForm"] for x in _words()] == WORDS[:3]


def test_adding_and_removing_a_deck_saves_this_languages_choice_alone(main, anki):
    _choose(main, **{"anki_sync_decks": {"ja": ["TheBank"], "zh": ["中文"]}})
    w = _open(main)
    w.add_box.activated.emit(0)                            # Grammar
    assert wait_until(lambda: w.decks == ["TheBank", "Grammar"])
    assert _saved(main)["anki_sync_decks"] == {"ja": ["TheBank", "Grammar"], "zh": ["中文"]}
    w.deck_list.setCurrentRow(0)
    QTest.keyClick(w.deck_list, Qt.Key.Key_Delete)
    assert w.decks == ["Grammar"]
    row = w.deck_list.itemWidget(w.deck_list.item(0))
    from PyQt6.QtWidgets import QToolButton
    row.findChild(QToolButton).click()
    assert w.decks == [] and not w.no_decks.isHidden() and not w.btn_sync.isEnabled()
    assert _saved(main)["anki_sync_decks"] == {"ja": [], "zh": ["中文"]}


# --- Sync now: append-only, one job (inv §4) --------------------------------------------------------------------- #
def test_sync_is_an_anki_sync_job_and_a_second_press_while_it_runs_starts_nothing(main, anki, monkeypatch,
                                                                                  ja_resources_dir):
    before = _migaku(ja_resources_dir)["words"]
    _choose(main)
    w = _open(main)
    gate = _Gate(monkeypatch)
    w.btn_sync.click()
    assert wait_until(lambda: gate.modes)
    assert w.busy() and w.status.text() == strings.ANKI_SYNCING
    assert not w.chk_suspended.isEnabled(), "the scope never changes under a job (inv defect 4)"
    w.on_sync()
    w.btn_sync.click()
    live = main.services.registry.live("anki-sync")
    assert len(live) == 1 and live[0].label == strings.ANKI_JOB_SYNC
    gate.event.set()
    _idle(main, w)
    assert gate.modes == ["delta"], "one sync, a plain click: only what is new (the engine reads all on a first sync)"
    words = _words()
    assert words[:len(before)] == before, "append-only: every entry kept, in its order"
    assert [x["dictForm"] for x in words[len(before):]] == WORDS[:3]
    assert w.status.text() == strings.ANKI_SYNCED.format(added=3, scanned=3)
    assert w.delta.text() == "+3" and w.total.text() == f"{anki_sync.count_known('ja'):,}"


def test_shift_click_re_reads_every_card(main, anki, monkeypatch):
    _choose(main)
    w = _open(main)
    w.btn_sync.click()
    _idle(main, w)
    gate = _Gate(monkeypatch)
    gate.event.set()
    QTest.mouseClick(w.btn_sync, Qt.MouseButton.LeftButton)
    _idle(main, w)
    QTest.mouseClick(w.btn_sync, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    _idle(main, w)
    assert gate.modes == ["delta", "full"]
    assert "Shift-click" in w.btn_sync.toolTip()


def test_its_result_reaches_the_automation_service(main, anki):
    heard = []
    main.services.automation = type("A", (), {"anki_synced": lambda self, r, lang: heard.append((r.added, lang))})()
    _choose(main)
    w = _open(main)
    w.btn_sync.click()
    _idle(main, w)
    assert heard == [(3, "ja")]


def test_nothing_starts_while_an_update_holds_the_children(main, anki, monkeypatch):
    from app import updater
    _choose(main)
    w = _open(main)
    monkeypatch.setattr(updater, "children_held", lambda: True)
    for press in (w.btn_sync.click, w.btn_replace.click):
        press()
        assert w.status.text() == strings.ANKI_UPDATE_WAITS and not w.busy()
    assert main.services.registry.snapshot() == () and not os.path.exists(_file())


def test_the_automatic_syncs_result_reads_the_numbers_again(main, anki):
    _choose(main)
    w = _open(main)
    assert w.total.text() == "0"
    anki_sync.sync("ja", "http://127.0.0.1:8765", ["TheBank"], [])
    from app.services.automation import State
    main.bridge.automation_changed.emit(State("synced", "ja", 3, 3, None, None, 7))
    assert wait_until(lambda: w.total.text() == "3")


# --- Replace: dry run → the numbers → backup → write (inv §2, §4; W3.4-1) ----------------------------------------- #
def test_replace_asks_with_the_true_numbers_and_esc_and_enter_are_no(main, anki, ja_resources_dir):
    _migaku(ja_resources_dir)
    before = _bytes(_file())
    _choose(main)
    w = _open(main)
    now = anki_sync.count_known("ja")
    for no in (Qt.Key.Key_Escape, Qt.Key.Key_Return):
        w.btn_replace.click()
        assert wait_until(lambda: getattr(w, "question", None) is not None and w.question.isVisible())
        card = w.question
        assert card.title.text() == strings.ANKI_REPLACE_TITLE
        assert card.body.text() == strings.ANKI_REPLACE_BODY.format(now=now, after=3, anki=3, graduated=0, ignored=3)
        assert "Finished" not in card.body.text() and "earlier imports will be removed" not in card.body.text()
        assert card.default is card.no and card.yes.text() == strings.ANKI_REPLACE_YES
        assert wait_until(lambda: QApplication.focusWidget() is card.no)
        _say_no_with(no)
        assert wait_until(lambda: not w.busy())
        w.question = None
    assert _bytes(_file()) == before and _trash() == []


def test_replace_after_yes_backs_up_first_keeps_the_ignored_words_and_says_so(main, anki, ja_resources_dir):
    data = _migaku(ja_resources_dir)
    before = _bytes(_file())
    ignored = [x for x in data["words"] if x["knownStatus"] == "IGNORED"]
    _choose(main)
    w = _open(main)
    w.btn_replace.click()
    assert wait_until(lambda: getattr(w, "question", None) is not None and w.question.isVisible())
    w.question.yes.click()
    _idle(main, w)
    assert [x["dictForm"] for x in _words() if x.get("source") == "AnkiConnect"] == WORDS[:3]
    assert [x for x in _words() if x["knownStatus"] == "IGNORED"] == ignored
    assert len(_trash()) == 1 and _bytes(os.path.join(get_user_files_path("ja"), ".trash", _trash()[0])) == before
    assert w.status.text() == (strings.ANKI_REPLACED.format(total=3, added=3, graduated=0)
                               + strings.ANKI_REPLACED_IGNORED.format(ignored=3))
    assert wait_until(lambda: not w.btn_restore.isHidden()), "a backup to put back: Restore previous shows"


def test_replace_whose_numbers_changed_meanwhile_asks_again_and_writes_nothing_until_yes(main, anki,
                                                                                         ja_resources_dir):
    _migaku(ja_resources_dir)
    before = _bytes(_file())
    _choose(main)
    w = _open(main)
    w.btn_replace.click()
    assert wait_until(lambda: getattr(w, "question", None) is not None and w.question.isVisible())
    first = w.question
    anki.add(WORDS[3], deck="TheBank")                     # studied in Anki while the question was open
    first.yes.click()
    assert wait_until(lambda: w.question is not first and w.question.isVisible(), 10)
    assert w.question.title.text() == strings.ANKI_REPLACE_AGAIN_TITLE
    assert "→ 4\n• 4 from Anki" in w.question.body.text()
    assert w.busy() and _bytes(_file()) == before and _trash() == []
    w.question.yes.click()
    _idle(main, w)
    assert [x["dictForm"] for x in _words() if x.get("source") == "AnkiConnect"] == WORDS[:4]


def test_replace_from_an_empty_anki_never_asks_and_never_writes(main, monkeypatch, ja_resources_dir):
    _migaku(ja_resources_dir)
    before = _bytes(_file())
    monkeypatch.setattr("urllib.request.urlopen", FakeAnki([{"word": WORDS[0], "deck": "TheBank", "new": True}]))
    _choose(main)
    w = _open(main)
    w.btn_replace.click()
    _idle(main, w)
    assert "no words" in w.status.text() and getattr(w, "question", None) is None
    assert _bytes(_file()) == before and _trash() == []


# --- Restore previous (inv §2; defect 7) ------------------------------------------------------------------------ #
def test_restore_names_what_it_puts_back_enter_is_no_and_yes_backs_up_first(main, anki, ja_resources_dir):
    _migaku(ja_resources_dir)
    original, original_known = _bytes(_file()), anki_sync.count_known("ja")
    _choose(main)
    w = _open(main)
    w.btn_replace.click()
    assert wait_until(lambda: getattr(w, "question", None) is not None and w.question.isVisible())
    w.question.yes.click()
    _idle(main, w)
    replaced = _bytes(_file())
    point_name = anki_sync.load_state("ja")["last_backup"]
    assert wait_until(lambda: not w.btn_restore.isHidden())
    w.question = None
    w.btn_restore.click()
    assert wait_until(lambda: getattr(w, "question", None) is not None and w.question.isVisible())
    card = w.question
    when = QAW.AW.backup_time(point_name).strftime(strings.ANKI_WHEN)
    assert card.title.text() == strings.ANKI_RESTORE_TITLE.format(when=when)
    assert card.body.text() == strings.ANKI_RESTORE_BODY.format(now=3, then=original_known)
    assert card.default is card.no
    assert wait_until(lambda: QApplication.focusWidget() is card.no)
    _say_no_with(Qt.Key.Key_Return)
    assert wait_until(lambda: not w.busy()) and _bytes(_file()) == replaced
    w.question = None
    w.btn_restore.click()
    assert wait_until(lambda: getattr(w, "question", None) is not None and w.question.isVisible())
    w.question.yes.click()
    _idle(main, w)
    assert _bytes(_file()) == original
    assert len(_trash()) == 2, "the replaced list was backed up before the restore"
    assert w.status.text() == strings.ANKI_RESTORED.format(total=anki_sync.count_known("ja"))


# --- the language (🧭 IK-12; inv defect 3) ---------------------------------------------------------------------- #
def test_idle_it_follows_the_main_windows_language(main, anki):
    _choose(main, **{"anki_sync_decks": {"ja": ["TheBank"], "zh": ["中文"]}})
    w = _open(main)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh" and w.decks == ["中文"])
    assert wait_until(lambda: not w._probing)
    assert w.heading.toolTip().startswith("Adds the words from Chinese cards")


def test_a_switch_during_a_sync_waits_for_it_its_result_goes_to_the_bar_and_only_its_language_is_written(
        main, anki, monkeypatch):
    _choose(main, **{"anki_sync_decks": {"ja": ["TheBank"], "zh": ["中文"]}})
    w = _open(main)
    gate = _Gate(monkeypatch)
    w.btn_sync.click()
    assert wait_until(lambda: gate.modes)
    main.services.settings.set({"target_language": "zh"})
    assert main.services.settings.flush(5)
    QTest.qWait(100)
    assert w.language == "ja" and w.busy(), "never cut: still the language it writes for"
    gate.event.set()
    _idle(main, w)
    line = strings.ANKI_SYNCED.format(added=3, scanned=3)
    assert wait_until(lambda: w.language == "zh")
    assert main.bar_line.full() == line
    assert [x["dictForm"] for x in _words("ja")] == WORDS[:3] and not os.path.exists(_file("zh"))
    assert w.status.text() == "" and w.decks == ["中文"]


# --- the doors (inv §1 #4, #19; defect 8) ------------------------------------------------------------------------ #
def test_without_their_openers_the_doors_are_hidden(main, anki):
    w = _open(main, connect=False)
    names = {o.name for o in windows.OPENERS}
    assert w.btn_backfill.isHidden() == ("backfill" not in names)
    assert w.btn_apkg.isHidden() == ("apkg" not in names)


def test_the_apkg_door_never_closes_this_window_even_mid_job(main, anki, monkeypatch):
    opened = []
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + [
        windows.Opener("apkg", "Import .apkg", "x", windows.always, lambda s: opened.append("apkg")),
        windows.Opener("backfill", "Backfill", "x", lambda s, lang: lang == "ja", lambda s: opened.append("bf"))])
    _choose(main)
    w = _open(main)
    gate = _Gate(monkeypatch)
    w.btn_sync.click()
    assert wait_until(lambda: gate.modes)
    w.btn_apkg.click()
    w.btn_backfill.click()
    assert opened == ["apkg", "bf"] and w.isVisible() and windows.opened(main, QAW.NAME) is w
    gate.event.set()
    _idle(main, w)
    assert w.status.text() == strings.ANKI_SYNCED.format(added=3, scanned=3), "its result is still shown"


def test_the_switches_save_their_own_key_and_the_first_pick_with_them(main, anki):
    w = _open(main)
    assert w._unsaved_pick
    w.chk_auto.click()
    w.chk_generate.click()
    saved = _saved(main)
    assert saved["anki_sync_auto"] is True and saved["anki_auto_generate"] is True
    assert saved["anki_sync_decks"]["ja"] == ["TheBank"], "a first action saves the pick shown"
    w.chk_suspended.click()
    assert _saved(main)["anki_sync_include_suspended"] is True
