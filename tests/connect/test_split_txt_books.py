"""A book 2.x split into `.txt` parts is a book for its audiobook — Kura-TX, B1–B3 (Mattias's 3.0.2 field report: "All
my books are also pre-chopped text-files … it only gets the audio (asks for it) if I have added them as epubs. But
this is from the migration!"). Lean (PROVISIONAL, the lead 2026-11-12): a folder's `<name>_<NN>.txt` parts are one
book, keyed by its parts' bytes; ONE joined `.txt` of them in order — the app's own file, in Connect's folder — stands
wherever an EPUB's path stood: the book's question, *Pick its audiobook…*, the line-up (Anki Miner's `sync` takes a
`.txt`), *Add the narrator's voice*. The book's own question names the title: it is the check against a learner's own
numbered notes, and dismissing it leaves them as they were.

What a wrong answer would cost: Mattias's migrated books mined as hundreds of text-only cards that never get the
narrator's voice (a word Connect made is never made again); a learner's numbered notes treated as one book by a rule
too wide; worst, a learner's own files moved, renamed or rewritten — the join is the app's own file, never theirs.

Real data: 芥川龍之介「蜘蛛の糸」 (public domain) split as 2.x saved it (`Test Resources/ja/books/split_2x/`, two parts
`蜘蛛の糸_01.txt`, `_02.txt`), read by a real look into a real store from a learner's library folder; its audiobook a
real folder of tagged MP3s under an English album name (Hon's look leaves it alone); Anki Miner the suite's fake.
"""
import hashlib
import json
import os

import pytest

from app import audiobooks, library_store as ls
from app.connect import library, lineup, runner
from app.connect.ledger import Ledger
from tests.connect.test_lineup import LINE_UP_311, _record_miner, _until, no_child_left  # noqa: F401
from tests.test_audiobook_items import _audio_folder, _audio_items, _record
from tests.test_sources_scan import _drive, _empty, _look, _write

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
SPLIT = os.path.join(RESOURCES, "ja", "books", "split_2x")
TITLE = "蜘蛛の糸"


def _part_text(n):
    with open(os.path.join(SPLIT, f"{TITLE}_{n:02d}.txt"), encoding="utf-8") as f:
        return f.read()


def _tree(top):
    """Every file under `top`: (path, its bytes' sha256, size, mtime_ns) — the learner's folder as it stands."""
    out = []
    for folder, _dirs, files in os.walk(top):
        for name in sorted(files):
            p = os.path.join(folder, name)
            st = os.stat(p)
            with open(p, "rb") as f:
                out.append((p, hashlib.sha256(f.read()).hexdigest(), st.st_size, st.st_mtime_ns))
    return sorted(out)


def _parts_of(store):
    """The library's text items, in id order: [(id, rel_path)]."""
    return store.conn.execute("SELECT id, rel_path FROM items WHERE source_type != 'audio' ORDER BY id").fetchall()


@pytest.fixture
def split(tmp_path, fake_miner, monkeypatch):
    """A learner's library folder holding a 2.x split book (`HighPriority/蜘蛛の糸/蜘蛛の糸_NN.txt`, as Mattias's data
    folder held his) and, in another folder, its audiobook under an English album name — read by a real look; Connect's
    Steps over that store, Anki Miner the fake (3.11: `sync`), plugged in, the speech model there."""
    store, data_dir = _empty("ja")
    src = _drive("driveB")
    folder = os.path.join(src, "HighPriority", TITLE)
    paths = [_write(os.path.join(folder, f"{TITLE}_{n:02d}.txt"), _part_text(n)) for n in (1, 2)]
    files = _audio_folder(os.path.join(src, "Audio", "The Spider's Thread"), "The Spider's Thread",
                          audiobooks.MIN_SECONDS + 600)
    with store:
        for top in ("HighPriority", "Audio"):          # 2.x's tier folder read as a library folder (K8), as his was
            _look(store, "ja", store.add_source(os.path.join(src, top)))
        assert {t for (t,) in store.conn.execute("SELECT title FROM works")} >= {TITLE}
        parts = [i for i, _rel in _parts_of(store)]
        [item] = _audio_items(store)
        rec = _record(store, item["id"])
    assert len(parts) == 2 and rec["book"] is None and rec["ask"] is None, "two parts; the audiobook left alone"
    _record_miner()
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    steps = runner.Steps({"connect_anki_miner_path": fake_miner.path})
    monkeypatch.setattr(steps, "_miner_profile", lambda lang, job: (fake_miner.path, "p-surasura"))
    monkeypatch.setattr(steps, "on_battery", lambda: False)
    return {"steps": steps, "src": src, "paths": paths, "parts": parts, "audio": item["id"], "files": files,
            "data_dir": data_dir}


