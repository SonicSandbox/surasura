# SPDX-License-Identifier: GPL-3.0-or-later
"""Laptop round 8 #50 (LF4-3 = A, extended): each card Junban places with the list carries the show it's for.

Sonic (2026-10-22): "I'd add the show title it came from, and probably the show that it's targeted for in case the 2
are different right? One wouldn't change, the other would if it's shuffled." The `from` tag is Connect's, fixed at
mining. The `for` label (`Surasura::for::<show>`) follows the order: the show of the file the journey first meets the
card's word in. Only notes whose label changed are written ("update only what changed"): one `removeTags` and one
`addTags` per show whose notes changed, none in the steady state.

What a wrong answer costs: a label naming a show the card isn't for (a shuffle never followed), a write per card on
every re-order (Anki busy for nothing), labels stripped because the library couldn't be read for a moment, or a
positions-only move (every drag) writing to notes. Against the fake collection (real Japanese words; never Anki).
"""
import pytest

from modules.junban import auto, show_tags
from modules.junban.tests.connect_scene import CONNECT_TAG, SCENE, runs_on_disk, scene
from modules.junban.tests.connect_scene import settings as connect_settings
from modules.junban.tests.test_reposition import _patched

FOR = "Surasura::for::"
# 散歩 and 冒険 are met first in file 1, 老婆 in file 3 (the scene's journey; here a card Connect made, in the queue);
# 走る is yours (no label)
ON_THE_LIST = ([row for row in SCENE if row[0] in ("散歩", "冒険", "走る")]
               + [("老婆", "老婆が笑った。", 7000, [CONNECT_TAG], 0)])
SHOWS = ["Re:Zero kara Hajimeru Isekai Seikatsu", "Re:Zero kara Hajimeru Isekai Seikatsu", "Yomi no Tsugai"]


def _labels(fake, word):
    return [t for t in fake.notes[fake.card_of(word)["note"]].get("tags") or () if str(t).startswith(FOR)]


def _label_calls(fake):
    return [(action, sorted(notes), tag) for action, notes, tag in fake.tag_calls if str(tag).startswith(FOR)]


def _reorder(fake, monkeypatch, shows, actions=True):
    monkeypatch.setattr(show_tags, "file_shows",
                        lambda language, current=False: list(shows) if shows is not None else None)
    settings = connect_settings(junban_auto_reorder=True, junban_auto_actions=actions)
    fake.tag_calls.clear()
    before = len(fake.requests)
    with _patched(fake):
        done = auto.reorder(settings, list_current=True)
    assert done["outcome"] == "ran", done
    return len(fake.requests) - before


# --- the plan: pure ----------------------------------------------------------------------------------------------- #
def test_the_plan_writes_only_the_notes_whose_label_changes():
    cards = [{"note": 1, "file": 1}, {"note": 2, "file": 1}, {"note": 3, "file": 2}]
    notes = {1: {"tags": ["Surasura::for::ReZero"]}, 2: {"tags": ["auto-mined"]}, 3: {"tags": ["Surasura::for::ReZero"]}}
    planned = show_tags.plan(cards, ["ReZero", "Yomi no Tsugai"], notes)
    assert planned["add"] == {"Surasura::for::ReZero": [2], "Surasura::for::Yomi_no_Tsugai": [3]}
    assert planned["remove"] == {"Surasura::for::ReZero": [3]}, "note 1 already says ReZero: untouched"
    assert planned["counts"] == {"labelled": 3, "changed": 2}


def test_a_note_with_two_cards_takes_its_earliest_cards_show():
    cards = [{"note": 7, "file": 3}, {"note": 7, "file": None}, {"note": 7, "file": 2}]
    planned = show_tags.plan(cards, ["A", "Hibike Euphonium", "C"], {7: {"tags": []}})
    assert planned["add"] == {"Surasura::for::Hibike_Euphonium": [7]}


def test_a_card_no_longer_placed_with_the_list_loses_its_label_and_one_with_no_show_gets_none():
    cards = [{"note": 1, "file": None}, {"note": 2, "file": 2}, {"note": 3, "file": 9}]
    notes = {1: {"tags": ["surasura::FOR::ReZero"]}, 2: {"tags": ["Surasura::for::ReZero"]}, 3: {"tags": []}}
    planned = show_tags.plan(cards, ["ReZero", None], notes)
    assert planned["remove"] == {"surasura::FOR::ReZero": [1], "Surasura::for::ReZero": [2]}, \
        "unplaced (1), and a file whose item names no show (2): their old label comes off, in its own spelling"
    assert planned["add"] == {}, "a file number past the library's files names no show (3)"


def test_a_library_that_cannot_be_read_plans_nothing_and_strips_no_label():
    cards = [{"note": 1, "file": 1}]
    planned = show_tags.plan(cards, None, {1: {"tags": ["Surasura::for::ReZero"]}})
    assert not show_tags.has_work(planned)


