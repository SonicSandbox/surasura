"""Connect mines books and texts through Anki Miner's `reading` (round 2's Z-9; Sonic 2026-10-28: "Can't mine text
right now so it's an incomplete experience. At the very least that must be implemented."), behind the feature name.

What a wrong answer would cost: these jobs write the learner's Anki unattended. A book's job sent to an Anki Miner that
can't read books is refused (or worse, its window opened); a word sent without its sentence makes a card from the
wrong line; a book whose file Anki Miner can't open, said as "open Anki Miner", sends the learner to the window Sonic
never wants to open; and without the feature any change at all moves a learner's video mining or their book rows.

Real text (the suite's `ja/context_test.txt`, `zh/chinese_text_1.txt`), a real EPUB built the way the book suite builds
one (`tests/test_book_chapters._novel`, Hon's records from `extract.book_split`), a real store for the runner's reads;
Anki Miner is the suite's fake (`fake_anki_miner.py`, extended with the request's own JSON), Anki is `FakeSteps`'.
"""
import json
import os

import pytest

from app import cues, extract, library_store
from app.connect import anki_miner, fields, inbox, library, pick, reading, runfile, runner, setup
from app.connect.ledger import Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_anki_miner import LAPIS_EXPORT
from tests.connect.test_p41_asked import StoreSteps, _library, _place_top, _mined, _jobs, _run
from tests.test_book_chapters import _epub, _lines, _novel

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
TEXT_JA = os.path.join(RESOURCES, "ja", "context_test.txt")
TEXT_ZH = os.path.join(RESOURCES, "zh", "chinese_text_1.txt")
WORDS = [("冒険", "ボウケン"), ("今夜", "コンヤ")]


def _record(features):
    """Connect's setup record naming the Anki Miner it last found (its `version` answer's features)."""
    assert setup.write_record({"anki_miner": {"app": "3.11.0", "schema": 1, "features": list(features)}})


# --------------------------------------------------------------------------- #
# The feature: one answer, everywhere
# --------------------------------------------------------------------------- #
def test_books_are_mined_only_with_an_anki_miner_that_names_reading_and_audio_still_waits():
    """`mines_now`: this Surasura knows Z-9 now, so books and texts open with the Anki Miner its setup record last found
    naming `reading` — never without a record, never with one that doesn't name it; audio (Z-16) stays shut."""
    assert anki_miner.mines("books") and not anki_miner.mines("audio")
    assert not anki_miner.mines_now("books"), "no record yet: no"
    _record(["word-from-line", "dry-run"])
    assert not anki_miner.mines_now("books")
    _record(["word-from-line", "reading", "audio-episodes"])
    assert anki_miner.mines_now("books") and not anki_miner.mines_now("audio")
    _record(["word-from-line"])                         # another Anki Miner found since: read again
    assert not anki_miner.mines_now("books")


def test_without_reading_the_rows_the_gaps_and_the_mine_press_are_as_before(tmp_path):
    """Byte-for-byte today's behaviour without the feature: a text's row still says *Waits for Anki Miner*
    (`view_rows._mines` False), no gap names it, *Mine* on it asks for nothing, and the runner never asks for a
    reading source — while with `reading` each of those opens, through the same one rule."""
    from app.qt.mine_actions import videos_of
    from app.services import view_rows
    ids, kinds = _library()
    text = [i for i in ids if kinds[i] == ".txt"][-1]
    ep = view_rows.Episode._make([None] * len(view_rows.Episode._fields))._replace(id=text, media_word="text",
                                                                                   text="books")
    row = type("Row", (), {"episodes": [ep], "media_word": "text"})()
    steps = StoreSteps(str(tmp_path))
    steps.reading = lambda lang, job: pytest.fail("no reading source is asked for without the feature")
    for features, opens in ((["word-from-line"], False), (["word-from-line", "reading"], True)):
        _record(features)
        steps.can = {"books"} if opens else frozenset()
        with c.store("ja") as s:
            assert inbox._waits_for_books(s, text) is (not opens)
        assert view_rows._mines("books") is opens
        assert videos_of(row, [text]) == (([text], None) if opens else ([], ep))
        if not opens:
            assert runner._reading_source(steps, "ja", {"item_id": text}) is None


