"""The known-word importers and Extract in Qt (W3.4 row 2; `app/qt/importers.py`): every control of the inventory's
§1 and every confirmation of its §2 in the Qt windows, the confirmations' gates, the children's arguments, and the key.

What a wrong answer would cost: the user's known words replaced by a click they didn't confirm, or with numbers the
confirmation didn't state (Migaku's and Jiten's Tk windows asked nothing, or didn't say "replace"); Enter or Esc read
as "yes" on a replace; the Jiten key on a command line, in a log or in settings.json; a Chinese list replaced with
Jiten's Japanese words; Extract replacing a show the library holds; the window frozen while a deck is tokenized (the
child's job); a door that opens nothing.

The children are recorded (`tools.run` stood in for) except where a test names a real child; the decks, the Migaku
export and the texts are the real ones in `tests/Test Resources/`.
"""
import json
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import anki_db_import, extract, settings_manager
from app.path_utils import get_data_path, get_settings_path, get_user_files_path
from app.qt import confirm, importers, shell, strings, windows
from app.services import tools
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems

RES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
DECK = os.path.join(RES, "ja", "testAnki.apkg")
MIGAKU = os.path.join(RES, "ja", "MigakuDb.db")
SECRET = "jiten-secret-key-123"


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


class Runs:
    """`tools.run` stood in for: each call recorded; the test plays the child's lines and its end."""

    def __init__(self):
        self.calls = []

    def __call__(self, registry, kind, label, argv, env=None, on_line=None, on_end=None, on_quit="cancel", **_kw):
        call = SimpleNamespace(kind=kind, label=label, argv=list(argv), env=dict(env or {}), on_line=on_line,
                               on_end=on_end, on_quit=on_quit)
        self.calls.append(call)
        return call

    def end(self, code, *lines):
        call = self.calls[-1]
        for line in lines:
            call.on_line(line)
        call.on_end(code)
        QApplication.processEvents()


@pytest.fixture
def runs(monkeypatch):
    r = Runs()
    monkeypatch.setattr(tools, "run", r)
    return r


def _card(w):
    cards = [c for c in w.findChildren(confirm.Confirm) if c.answer is None]
    return cards[-1] if cards else None


def _known(words):
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": words}, f, ensure_ascii=False)


CURRENT = [{"dictForm": "冒険", "knownStatus": "KNOWN", "hasCard": 1},
           {"dictForm": "旅", "knownStatus": "KNOWN", "source": "GraduatedList"},
           {"dictForm": "えっと", "knownStatus": "IGNORED", "hasCard": 0}]


# --- the doors and the wiring --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["apkg_known", "migaku", "jiten", "extract"])
def test_each_door_opens_its_window_once_and_every_control_is_wired_tipped_and_named(main, name):
    op = next(o for o in windows.OPENERS if o.name == name)
    w = windows.launch(main, op)
    assert w is not None and w.isVisible() and w.windowTitle().endswith("— Surasura")
    assert windows.launch(main, op) is w                      # one of a kind, raised
    found, walked = problems(w)
    assert found == [] and walked >= 2


def test_jitens_door_shows_for_japanese_only(main):
    op = next(o for o in windows.OPENERS if o.name == "jiten")
    assert windows.available(op, {}, "ja") and not windows.available(op, {}, "zh")
    for name in ("apkg_known", "migaku", "extract"):
        o = next(o for o in windows.OPENERS if o.name == name)
        assert windows.available(o, {}, "zh") and o.module is None


# --- .apkg (inv §2) ------------------------------------------------------------------------------------------------ #
def test_the_deck_window_reads_the_deck_on_a_worker_and_shows_its_fields_and_first_notes(main, runs):
    w = importers.open_deck(main)
    assert not w.go.isEnabled() and not w.field.isVisibleTo(w)
    w.path.setText(DECK)
    w.choose(DECK)
    assert w.status.text() == strings.APKG_READING            # the read is a worker's: the window answers at once
    assert wait_until(lambda: w.deck is not None)
    assert w.field.isVisibleTo(w) and w.field.currentText() == w.deck.default
    assert w.sample.toPlainText() == w.deck.samples[w.deck.default]
    assert w.go.isEnabled()
    labels = [l.text() for l in w.findChildren(type(w.status))]
    assert strings.APKG_EVERY_NOTE in labels                  # the tested sentence, kept (inv §2.1 #8)


def test_a_deck_that_isnt_there_is_said_by_the_read_on_a_worker(main, runs, tmp_path):
    """IK-59: the window's thread never looks at the disk; the worker's read says the deck can't be read."""
    w = importers.open_deck(main)
    w.choose(str(tmp_path / "無い.apkg"))
    assert wait_until(lambda: w.status.text().startswith(strings.IMPORTERS_READ_FAILED.split("{")[0]))
    assert w.deck is None and not w.go.isEnabled()


