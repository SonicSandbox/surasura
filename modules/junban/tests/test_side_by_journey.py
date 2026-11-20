# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-D (Sonic's ruling 3, 2026-11-17): side by side weaves a card by its word's title on the journey — the title of
the file the word is first met in, in study order — not by the title it was mined from.

What a wrong answer would cost a learner: a book whose words were mined ahead from a show counted 0 cards, so it
stepped aside and never got a turn; a title moved up in Current leaving its words in another title's turns; every
remaining pair swapped (and rewritten in Anki) once an odd number of woven cards were studied; a text card from a book
(`… @ ¶8`) naming nothing.

Real words (Japanese and Chinese), real library stores built from `tests/Test Resources` names; never Anki.
"""
import pytest

from modules.junban import connect, pins, reposition, show_tags, source_names, spaced
from modules.junban.tests.connect_scene import scene, settings, without_connect
from modules.junban.tests.test_reposition import _patched, _results

LANGUAGES = ["ja", "zh"]
WORDS = {"ja": ["冒険", "散歩", "老婆", "眼鏡", "須藤", "図書館"],
         "zh": ["冒险", "散步", "老太太", "眼镜", "苏东", "图书馆"]}
SAID = {"ja": "{}の話をした。", "zh": "我们聊了{}。"}


# --- which title a card is (`pins.side_groups`) --------------------------------------------------------------------- #
def _show(language):
    """Title A: a book of two parts (items 10, 11); title B: a show (item 20); a 6+ Months title's item 40 (not taking
    turns); file 5's item can't be told (two items carry its path: None). Files 1–5 in study order."""
    w = WORDS[language]
    a_part = f"{w[0]}_01"
    side = ([[10, 11], [20]], {}, {10: {source_names.key(a_part)}, 20: {source_names.key(w[1] + " - 03")}})
    files = [10, 11, 20, 40, None]
    return side, files, a_part + " @ 00:01:00", w[1] + " - 03 @ 00:02:00"


def _cards(language, rows):
    """`rows`: (its journey file or None, the source it was mined from) -> card dicts and their notes."""
    w = WORDS[language]
    cards, notes = [], {}
    for n, (number, source) in enumerate(rows):
        card = {"card_id": 100 + n, "note": 900 + n, "word": w[n % len(w)]}
        if number is not None:
            card["file"] = number
        cards.append(card)
        notes[900 + n] = {"fields": {"MiscInfo": source}}
    return cards, notes


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_card_is_the_title_its_word_is_first_met_in_not_the_one_it_was_mined_from(language):
    """Mining ahead: words first met in the book (files 1, 2) but mined from the show are the book's; a word first met
    in the show but mined from the book is the show's; a word first met in a title not taking turns (file 4) is
    neither's, though it was mined from the book."""
    side, files, from_a, from_b = _show(language)
    cards, notes = _cards(language, [(1, from_b), (2, from_b), (3, from_a), (4, from_a)])
    assert pins.side_groups(language, cards, notes, side=side, files=files) == [[100, 101], [102]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_card_with_no_place_to_go_by_keeps_its_mined_source(language):
    """No journey place (off the list), the priority order's list (file 0), a file number past the library's, a file
    whose item can't be told — each falls back to where it was mined (the pins' matching); no numbers at all (`files`
    None: the last Generate's, with the order moved since) is the mined source for every card, as before."""
    side, files, from_a, from_b = _show(language)
    cards, notes = _cards(language, [(None, from_a), (0, from_b), (99, from_a), (5, from_b), (1, from_b)])
    assert pins.side_groups(language, cards, notes, side=side, files=files) == [[104, 100, 102], [101, 103]]
    assert pins.side_groups(language, cards, notes, side=side, files=None) == [[100, 102], [101, 103, 104]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_when_current_is_reordered_the_words_go_with_their_titles(language):
    """The show moved above the book: the turns' groups follow Current's order, each word still its title's."""
    side, files, from_a, from_b = _show(language)
    (a, b), notes_of, names = side[0], side[1], side[2]
    cards, notes = _cards(language, [(1, from_b), (3, from_a), (2, from_b)])
    assert pins.side_groups(language, cards, notes, side=([b, a], notes_of, names), files=files) == [[101], [100, 102]]


# --- the files' items (`show_tags.file_items`) ---------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_file_items_names_each_study_order_file_by_its_item_and_follows_a_move(language):
    """File n is the n-th item of the study order — the store's own id, so two titles of one name (YouTube's Processed)
    never lump together; read as `file_shows` reads it: a move is followed at once for a fast re-plan's numbers, and
    the last Generate's numbers give none until the next Generate."""
    from app import library_store as ls
    from tests.test_library_store_support import migrated, roots
    store = migrated(language, shows=2, episodes=2, loose=1, tiers=("now",))
    with store:
        ids = [i for (i,) in store.conn.execute("SELECT id FROM items WHERE tier = 'now' ORDER BY ord, id")]
        store.record_analysed(store.versions()["order_version"])
    assert show_tags.file_items(language) == ids
    store = ls.open_store(language, *roots(language))
    with store:
        store.move([ids[-1]], "now", before_id=ids[0])
    assert show_tags.file_items(language, current=True) == [ids[-1]] + ids[:-1]
    assert show_tags.file_items(language) is None, "the numbers are the last Generate's: the order has moved since"
    assert show_tags.file_shows(language) is None
    with ls.open_store(language, *roots(language)) as again:
        titled = dict(again.conn.execute("SELECT i.id, w.title FROM items i LEFT JOIN works w ON w.id = i.work_id"))
    assert show_tags.file_shows(language, current=True) == [titled[i] for i in [ids[-1]] + ids[:-1]], "one read"


def test_file_items_with_no_library_store_is_no_number_to_go_by(monkeypatch):
    """No store: [] (every card by its mined source, counted as before), never None (which leaves the count be)."""
    monkeypatch.setattr(pins, "_open_store", lambda language: None)
    assert show_tags.file_items("ja") == [] and show_tags.file_shows("ja") is None


# --- through a run, on a real store --------------------------------------------------------------------------------- #
SCORE = {1: 50, 0: 40, 2: 30, 3: 20}          # by word index: the list's best word is w1


def _number(language, item_id, current=False):
    """The study-order file number of an item, as Generate numbers the files (side by side on: the titles interleave)."""
    return show_tags.file_items(language, current=current).index(item_id) + 1


def _run_scene(tmp_path, language, place):
    """A real store (`tests/test_side_by_side._library`): NOW = show A (6 episodes), show B (3), a book (one text);
    Soon = show D (2), below the line. Five cards, every one mined ahead from D. `place(a, b, book)` -> {word index:
    the item its word is first met in}; the list (`Sequence`) numbers those items' files as the store's order does.
    -> (store, (a, b, book, d), fake, journey {word index: file number})."""
    from tests.test_side_by_side import _library
    store, a, b, book, d = _library(language)
    store.set_library_options(side_by_side=True)
    store.record_analysed(store.versions()["order_version"])          # (as a Generate leaves it)
    w = WORDS[language]
    d_rel = store.item(d[0])["rel_path"].replace("\\", "/")
    mined = d_rel.split("/")[-2] + " — " + d_rel.split("/")[-1].rsplit(".", 1)[0] + " @ 00:01:00"
    order = [1, 0, 2, 3, 4]                         # Anki's order now: A's best word first (its due is the lowest)
    fake = scene(tmp_path, without_connect([(w[k], SAID[language].format(w[k]), 1000 + k, [], 0) for k in order]))
    for card in fake.cards.values():
        fake.notes[card["note"]]["fields"]["MiscInfo"]["value"] = mined
    journey = {k: _number(language, item_id) for k, item_id in place(a, b, book).items()}
    # (over the scene's own list)
    _results(tmp_path, progressive=[(journey[k], w[k], w[k], SCORE[k], 5) for k in sorted(journey, key=journey.get)])
    return store, (a, b, book, d), fake, journey


def _rows(journey, language):
    """The fast re-plan's rows for `journey` ({word index: file number}), the progressive list's columns."""
    w = WORDS[language]
    return [{"Sequence": journey[k], "Word": w[k], "Orth": w[k], "Score": SCORE[k], "Occurrences (Global)": 5}
            for k in sorted(journey, key=lambda k: (journey[k], -SCORE[k]))]


def _mined_ahead(a, b, book):
    return {1: a[0], 3: a[1], 0: b[0], 2: book}


def _on(monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))


def _words(stats, language):
    w = WORDS[language]
    return [w.index(row.word) for row in stats["order"]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_book_whose_words_were_mined_from_a_show_takes_its_turn(tmp_path, monkeypatch, language):
    """The tester's library: every card mined ahead from D (below the line). Before, no card was any title's — nothing
    woven, every title counted 0, the book stepped aside. Now each card is its word's first title: A's w1 and w3, B's
    w0, the book's w2 — A and B take turns, then the book steps in for B; each title counted for the store, the book
    1 — so the window and Connect's top give it its turn too."""
    _on(monkeypatch)
    store, (a, b, book, _d), fake, _journey = _run_scene(tmp_path, language, _mined_ahead)
    assert store.side_by_side() == [a, b, [book]]
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="list_first", target_language=language))
    assert _words(stats, language)[:4] == [1, 0, 3, 2]
    assert [row.weave[0] for row in stats["order"][:4]] == [0, 1, 0, 2]
    assert stats["side_cards"] == [[a, 2], [b, 1], [[book], 1]]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reorder_of_current_takes_the_words_with_their_titles_in_the_fast_re_plan(tmp_path, monkeypatch, language):
    """B moved above A. The fast re-plan's job reads the order as it stands (its rows' numbers, the store's new order):
    B's w0 is B's, A's words A's — the groups follow Current. The 順 window's run, reading the last Generate's numbers
    while the move waits for the next Generate, goes by the mined source (nothing woven here) and counts nothing for the
    store, rather than reading stale files."""
    _on(monkeypatch)
    store, (a, b, book, _d), fake, _journey = _run_scene(tmp_path, language, _mined_ahead)
    store.move(b, "now", before_id=a[0])
    assert store.side_by_side() == [b, a, [book]]
    moved = {k: _number(language, item_id, current=True) for k, item_id in _mined_ahead(a, b, book).items()}
    with _patched(fake):
        report = reposition.run(settings(junban_unlisted="list_first", target_language=language), refresh=False,
                                job=spaced.Job(automatic=True, rows=_rows(moved, language)))
    assert report["ok"], report["problems"]
    of = {row.word: row.weave[0] for row in report["stats"]["order"] if row.weave is not None}
    w = WORDS[language]
    assert of == {w[0]: 0, w[1]: 1, w[3]: 1, w[2]: 2}
    assert report["stats"]["side_cards"] == [[b, 1], [a, 2], [[book], 1]]
    with _patched(fake):
        _writes, window = reposition.dry_run(settings(junban_unlisted="list_first", target_language=language))
    assert "woven" not in window, "the window: stale numbers, so the mined source (D's: no title's)"
    assert "side_cards" not in window, "and no count over the one the fast re-plan recorded at the move"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_re_plan_after_one_studied_card_rewrites_no_pair(tmp_path, monkeypatch, language):
    """The phase through a run: the job weaves A, B, A, the book; the learner studies A's first card; the next job
    starts with B (whose card Anki now holds first) and writes nothing — before, it began with A again and swapped
    every pair still to come."""
    _on(monkeypatch)
    store, _titles, fake, journey = _run_scene(tmp_path, language, _mined_ahead)
    rows = _rows(journey, language)
    with _patched(fake):
        first = reposition.run(settings(junban_unlisted="list_first", target_language=language), refresh=False,
                               job=spaced.Job(automatic=True, rows=rows))
    assert first["ok"], first["problems"]
    before = fake.queue_order()
    assert [WORDS[language].index(x) for x in before[:4]] == [1, 0, 3, 2]
    studied = fake.card_of(before[0])
    studied["type"], studied["queue"] = 2, 2
    with _patched(fake):
        again = reposition.run(settings(junban_unlisted="list_first", target_language=language), refresh=False,
                               job=spaced.Job(automatic=True, rows=rows))
    assert again["ok"], again["problems"]
    assert fake.queue_order() == before[1:]
    assert again["stats"]["to_write"] == 0
    store.close()