# --------------------------------------------------------------------------- #
# The words: each by its sentence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path, lang", [(TEXT_JA, "ja"), (TEXT_ZH, "zh")])
def test_a_texts_sentences_are_its_cues_and_each_word_goes_with_its_own_sentence(path, lang):
    """`cues.reading`: every sentence the tokenizer reads is a cue (no times), its text as the file writes it with its
    line breaks and spaces out; a word's line is its sentence, never its neighbours (no expansion)."""
    read, tokens = cues.reading(path, lang)
    assert read.units and len(read) > 3 and all(c.start == c.end == 0 for c in read)
    assert all(c.text and "\n" not in c.text for c in read)
    with open(path, encoding="utf-8") as f:
        squeezed = "".join(f.read().split())
    assert all("".join(c.text.split()) in squeezed for c in read), "each sentence as the file writes it"
    assert {t.cue for t in tokens} <= set(range(len(read)))
    got = pick.pick(read, tokens, lang, lambda key: False, mode="unknown")
    assert got["words"]
    for w in got["words"]:
        assert w["line_expansion"] == [0, 0] and w["line_text"] in [c.text for c in read]
        assert w["surface"] in w["line_text"] or lang == "zh"


def test_an_empty_text_has_no_sentence_and_no_word(tmp_path):
    empty = tmp_path / "空.txt"
    empty.write_text("\r\n\r\n", encoding="utf-8")
    read, tokens = cues.reading(str(empty), "ja")
    assert list(read) == [] and tokens == [] and read.units


def test_a_reading_run_file_names_the_file_and_each_word_by_its_sentence(tmp_path):
    """`runfile`: a book's episode names `reading_file` (absolute), no video, subtitle or offset; each word its
    `line_text`, and `unit_index` only when the pick knows it — never a time or an expansion. A bad index is refused
    before a byte is written; a video's run file keeps exactly its keys."""
    words = [{"word": "冒険", "sent": ["冒険"], "line_text": "冒険だ。", "line_start": 0.0, "line_expansion": [0, 0]},
             {"word": "今夜", "sent": ["今夜"], "line_text": "今夜は冒険。", "line_start": 0.0, "line_expansion": [0, 0],
              "unit_index": 2}]
    sent = runfile.word_requests(words, ["reading"], book=True)
    assert sent == [{"word": "冒険", "line_text": "冒険だ。"}, {"word": "今夜", "line_text": "今夜は冒険。", "unit_index": 2}]
    episode = runfile.reading_episode("job-1-1", "book.epub", sent, tags="surasura::connect::job-1")
    assert set(episode) == {"run_id", "reading_file", "tags", "words"} and os.path.isabs(episode["reading_file"])
    path = runfile.write(str(tmp_path / "run.json"), runfile.build(str(tmp_path / "runs"), "ja", [episode]))
    assert json.load(open(path, encoding="utf-8"))["episodes"][0]["words"][1]["unit_index"] == 2
    for bad in (-1, True, 1.5, "2"):
        with pytest.raises(runfile.RunFileError):
            runfile.check(runfile.build(str(tmp_path), "ja", [dict(episode, words=[dict(sent[0], unit_index=bad)])]))
    # Z-2 works the same way on a book: the word as its sentence writes it and its reading go with every entry, the
    # second word's sentence still its own (a word's reading never read as "this is a book")
    named = [dict(words[0], word="為る", sent=["する"], surface="する", front_reading="する", predicted_class="IS-P9"),
             words[1]]
    sent = runfile.word_requests(named, ["reading", "word-from-line"], book=True)
    assert sent == [{"word": "する", "line_text": "冒険だ。", "reading": "する"},
                    {"word": "今夜", "line_text": "今夜は冒険。", "unit_index": 2}]
    video = runfile.episode("job-2-1", "a.mkv", "a.srt", runfile.word_requests(words, ["reading"]))
    assert set(video) == {"run_id", "video_file", "subtitle_file", "subtitle_offset", "tags", "words"}
    assert all(set(w) == {"word", "line_start", "line_expansion"} for w in video["words"])