def test_the_deck_import_runs_only_after_a_yes_that_names_what_it_adds(main, runs):
    w = importers.open_deck(main)
    w.choose(DECK)
    assert wait_until(lambda: w.deck is not None)
    w.go.click()
    card = _card(w)
    assert card is not None and runs.calls == []
    assert f"{w.deck.notes:,} notes" in card.body.text() and w.deck.default in card.body.text()
    QTest.keyClick(card, Qt.Key.Key_Escape)                   # Esc is No
    QApplication.processEvents()
    assert runs.calls == []
    w.go.click()
    _card(w).yes.click()
    [call] = runs.calls
    assert call.kind == "known-import"
    assert call.argv == ["anki_db_import.py", "--language", "ja", f"--file={DECK}", f"--field={w.deck.default}"]
    assert not w.go.isEnabled()                               # one at a time
    runs.end(0, "Found 40 words in 'Sentence'", anki_db_import.result_line(anki_db_import.Merge(12, 3, 52, None,
                                                                                                  None, False)))
    assert w.status.text() == strings.APKG_DONE.format(added=12, raised=3, total=52)
    assert w.go.isEnabled() and not w.log_button.isVisibleTo(w)


def test_a_busy_or_failed_deck_import_says_why_and_offers_the_log(main, runs):
    w = importers.open_deck(main)
    w.choose(DECK)
    assert wait_until(lambda: w.deck is not None)
    w.start(DECK, w.deck.default, "ja")
    runs.end(5, "Error: Your known words are being updated by Anki known-words sync. Nothing was changed: try again "
                "in a moment.")
    assert w.status.text().startswith(strings.IMPORTERS_FAILED.format(why="Your known words are being updated"))
    assert w.log_button.isVisibleTo(w)


def test_a_file_that_isnt_a_deck_is_said_and_nothing_is_read(main, runs, tmp_path):
    w = importers.open_deck(main)
    text = tmp_path / "本文.txt"
    text.write_text("吾輩は猫である。", encoding="utf-8")
    w.choose(str(text))
    assert w.status.text() == strings.APKG_NOT_A_DECK and w.deck is None and not w.go.isEnabled()


def test_the_real_child_imports_a_real_deck_into_known_words(main):
    """End to end: the window's argv through the real runner and the source map (`python app/anki_db_import.py`)."""
    _known(CURRENT)
    w = importers.open_deck(main)
    w.choose(DECK)
    assert wait_until(lambda: w.deck is not None)
    w.start(DECK, w.deck.default, "ja")
    assert wait_until(lambda: not w.busy(), timeout=120)
    assert w.status.text().startswith(strings.APKG_DONE.split("{")[0]), w.status.text()
    with open(os.path.join(get_user_files_path("ja"), "KnownWord.json"), encoding="utf-8") as f:
        words = json.load(f)["words"]
    assert [x["dictForm"] for x in words[:3]] == ["冒険", "旅", "えっと"] and len(words) > 3
    assert os.listdir(os.path.join(get_user_files_path("ja"), ".trash"))   # the dated backup


# --- Migaku (inv §3) --------------------------------------------------------------------------------------------------- #
def test_copy_puts_the_console_line_on_the_clipboard(main, runs):
    from app import migaku_converter
    w = importers.open_migaku(main)
    w.copy.click()
    assert QApplication.clipboard().text() == migaku_converter.CONSOLE_CODE
    assert w.status.text() == strings.MIGAKU_COPIED


def test_a_migaku_file_is_read_first_then_one_confirmation_with_both_numbers_cancel_the_default(main, runs):
    _known(CURRENT)
    w = importers.open_migaku(main)
    w.read(MIGAKU)
    assert wait_until(lambda: _card(w) is not None)
    card = _card(w)
    from app import importers_view
    plan = importers_view.migaku_plan(MIGAKU, "ja")           # the numbers stated are the plan's (read first)
    assert f"{plan.now:,} → {plan.after:,}" in card.body.text() and plan.now == 2 and plan.after > 2
    assert plan.graduated == 0 and "Graduates" not in card.body.text()   # 旅 is in the export: no "0 … kept" line
    assert plan.ignored == 1 and strings.IGNORED_BACK[0].format(n=1) in card.body.text()   # えっと (IK-50)
    assert "1 word you ignored in Migaku is no longer ignored (the backup keeps it)." in card.body.text()   # IK-2
    assert card.yes.text() == strings.MIGAKU_ASK_YES and card.yes.property("kind") == "danger"
    assert card.default is card.no
    QTest.keyClick(card, Qt.Key.Key_Return)                    # Enter = Cancel on a replace
    QApplication.processEvents()
    assert runs.calls == [] and card.answer is False
    w.read(MIGAKU)
    assert wait_until(lambda: _card(w) is not None)
    _card(w).yes.click()
    [call] = runs.calls
    assert call.kind == "known-import" and call.argv == ["migaku_converter.py", MIGAKU, "--language", "ja",
                                                         "--expect", importers_view.expect_arg(plan)]
    runs.end(0, "Found 10 words", "Conversion complete!")
    assert w.status.text() == strings.MIGAKU_DONE