# --- a book's text cards (`source_names`) --------------------------------------------------------------------------- #
BOOK = {"ja": ("カラフル (文春文庫) - 森 絵都", "第1章"), "zh": ("红楼梦 (人民文学出版社) - 曹雪芹", "第一回")}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_text_cards_paragraph_source_names_its_book_part_and_never_a_video(language):
    """Anki Miner's text card: `<the part's name> @ ¶8`. Its key is apart from every video's (`¶/…`); the book's part
    carries it — named after its EPUB (`<title> epub_25`) or not, and in its folder form — so a pin, Take out and side
    by side's fallback find it; a subtitle of the same name never does; a part whose name is no title (`第1章`) only by
    its folder."""
    title, chapter = BOOK[language]
    card = source_names.card_key(f"{title}_25 @ ¶8")
    assert card == "¶/" + source_names.key(f"{title}_25")
    assert source_names.card_key(f"{title}_25 @ ¶ 12") == card
    assert card in pins.names_of(f"Sources/{title} epub/{title} epub_25.txt")
    assert card in pins.names_of(f"Sources/{title}/{title}_25.txt")
    assert card not in pins.names_of(f"Sources/{title}/{title}_25.srt"), "a video of that name: never"
    assert card not in pins.names_of(f"Sources/{title}/{title}_26.txt")
    short = source_names.card_key(f"{chapter} @ ¶3")
    assert short not in pins.names_of(f"Sources/{title}/{chapter}.txt")
    assert source_names.card_key(f"{title} — {chapter} @ ¶3") in pins.names_of(f"Sources/{title}/{chapter}.txt")
    # a time stays a video's; a paragraph mark with no number, or another word after ` @ `, names nothing
    assert source_names.card_key(f"{title}_25 @ 00:01:02") == source_names.key(f"{title}_25")
    for misc in (f"{title}_25 @ ¶", f"{title}_25 @ p.8", f"{title}_25 ¶8", f"{title}_25 @ 8"):
        assert source_names.card_key(misc) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_book_card_off_the_list_falls_back_to_its_book_by_its_paragraph_source(language):
    """Side by side's fallback (a card with no journey place): the book's text card goes to the book's group."""
    title, _chapter = BOOK[language]
    book_path = f"Sources/{title} epub/{title} epub_25.txt"
    side = ([[10], [20]], {}, {10: pins.names_of(book_path), 20: pins.names_of("番組/番組 - 03.srt")})
    cards = [{"card_id": 1, "note": 7, "word": WORDS[language][5]}]
    notes = {7: {"fields": {"MiscInfo": f"{title}_25 @ ¶8"}}}
    assert pins.side_groups(language, cards, notes, side=side, files=[20]) == [[1], []]