# --------------------------------------------------------------------------- #
# Anki Miner's answer
# --------------------------------------------------------------------------- #
@pytest.fixture
def book_batch(tmp_path, fake_miner):
    """mine_batch on a book: the words of the suite's text, the Lapis mapping, the text as the reading file."""
    read, tokens = cues.reading(TEXT_JA, "ja")
    words = [w for w in pick.pick(read, tokens, "ja", lambda key: False, mode="unknown")["words"]
             if w["word"] in ("冒険", "今夜", "彼")]
    for w in words:
        w["sent"] = [w["word"]]

    def run(**kw):
        return anki_miner.mine_batch(fake_miner.path, "ja", "job-1", None, None, words, fields.from_export(LAPIS_EXPORT),
                                     "Surasura", str(tmp_path / "runs" / "job-1"), "http://127.0.0.1:9",
                                     reading=TEXT_JA, **kw)
    return run, words


def test_a_book_batch_sends_its_sentences_and_reads_back_each_cards_place(book_batch, fake_miner):
    """The fake built from the request's JSON reads the text's sentences; each row comes back with its `unit_index` and
    `location` and no time — every card made, none called another line for having no time."""
    run, words = book_batch
    fake_miner.plan(app="3.11.0", features=["word-from-line", "reading"])
    done = run()
    episode = fake_miner.run_files()[0]["episodes"][0]
    assert episode["reading_file"] == os.path.abspath(TEXT_JA) and "video_file" not in episode
    assert [w["line_text"] for w in episode["words"]] == [w["line_text"] for w in words]
    assert [o["outcome"] for o in done["outcomes"]] == ["made"] * len(words)
    assert all(o["location"] == "ch.0" and isinstance(o["unit_index"], int) for o in done["outcomes"])
    assert not any(o["other_line"] for o in done["outcomes"]) and all(o["returned_start"] is None
                                                                        for o in done["outcomes"])


def test_a_sentence_anki_miner_cant_find_is_not_found_never_a_card(book_batch, fake_miner):
    run, words = book_batch
    fake_miner.plan(app="3.11.0", features=["reading"], units=[{"index": 0, "location": "一", "text": "冒険だ。"}])
    done = run()
    assert {o["word"]: o["outcome"] for o in done["outcomes"]}["冒険"] == "made"
    assert {o["outcome"] for o in done["outcomes"] if o["word"] != "冒険"} == {"not_found"}


def test_a_book_anki_miner_cant_read_is_refused_before_anki_with_its_reason(book_batch, fake_miner):
    """SOURCE_UNREADABLE (new in Z-9): stopped before anything reached Anki — refused with its reason (`unreadable`),
    never uncertain, no result read."""
    run, _words = book_batch
    fake_miner.plan(app="3.11.0", features=["reading"], mine="source-unreadable")
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        run()
    assert (e.value.kind, e.value.code) == ("unreadable", "SOURCE_UNREADABLE") and "DRM" in e.value.message


def test_a_book_is_never_sent_to_an_anki_miner_that_cant_read_books(book_batch, fake_miner):
    run, _words = book_batch
    fake_miner.plan(app="3.10.1", features=["word-from-line"])
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        run()
    assert e.value.kind == "no-reading" and "mine" not in fake_miner.commands()


# --------------------------------------------------------------------------- #
# Placing a card on its part (Hon's chapter record)
# --------------------------------------------------------------------------- #
@pytest.fixture
def novel(tmp_path):
    epub = _novel(tmp_path)
    docs, _ = extract.epub_documents(epub)
    parts = extract.book_split(docs, 1500)
    return epub, docs, {100 + n: p.chapter for n, p in enumerate(parts)}, parts


def _first_unique(text, docs, n):
    """A line of `text` that occurs once in document n (the suite's prose repeats its lines)."""
    return next(ln for ln in text.splitlines() if ln and docs[n].text.count(ln) == 1)


def test_a_card_is_placed_on_the_part_holding_its_sentence(novel):
    """`location` `ch.<n>` names document n; with one part over it the part is known without reading the EPUB, and
    where a chapter's parts share a document the sentence's offsets choose — whitespace ignored, as Anki Miner joins
    a paragraph's lines."""
    epub, docs, records, parts = novel
    reads = []

    def documents():
        reads.append(1)
        return docs
    alone = next(i for i, r in records.items() if not any(_spans(o, r["docs"][0]) for o in records.values()
                                                         if o is not r))
    assert reading.place(f"ch.{records[alone]['docs'][0]}", "なんでも", records, documents) == alone
    assert reads == [], "one part over the document: the EPUB is never read"
    placed = 0
    for item, record in records.items():
        first, last = record["docs"]
        for n in (first, last):
            if sum(_spans(o, n) for o in records.values()) < 2:
                continue
            body = parts[item - 100].text
            line = next((ln for ln in body.splitlines() if ln and docs[n].text.count(ln) == 1
                         and _inside(docs[n].text.find(ln), record, n)), None)
            if line is None:
                continue
            assert reading.place(f"ch.{n}", line[:3] + "\n " + line[3:], records, documents) == item
            placed += 1
    assert placed >= 2, "the test placed sentences in parts that share a document"