def _job(item_id, jid=1):
    return {"id": jid, "item_id": item_id, "language": "ja", "asked_at": None}


def _joined(split, n=0):
    """The book Connect reads a part as (`Steps.reading`'s second answer)."""
    got = split["steps"].reading("ja", _job(split["parts"][n]))
    assert got is not None
    return got


# --- B1: the parts are one book ----------------------------------------------------------------------------------- #

def test_a_2x_split_part_reads_as_its_own_text_and_as_one_joined_book_of_every_part_in_order(split):
    """Mattias's cause: a `.txt` part was `(part, None)` — no book — so `_line_up` returned at once: no question, no
    line-up. Now the part is still what Anki Miner reads (its words were picked from it), and its book is ONE joined
    `.txt` of the parts in order, in Connect's own folder — never in the learner's."""
    reading, book = _joined(split)
    assert os.path.basename(reading) == f"{TITLE}_01.txt", "the part itself is read, as before"
    assert book and book.lower().endswith(".txt") and os.path.isfile(book)
    from app.cli.verbs import _connect_folder
    assert ls.path_key(os.path.dirname(book)) == ls.path_key(os.path.join(_connect_folder(), "books"))
    with open(book, encoding="utf-8") as f:
        text = f.read()
    one, two = _part_text(1), _part_text(2)
    assert text.index(one.splitlines()[0]) < text.index(two.splitlines()[0]), "part 1 before part 2"
    assert all(line in text for line in (one + two).splitlines() if line.strip())
    assert _joined(split, 1)[1] == book, "every part names the same book"


def test_the_learners_files_are_never_moved_renamed_or_rewritten_and_the_library_copies_neither(split):
    """User data is sacred: the join reads the parts and writes only its own file — the learner's folder and the
    library's copies stay byte for byte, name for name, time for time."""
    before = (_tree(split["src"]), _tree(os.path.join(split["data_dir"], "Library")))
    _joined(split)
    _joined(split, 1)
    assert (_tree(split["src"]), _tree(os.path.join(split["data_dir"], "Library"))) == before


def test_the_books_question_names_the_title_and_is_keyed_by_its_parts_bytes(split, fake_miner):
    """B1 → Kura-AB2's question: the joined book with no audiobook asks once, by its first part — *Do you have
    「蜘蛛の糸」's audiobook?* — keyed by the parts' sha256s in order (a moved folder is the same book; a part changed is
    asked again). Nothing started."""
    _reading, book = _joined(split)
    got = split["steps"].line_up("ja", _job(split["parts"][1], 2), book)
    shas = []
    for n in (1, 2):
        with open(split["paths"][n - 1], "rb") as f:
            shas.append(hashlib.sha256(f.read()).hexdigest())
    assert got == {"book_ask": runner.BOOK_AUDIO_ASK.format(title=TITLE), "item_id": split["parts"][0],
                   "key": f"sha256:{hashlib.sha256(chr(10).join(shas).encode('ascii')).hexdigest()}",
                   "epub": os.path.abspath(book)}
    assert "sync" not in fake_miner.commands()