# --- the Haiku pass's gaps (KD-13…) ---------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_first_and_last_file_numbers_and_a_scene_with_no_titles_card(language):
    """File 1 and the last file are places (the last item real here: a wrong bound would take `files[-1]` for file
    0); file 0 and one past the last are not (the mined source); no card in any title is no weave (None)."""
    side, _files, from_a, from_b = _show(language)
    files = [20, 11, 10]
    cards, notes = _cards(language, [(1, from_a), (3, from_b), (0, from_b), (4, from_a)])
    assert pins.side_groups(language, cards, notes, side=side, files=files) == [[101, 103], [100, 102]]
    stray, stray_notes = _cards(language, [(None, "番組 - 09 @ 00:00:09")])
    assert pins.side_groups(language, stray, stray_notes, side=side, files=files) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_card_off_the_list_never_anchors_the_turns(language):
    """B's held card (a list card waiting for its word, *i+1 first*) holds Anki's first place, but it is no list pick
    yet: the phase goes by A's list word (the lowest due among the list picks), so A leads."""
    from modules.junban import plan as P
    w = WORDS[language]
    rank = {w[0]: 0, w[1]: 1, w[2]: 2}
    cards = [{"card_id": 1, "due": 120, "type": 0, "queue": 0, "word": w[0], "note": 1, "tier": "list", "sort": (1,)},
             {"card_id": 2, "due": 130, "type": 0, "queue": 0, "word": w[1], "note": 2, "tier": "list", "sort": (5,)},
             {"card_id": 3, "due": 140, "type": 0, "queue": 0, "word": w[2], "note": 3, "tier": "list", "sort": (6,)},
             {"card_id": 4, "due": 100, "type": 0, "queue": 0, "word": w[5], "note": 4, "tier": "multi",
              "sort": (5, 100), "held": True, "waits": ((w[3],), 3)}]
    _writes, stats = P.plan(cards, rank, weave=[[1], [2, 3, 4]], width=2)
    assert [row.weave[0] for row in stats["order"] if row.weave is not None][:3] == [0, 1, 1]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undos_row_walked_from_soon_into_now_takes_the_undos_version(language):
    """Part A the other way: the line raised while B sat in 6+ Months — B's rows recorded in Soon come back in NOW
    (crossed: the Undo's version); its row recorded in NOW stays in NOW (its own version)."""
    from tests.test_side_by_side import _library
    store, a, b, _loose, _d = _library(language, first=2, second=3)
    store.set_soon_line(len(a) + 1)
    assert store.ids("now")[:len(a) + 1] == a + b[:1]
    values = {i: store.conn.execute("SELECT tier, changed_in FROM items WHERE id = ?", (i,)).fetchone() for i in b}
    assert [values[i][0] for i in b] == ["now"] + ["soon"] * (len(b) - 1)
    moved = store.place(b, "goal")
    store.set_soon_line(len(a) + len(b) + 1)
    undone = store.undo(moved)
    now = {i: store.conn.execute("SELECT tier, changed_in FROM items WHERE id = ?", (i,)).fetchone() for i in b}
    assert [now[i][0] for i in b] == ["now"] * len(b)
    assert now[b[0]][1] == values[b[0]][1]
    assert [now[i][1] for i in b[1:]] == [undone.version] * (len(b) - 1)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_card_of_a_book_not_in_the_library_is_away_never_the_one_books(language):
    """The 順 footer's offer (`backlog_shows.look`): a text card's `¶/…` key has no folder `¶` — a card of another
    book is away, even in a library of one book; the book's own card is the book's."""
    from modules.junban import backlog_shows as bs
    title, _chapter = BOOK[language]
    path = f"Sources/{title} epub/{title} epub_25.txt"
    items = [bs.Item(1, "now", 10, title, frozenset(pins.names_of(path)), True)]
    got = bs.look({1: f"{title}_25 @ ¶8", 2: f"{WORDS[language][2]}{WORDS[language][3]}_03 @ ¶2"}, items)
    states = sorted((s.cards, s.state) for s in got["shows"])
    assert states == [(1, "away"), (1, "in")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_two_items_both_end_with_names_no_item(language, monkeypatch):
    """Mutant D41 (2026-11-18): a study-order file whose path ends with two items' paths (a copy beside its original,
    one folder deeper) can't be told: no item — so its cards keep their mined source — while a file one item names is
    that item's. Its show is still named when both items are of one title (`file_shows`, as before)."""
    import contextlib
    from app import analyzer
    w = WORDS[language]
    rows = [(f"Sources/{w[0]}/{w[0]}_01.srt", w[0], 1), (f"Sources/old/Sources/{w[0]}/{w[0]}_01.srt", w[0], 2),
            (f"Sources/{w[1]}/{w[1]}_01.srt", w[1], 3)]

    class Store:
        conn = type("C", (), {"execute": lambda self, *a: type("R", (), {"fetchall": lambda s: rows})()})()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def _reading(self):
            return contextlib.nullcontext()

        def _versions(self):
            return {"order_version": 1, "analysed_order_version": 1, "test": language}
    monkeypatch.setattr(pins, "_open_store", lambda lang: Store())
    found = [(f"D:/data/Sources/old/Sources/{w[0]}/{w[0]}_01.srt",), (f"D:/data/Sources/{w[1]}/{w[1]}_01.srt",)]
    monkeypatch.setattr(analyzer, "resolve_found_files", lambda *a, **k: found)
    show_tags._MEMO.clear()
    assert show_tags.file_items(language) == [None, 3]
    assert show_tags.file_shows(language) == [w[0], w[1]]
    show_tags._MEMO.clear()