def _spans(record, n):
    return record["docs"][0] <= n <= record["docs"][1]


def _inside(at, record, n):
    first, last = record["docs"]
    return at >= 0 and (n != first or at >= record["start"]) and (n != last or at < record["end"])


def test_a_toc_label_names_every_document_carrying_it_in_order(tmp_path):
    """A TOC that repeats a label across two files (Hon's proof: one book did): the sentence is looked for in each
    document with the label, the first holding it wins; an unknown label, no parts or a sentence in neither: None."""
    lines = _lines()
    docs_in = [{"href": "a.xhtml", "body": "".join(f"<p>{ln}</p>" for ln in lines[:5])},
               {"href": "b.xhtml", "body": "".join(f"<p>{ln}</p>" for ln in lines[5:])}]
    epub = _epub(tmp_path / "旅.epub", docs_in, [("a.xhtml", "第一章"), ("b.xhtml", "第一章")])
    docs, _ = extract.epub_documents(epub)
    assert [d.label for d in docs] == ["第一章", "第一章"]
    records = {1: {"docs": [0, 0], "start": 0, "end": len(docs[0].text)},
               2: {"docs": [1, 1], "start": 0, "end": 40}, 3: {"docs": [1, 1], "start": 40, "end": len(docs[1].text)}}
    read = reading.documents_of(epub)
    assert reading.place("第一章", lines[1], records, read) == 1
    late = next(ln for ln in lines[5:] if docs[1].text.find(ln) >= 40)
    assert reading.place("第一章", late, records, read) == 3
    assert reading.place("第一章", "どこにもない文。", records, read) is None
    assert reading.place("第九章", lines[1], records, read) is None
    assert reading.place("ch.0", lines[1], {}, read) is None and reading.place(None, lines[1], records, read) is None


def test_the_file_named_is_the_books_epub_when_its_there_else_the_items_own_text(tmp_path):
    """`reading.source`: the EPUB a part was cut from (cover, chapter labels) when it is on this computer; else the
    library's own text (a text, a PDF's, a book whose EPUB is away) — never nothing."""
    epub = _novel(tmp_path)
    part = str(tmp_path / "旅の記録_01.txt")
    origin = {"producer": "source", "origin": f"{epub}#1"}
    assert reading.source(part, origin) == (epub, epub)
    assert reading.source(part, {"producer": "source", "origin": f"{tmp_path / 'gone.epub'}#1"}) == (part, None)
    assert reading.source(part, {"producer": "source", "origin": str(tmp_path / "本.pdf")}) == (part, None)
    assert reading.source(part, None) == (part, None)
    assert reading.source(epub, None) == (epub, epub), "an item that is the EPUB itself"


def test_a_text_anki_miner_wouldnt_take_is_named_as_a_txt_of_its_text(tmp_path):
    """Review R1-2: Anki Miner reads `.epub` and `.txt` only (any other file is BAD_RUN_FILE): a library text kept as
    `.md` is named as a `.txt` of its text in the job's run folder; an `.epub` or a `.txt` as it is."""
    with open(TEXT_JA, encoding="utf-8") as f:
        body = f.read()
    md = tmp_path / "冒険のメモ.md"
    md.write_text(body, encoding="utf-8")
    named = reading.as_text(str(md), str(tmp_path / "runs" / "job-1"), "ja")
    assert named == str(tmp_path / "runs" / "job-1" / "冒険のメモ.txt")
    with open(named, encoding="utf-8") as f:
        assert "".join(f.read().split()) == "".join(body.split())
    assert reading.as_text(TEXT_JA, str(tmp_path), "ja") == TEXT_JA