def test_parts_saved_in_shift_jis_or_with_a_bom_join_as_one_utf8_text(tmp_path):
    """A part an old Windows editor saved (Shift_JIS; UTF-8 with a BOM): each read as a Generate reads it
    (`path_utils.read_text`), the joined book one UTF-8 text with no BOM inside and no mojibake — what Anki Miner
    lines up is the words the learner reads."""
    store, data_dir = _empty("ja")
    src = _drive("old-windows")
    one, two = _part_text(1), _part_text(2)
    for name, data in ((f"{TITLE}_01.txt", one.encode("cp932", errors="ignore")),
                       (f"{TITLE}_02.txt", "\ufeff".encode("utf-8") + two.encode("utf-8"))):
        path = _write(os.path.join(src, TITLE, name), "")
        with open(path, "wb") as f:
            f.write(data)
        t = os.path.getmtime(path) - 60
        os.utime(path, (t, t))
    with store:
        _look(store, "ja", store.add_source(src))
        first = _parts_of(store)[0][0]
        book = library.split_book(store, first, "ja")
    with open(book, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    assert "\ufeff" not in text and "\ufffd" not in text
    assert one.splitlines()[0][:20] in text and two.splitlines()[0][:20] in text


def test_a_part_changed_in_the_library_joins_again_at_the_same_place_under_a_new_key(split):
    """The join is made again when a part's copy changes (its size or time): the same path — a pairing names it —,
    the new text, a new key (a new edition asks again, as an EPUB's does)."""
    _reading, book = _joined(split)
    key = _book_of(split, book)["sha256"]
    rel = _parts_of_rel(split)[1]
    copy = os.path.join(split["data_dir"], *rel.split("/"))
    with open(copy, "a", encoding="utf-8", newline="\n") as f:
        f.write("　御釈迦様は極楽の蓮池のふちに立って、この一部始終をじっと見ていらっしゃいましたが、\n")
    _reading, again = _joined(split, 1)
    assert again == book
    with open(book, encoding="utf-8") as f:
        assert "この一部始終をじっと見ていらっしゃいましたが" in f.read()
    assert _book_of(split, book)["sha256"] != key


def _book_of(split, book):
    with split["steps"]._open("ja") as store:
        return library.book_of(store, book)


def _parts_of_rel(split):
    with split["steps"]._open("ja") as store:
        return [rel for _i, rel in _parts_of(store)]


def _library_of(names, texts=None):
    """A fresh library of one folder of loose `.txt` files (`names`, each a real Japanese text) -> (store — open: the
    caller closes it —, {name: id})."""
    store, _data_dir = _empty("ja")
    src = _drive("notes")
    for k, name in enumerate(names):
        _write(os.path.join(src, "ノート", name), (texts or {}).get(name) or _part_text(1 + k % 2) + f"\n{name}\n")
    _look(store, "ja", store.add_source(src))
    ids = {os.path.basename(rel): i for i, rel in _parts_of(store)}
    return store, ids


def test_what_is_not_a_split_book_stays_a_text_one_part_two_names_or_a_plain_name():
    """The rule is narrow on purpose: two or more `<name>_<NN>.txt` of ONE name in one folder. One such part alone,
    parts of two names, or a plain name is a text as before — its job reads it alone, no book, no question."""
    store, ids = _library_of(["日記_01.txt", "手紙_02.txt", "読書メモ.txt"])
    with store:
        assert [store.split_book(i) for i in ids.values()] == [None, None, None]


def test_a_split_books_parts_go_by_their_numbers_never_by_their_names_letters_a_chapters_label_too():
    """2.x numbered past 99 (Mattias's CHAOS;CHILD_100.txt): `_09` < `_10` < `_100`, and a chapter's part
    (`<name>_NN (3) <label>.txt`, `extract.part_name`'s form) is a part of the same book."""
    names = ["蜘蛛の糸_100.txt", "蜘蛛の糸_10.txt", "蜘蛛の糸_09 (1) 地獄.txt"]
    store, ids = _library_of(names)
    with store:
        got = store.split_book(ids["蜘蛛の糸_10.txt"])
        assert got["parts"] == [ids["蜘蛛の糸_09 (1) 地獄.txt"], ids["蜘蛛の糸_10.txt"], ids["蜘蛛の糸_100.txt"]]
        assert got == store.split_book(ids["蜘蛛の糸_100.txt"]), "every part names the same book"
        assert os.path.basename(got["path"]).startswith(ls.JOINED_PREFIX)


def test_an_epubs_own_parts_are_its_book_never_a_split_book(tmp_path):
    """A 3.0 EPUB's parts are named `<base>_NN.txt` too: they are the EPUB's book (its `<epub>#<n>` origins), never
    joined — the EPUB is the book, as before."""
    from tests.test_audiobook_items import _epub
    store, _data_dir = _empty("ja")
    src = _drive("books")
    _epub(os.path.join(src, f"{TITLE}.epub"), TITLE, "ja")
    with store:
        _look(store, "ja", store.add_source(src))
        parts = [i for i, _rel in _parts_of(store)]
        assert parts and [store.split_book(i) for i in parts] == [None] * len(parts)


def test_dismissing_the_books_question_mines_it_as_the_text_it_was_and_leaves_every_file_as_it_was(split, tmp_path):
    """The lead's check (PROVISIONAL): a learner's numbered notes would ask *Do you have 「…」's audiobook?* once —
    naming the title, so it is plain which files it means. *Dismiss* lets them go for good, mined as they were (each
    part its own text), and nothing of theirs was touched."""
    before = (_tree(split["src"]), _tree(os.path.join(split["data_dir"], "Library")))
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = ledger.queue("ja", split["parts"][0], "mine", None, "store-1")
        book = _joined(split)
        with pytest.raises(runner.Wait) as w:
            runner._line_up(split["steps"], ledger, "ja", ledger.job_by_id(jid), book)
        assert w.value.reason == runner.BOOK_AUDIO_ASK.format(title=TITLE)
        [need] = [n for n in ledger.needs("ja", listed=False) if n["kind"] == runner.BOOK_AUDIO_NEED]
        assert ledger.dismiss(need["id"])
        assert runner._line_up(split["steps"], ledger, "ja", ledger.job_by_id(jid), book) is None
        later = ledger.queue("ja", split["parts"][1], "mine", None, "store-1")
        assert runner._line_up(split["steps"], ledger, "ja", ledger.job_by_id(later), _joined(split, 1)) is None, \
            "the other part never asks again"
    assert (_tree(split["src"]), _tree(os.path.join(split["data_dir"], "Library"))) == before


# --- B2: *Pick its audiobook…* -------------------------------------------------------------------------------------- #

def _pick(split):
    """*Pick its audiobook…* as the window does it: the book's list (`Store.book_audiobooks`, by the part the question
    is asked by), then the pick (`Store.pick_audiobook_book`)."""
    _reading, book = _joined(split)
    with split["steps"]._open("ja") as store:
        offered = store.book_audiobooks(split["parts"][0])
        change = store.pick_audiobook_book(split["audio"], offered["epub"])
    return book, offered, change


def test_pick_its_audiobook_lists_the_lone_audiobook_for_the_joined_book_and_pairs_them(split):
    """B2: the question's *Pick its audiobook…* lists the library's lone audiobook for the split book (named by its
    title), and the pick pairs them: the audiobook joins the book's title, after its last part, and Connect finds the
    pair by the joined book (`audiobook_of_book`) — the key its line-up is kept by."""
    book, offered, change = _pick(split)
    assert offered["epub"] == os.path.abspath(book) and offered["title"] == TITLE
    assert [a["item_id"] for a in offered["audiobooks"]] == [split["audio"]]
    assert change is not None
    with split["steps"]._open("ja") as store:
        ab = library.audiobook_of_book(store, book)
        works = {store.item(i)["work_id"] if "work_id" in store.item(i) else
                 store.conn.execute("SELECT work_id FROM items WHERE id = ?", (i,)).fetchone()[0]
                 for i in split["parts"] + [split["audio"]]}
        assert ab is not None and ab["item_id"] == split["audio"] and ab["key"] and ab["title"] == TITLE
        assert len(works) == 1, "the audiobook is in the book's title"
        assert library.paired_books(store) == [(os.path.abspath(book), split["audio"],
                                                library.book_of(store, book)["sha256"])]
        assert store.pick_audiobook_book(split["audio"], book) is None, "paired already: nothing written"


def test_the_pair_survives_the_next_look_and_undo_takes_it_back_whole(split):
    """A look after the pick weighs only lone audiobooks: the pair stays. Undo of the pick: the audiobook alone again,
    in its own title, as it was."""
    book, _offered, change = _pick(split)
    with split["steps"]._open("ja") as store:
        for top in ("HighPriority", "Audio"):
            root = store.conn.execute("SELECT id FROM roots WHERE path = ?",
                                      (os.path.join(split["src"], top),)).fetchone()
            _look(store, "ja", root[0] if root else store.add_source(os.path.join(split["src"], top)))
        assert library.audiobook_of_book(store, book)["item_id"] == split["audio"]
        store.undo(change)
        assert library.audiobook_of_book(store, book) is None
        assert _record(store, split["audio"])["book"] is None


def test_a_joined_book_no_part_of_this_library_names_is_never_paired(split, tmp_path):
    """The pick reads the joined book's sidecar, never trusts it: a `.txt` that isn't this library's split book (a
    stray file named like one, a sidecar naming items that aren't such parts) pairs nothing."""
    _reading, book = _joined(split)
    stray = os.path.join(os.path.dirname(book), os.path.basename(book).replace(".txt", "0.txt"))
    with open(book, encoding="utf-8") as f, open(stray, "w", encoding="utf-8") as g:
        g.write(f.read())
    with open(os.path.splitext(book)[0] + ".json", encoding="utf-8") as f, \
            open(os.path.splitext(stray)[0] + ".json", "w", encoding="utf-8") as g:
        g.write(f.read())
    with split["steps"]._open("ja") as store:
        assert store.joined_book(stray) is None and store.pick_audiobook_book(split["audio"], stray) is None
        assert _record(store, split["audio"])["book"] is None


# --- B3: the line-up, as is ----------------------------------------------------------------------------------------- #

def _sentences(text):
    return [s + "。" for s in text.replace("\n", "").replace("　", "").split("。") if s.strip()]


def _synced(split, fake_miner):
    """The book paired (`_pick`) and its line-up asked as a part's job asks it, Anki Miner's sync answering each
    audio file's SRT of the book's sentences: file 1 part 1's first six, file 2 the rest of part 1 and part 2's first
    four, file 3 the rest of part 2 but its last (never heard); the look after it ends reads it lined up -> (book, its
    pair key, the parts' sentences, the audio files' names)."""
    from tests.connect.test_lineup import _srt_of
    book, _offered, _change = _pick(split)
    one, two = _sentences(_part_text(1)), _sentences(_part_text(2))
    names = [os.path.basename(f) for f in split["files"]]
    plan = {names[0]: one[:6], names[1]: one[6:] + two[:4], names[2]: two[4:-1]}
    fake_miner.plan(speech={"installed": ["small"], "model": "small"}, sync={
        "files": {n: {"status": "synced", "srt": _srt_of(lines)} for n, lines in plan.items()},
        "report": {"grade": "A", "sentence_pct": 95, "audio_pct": 92, "unheard": []}})
    with pytest.raises(runner.Wait) as w:
        split["steps"].line_up("ja", _job(split["parts"][1], 2), book)
    assert runner.lining_up(w.value.reason)
    with split["steps"]._open("ja") as store:
        key = library.audiobook_of_book(store, book)["key"]
    _until(lambda: not lineup.running(key))
    assert split["steps"].line_up("ja", _job(split["parts"][1], 2), book)["lineup"], "the next look: lined up"
    return book, key, (one, two), names


def test_once_paired_the_joined_book_is_lined_up_by_anki_miners_sync_and_its_words_cut_from_their_cues(split, fake_miner):
    """B3: the part's line-up starts Anki Miner's `sync` on the joined `.txt` (it takes one `.epub` or `.txt`) with the
    audiobook's files in order; once lined up, a word of part 2 is cut from the cue holding its sentence — in the
    audio file that reads it — and a sentence never heard goes as the book (no clip, never a neighbour's)."""
    book, key, (_one, two), names = _synced(split, fake_miner)
    steps = split["steps"]
    job = _job(split["parts"][1], 2)
    sent = json.load(open(os.path.join(lineup.folder(key), "sync.json"), encoding="utf-8"))["episodes"][0]
    assert sent["book"] == os.path.abspath(book) and sent["audio"] == [os.path.abspath(f) for f in split["files"]]
    assert fake_miner.commands().count("sync") == 1
    got = steps.line_up("ja", job, book)
    assert got["lineup"]["grade"] == "A" and got["item_id"] == split["audio"]
    heard = {"word": "x", "reading": "x", "surface": two[2][:2], "line_text": two[2]}
    unheard = {"word": "y", "reading": "y", "surface": two[-1][:2], "line_text": two[-1]}
    groups, rest = lineup.split([heard, unheard], got["lineup"])
    assert [os.path.basename(a) for a, _s in groups] == [names[1]] and rest == [unheard]
    assert steps.lined_up("ja", book)["item_id"] == split["audio"]
    assert steps.lineable("ja", book) is True and steps.first_part("ja", book) == split["parts"][0]


def test_stop_on_a_part_waiting_while_its_joined_book_lines_up_stops_that_sync(split, fake_miner):
    """AB-Q3's *Stop* on a part's row while its book lines up: the part names no EPUB, so its book is found as the
    split book it is a part of — that pair's sync is stopped (its cancel file), never left running for hours."""
    book, _offered, _change = _pick(split)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"}, sync={
        "files": {}, "report": {"grade": "A", "unheard": []}, "hold": 30.0})
    job = _job(split["parts"][1], 2)
    with pytest.raises(runner.Wait):
        split["steps"].line_up("ja", job, book)
    with split["steps"]._open("ja") as store:
        key = library.audiobook_of_book(store, book)["key"]
    assert lineup.running(key)
    split["steps"].stop_line_up("ja", job)
    assert lineup.read(key)["status"] == lineup.STOPPED
    assert os.path.isfile(os.path.join(lineup.folder(key), "run", lineup.RUN_ID, "cancel"))
    _until(lambda: not lineup.running(key))