def test_a_label_anki_keeps_composed_is_the_same_label_as_a_decomposed_title():
    # round 2 B5: Anki stores tags in NFC; a title read in NFD (a folder from a Mac) must never flap remove-then-add
    import unicodedata
    nfc = unicodedata.normalize("NFC", "ざつ旅")
    planned = show_tags.plan([{"note": 1, "file": 1}], [unicodedata.normalize("NFD", "ざつ旅")],
                             {1: {"tags": ["Surasura::for::" + nfc]}})
    assert not show_tags.has_work(planned)


def test_the_label_is_kept_whatever_its_case():
    planned = show_tags.plan([{"note": 1, "file": 1}], ["ReZero"], {1: {"tags": ["surasura::for::rezero"]}})
    assert not show_tags.has_work(planned), "Anki's tags ignore case: no remove-then-add of the same label"


# --- through a re-order --------------------------------------------------------------------------------------------- #
def test_a_reorder_labels_each_placed_card_once_then_writes_nothing_while_nothing_moved(tmp_path, monkeypatch):
    fake = scene(tmp_path, ON_THE_LIST)
    _reorder(fake, monkeypatch, SHOWS)
    assert _labels(fake, "散歩") == _labels(fake, "冒険") == ["Surasura::for::Re:Zero_kara_Hajimeru_Isekai_Seikatsu"]
    assert _labels(fake, "老婆") == ["Surasura::for::Yomi_no_Tsugai"]
    assert _labels(fake, "走る") == [], "yours: not placed by the journey, no show"
    assert [action for action, _n, _t in _label_calls(fake)] == ["addTags", "addTags"], "one request a show"

    requests = _reorder(fake, monkeypatch, SHOWS)
    assert _label_calls(fake) == [], "the steady state: no label request at all"
    assert requests > 0


def test_after_a_shuffle_only_the_cards_whose_show_changed_are_retagged(tmp_path, monkeypatch):
    fake = scene(tmp_path, ON_THE_LIST)
    _reorder(fake, monkeypatch, SHOWS)
    roba = list(fake.notes[fake.card_of("老婆")["note"]]["tags"])
    shuffled = ["Hibike! Euphonium 3", None, "Yomi no Tsugai"]     # file 1 is another show's episode now
    _reorder(fake, monkeypatch, shuffled)
    moved = sorted([fake.card_of("散歩")["note"], fake.card_of("冒険")["note"]])
    assert _label_calls(fake) == [
        ("removeTags", moved, "Surasura::for::Re:Zero_kara_Hajimeru_Isekai_Seikatsu"),
        ("addTags", moved, "Surasura::for::Hibike!_Euphonium_3")], "two requests: the old label off, the new on"
    assert fake.notes[fake.card_of("老婆")["note"]]["tags"] == roba, "老婆's show didn't change: untouched"


def test_labels_alone_are_written_without_a_new_snapshot(tmp_path, monkeypatch):
    """The early return (every card already in place): the labels go on, but no snapshot — one of nothing would
    replace the way back from the last run that moved cards."""
    fake = scene(tmp_path, ON_THE_LIST)
    _reorder(fake, monkeypatch, SHOWS)
    _reorder(fake, monkeypatch, SHOWS)
    snapshots = runs_on_disk()
    _reorder(fake, monkeypatch, ["Hibike! Euphonium 3", None, "Yomi no Tsugai"])
    assert _labels(fake, "散歩") == ["Surasura::for::Hibike!_Euphonium_3"]
    assert runs_on_disk() == snapshots


def test_a_positions_only_move_writes_no_label_and_reads_no_show(tmp_path, monkeypatch):
    fake = scene(tmp_path, ON_THE_LIST)
    monkeypatch.setattr(show_tags, "file_shows", lambda language: pytest.fail("a positions-only move reads no show"))
    with _patched(fake):
        done = auto.reorder(connect_settings(junban_auto_reorder=True, junban_auto_actions=False), list_current=True)
    assert done["outcome"] == "ran", done
    assert _label_calls(fake) == []


def test_a_library_read_failure_during_a_reorder_leaves_every_label(tmp_path, monkeypatch):
    fake = scene(tmp_path, ON_THE_LIST)
    _reorder(fake, monkeypatch, SHOWS)
    _reorder(fake, monkeypatch, None)
    assert _label_calls(fake) == []
    assert _labels(fake, "老婆") == ["Surasura::for::Yomi_no_Tsugai"]


# --- the shows, from the library store ------------------------------------------------------------------------------ #
def test_file_shows_names_each_study_order_file_by_its_works_title_and_follows_a_move():
    from app import library_store as ls
    from tests.test_library_store_support import migrated
    store = migrated("ja", shows=2, episodes=2, loose=1, tiers=("now",))
    with store:
        rows = store.conn.execute("SELECT i.id, i.rel_path, w.title FROM items i LEFT JOIN works w ON w.id = i.work_id "
                                  "WHERE i.tier = 'now' ORDER BY i.ord, i.id").fetchall()
    titled = [title for _id, _rel, title in rows]
    assert all(titled) and titled[0] == titled[1] != titled[2] == titled[3], rows     # two shows of two episodes
    assert show_tags.file_shows("ja", current=True) == titled, "file n is the n-th item of the study order, by its work"

    store = ls.open_store("ja", *_roots())
    with store:
        store.move([rows[-1][0]], "now", before_id=rows[0][0])       # the loose file goes first
    again = show_tags.file_shows("ja", current=True)
    assert again == [titled[-1]] + titled[:-1], "a move is followed at once (the memo is keyed on the store)"
    # round 2 B2: numbers read from the last Generate (the 順 window's run) are the old order's: no show at all until
    # the next Generate, never the show that moved into a file's place
    assert show_tags.file_shows("ja") is None