# --------------------------------------------------------------------------- #
# The runner: a book in the top 20 is a mining job
# --------------------------------------------------------------------------- #
class BookSteps(StoreSteps):
    """StoreSteps with the runner's own reading-source rule over the real store (`Steps.reading`, `Steps.subtitle`):
    its pick records the file it was told to read."""
    reading = runner.Steps.reading
    subtitle = runner.Steps.subtitle
    can = frozenset({"books"})

    def pick(self, lang, job, video, reading=None):
        self.log.append(("reading", job["item_id"], video, reading))
        return super().pick(lang, job, video)


def _parts_in_store(tmp_path, lang="ja"):
    """Two parts of a real EPUB (its first chapter's first two) added with their origin records (`<epub>#<n>` + Hon's `chapter`), as Extract does."""
    epub = _novel(tmp_path)
    docs, _ = extract.epub_documents(epub)
    pieces = extract.book_split(docs, 1500)[1:3]         # the first chapter's first two parts: one document shared
    data = c.dirs(lang)[0]
    folder = os.path.join(data, library_store.CONTENT_FOLDER, "旅の記録")
    os.makedirs(folder, exist_ok=True)
    files, st = [], os.stat(epub)
    for n, p in enumerate(pieces, 1):
        files.append(os.path.join(folder, f"旅の記録_{n:02d}.txt"))
        with open(files[-1], "w", encoding="utf-8") as f:
            f.write(p.text)
    origins = {f: {"origin": f"{epub}#{n}", "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": "0" * 64,
                   "show": "旅の記録", "episode": n, "chapter": p.chapter}
               for n, (f, p) in enumerate(zip(files, pieces), 1)}
    with c.store(lang) as s:
        added = s.insert(files, "now", origins=origins).added
        with s._writing():
            s.conn.execute(f"UPDATE items SET source_type = 'epub' WHERE id IN ({','.join('?' * len(added))})",
                           added)
    return epub, added, {i: p.chapter for i, p in zip(added, pieces)}


def test_once_anki_miner_reads_books_a_book_in_the_line_is_mined_from_its_epub_with_no_timing_check(tmp_path):
    """A book's part entering the top 20 is a mining job, never *Waits for Anki Miner*: picked from its own text with
    the EPUB named as the file Anki Miner reads, no video looked for, no timing check, mined and recorded; a text with
    no EPUB names its own file. The store's read of the book's parts gives Hon's records."""
    _ids, _kinds = _library()
    epub, parts, records = _parts_in_store(tmp_path)
    text = [i for i in _ids if _kinds[i] == ".txt"][-1]
    steps = BookSteps(str(tmp_path), "ja", {"words": {str(parts[0]): WORDS, str(text): WORDS[1:]}})
    _place_top(text)
    _place_top(parts[0])
    _run(steps)
    assert ("reading", parts[0], None, epub) in steps.log
    assert ("reading", text, None, os.path.join(c.dirs("ja")[0], *_rel(text).split("/"))) in steps.log
    assert ("fit", parts[0]) not in steps.log and ("fit", text) not in steps.log
    assert _jobs(parts[0])[-1]["state"] == "done" and parts[0] in _mined(steps)
    with c.store("ja") as s:
        assert library.book_parts(s, epub) == records


def _rel(item_id):
    with c.store("ja") as s:
        return s.item(item_id)["rel_path"]


def test_a_cards_part_is_named_and_one_from_another_part_is_another_line(tmp_path):
    """`Steps._place`: each card's `location` put on its part through the store's records — the job's own part, or
    another's (the same sentence twice in a book): `other_line`; a row with no location is left as it is."""
    _library()
    epub, parts, records = _parts_in_store(tmp_path)
    docs, _ = extract.epub_documents(epub)
    first, second = (records[p] for p in parts)
    shared = first["docs"][1]
    assert second["docs"][0] == shared, "the novel's first chapter: two parts in one document"
    # the shared document: its first lines are the first part's; the second part's last document is its own
    mine = next(ln for ln in docs[shared].text.splitlines() if ln and _inside(docs[shared].text.find(ln), first, shared))
    theirs = docs[second["docs"][1]].text.splitlines()[0]
    picked = {"reading": epub, "book": epub, "words": [{"word": "冒険", "reading": "ボウケン", "line_text": mine},
                                                       {"word": "今夜", "reading": "コンヤ", "line_text": theirs},
                                                       {"word": "彼", "reading": "カレ", "line_text": mine}]}
    outcomes = [{"word": "冒険", "reading": "ボウケン", "location": f"ch.{shared}", "other_line": False},
                {"word": "今夜", "reading": "コンヤ", "location": f"ch.{second['docs'][1]}", "other_line": False},
                {"word": "彼", "reading": "カレ", "location": None, "other_line": False}]
    runner.Steps._place(runner.Steps.__new__(runner.Steps), "ja", {"id": 1, "item_id": parts[0]}, picked, outcomes)
    assert [(o.get("part"), o["other_line"]) for o in outcomes] == [(parts[0], False), (parts[1], True), (None, False)]