def test_a_replace_with_no_dismissed_words_says_no_ignored_line(main, runs):
    """IK-44: the "N words you ignored come back" line only when there are some — never "0 … come back"."""
    _known([w for w in CURRENT if w["knownStatus"] != "IGNORED"])
    w = importers.open_migaku(main)
    w.read(MIGAKU)
    assert wait_until(lambda: _card(w) is not None)
    assert "ignored" not in _card(w).body.text()
    _card(w).no.click()
    j = importers.open_jiten(main)
    j.key.setText(SECRET)
    j.go.click()
    _fetched(runs, [{"wordText": "猫", "state": 5}])
    assert wait_until(lambda: _card(j) is not None)
    body = _card(j).body.text()
    assert "ignored" not in body and "1 word from past Graduates kept" in body
    _card(j).no.click()


def _unreadable_known():
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
        f.write('{"words": [{"dictForm": "冒険"')


def test_an_unreadable_known_words_file_is_said_before_any_question_or_replace(main, runs):
    """AD2-1: Migaku's and Jiten's plans refuse a known-words file that exists but can't be read — the window says so,
    asks nothing and starts no replace (Jiten's fetched cards are removed)."""
    _unreadable_known()
    w = importers.open_migaku(main)
    w.read(MIGAKU)
    assert wait_until(lambda: w.status.text() == strings.KNOWN_UNREADABLE)
    assert _card(w) is None and runs.calls == []
    j = importers.open_jiten(main)
    j.key.setText(SECRET)
    j.go.click()
    folder = os.path.dirname(runs.calls[-1].argv[-1])
    _fetched(runs, [{"wordText": "猫", "state": 5}])
    assert wait_until(lambda: j.status.text() == strings.KNOWN_UNREADABLE)
    assert _card(j) is None and len(runs.calls) == 1 and not os.path.exists(folder)


def test_a_language_switch_drops_an_open_replace_question_and_never_replaces_the_other_language(main, runs):
    """AD2-5: the question named one language's numbers; a switch to the other drops it, unanswered — a Yes could
    never replace the Chinese known words under the Japanese numbers."""
    _known(CURRENT)
    w = importers.open_migaku(main)
    w.read(MIGAKU)
    assert wait_until(lambda: _card(w) is not None)
    card = _card(w)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh")
    assert card.answer is False and _card(w) is None
    card.yes.click()                                          # a click on the dropped card does nothing
    QApplication.processEvents()
    assert runs.calls == []


def test_a_plan_read_for_one_language_is_never_asked_in_the_other(main, runs, monkeypatch):
    """AD2-5: the export was read for Japanese; the switch landed before the answer — it asks nothing."""
    _known(CURRENT)
    from app import importers_view
    plans = []

    def run_in_worker(fn, *a, then=None, failed=None):
        if getattr(fn, "__self__", None) is main.services:   # (the window's own language switch: same bridge, W3.2)
            return fn(*a)
        plans.append((fn(*a), then))
    monkeypatch.setattr(importers.bridge, "run_in_worker", run_in_worker)
    w = importers.open_migaku(main)
    w.read(MIGAKU)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh")
    [(plan, then)] = plans
    then(plan)                                                # the Japanese answer lands now
    assert _card(w) is None and runs.calls == []
    assert isinstance(plan, importers_view.Plan)


def test_a_language_switch_drops_the_deck_question_and_the_import_names_the_language_asked(main, runs):
    """AD2-5: the deck window's question too; and a Yes starts the child in the language it was asked in."""
    w = importers.open_deck(main)
    w.choose(DECK)
    assert wait_until(lambda: w.deck is not None)
    w.go.click()
    card = _card(w)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh")
    assert card.answer is False and runs.calls == []
    w.start(DECK, w.deck.default, "ja")
    assert runs.calls[-1].argv[:3] == ["anki_db_import.py", "--language", "ja"]


def test_a_language_switch_drops_jitens_question_and_its_fetched_cards(main, runs):
    _known(CURRENT)
    j = importers.open_jiten(main)
    j.key.setText(SECRET)
    j.go.click()
    folder = os.path.dirname(runs.calls[-1].argv[-1])
    _fetched(runs, [{"wordText": "猫", "state": 5}])
    assert wait_until(lambda: _card(j) is not None)
    card = _card(j)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: j.language == "zh")
    assert card.answer is False and len(runs.calls) == 1 and not os.path.exists(folder)


def test_a_replace_whose_numbers_moved_reads_again_and_asks_again(main, runs):
    """IK-56: the child found the known words changed since the yes (a sync appended words) and wrote nothing; the
    window says so, reads again and asks with the numbers as they are now."""
    _known(CURRENT)
    from app import anki_sync
    w = importers.open_migaku(main)
    w.read(MIGAKU)
    assert wait_until(lambda: _card(w) is not None)
    _card(w).yes.click()
    runs.end(anki_sync.EXIT_CHANGED, "Error: Your known words changed since you confirmed, so nothing was replaced.")
    assert wait_until(lambda: _card(w) is not None)
    assert len(runs.calls) == 1 and strings.KNOWN_CHANGED == w.status.text()
    j = importers.open_jiten(main)
    j.key.setText(SECRET)
    j.go.click()
    folder = os.path.dirname(runs.calls[-1].argv[-1])
    _fetched(runs, [{"wordText": "猫", "state": 5}])
    assert wait_until(lambda: _card(j) is not None)
    _card(j).yes.click()
    runs.end(anki_sync.EXIT_CHANGED, "Error: Your known words changed since you confirmed, so nothing was replaced.")
    assert wait_until(lambda: _card(j) is not None)             # asked again from the same fetched cards
    assert os.path.exists(folder) and len(runs.calls) == 3
    _card(j).no.click()
    assert not os.path.exists(folder)


