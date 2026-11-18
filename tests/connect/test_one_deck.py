"""One deck (Michi-DK, a Send report, 2026-11-18): Connect's cards land in the deck Surasura shows for new cards — the
one 順 keeps in order — never only where Anki Miner's own settings say; and the cards it made before, in Anki Miner's
deck, are found and moved on the learner's press, with an Undo.

The tester's settings: Settings showed *New cards a day · from Anki (deck: Japanese::Mining Deck)* (順's deck), while
Anki Miner's own window had "Japanese::Anki Miner": every card Connect made went there, and 順 never ordered one.

What a wrong answer would cost a learner, in order:
  * cards in a deck nobody keeps in order (the report itself) — or a run aimed at a deck Anki lacks (Anki Miner refuses
    the whole run);
  * Anki Miner's own setting changed behind their back (the deck they mine into by hand): never written here;
  * a move that takes another language's cards, a card they mined by hand, or a card from a Custom Study session; a
    move with no snapshot or an Undo that drags back a card they moved again since;
  * Chinese mined into the Japanese deck (one `junban_deck` for both languages, AD-1).

Against the fake Anki Miner (`fake_anki_miner.py`) and a patched `urlopen` (a fake AnkiConnect), never a live Anki.
"""
import json
import os
import re
import urllib.error
from unittest import mock

import pytest

from app import anki_connect, locks
from app.cli import verbs
from app.connect import decks, fields, setup
from app.services import needs
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

JA_DECK = "Japanese::Mining Deck"           # the deck Surasura shows (順's), the tester's own
MINER_DECK = "Japanese::Anki Miner"         # Anki Miner's own (its window's)
ZH_DECK = "中文::挖词"
EXPORT_DECK = "DevTest"                     # the fake Anki Miner's settings export names this one

# A mapping as `fields.from_export` reads Anki Miner's Lapis profile
LAPIS = fields.Mapping(MINER_DECK, "Lapis", {"word": "Expression", "sentence": "Sentence", "source": "MiscInfo"},
                       "Expression", "Sentence", "MiscInfo", None)


def _ja(**more):
    return dict({"junban_scope": "deck", "junban_deck": JA_DECK, "junban_replan_deck": JA_DECK,
                 "junban_replan_language": "ja"}, **more)


# --- which deck a run mines into ------------------------------------------------------------------------------------ #
def test_a_run_mines_into_the_deck_surasura_shows_and_keeps_anki_miners_own_as_carded():
    # why: the report — Anki Miner's own deck won; now the run names 順's deck, Anki Miner's kept for the card check
    run = fields.for_run(LAPIS, _ja(), "ja", decks=[JA_DECK, MINER_DECK])
    assert run.deck == JA_DECK and run.own_deck == MINER_DECK
    assert fields.for_run(LAPIS, _ja(), "ja", decks=[JA_DECK.lower()]).deck == JA_DECK, "Anki ignores case"
    assert (run.note_type, run.fields, run.word) == (LAPIS.note_type, LAPIS.fields, LAPIS.word), "only the deck moves"


def test_the_same_deck_or_no_deck_shown_leaves_the_mapping_as_anki_miner_has_it():
    assert fields.for_run(LAPIS._replace(deck=JA_DECK), _ja(), "ja") == LAPIS._replace(deck=JA_DECK)
    assert fields.for_run(LAPIS, {"junban_deck": ""}, "ja") is LAPIS            # setup never picked one
    assert fields.for_run(LAPIS, _ja(junban_scope="all"), "ja") is LAPIS      # 順 orders every deck: none shown
    assert fields.surasura_deck(None, "ja") is None


def test_chinese_never_takes_the_deck_recorded_for_japanese():
    # why: one `junban_deck` for both languages (AD-1) — recorded for Japanese, it is no Chinese deck
    assert fields.surasura_deck(_ja(), "zh") is None
    assert fields.for_run(LAPIS._replace(deck="Anki Miner"), _ja(), "zh").deck == "Anki Miner"
    chinese = {"junban_deck": ZH_DECK, "junban_replan_deck": ZH_DECK, "junban_replan_language": "zh"}
    assert fields.for_run(LAPIS._replace(deck="Anki Miner"), chinese, "zh").deck == ZH_DECK


