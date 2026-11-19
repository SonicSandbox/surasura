"""Kantan-B3: *Count as known in Anki* counts a card only when it is Suspended AND Marked, by default (Sonic's ruling,
2026-11-18).

Learners suspend a card for two reasons: "I know this", and "a bad sentence — I still want the word". The default was
*Suspended* alone, so every bad-sentence suspend marked its word known. Now the default is both states at once (as Sonic
works: one hotkey marks, one suspends), so a plain suspend means "bad sentence" and never counts.

Pinned here, end to end — settings.json → the terms → the search Surasura sends → the words marked known:
- a file without the key (a new install, anyone who never changed it) reads `["suspended", "marked"]`;
- a plain-suspended card is not known by default; suspended + marked is;
- a learner's own choice (Suspended only, Marked only, off) is kept exactly — never rewritten by a load or a save;
- Surasura's own suspensions (Junban's later / out, Connect's shelf) and Anki's leeches never count, marked or not;
- a learner on the old default keeps every word already counted (nothing is un-known): the next read only offers.

What a wrong answer would cost: every card suspended for a bad sentence marks a word the learner never learnt known —
his list and journey skip it. Real words, ja + zh; settings.json, KnownWord.json and the record in the test's temp root
(conftest's SURASURA_TEST_ROOT); a stand-in Anki that answers the search as Anki does, never a live one.
"""
import contextlib
import json
import os
import re

import pytest

from app import anki_connect, settings_manager
from app.connect import known_signal
from app.path_utils import get_settings_path, get_user_files_path

URL = "http://127.0.0.1:8765"
DECK = "Mining"
WORDS = {"ja": ("残念", "綺麗", "大丈夫", "泥棒", "諦める", "上層部"),
         "zh": ("遗憾", "漂亮", "没关系", "小偷", "放弃", "上层")}


def _tag_hit(tags, wanted):
    wanted = wanted.lower()
    return any(t.lower() == wanted or t.lower().startswith(wanted + "::") for t in tags)