def test_file_shows_with_no_library_store_is_none_never_an_empty_list(monkeypatch):
    from modules.junban import pins
    monkeypatch.setattr(pins, "_open_store", lambda language: None)
    assert show_tags.file_shows("ja") is None


def _roots():
    from app.path_utils import get_data_path, get_user_files_path
    return get_data_path("ja"), get_user_files_path("ja")


# --- round 2: never in a review, never an unfinished run ------------------------------------------------------------ #
class _ReviewStarts:
    """A review that begins once the run is under way: `guiReviewActive` answers False `quiet` times, then True."""

    def __init__(self, fake, quiet):
        self.quiet, self._dispatch = quiet, fake._dispatch
        fake._dispatch = self

    def __call__(self, action, params):
        if action == "guiReviewActive":
            self.quiet -= 1
            return self.quiet < 0
        return self._dispatch(action, params)


def _review_checks(fake):
    return sum(1 for r in fake.requests if r["action"] == "guiReviewActive")


def test_labels_alone_wait_while_you_review(tmp_path, monkeypatch):
    """round 2 B3: the 'already in place' path sends only labels — never in the middle of a review."""
    fake = scene(tmp_path, ON_THE_LIST)
    _reorder(fake, monkeypatch, SHOWS)
    before = _review_checks(fake)
    _reorder(fake, monkeypatch, SHOWS)                  # the checks a run asks before it finds nothing to move
    _ReviewStarts(fake, _review_checks(fake) - before)  # …all quiet; the review begins right before the labels
    _reorder(fake, monkeypatch, ["Hibike! Euphonium 3", None, "Yomi no Tsugai"])
    assert _label_calls(fake) == [], "a review began: no label written"
    assert _labels(fake, "散歩") == ["Surasura::for::Re:Zero_kara_Hajimeru_Isekai_Seikatsu"]


def test_a_review_found_before_the_actions_writes_no_label(tmp_path, monkeypatch):
    """round 2 B3: the re-check just before the actions (`_still_new`) found a review: no touch-up, no label."""
    fake = scene(tmp_path, ON_THE_LIST + [row for row in SCENE if row[0] == "図書館"])
    from modules.junban import reposition
    real = reposition._still_new
    monkeypatch.setattr(reposition, "_still_new", lambda url, later, touchups=False: None)
    _reorder(fake, monkeypatch, SHOWS)
    assert _label_calls(fake) == []
    monkeypatch.setattr(reposition, "_still_new", real)


def test_a_label_anki_refused_is_a_warning_and_never_holds_up_the_next_reorder(tmp_path, monkeypatch):
    """round 2 B4: a label isn't in the snapshot; one that didn't go on must not leave the run unfinished (every later
    automatic re-order would be refused until a Restore)."""
    from modules.junban import ankiconnect
    fake = scene(tmp_path, ON_THE_LIST)
    real = ankiconnect.add_tags

    def refuse_labels(url, notes, tag, chunk=150):
        if str(tag).startswith(FOR):
            return [], [(n, "Anki refused") for n in notes]
        return real(url, notes, tag, chunk=chunk)
    monkeypatch.setattr(ankiconnect, "add_tags", refuse_labels)
    monkeypatch.setattr(show_tags, "file_shows", lambda language, current=False: list(SHOWS))
    settings = connect_settings(junban_auto_reorder=True, junban_auto_actions=True)
    with _patched(fake):
        done = auto.reorder(settings, list_current=True)
    assert done["outcome"] == "ran" and done["report"]["ok"], done
    assert any("show label" in w for w in done["report"]["warnings"]), done["report"]["warnings"]
    monkeypatch.setattr(ankiconnect, "add_tags", real)
    _reorder(fake, monkeypatch, SHOWS)
    assert _labels(fake, "老婆") == ["Surasura::for::Yomi_no_Tsugai"], "the next re-order runs and writes it"


# why: the warning counts cards, not failures; two show labels Anki refused on the same note are one card, so the line says 1.
def test_two_label_refusals_on_one_note_count_as_one_card_in_the_warning():
    """The warning counts the cards whose labels Anki kept old, so two refused labels on one note read as one."""
    from modules.junban import reposition
    failures = [(7000, "Anki refused"), (7000, "Anki refused")]
    lines = reposition._labels_warning(failures)
    assert len(lines) == 1, lines
    assert lines[0].startswith("1 card kept an old show label"), lines[0]
    # why: failures on different notes are different cards, so two notes read as 2 (a constant count would not).
    other = [(7000, "Anki refused"), (7001, "Anki refused")]
    lines = reposition._labels_warning(other)
    assert len(lines) == 1, lines
    assert lines[0].startswith("2 cards kept an old show label"), lines[0]