def test_a_deck_anki_lacks_keeps_anki_miners_own_and_anki_unread_keeps_surasuras():
    # why: Anki Miner refuses a whole run whose deck Anki lacks; unread, Anki Miner's own check says what's wrong
    assert fields.for_run(LAPIS, _ja(), "ja", decks=[MINER_DECK, "Default"]) is LAPIS
    assert fields.for_run(LAPIS, _ja(), "ja", decks=None).deck == JA_DECK


# --- the CLI: the run file Anki Miner reads ------------------------------------------------------------------------- #
@pytest.fixture
def library():
    """A Japanese library generated once by `surasura-cli generate`; its subtitle, and a stand-in video beside it."""
    folder = h.seed_library("ja")
    h.write_settings()
    code, lines = h.run_cli("generate")
    assert code == 0 and h.answer(lines)["ran"] is True, lines
    subtitle = os.path.join(folder, "phrases_sample.srt")
    video = os.path.join(folder, "phrases_sample.mkv")
    with open(video, "wb") as f:
        f.write(b"\x1aE\xdf\xa3")
    return subtitle, video


def test_the_run_file_names_surasuras_deck_and_anki_miners_settings_are_never_written(library, fake_miner):
    subtitle, video = library
    h.write_settings(connect_anki_miner_path=fake_miner.path, **_ja())
    code, lines = h.run_cli("pick", "--file", subtitle, "--video", video, "--job", "job-7")
    result = h.answer(lines)
    assert code == 0 and result["run_file"], result
    with open(result["run_file"], encoding="utf-8") as f:
        data = json.load(f)
    assert data["config"]["anki_deck_name"] == JA_DECK, "the deck 順 keeps in order, for this run alone"
    assert data["config"]["anki_note_type"] == "Lapis", "the note type is still Anki Miner's own"
    assert "settings-import" not in fake_miner.commands(), "Anki Miner's own deck is never changed"


def test_without_a_deck_shown_the_run_file_keeps_anki_miners_deck(library, fake_miner):
    subtitle, video = library
    h.write_settings(connect_anki_miner_path=fake_miner.path, junban_scope="all", junban_deck=JA_DECK)
    code, lines = h.run_cli("pick", "--file", subtitle, "--video", video, "--job", "job-8")
    result = h.answer(lines)
    assert code == 0 and result["run_file"], result
    with open(result["run_file"], encoding="utf-8") as f:
        assert json.load(f)["config"]["anki_deck_name"] == EXPORT_DECK


def test_setup_notes_anki_miners_own_deck_and_hands_both_decks_on(fake_miner, tmp_path):
    # why: the record is Settings' line (both decks named); the mapping carries Anki Miner's deck for the card check
    h.write_settings(connect_anki_miner_path=fake_miner.path, **_ja())
    setup.write_record({})                  # a record Connect's setup made (only one that exists is written)
    _info, _profile, mapping = verbs._anki_miner_setup(verbs.settings(), "ja", str(tmp_path / "run"))
    assert (mapping.deck, mapping.own_deck) == (JA_DECK, EXPORT_DECK)
    assert setup.miner_deck("ja") == EXPORT_DECK and setup.miner_deck("zh") is None


def test_the_pick_counts_the_words_carded_in_both_decks(library, fake_miner, monkeypatch):
    # why: a word the learner mined by hand into Anki Miner's deck has its card: Connect mines it again elsewhere
    # only if that deck is left out of the card check (Anki's duplicate check is per deck)
    from types import SimpleNamespace
    from app.connect import pick as picking
    subtitle, video = library
    h.write_settings(connect_anki_miner_path=fake_miner.path, **_ja())
    asked = []
    monkeypatch.setattr(picking, "carded", lambda lang, settings, decks=(): asked.append(list(decks)) or
                        (set(), "backlog"))
    ns = SimpleNamespace(lang="ja", file=subtitle, video=video, reading=None, words=None, job="job-9", wait=30,
                         made=(), listed=None, held=None, unsure=())
    out = verbs.pick(ns)
    assert out["run_file"] and asked == [[JA_DECK, EXPORT_DECK]]