def test_its_text_only_cards_get_add_the_narrators_voice_unchanged_the_offer_the_rows_entry_and_the_plan(
        split, fake_miner, tmp_path):
    """B4 (A1/A2 as they are): Mattias's cards made from a part before its audiobook was paired are offered the
    narrator's voice once the joined book lines up — the one *Needs you* line on the audiobook, the row's ⋯ entry on
    any part — and *Add audio*'s plan places each card's sentence in the line-up: heard → can, never heard → unheard."""
    from app.connect import actions, add_audio
    from tests.connect.test_add_audio import MAPPING
    from tests.connect.test_sentence_audio import FakeAnki
    book, _key, (_one, two), _names = _synced(split, fake_miner)
    anki = FakeAnki()
    anki.add(500, two[1], two[1][:2])
    anki.add(501, two[-1], two[-1][:2])
    with split["steps"]._open("ja") as store:
        library.record_batch(store, split["parts"][1], {"w0": [500], "w1": [501]}, "2026-11-01T00:00:00Z")
        sha = library.book_of(store, book)["sha256"]
        assert add_audio.book_items(store, book) == sorted(split["parts"])
    assert split["steps"].made_before("ja", book) == (TITLE, [500, 501], sha)
    ledger_path = str(tmp_path / "ledger.sqlite")
    with Ledger(ledger_path) as ledger:
        runner._add_audio_offers(split["steps"], ledger, "ja")
        [offer] = [n for n in ledger.needs("ja") if n["kind"] == runner.ADD_AUDIO_NEED]
        assert offer["item_id"] == split["audio"] and offer["say"] == runner.ADD_AUDIO_ASK.format(title=TITLE)
    assert actions.add_audio_offer("ja", split["parts"][:1], {"connect_enabled": True}, steps=split["steps"],
                                   path=ledger_path) == {"epub": os.path.abspath(book), "title": TITLE, "n": 2}
    got = add_audio.plan(anki, split["steps"], "ja", book, MAPPING)
    assert got["lined"] and sorted(got["can"]) == [500] and got["unheard"] == [501]