class SearchingAnki:
    """Cards in memory; `find_cards` answers the search the way Anki does for the terms Surasura sends (a tag matches
    itself and its children, any case; `-` excludes; `tag:marked` is Anki's Mark)."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> {"word", "new", "suspended", "tags", "note"}
        monkeypatch.setattr(anki_connect, "find_cards", self.find)
        monkeypatch.setattr(anki_connect, "cards_info",
                            lambda url, ids: [{"cardId": c, "note": self.cards[c]["note"]} for c in ids])
        monkeypatch.setattr(anki_connect, "notes_info", lambda url, ids: [self._note(n) for n in ids])
        monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **kwargs: "DevTest")
        monkeypatch.setattr(anki_connect, "writer", lambda *a, **k: contextlib.nullcontext())

    def add(self, card, word, new=True, suspended=False, tags=()):
        self.cards[card] = {"word": word, "new": new, "suspended": suspended, "tags": list(tags), "note": card + 1000}

    def _note(self, note):
        card = next(c for c in self.cards.values() if c["note"] == note)
        return {"noteId": note, "modelName": "Lapis", "fields": {"Word": {"value": card["word"], "order": 0}}}

    def find(self, url, query):
        assert query.startswith(f'(deck:"{DECK}")'), query
        terms = re.findall(r'-?[a-z]+:[^\s]+', query.split(")", 1)[1])
        out = []
        for cid, card in sorted(self.cards.items()):
            ok = True
            for term in terms:
                neg, (key, value) = term.startswith("-"), term.lstrip("-").split(":", 1)
                if key == "is":
                    hit = card["suspended"] if value == "suspended" else card["new"] if value == "new" else False
                elif key == "tag":
                    hit = _tag_hit(card["tags"], value)
                else:
                    raise AssertionError(f"a term this stand-in doesn't know: {term}")
                ok = ok and (hit != neg)
            if ok:
                out.append(cid)
        return out


@pytest.fixture
def anki(monkeypatch):
    return SearchingAnki(monkeypatch)


def _write_settings(values):
    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False)


def _file():
    with open(get_settings_path(), encoding="utf-8") as f:
        return json.load(f)


def _known_forms(language):
    path = os.path.join(get_user_files_path(language), "KnownWord.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {w.get("dictForm") for w in json.load(f).get("words", []) if isinstance(w, dict)}


# --- the default --------------------------------------------------------------------------------------------------- #
def test_the_default_is_suspended_and_marked():
    # why: the one place the default lives; every reader's fallback is this value, never a second copy
    assert settings_manager.DEFAULT_SETTINGS["known_from_anki"] == ["suspended", "marked"]


@pytest.mark.parametrize("on_disk", [None, {"connect_enabled": True}], ids=["no-file", "file-without-the-key"])
def test_a_learner_who_never_changed_it_reads_suspended_and_marked(on_disk):
    # why: a new install has no settings.json; an older learner's file holds only the keys they changed
    if on_disk is not None:
        _write_settings(on_disk)
    loaded = settings_manager.load_settings()
    assert loaded["known_from_anki"] == ["suspended", "marked"]
    assert known_signal.signal(dict(loaded, connect_enabled=True)) == ["suspended", "marked"]
    # a settings dict without the key (a caller that never loaded the file) falls back to the same default
    assert known_signal.signal({"connect_enabled": True}) == ["suspended", "marked"]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_by_default_a_plain_suspend_is_never_known_and_suspended_and_marked_is(anki, language):
    # why: the ruling itself — a plain suspend means "bad sentence, I still want the word"
    bad_sentence, knows, marked_only, *_rest = WORDS[language]
    _write_settings({"connect_enabled": True})
    settings = settings_manager.load_settings()
    known_signal.read(language, URL, [DECK], [], settings)                      # the baseline: nothing signalled yet
    anki.add(1, bad_sentence, new=False, suspended=True)                         # suspended for its sentence
    anki.add(2, knows, new=False, suspended=True, tags=["marked"])               # marked + suspended: "I know this"
    anki.add(3, marked_only, new=False, suspended=False, tags=["marked"])        # marked, still studied
    got = known_signal.read(language, URL, [DECK], [], settings)
    assert got["marked"] == [knows]
    assert _known_forms(language) == {knows}


# --- a learner's own choice: kept exactly ----------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_learners_explicit_suspended_only_is_kept_and_still_counts_a_plain_suspend(anki, language):
    # why: a learner who chose Suspended alone keeps exactly that — the new default never rewrites a choice
    bad_sentence, *_rest = WORDS[language]
    _write_settings({"connect_enabled": True, "known_from_anki": ["suspended"], "known_from_anki_chosen": True})
    settings = settings_manager.load_settings()
    assert settings["known_from_anki"] == ["suspended"]
    known_signal.read(language, URL, [DECK], [], settings)
    anki.add(1, bad_sentence, new=True, suspended=True)
    assert known_signal.read(language, URL, [DECK], [], settings)["marked"] == [bad_sentence]


@pytest.mark.parametrize("chosen", [["suspended"], ["marked"], ["flag:3"], [], ["suspended", "marked"]])
def test_a_save_of_another_setting_never_writes_or_rewrites_the_choice(chosen):
    # why: "never rewritten" — the window's saves write only their own keys onto the file as it is: a chosen value
    # stays byte-for-byte, and a file without the key never gains it
    _write_settings({"connect_enabled": True, "known_from_anki": chosen, "known_from_anki_chosen": True})
    settings_manager.save_keys({"words_per_day": 7})
    assert _file()["known_from_anki"] == chosen and _file()["known_from_anki_chosen"] is True
    assert settings_manager.load_settings()["known_from_anki"] == chosen
    _write_settings({"connect_enabled": True})
    settings_manager.save_keys({"words_per_day": 7})
    assert "known_from_anki" not in _file()


@pytest.mark.parametrize("chosen", [["marked"], ["flag:3"], [], ["suspended", "flag:1"]])
def test_a_choice_saved_before_the_marker_existed_is_kept(chosen):
    # why: only the old default itself can be a copy of a default; any other value was a learner's pick (2.x, 3.0)
    _write_settings({"connect_enabled": True, "known_from_anki": chosen})
    assert settings_manager.load_settings()["known_from_anki"] == chosen


@pytest.mark.parametrize("marker", [None, False])
def test_the_old_default_saved_by_a_first_save_reads_as_the_new_default(marker):
    # why: the root cause found in review — a first save with no settings.json yet writes every default
    # (`save_keys` → `_read_file_as_is` → `load_settings`), so most 3.0 installs hold ["suspended"] though nobody
    # picked it; read as written, the new default would reach almost no one
    on_disk = {"connect_enabled": True, "known_from_anki": ["suspended"]}
    if marker is not None:
        on_disk["known_from_anki_chosen"] = marker
    _write_settings(on_disk)
    assert settings_manager.load_settings()["known_from_anki"] == ["suspended", "marked"]
    assert _file()["known_from_anki"] == ["suspended"]                         # read so, never rewritten


def test_a_first_save_with_no_file_writes_todays_default_and_no_pick():
    # why: the same first save today: what it writes reads back as the default, never as a learner's pick
    assert not os.path.exists(get_settings_path())
    settings_manager.save_keys({"words_per_day": 7})
    assert _file().get("known_from_anki_chosen") is False
    assert settings_manager.load_settings()["known_from_anki"] == ["suspended", "marked"]


@pytest.mark.parametrize("picks, written", [
    (["suspended"], ["suspended"]),                     # Suspended alone, picked from the default: kept from now on
    (["marked"], ["marked"]),
    ([], []),                                           # off
])
def test_a_pick_in_settings_writes_the_marker_so_suspended_alone_stays_chosen(picks, written):
    # why: without the marker a learner's Suspended alone would read as the old default and turn back into both
    from app.qt import settings_catalog as catalog
    from app.services.settings import freeze
    row = catalog.ROW["known_from_anki"]
    _write_settings({"connect_enabled": True})
    changes, _update = catalog.change(row, freeze(settings_manager.load_settings()), "ja", picks)
    assert changes == {"known_from_anki": written, "known_from_anki_chosen": True}
    settings_manager.save_keys(changes)
    assert settings_manager.load_settings()["known_from_anki"] == written
    # the shown states picked again: nothing written, the marker neither (S19)
    again = catalog.change(row, freeze(settings_manager.load_settings()), "ja", written)[0]
    assert again == {}


# --- Surasura's own suspensions: never ---------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("junban_tag", ["", "MyTag"])
def test_junbans_later_and_out_the_shelf_and_a_leech_never_count_even_marked(anki, language, junban_tag):
    # why: Junban's later suspends a whole backlog of new cards; a learner may have marked one of them too — with the
    # default (both states) only the learner's own suspend + mark says "I know this"
    later, out, shelf, leech, mine, _rest = WORDS[language]
    parent = junban_tag or "Surasura"
    settings = {"connect_enabled": True, "junban_tag": junban_tag}          # the default terms
    known_signal.read(language, URL, [DECK], [], settings)
    anki.add(1, later, new=True, suspended=True, tags=[f"{parent}::later", "marked"])
    anki.add(2, out, new=True, suspended=True, tags=[f"{parent.lower()}::out", "marked"])
    anki.add(3, shelf, new=False, suspended=True, tags=["surasura::shelf", "marked"])
    anki.add(4, leech, new=False, suspended=True, tags=["leech", "marked"])
    anki.add(5, mine, new=True, suspended=True, tags=["Marked"])                 # Anki's tag search ignores case
    got = known_signal.read(language, URL, [DECK], [], settings)
    assert got["marked"] == [mine]
    assert _known_forms(language) == {mine}


# --- a learner on the old default: nothing is un-known ------------------------------------------------------------ #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_on_the_old_default_words_already_counted_stay_known_and_the_next_read_only_offers(anki, language):
    # why: an existing learner's record was written with the old default's terms; the new default is "another
    # signal" — a first read again: an offer for cards already suspended + marked, never a flood of marks, and never
    # a word taken back out of KnownWord.json
    counted, bad_sentence, knows, *_rest = WORDS[language]
    old = {"connect_enabled": True, "known_from_anki": ["suspended"]}            # what the old default read as
    known_signal.read(language, URL, [DECK], [], old)
    anki.add(1, counted, new=False, suspended=True)
    assert known_signal.read(language, URL, [DECK], [], old)["marked"] == [counted]
    anki.add(2, bad_sentence, new=False, suspended=True)
    anki.add(3, knows, new=False, suspended=True, tags=["marked"])
    now = {"connect_enabled": True}                                              # the key never written: the default
    got = known_signal.read(language, URL, [DECK], [], now)
    assert got["marked"] == [] and got["offered"] == 1
    assert [c["word"] for c in known_signal.load(language)["offer"]["cards"]] == [knows]
    assert _known_forms(language) == {counted}                                   # still known
    anki.add(4, WORDS[language][3], new=False, suspended=True)                    # a plain suspend from now on
    assert known_signal.read(language, URL, [DECK], [], now)["marked"] == []


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_an_offer_still_asked_from_the_old_default_never_marks_a_plain_suspend(anki, language):
    # why: found in review — an upgrader's unanswered *Mark their words known?* was made under the old default's
    # search; answered after the change with nothing new, its plain-suspended cards must be checked again under the
    # new signal: only the ones also marked become known
    plain, both, *_rest = WORDS[language]
    old = {"connect_enabled": True, "known_from_anki": ["suspended"]}
    anki.add(1, plain, new=False, suspended=True)
    anki.add(2, both, new=False, suspended=True, tags=["marked"])
    assert known_signal.read(language, URL, [DECK], [], old)["offered"] == 2     # the first read: an offer
    now = {"connect_enabled": True}
    got = known_signal.read(language, URL, [DECK], [], now)                     # other terms, nothing new
    assert got["marked"] == [] and got["offered"] == 0
    assert known_signal.accept_offer(language, URL) == [both]
    assert _known_forms(language) == {both}


# --- where a learner sees it --------------------------------------------------------------------------------------- #
def test_the_rows_question_mark_line_says_the_default_in_twelve_words_or_fewer():
    # why: the change is invisible in Anki; the row's ? line is where a learner reads why a plain suspend stopped counting
    from app.qt import settings_strings as S
    help_line = S.ROWS["known_from_anki"][1]
    assert len(help_line.replace("+", " ").split()) <= 12, help_line
    assert "Marked" in help_line and "suspend" in help_line.lower()


def test_the_settings_row_shows_suspended_and_marked_picked_for_a_file_without_the_key():
    from app.qt import settings_catalog as catalog
    from app.services.settings import freeze
    row = catalog.ROW["known_from_anki"]
    _write_settings({"connect_enabled": True})
    settings = freeze(settings_manager.load_settings())
    assert list(catalog.value(row, settings, "ja")) == ["suspended", "marked"]
    assert catalog.help_line(row, settings, "ja") == "Counts only cards that are Suspended + Marked, all at once"


def test_setup_known_page_line_names_suspend_and_mark():
    # why: setup is where a new learner first meets Anki in Surasura: one short line (PROVISIONAL)
    from app.qt import wizard_strings as W
    assert len(W.KNOWN_FROM_ANKI_SIGNAL.split()) <= 12
    assert "suspend" in W.KNOWN_FROM_ANKI_SIGNAL.lower() and "mark" in W.KNOWN_FROM_ANKI_SIGNAL.lower()