def test_run_mapping_asks_anki_for_its_decks_once_and_briefly(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    mapping = LAPIS
    fake = FakeAnki({1: [1, MINER_DECK]})
    with mock.patch("urllib.request.urlopen", fake):
        assert verbs._run_mapping(_ja(), "ja", mapping) is mapping, "Anki lacks Surasura's deck: Anki Miner's"
        fake.decks.add(JA_DECK)
        assert verbs._run_mapping(_ja(), "ja", mapping).deck == JA_DECK
        fake.closed = True
        assert verbs._run_mapping(_ja(), "ja", mapping).deck == JA_DECK, "Anki unread: Surasura's"
    assert [a for a, _p, _h in fake.requests] == ["deckNames"] * 3, "one request a call, no probe"
    assert verbs._run_mapping(_ja(junban_scope="all"), "ja", mapping) is mapping


def test_the_record_is_written_only_when_anki_miners_deck_changed(monkeypatch):
    setup.write_record({})
    assert setup.note_miner_deck("ja", MINER_DECK) is True
    writes = []
    monkeypatch.setattr(setup, "write_record", lambda record: writes.append(record) or True)
    assert setup.note_miner_deck("ja", MINER_DECK) is False and writes == []
    assert setup.note_miner_deck("zh", "Anki Miner") is True
    assert writes[0]["miner_decks"] == {"ja": MINER_DECK, "zh": "Anki Miner"}


def test_no_record_yet_writes_none(monkeypatch):
    monkeypatch.setattr(setup, "read_record", lambda: {})
    assert setup.note_miner_deck("ja", MINER_DECK) is False


# --- a fake AnkiConnect --------------------------------------------------------------------------------------------- #
class FakeAnki:
    """A patched `urlopen` holding cards {card: [note, deck]}; `filtered` names Custom Study decks. Answers what the
    deck move asks — findCards (`nid:…`, `-deck:"X"` with its subdecks, `-deck:filtered`), getDecks, changeDeck,
    deckNames, guiReviewActive — and records each request with whether the Anki-write lock was held. A deck term reads
    as Anki reads it: `_` one character, `*` any run, `\\_` / `\\*` themselves, case ignored, its subdecks too.
    `fail_on`: (action, after how many of them succeed) -> the next one is refused, as an Anki that stopped answering."""

    def __init__(self, cards, filtered=(), reviewing=False, closed=False):
        self.cards = {int(c): list(v) for c, v in cards.items()}
        self.decks = {d for _n, d in self.cards.values()}
        self.filtered, self.reviewing, self.closed = set(filtered), reviewing, closed
        self.requests = []
        self.fail_on = None

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        action, params = payload["action"], payload.get("params") or {}
        self.requests.append((action, params, locks.held_here(anki_connect.WRITER_LOCK)))
        if self.closed:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        if self.fail_on and self.fail_on[0] == action:
            if self.fail_on[1] <= 0:
                raise urllib.error.URLError(TimeoutError("timed out"))
            self.fail_on = (action, self.fail_on[1] - 1)
        result = None
        if action == "requestPermission":
            result = {"permission": "granted", "version": 6}
        elif action == "deckNames":
            result = sorted(self.decks)
        elif action == "guiReviewActive":
            result = self.reviewing
        elif action == "findCards":
            result = self._find(params["query"])
        elif action == "getDecks":
            out = {}
            for c in params["cards"]:
                out.setdefault(self.cards[int(c)][1], []).append(int(c))
            result = out
        elif action == "changeDeck":
            self.decks.add(params["deck"])          # (AnkiConnect makes a deck it lacks)
            for c in params["cards"]:
                self.cards[int(c)][1] = params["deck"]
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"result": result, "error": None}, ensure_ascii=False).encode("utf-8")
        return response

    @staticmethod
    def _pattern(term):
        out, i = "", 0
        while i < len(term):
            ch = term[i]
            if ch == "\\" and i + 1 < len(term):
                out, i = out + re.escape(term[i + 1]), i + 2
                continue
            out += "." if ch == "_" else ".*" if ch == "*" else re.escape(ch)
            i += 1
        return re.compile(f"(?:{out})(?:::.*)?", re.I | re.S)

    def _find(self, query):
        notes = {int(n) for n in re.match(r"nid:([\d,]+)", query).group(1).split(",")}
        away = self._pattern(re.search(r'-deck:"((?:[^"\\]|\\.)*)"', query).group(1))
        return [c for c, (n, d) in self.cards.items() if n in notes and not away.fullmatch(d)
                and ("-deck:filtered" not in query or d not in self.filtered)]

    def moves(self):
        return [(p["deck"], sorted(p["cards"]), held) for a, p, held in self.requests if a == "changeDeck"]