def test_each_question_names_its_language(main, runs):
    """IK-53: a question never says which list it writes; now its title names it (日本語 / 中文), and the deck's says
    that words still being learned become known."""
    _known(CURRENT)
    w = importers.open_migaku(main)
    w.read(MIGAKU)
    assert wait_until(lambda: _card(w) is not None)
    assert strings.LANGUAGE_NAMES["ja"] in _card(w).accessibleName()
    _card(w).no.click()
    d = importers.open_deck(main)
    d.choose(DECK)
    assert wait_until(lambda: d.deck is not None)
    d.go.click()
    assert strings.LANGUAGE_NAMES["ja"] in _card(d).accessibleName() and "still learning" in _card(d).body.text()


def test_choose_a_file_asks_too(main, runs, monkeypatch):
    """The Tk window's *Select File Manually…* replaced the known words with no question at all (inv §3.9)."""
    _known(CURRENT)
    monkeypatch.setattr(importers, "_pick_file", lambda *a: MIGAKU)
    w = importers.open_migaku(main)
    w.choose.click()
    assert wait_until(lambda: _card(w) is not None)
    assert runs.calls == []


def test_find_it_for_me_says_what_it_found(main, runs, tmp_path):
    import sqlite3
    w = importers.open_migaku(main)
    w.find_it(str(tmp_path))
    assert wait_until(lambda: w.status.text() == strings.MIGAKU_NO_DB)
    sqlite3.connect(tmp_path / "other.db").close()
    w.find_it(str(tmp_path))
    assert wait_until(lambda: w.status.text() == strings.MIGAKU_NOT_MIGAKU)
    import shutil
    shutil.copy2(MIGAKU, tmp_path / "MigakuDb.db")
    w.find_it(str(tmp_path))
    assert wait_until(lambda: _card(w) is not None) and runs.calls == []


def test_a_db_that_isnt_migakus_is_said_and_nothing_asked(main, runs, tmp_path):
    import sqlite3
    other = tmp_path / "other.db"
    sqlite3.connect(other).close()
    w = importers.open_migaku(main)
    w.read(str(other))
    assert wait_until(lambda: w.status.text() == strings.MIGAKU_NOT_A_DB)
    assert _card(w) is None


def test_a_failed_migaku_import_says_why(main, runs):
    w = importers.open_migaku(main)
    w.start(MIGAKU, "ja")
    runs.end(1, "Error: could not back up your current known words, so nothing was changed (disk full).")
    assert "could not back up" in w.status.text() and w.log_button.isVisibleTo(w)


# --- Jiten (inv §4) -------------------------------------------------------------------------------------------------- #
def _fetched(runs, cards):
    """Play step 1's child: it keeps `cards` where the window asked, and exits 0."""
    path = runs.calls[-1].argv[-1]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False)
    runs.end(0, f"Fetched {len(cards)} cards; nothing changed yet.")


def test_jiten_fetches_first_with_the_key_in_the_environment_only_then_asks_with_both_numbers(main, runs):
    _known(CURRENT)
    w = importers.open_jiten(main)
    assert not w.go.isEnabled()
    w.key.setText(SECRET)
    assert w.key.echoMode() == w.key.EchoMode.Password
    w.go.click()
    [fetch] = runs.calls
    assert fetch.kind == "known-import" and fetch.argv[:4] == ["jiten_converter.py", "--language", "ja",
                                                               "--save-cards"]
    assert not any(SECRET in a for a in fetch.argv) and SECRET not in fetch.label
    from app import jiten_converter
    assert fetch.env == {jiten_converter.API_KEY_ENV: SECRET}
    folder = os.path.dirname(fetch.argv[-1])
    _fetched(runs, [{"wordText": "猫", "state": 5}, {"wordText": "犬", "state": 2}])
    assert wait_until(lambda: _card(w) is not None)
    card = _card(w)
    assert "2 → 2" in card.body.text()
    assert "1 word from past Graduates kept" in card.body.text()
    assert "1 word you ignored in Migaku is no longer ignored (the backup keeps it)" in card.body.text()   # IK-2
    assert card.default is card.no and len(runs.calls) == 1   # nothing replaced before the yes
    card.yes.click()
    replace = runs.calls[-1]
    assert replace.argv == ["jiten_converter.py", "--language", "ja", "--cards", os.path.join(folder, "cards.json"),
                            "--expect", "2,2,1,1"]
    assert replace.env == {}                                  # step 2 needs no key
    runs.end(0, "Conversion complete!")
    assert w.status.text() == strings.JITEN_DONE
    assert not os.path.exists(folder)                         # the fetched cards removed once the replace ended
    assert SECRET not in w.status.text()