def test_a_book_anki_miner_cant_read_is_a_plain_needs_you_never_its_window(tmp_path, monkeypatch):
    """SOURCE_UNREADABLE on a book's batch: *Needs you* with the book's title and Anki Miner's reason, in plain words —
    nothing that sends you to Anki Miner; an Anki Miner that lost `reading` since the pick sets the job aside as a
    book waits (`BOOKS_WAIT`: queued again by itself once one reads books)."""
    from app.cli import verbs
    steps = runner.Steps.__new__(runner.Steps)
    steps.loaded, steps.url, steps._anki_miner_sets = {"connect_anki_miner_path": __file__}, "http://127.0.0.1:9", {}
    steps.title = lambda lang, job: "旅の記録 01"
    steps.show = lambda lang, job: None
    steps.run_dir = lambda job: str(tmp_path / "runs")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda *a, **k: ({"features": ["reading"]}, "p1", None))
    picked = {"reading": str(tmp_path / "旅の記録.epub"), "book": None, "profile": "p1", "video": None, "subtitle": None}
    _record(["word-from-line", "reading"])
    for kind, code, raised, said in (("unreadable", "SOURCE_UNREADABLE", runner.Needs, "旅の記録 01"),
                                     ("no-reading", None, runner.Skip, runner.BOOKS_WAIT)):
        def refuse(*a, **k):
            raise anki_miner.AnkiMinerError(kind, "The book has no readable text (DRM?)", code=code,
                                            verdict={"app": "3.10.1", "schema": 1, "features": ["word-from-line"]})
        monkeypatch.setattr(anki_miner, "mine_batch", refuse)
        with pytest.raises(raised) as e:
            steps.mine("ja", {"id": 1, "item_id": 7}, picked, [], 1)
        line = getattr(e.value, "say", None) or getattr(e.value, "why", None)
        assert said in line and "open anki miner" not in line.lower() and "Anki Miner's window" not in line
    # review R1-1: the record now names the Anki Miner installed, so the job set aside stays aside (never queued again
    # and refused at every look)
    assert not anki_miner.mines_now("books")
    assert "DRM" in runner.BOOK_UNREADABLE.format(title="t", why="The book has no readable text (DRM?)")


def test_with_the_ledger_a_book_set_aside_before_is_queued_again_and_mined_as_a_book(tmp_path):
    """A book's job set aside while Anki Miner couldn't read books is queued again once the setup record names
    `reading` — the same job, mined as a book (its EPUB named), nothing to undo."""
    _library()
    epub, parts, _records = _parts_in_store(tmp_path)
    steps = BookSteps(str(tmp_path), "ja", {"words": {str(parts[0]): WORDS}})
    steps.can = frozenset()
    _place_top(parts[0])
    _run(steps)
    assert (_jobs(parts[0])[-1]["state"], _jobs(parts[0])[-1]["reason"]) == ("skipped", runner.BOOKS_WAIT)
    steps.can = frozenset({"books"})
    _run(steps)
    assert len(_jobs(parts[0])) == 1 and _jobs(parts[0])[-1]["state"] == "done"
    assert ("reading", parts[0], None, epub) in steps.log
    with Ledger() as ledger:
        assert ledger.picked(_jobs(parts[0])[-1]["id"])["reading"] == epub


def test_a_books_cards_keep_anki_miners_media_names(tmp_path):
    """A book's cards have no clip and the book's cover as their picture: Connect's renaming by the line (a video's
    clip and frame) never runs on them — every card's line is 0 s, so it would give every card's picture one name."""
    steps = runner.Steps.__new__(runner.Steps)
    steps.pairing = lambda lang, job: pytest.fail("a book's media are never renamed")
    assert steps.name_media("ja", {"id": 1, "item_id": 7}, {"reading": "旅の記録.epub"}, [(1, 0.0, 0.0, "冒険だ。")]) is None