# Connect's notes per language (the store's `made_words`: note -> its word), from the tester's kind of Japanese
JA_MADE = {101: "勉強", 102: "大丈夫", 103: "先輩", 104: "気がつく"}
ZH_MADE = {201: "学习"}
# Their cards: two in Anki Miner's deck, one already in 順's (a subdeck counts as in it), one in a Custom Study
# session; a Chinese one in Anki Miner's default deck; one the learner mined by hand in Anki Miner's deck (not ours)
CARDS = {1001: [101, MINER_DECK], 1002: [102, MINER_DECK], 1003: [103, JA_DECK + "::Bocchi"],
         1004: [104, "Filtered Deck 1"], 2001: [201, "Anki Miner"], 3001: [999, MINER_DECK]}


@pytest.fixture
def anki(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    fake = FakeAnki(CARDS, filtered={"Filtered Deck 1"})
    from app.connect import library
    monkeypatch.setattr(library, "made_notes_of", lambda lang: {"ja": JA_MADE, "zh": ZH_MADE}.get(lang, {}))
    monkeypatch.setattr(library, "made_fingerprint", lambda lang: [len(JA_MADE if lang == "ja" else ZH_MADE)])
    decks.forget()
    with mock.patch("urllib.request.urlopen", fake):
        yield fake
    decks.forget()


def test_strays_are_this_languages_connect_cards_outside_the_deck_and_never_custom_study(anki):
    got = decks.strays(_ja(), "ja")
    assert got == {"deck": JA_DECK, "from": {MINER_DECK: 2}, "cards": 2}
    assert all(a not in ("changeDeck",) for a, _p, _h in anki.requests), "reading only"


def test_strays_are_asked_of_anki_once_while_kept_and_again_after_a_move(anki):
    decks.strays(_ja(), "ja")
    asked = len(anki.requests)
    decks.strays(_ja(), "ja")
    assert len(anki.requests) == asked, "kept: Needs you's refreshes don't ask Anki each time"
    decks.forget()
    decks.strays(_ja(), "ja")
    assert len(anki.requests) > asked


def test_no_strays_without_a_deck_shown_nothing_made_or_anki_closed(anki, monkeypatch):
    assert decks.strays(_ja(junban_scope="all"), "ja") is None
    assert decks.strays(_ja(), "zh") is None, "the Japanese deck is no Chinese deck"
    anki.closed = True
    decks.forget()
    assert decks.strays(_ja(), "ja") is None
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    anki.closed = False
    assert decks.strays(_ja(), "ja") is None and decks.forget() is None


def test_chinese_strays_are_chinese_cards_only(anki):
    chinese = {"junban_deck": ZH_DECK, "junban_replan_deck": ZH_DECK, "junban_replan_language": "zh"}
    anki.cards[2002] = [201, ZH_DECK]
    assert decks.strays(chinese, "zh") == {"deck": ZH_DECK, "from": {"Anki Miner": 1}, "cards": 1}


# --- the move and its Undo ------------------------------------------------------------------------------------------ #
def test_the_move_snapshots_first_moves_under_the_lock_and_reads_back(anki):
    got = decks.move(_ja(), "ja")
    assert got["ok"] and got["moved"] == 2 and got["deck"] == JA_DECK and got["id"]
    assert got["say"] == decks.MOVED.format(n=2, deck=JA_DECK)
    assert anki.moves() == [(JA_DECK, [1001, 1002], True)], "one changeDeck, holding the one Anki writer"
    assert anki.cards[3001][1] == MINER_DECK, "a card mined by hand stays"
    assert anki.cards[1004][1] == "Filtered Deck 1" and anki.cards[2001][1] == "Anki Miner"
    with open(os.path.join(decks._folder(), f"{got['id']}.json"), encoding="utf-8") as f:
        snap = json.load(f)
    assert snap["deck"] == JA_DECK and snap["from"] == {MINER_DECK: [1001, 1002]} and snap["language"] == "ja"
    assert decks.strays(_ja(), "ja") is None, "asked again after the move: none left"


def test_undo_puts_each_card_back_where_it_came_from_but_never_one_moved_again_since(anki):
    anki.cards[1005] = [102, "日本語::旧"]           # a second card of a note, in another deck of the learner's
    got = decks.move(_ja(), "ja")
    assert got["moved"] == 3
    anki.cards[1002][1] = "日本語::後で"              # the learner moved one on since: theirs now
    back = decks.move_back(_ja(), got["id"])
    assert back == {"ok": True, "say": decks.UNDONE.format(n=2), "back": 2}
    assert (anki.cards[1001][1], anki.cards[1005][1], anki.cards[1002][1]) == (MINER_DECK, "日本語::旧", "日本語::後で")
    assert all(held for _d, _c, held in anki.moves())
    again = decks.move_back(_ja(), got["id"])
    assert again == {"ok": False, "say": decks.NOTHING_BACK, "back": 0}, "a second Undo moves nothing, and says so"


def test_no_move_while_reviewing_or_while_another_writer_holds_anki(anki):
    anki.reviewing = True
    got = decks.move(_ja(), "ja")
    assert not got["ok"] and got["say"] == anki_connect.REVIEWING and anki.moves() == []
    anki.reviewing = False
    with anki_connect.writer("順 reorder"):
        import threading
        out = []
        t = threading.Thread(target=lambda: out.append(decks.move(_ja(), "ja")))
        t.start()
        t.join(10)
    assert out and not out[0]["ok"] and anki.moves() == [], "refused, never waited into a write"
    assert not os.path.isdir(decks._folder()) or not os.listdir(decks._folder()), "no snapshot for a refused move"


def test_a_move_anki_stops_answering_in_still_offers_its_undo(anki):
    # why: Anki may have taken the change though its answer was lost — never "nothing was moved" with no Undo
    anki.fail_on = ("changeDeck", 0)
    got = decks.move(_ja(), "ja")
    assert not got["ok"] and got["id"] and got["moved"] is None
    assert got["say"].startswith("Anki stopped answering while the cards went to")
    anki.fail_on = None
    anki.cards[1001][1] = JA_DECK                   # (Anki had taken it for this one)
    assert decks.move_back(_ja(), got["id"])["back"] == 1 and anki.cards[1001][1] == MINER_DECK


def test_a_move_of_many_cards_goes_in_chunks_and_an_undo_stopped_part_way_says_what_went_back(anki, monkeypatch):
    monkeypatch.setattr(decks, "CHUNK", 1)
    anki.cards[1006] = [104, "日本語::旧"]
    got = decks.move(_ja(), "ja")
    assert got["moved"] == 3 and [len(c) for _d, c, _h in anki.moves()] == [1, 1, 1]
    anki.fail_on = ("changeDeck", 1)                # the first home deck goes back, then Anki stops
    back = decks.move_back(_ja(), got["id"])
    assert not back["ok"] and back["back"] == 1 and back["say"].startswith("Put 1 cards back, then Anki stopped")


def test_undo_never_makes_again_a_deck_deleted_since(anki):
    got = decks.move(_ja(), "ja")
    anki.decks.discard(MINER_DECK)
    anki.cards[3001][1] = "Default"                 # the hand-mined card went too: the deck is gone from Anki
    back = decks.move_back(_ja(), got["id"])
    assert back == {"ok": False, "say": decks.HOME_GONE.format(deck=JA_DECK), "back": 0}
    assert MINER_DECK not in anki.decks and anki.cards[1001][1] == JA_DECK


def test_the_press_moves_only_to_the_deck_its_button_named(anki):
    got = decks.move(_ja(), "ja", deck="日本語::前のデッキ")
    assert got == {"ok": False, "say": decks.DECK_CHANGED.format(deck=JA_DECK)} and anki.moves() == []
    assert decks.move(_ja(), "ja", deck=JA_DECK)["moved"] == 2


def test_a_deck_name_holding_anki_wildcards_is_read_as_written(anki):
    # why: `_` is one character in Anki's search — "Mining_Deck" would hide the cards in "Mining Deck"
    settings = _ja(junban_deck="Japanese::Mining_Deck", junban_replan_deck="Japanese::Mining_Deck")
    for c in (1001, 1002):
        anki.cards[c][1] = "Japanese::Mining Deck"
    assert decks.strays(settings, "ja")["from"] == {"Japanese::Mining Deck": 2, JA_DECK + "::Bocchi": 1}
    assert decks._term("a_b*c") == r'deck:"a\_b\*c"'


def test_a_strange_answer_from_anki_is_no_crash(anki, monkeypatch):
    monkeypatch.setattr(anki_connect, "invoke", lambda *a, **k: ["not", "a", "dict"])
    assert decks.strays(_ja(), "ja") is None
    got = decks.move(_ja(), "ja")
    assert got["ok"] is False and "say" in got


def test_nothing_left_to_move_and_an_undo_whose_record_is_gone(anki):
    for c in (1001, 1002):
        anki.cards[c][1] = JA_DECK
    got = decks.move(_ja(), "ja")
    assert got["ok"] and got["moved"] == 0 and got["id"] is None and anki.moves() == []
    assert decks.move_back(_ja(), "20261118-000000-1") == {"ok": False, "say": decks.UNDO_GONE}
    assert decks.move(_ja(junban_scope="all"), "ja") == {"ok": False, "say": decks.NO_DECK}


# --- Needs you's card ----------------------------------------------------------------------------------------------- #
RECORD = {"deck": JA_DECK, "from": {MINER_DECK: 12}, "cards": 12}


def test_the_card_names_both_decks_and_offers_the_move_by_the_decks_name():
    [e] = [e for e in needs.entries(None, strays=RECORD) if e.kind == needs.DECK_STRAYS]
    assert e.title == needs.STRINGS["strays_title"].format(n=12, where=f"“{MINER_DECK}”", deck=JA_DECK)
    assert e.actions == ("move_cards", "leave_cards") and e.unseen
    assert e.data["labels"]["move_cards"] == f"Move them to “{JA_DECK}”"
    one = needs._strays_entry({"deck": JA_DECK, "from": {MINER_DECK: 1, "x": 0}}, frozenset())
    assert one.title == needs.STRINGS["strays_title_one"].format(where=f"“{MINER_DECK}”", deck=JA_DECK)
    two = needs._strays_entry({"deck": JA_DECK, "from": {MINER_DECK: 3, "日本語": 2}}, frozenset())
    assert "2 other decks" in two.title and two.data["cards"] == 5


def _cards(record, answered):
    return [e for e in needs.entries(None, strays=record, answered=answered) if e.kind == needs.DECK_STRAYS]


def test_leave_them_answers_these_decks_only_and_an_empty_record_is_no_card():
    answered = frozenset([needs.strays_key(RECORD)])
    assert not _cards(RECORD, answered)
    assert _cards(dict(RECORD, **{"from": {"Anki Miner": 4}}), answered), "another deck asks again"
    assert _cards(dict(RECORD, **{"from": {MINER_DECK: 40}}), answered), "more cards there ask again"
    assert not _cards(dict(RECORD, **{"from": {MINER_DECK: 5}}), answered), "fewer (moved by hand) never do"
    assert needs._strays_entry({"deck": JA_DECK, "from": {}}, frozenset()) is None
    assert needs.answer_keys(needs._strays_entry(RECORD, frozenset())) == [needs.strays_key(RECORD)]


def test_the_gathers_read_never_raises(monkeypatch):
    monkeypatch.setattr(decks, "strays", lambda *_a: 1 / 0)
    assert needs.deck_strays("ja", _ja()) is None


# --- Settings' line ------------------------------------------------------------------------------------------------- #
def test_settings_names_both_decks_only_while_they_differ():
    pytest.importorskip("PyQt6")
    from app.qt import settings_connect, settings_strings as S
    setup.write_record({})
    assert settings_connect._decks_line(_ja(), "ja") == "", "no run read Anki Miner's deck yet"
    setup.note_miner_deck("ja", MINER_DECK)
    assert settings_connect._decks_line(_ja(), "ja") == S.MINER_DECKS.format(ours=JA_DECK, own=MINER_DECK)
    assert settings_connect._decks_line(_ja(junban_scope="all"), "ja") == ""
    setup.note_miner_deck("ja", JA_DECK)
    assert settings_connect._decks_line(_ja(), "ja") == ""