def test_jitens_cancel_replaces_nothing_and_removes_the_fetched_cards(main, runs):
    _known(CURRENT)
    w = importers.open_jiten(main)
    w.key.setText(SECRET)
    w.fetch()
    folder = os.path.dirname(runs.calls[-1].argv[-1])
    _fetched(runs, [{"wordText": "猫", "state": 5}])
    assert wait_until(lambda: _card(w) is not None)
    QTest.keyClick(_card(w), Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert len(runs.calls) == 1 and not os.path.exists(folder)


def test_the_key_is_never_saved_and_never_in_the_log(main, monkeypatch, tmp_path):
    """A real child for step 1, its fetch sent to a dead loopback proxy (never the network): the key reaches it through
    the environment, and neither settings.json nor the tool's log holds it."""
    import app.jiten_converter as jc
    w = importers.open_jiten(main)
    w.key.setText(SECRET)
    w.show_key.setChecked(True)
    assert w.key.echoMode() == w.key.EchoMode.Normal
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")      # refused at once: the child can't reach Jiten
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    w.fetch()
    assert wait_until(lambda: not w.busy(), timeout=60)
    with open(tools.log_path("known-import"), encoding="utf-8") as f:
        log = f.read()
    assert SECRET not in log and "Fetching vocabulary" in log
    path = get_settings_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            assert SECRET not in f.read()
    assert jc.API_KEY_ENV not in os.environ
    w.close()
    assert w.key.text() == ""


@pytest.mark.parametrize("code", [0, 1])
def test_jitens_fetched_cards_never_outlive_a_window_closed_during_the_fetch(main, runs, code):
    """AD2-8: the window closed while the child fetched — its folder (the user's whole Jiten vocabulary) is removed
    when the child ends, whatever its end."""
    j = importers.open_jiten(main)
    j.key.setText(SECRET)
    j.go.click()
    cards = runs.calls[-1].argv[-1]
    j.close()
    os.makedirs(os.path.dirname(cards), exist_ok=True)       # the child writes its cards after the close
    _fetched(runs, [{"wordText": "猫", "state": 5}]) if code == 0 else runs.end(1, "Error: Invalid API key.")
    assert not os.path.exists(os.path.dirname(cards))


def test_jitens_fetched_cards_go_with_a_window_destroyed_without_a_close(main, runs):
    """The app quitting with the question open destroys the window with its main window (no closeEvent): the cards
    (the user's whole Jiten vocabulary) go with it, never left in the temp folder."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    j = importers.open_jiten(main)
    j.key.setText(SECRET)
    j.go.click()
    folder = os.path.dirname(runs.calls[-1].argv[-1])
    _fetched(runs, [{"wordText": "猫", "state": 5}])
    assert wait_until(lambda: _card(j) is not None) and os.path.exists(folder)
    j.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QApplication.processEvents()
    assert not os.path.exists(folder)


def test_a_failed_fetch_removes_its_folder(main, runs):
    j = importers.open_jiten(main)
    j.key.setText(SECRET)
    j.go.click()
    folder = os.path.dirname(runs.calls[-1].argv[-1])
    runs.end(1, "Error: Invalid API key.")
    assert not os.path.exists(folder)


def test_every_writing_child_is_waited_for_at_quit_and_the_fetch_is_not(main, runs, tmp_path):
    """AD2-9: quitting cut a child wherever it was — Extract between its copy and the store's insert, a replace after
    its backup. The writers now finish (the window waits, as for an Anki write); Jiten's fetch only reads: cancelled."""
    _known(CURRENT)
    importers.open_deck(main).start(DECK, "Sentence", "ja")
    importers.open_migaku(main).start(MIGAKU, "ja")
    j = importers.open_jiten(main)
    j.key.setText(SECRET)
    j.fetch()
    fetch = runs.calls[-1]
    j._folder = os.path.dirname(fetch.argv[-1])
    j.replace(fetch.argv[-1])
    e = importers.open_extract(main)
    e.path.setText(_text(tmp_path))
    e.start("旅")
    assert [c.on_quit for c in runs.calls] == ["wait", "wait", "cancel", "wait", "wait"]
    for call in runs.calls:                                   # every child ends: nothing left in the temp folder
        call.on_end(1)
    QApplication.processEvents()
    assert not os.path.exists(j._folder or os.path.dirname(fetch.argv[-1]))


def test_an_import_that_wrote_tells_the_known_words_count_and_one_that_failed_does_not(main, runs, monkeypatch):
    """IK-54: after a replace the bar's known-words count went stale until the next sync."""
    told = []
    monkeypatch.setattr(main.services, "automation", SimpleNamespace(known_changed=lambda: told.append(1)))
    _known(CURRENT)
    m = importers.open_migaku(main)
    m.start(MIGAKU, "ja")
    runs.end(1, "Error: the database could not be read.")
    assert told == []
    m.start(MIGAKU, "ja")
    runs.end(0, "Conversion complete!")
    d = importers.open_deck(main)
    d.start(DECK, "Sentence", "ja")
    runs.end(0, anki_db_import.result_line(anki_db_import.Merge(0, 0, 52, None, None, False)))   # nothing new
    d.start(DECK, "Sentence", "ja")
    runs.end(0, anki_db_import.result_line(anki_db_import.Merge(12, 3, 52, None, None, False)))
    j = importers.open_jiten(main)
    j.replace(os.path.join(str(get_user_files_path("ja")), "cards.json"))
    runs.end(0, "Conversion complete!")
    assert told == [1, 1, 1]


def test_an_import_waiting_its_turn_says_so_until_it_runs(main, tmp_path):
    """IK-58: a known-words import waits behind a sync (one known-words writer at a time); its line said "Working…"
    while it only waited. Now it says what runs first, then that it works once it runs (the real registry)."""
    registry = main.services.registry
    sync = registry.submit("anki-sync", "Updating known words from Anki", start=lambda job: None)
    w = importers.open_migaku(main)
    job = w.start(str(tmp_path / "無い.db"), "ja")
    assert wait_until(lambda: w.status.text() == strings.IMPORTERS_WAITING_FOR.format(
        what="Updating known words from Anki"))
    sync.finish(ok=True)
    assert wait_until(lambda: w.status.text() != strings.IMPORTERS_WAITING_FOR.format(
        what="Updating known words from Anki"))
    assert job.wait(60) and wait_until(lambda: not w.busy(), timeout=30)


def test_jiten_is_off_for_chinese_and_follows_the_main_windows_language(main, runs):
    w = importers.open_jiten(main)
    w.key.setText(SECRET)
    assert w.go.isEnabled()
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh")
    assert not w.go.isEnabled() and w.status.text() == strings.JITEN_JAPANESE_ONLY
    assert w.fetch() is None and runs.calls == []


def test_a_rejected_key_says_so(main, runs):
    w = importers.open_jiten(main)
    w.key.setText("bad")
    w.fetch()
    runs.end(1, "Fetching vocabulary from Jiten API...", "Error: Invalid API key. Please check your API key and try "
                                                         "again.")
    assert "Invalid API key" in w.status.text() and len(runs.calls) == 1


# --- Extract (inv §1) ------------------------------------------------------------------------------------------------ #
def _text(tmp_path, name="旅の記録.txt"):
    with open(os.path.join(RES, "ja", "context_test.txt"), encoding="utf-8") as f:
        body = f.read()
    path = tmp_path / name
    path.write_text(body * 4, encoding="utf-8")
    return str(path)


def test_extract_offers_the_files_name_and_its_split_options(main, runs, tmp_path):
    w = importers.open_extract(main)
    src = _text(tmp_path)
    w.path.setText(src)
    w.choose(src)
    assert w.name.text() == "旅の記録"
    assert w.split_box.isVisibleTo(w) and w.group_box.isVisibleTo(w) and not w.deck_box.isVisibleTo(w)
    assert w.by_length.isChecked() and w.value.text() == str(settings_manager.load_settings().get("split_length",
                                                                                                    1500))
    w.by_pattern.setChecked(True)
    assert w.value.text() == extract.DEFAULT_DELIMITER
    w.by_length.setChecked(True)
    assert w.value.text().isdigit()
    assert not w.parts.isEnabled()
    w.group.setChecked(True)
    assert w.parts.isEnabled() and w.parts.value() == extract.DEFAULT_PARTS
    assert [w.section.itemText(i) for i in range(w.section.count())] == ["Current", "Soon", "Goal"]
    assert w.go.isEnabled()


def test_extract_checks_the_name_and_starts_the_child_with_the_section_chosen(main, runs, tmp_path):
    w = importers.open_extract(main)
    src = _text(tmp_path)
    w.path.setText(src)
    w.choose(src)
    w.section.setCurrentIndex(1)
    w.group.setChecked(True)
    w.parts.setValue(3)
    w.go.click()
    assert wait_until(lambda: runs.calls)
    [call] = runs.calls
    assert call.kind == "extract"
    assert call.argv == ["extract.py", "--language", "ja", f"--file={src}", "--name=旅の記録", "--section", "soon",
                         "--split", "length", f"--value={w.value.text()}", "--parts", "3"]
    runs.end(0, "Saving 4 parts", extract.result_line(extract.Result(0, 4, "旅の記録", "soon", True, None)))
    assert w.status.text() == strings.EXTRACT_DONE.format(parts=4, section="Soon", name="旅の記録")


def test_a_taken_name_starts_nothing_and_fills_in_the_free_one(main, runs, tmp_path):
    os.makedirs(os.path.join(get_data_path("ja"), "Processed", "旅の記録"))
    w = importers.open_extract(main)
    src = _text(tmp_path)
    w.path.setText(src)
    w.choose(src)
    w.go.click()
    assert wait_until(lambda: w.name.text() == "旅の記録 2")
    assert runs.calls == []
    assert w.status.text() == strings.EXTRACT_TAKEN.format(name="旅の記録", proposal="旅の記録 2")


def test_a_bad_length_or_name_starts_nothing(main, runs, tmp_path):
    w = importers.open_extract(main)
    src = _text(tmp_path)
    w.path.setText(src)
    w.choose(src)
    w.value.setText("0")
    w.go.click()
    assert w.status.text() == strings.EXTRACT_FAULTS["length"] and runs.calls == []
    w.value.setText("800")
    w.name.setText("..")
    w.go.click()
    assert wait_until(lambda: w.status.text() == strings.EXTRACT_BAD_NAME) and runs.calls == []


def test_a_deck_needs_its_field_and_the_tick_and_never_groups(main, runs):
    w = importers.open_extract(main)
    w.path.setText(DECK)
    w.choose(DECK)
    assert wait_until(lambda: w.deck is not None)
    assert w.deck_box.isVisibleTo(w) and not w.group_box.isVisibleTo(w) and not w.split_box.isVisibleTo(w)
    if not w.field.currentText():
        w.field.setCurrentIndex(0)
    assert not w.go.isEnabled()                               # the "I understand" gate (inv §1.4)
    w.understand.setChecked(True)
    assert w.go.isEnabled()
    w.go.click()
    assert wait_until(lambda: runs.calls)
    assert runs.calls[0].argv[-1] == f"--field={w.field.currentText()}" and "--parts" not in runs.calls[0].argv


@pytest.mark.parametrize("result, line", [
    (extract.Result(3, 4, "旅", "goal", False, "store"),
     strings.EXTRACT_PROCESSED_ONLY.format(parts=4, name="旅", section="Goal")),
    (extract.Result(1, 0, "旅", "now", False, "empty"), strings.EXTRACT_EMPTY),
])
def test_extracts_other_ends_are_said(main, runs, tmp_path, result, line):
    w = importers.open_extract(main)
    w.path.setText(_text(tmp_path))
    w.start("旅")
    runs.end(result.code, extract.result_line(result))
    assert w.status.text() == line


def test_extract_is_off_while_its_name_is_checked_and_runs_what_was_clicked(main, runs, tmp_path, monkeypatch):
    """AD2-6: a second click while the name is checked started a second child; an edit during the check ran the new
    file under the name checked for the old one. Now the button is off until the answer, and the answer runs the
    file, split, section and language of the click."""
    checks = []
    monkeypatch.setattr(importers.bridge, "run_in_worker",
                        lambda fn, *a, then=None, failed=None: checks.append((fn(*a), then)))
    w = importers.open_extract(main)
    src = _text(tmp_path)
    w.path.setText(src)
    w.choose(src)
    w.section.setCurrentIndex(1)
    w.go.click()
    assert not w.go.isEnabled() and w.busy()
    w.go.click()
    assert len(checks) == 1
    w.path.setText(_text(tmp_path, "別の本.txt"))
    w.section.setCurrentIndex(2)
    [(answer, then)] = checks
    then(answer)
    [call] = runs.calls
    assert f"--file={src}" in call.argv and call.argv[call.argv.index("--section") + 1] == "soon"


def test_extract_glues_every_value_to_its_option(main, runs, tmp_path):
    """AD2-7: a value starting with a dash (a --- chapter rule, a -draft name) reaches the child as a value."""
    w = importers.open_extract(main)
    src = _text(tmp_path)
    w.path.setText(src)
    w.choose(src)
    w.by_pattern.setChecked(True)
    w.value.setText("---")
    w.name.setText("-draft")
    w.start("-draft")
    argv = runs.calls[-1].argv
    assert "--value=---" in argv and "--name=-draft" in argv and f"--file={src}" in argv


def test_a_chinese_extract_runs_in_chinese_with_the_section_chosen(main, runs, tmp_path):
    """AD2-12: the windows ran on Japanese data only; a Chinese file through the Chinese window names zh to the child."""
    main.services.settings.set({"target_language": "zh"})
    w = importers.open_extract(main)
    assert wait_until(lambda: w.language == "zh")
    src = tmp_path / "夜市.txt"
    with open(os.path.join(RES, "zh", "chinese_text_1.txt"), encoding="utf-8") as f:
        src.write_text(f.read() * 3, encoding="utf-8")
    w.path.setText(str(src))
    w.choose(str(src))
    assert w.name.text() == "夜市"
    w.section.setCurrentIndex(2)
    w.go.click()
    assert wait_until(lambda: runs.calls)
    argv = runs.calls[0].argv
    assert argv[1:3] == ["--language", "zh"] and "--name=夜市" in argv and argv[argv.index("--section") + 1] == "goal"


def test_the_real_extract_child_adds_its_parts_to_the_library(main, tmp_path, monkeypatch):
    from tests.test_library_store_support import library, write_manifest
    monkeypatch.setenv(extract.NO_HELPER_ENV, "1")      # the child's detached helper would outlive this test's folders
    from app import library_store as ls
    data_dir, user_files_dir, doc = library("ja", shows=1, episodes=2, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    w = importers.open_extract(main)
    src = _text(tmp_path)
    w.path.setText(src)
    w.choose(src)
    w.section.setCurrentIndex(2)
    w.value.setText("400")
    w.go.click()
    assert wait_until(lambda: w.busy(), timeout=10)
    assert wait_until(lambda: not w.busy(), timeout=120)
    assert w.status.text().startswith("Extracted") and "Goal" in w.status.text(), w.status.text()
    store = ls.open_store("ja", data_dir, user_files_dir)
    try:
        assert any(e["physical_path"].startswith(f"{ls.CONTENT_FOLDER}/旅の記録/")      # SRC K3: every new copy in Library
                   for _i, e, _a in store.ordered("goal"))
    finally:
        store.close()


def test_a_disabled_primary_button_looks_disabled(main):
    """The capture showed Extract looking live with the "I understand" tick off: the primary rule outranked the plain
    `:disabled` one. A disabled primary now paints on the raised ground, not the iris."""
    w = importers.open_extract(main)
    w.resize(640, 320)
    QApplication.processEvents()

    def middle(b):
        img = b.grab().toImage()
        return img.pixelColor(img.width() // 2, 3).name()
    w.go.setEnabled(True)
    live = middle(w.go)
    w.go.setEnabled(False)
    assert middle(w.go) != live


def test_an_export_with_no_words_for_this_language_asks_nothing(main, runs, tmp_path):
    import sqlite3
    db = tmp_path / "migaku.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE WordList (dictForm, language, knownStatus)")
    c.execute("INSERT INTO WordList VALUES ('学习', 'zh', 'KNOWN')")
    c.commit()
    c.close()
    w = importers.open_migaku(main)
    w.read(str(db))
    assert wait_until(lambda: w.status.text() == strings.MIGAKU_EMPTY)
    assert _card(w) is None and runs.calls == []


def test_an_empty_jiten_account_asks_nothing_and_removes_the_fetched_cards(main, runs):
    w = importers.open_jiten(main)
    w.key.setText(SECRET)
    w.fetch()
    folder = os.path.dirname(runs.calls[-1].argv[-1])
    _fetched(runs, [])
    assert wait_until(lambda: w.status.text() == strings.JITEN_EMPTY)
    assert _card(w) is None and not os.path.exists(folder) and len(runs.calls) == 1


def test_a_deck_read_that_lands_after_another_choice_is_dropped(main, runs, tmp_path):
    w = importers.open_deck(main)
    w.choose(DECK)
    text = tmp_path / "本文.txt"
    text.write_text("吾輩は猫である。", encoding="utf-8")
    w.choose(str(text))                                         # chosen before the deck's read came back
    QTest.qWait(1500)
    assert w.deck is None and not w.go.isEnabled() and w.status.text() == strings.APKG_NOT_A_DECK


# --- the round-2 mutant pass's survivors ------------------------------------------------------------------------ #
def test_migakus_replace_runs_in_the_language_it_was_asked_in(main, runs):
    """`start` takes the language the question was read for, never the window's current one."""
    m = importers.open_migaku(main)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: m.language == "zh")
    m.start(MIGAKU, "ja", "2,3,0,0")
    assert runs.calls[-1].argv[2:4] == ["--language", "ja"]


# --- round 8 row 45: every press reacts at once ------------------------------------------------------------------- #
def test_choose_paints_its_arc_before_the_export_is_read_and_a_press_meanwhile_reads_nothing(main, runs,
                                                                                            monkeypatch):
    # The file picked, *Choose…* said nothing until the export's words were read (a worker): its arc now turns from
    # the pick, painted before the read is handed over, and goes when the question opens.
    from tests.qt.press_handover import HandOver, arc_turning
    _known(CURRENT)
    monkeypatch.setattr(importers, "_pick_file", lambda *a: MIGAKU)
    w = importers.open_migaku(main)
    assert QTest.qWaitForWindowExposed(w)
    handed = HandOver(monkeypatch, w.choose, lambda: arc_turning(w.choose))
    w.choose.click()
    read = handed.at("migaku_plan")
    assert read.shown and read.painted >= 1 and w.choose.isEnabled()      # never greyed
    w.choose.click()
    assert [h.name for h in handed].count("migaku_plan") == 1
    assert wait_until(lambda: _card(w) is not None) and not arc_turning(w.choose)


def test_a_second_choose_while_the_first_file_is_read_opens_no_dialog(main, runs, monkeypatch):
    # P5-A1: *Choose…* stays enabled while the file picked is read, so a second press opened the file dialog again —
    # its file was dropped, and the question that came was the FIRST file's. A press while one is live: no dialog.
    import threading
    from app import importers_view
    _known(CURRENT)
    gate, real = threading.Event(), importers_view.migaku_plan

    def held(path, language):
        gate.wait(5)
        return real(path, language)
    monkeypatch.setattr(importers_view, "migaku_plan", held)
    picks = []
    monkeypatch.setattr(importers, "_pick_file", lambda *a: picks.append(1) or MIGAKU)
    w = importers.open_migaku(main)
    assert QTest.qWaitForWindowExposed(w)
    w.choose.click()
    w.choose.click()                                      # the first file still being read
    assert len(picks) == 1
    gate.set()
    assert wait_until(lambda: _card(w) is not None)
