"""Which sound a card would get, and which cards fall due soon (AUDIO-FIND, 3.0.21; Sonic § 106, TheForge
`research/audio-fill-2026-11-26/PLAN.md` lane 1; ROLES *Card sound*). Read only: it decides, AUDIO-FILL writes (through
`sentence_audio`, the one writer) and cuts (`clips.py`'s direct cut, `add_audio.cut`).

- **`plan(language, notes, mapping, steps)`** -> {note id: Source}, for the notes given (notesInfo entries): a note whose
  sentence-audio field (Anki Miner's role `audio`) isn't exactly empty is `NONE` with its why (`sentence_audio`'s own
  rule); every other one gets the first source with real sound, in decision 2's order:
  1. `LINE` — **its own line in its episode**: Connect's record of the note (`ledger.note_lines`: the item its line was
     cut from and the line's start), the cue at that start (within NEAR_MS, `swap.line_cue`'s rule) that still says the
     card's sentence; else, the subtitle re-timed since, the ONE cue of the episode that says it word for word — two is
     none, never a neighbour's (`add_audio.place`'s rule) —; only with the episode's video on this PC.
  2. `AUDIOBOOK` — **its book's audiobook**: a card Connect made from a paired book's parts (the store's made words, as
     *Add audio* finds them) placed in the book's line-up (`Steps.lined_up`) by `add_audio.place`.
  3. `ELSEWHERE` — **the same sentence word for word in another episode** of the library (letters and digits,
     `lineup.clean`; never "close enough"), its video on this PC: the subtitles whose words hold the card's word
     (`TokenStore.holding`, one look for every card at once), each read once (`cues.read`, no tokenizer), its cues
     looked up in {sentence: cards}. The card's own episode is not "elsewhere". The first in the library's order.
  else `NONE`: `AI` (the AI voice's turn: Japanese) or `SILENT` (no voice for Chinese: it stays a sentence card).
- **`tally(plan)`** -> {"line", "audiobook", "elsewhere", "ai", "silent", "has_sound", "other"}: *Needs you*'s count
  ("other": no audio field mapped, a note gone).
- One file that can't be read (a subtitle, a line-up) leaves its cards to the next step, never the plan.
- **`due_days(url, deck, days, per_day)`** -> {note id: day}: the notes with a card due within `days` days (0 = today,
  overdue too), unsuspended — learning cards today, review cards by Anki's due day (`prop:due`), new cards by their
  place in the new queue (`per_day` a day, the order Junban writes): only the AI voice waits for this window, soonest
  first; real sound never waits (Sonic § 106).

Costs (the DSA floor): cards are grouped by item, so each subtitle is read once and its cues kept in two dicts (by
start, by clean text): a card's own line is a look-up, never a scan; a book's line-up is read once a book, its cues by
clean text (`place`'s scan only for a sentence no cue says whole); the other episodes are one byte search of the token
store's counts for every card's word at once, then only the files that hold one are read; Anki is asked one search a
day and a few id-only searches for the new queue, never once a card, and `cardsInfo` only for the new cards in the
window. Standard library; Anki through `anki_connect`.
"""
import logging
import os
from collections import namedtuple

log = logging.getLogger(__name__)

LINE, AUDIOBOOK, ELSEWHERE, NONE = "line", "audiobook", "elsewhere", "none"
AI = "the AI voice's turn"                      # NONE's why: no real sound for it (the AI voice reads Japanese only)
SILENT = "no sound for it here"                 # NONE's why in a language with no AI voice (Chinese)
NO_FIELD = "Anki Miner's field mapping names no field for the sentence's audio"
NEAR_MS = 5                                     # a re-time this small keeps a line's id (`swap.line_cue`)
NEW_PER_DAY = 20                                # Anki's own default, when the deck's can't be read
MAX_DAYS = 31                                   # the window's widest (the setting offers 1 / 3 / 7)
_NEAR = sorted(range(-NEAR_MS, NEAR_MS + 1), key=abs)        # the offsets a line's start is looked at, nearest first
_LAST_POS = 1 << 31                             # a new card's place is a 32-bit number in Anki

# One card's answer: `kind` LINE / AUDIOBOOK / ELSEWHERE / NONE; `item_id` the episode (LINE, ELSEWHERE) or the
# audiobook (AUDIOBOOK); `start` / `end` the line's times (ms); `line_id` the line's id (`swap.line_id`: what
# `clips.cut` takes); `cue` the line-up's `lineup.Cue` (AUDIOBOOK: what `add_audio.cut` takes); `why` (NONE)
Source = namedtuple("Source", "kind item_id start end line_id cue why", defaults=(None,) * 6)
_Card = namedtuple("_Card", "sentence word raw")


def plan(language, notes, mapping, steps, ledger_path=None):
    """Each note's source, read only -> {note id: Source} (see the module's docstring). A busy store is the
    runner's Wait (the caller asks again)."""
    from app.connect import add_audio, ledger
    from app.connect import sentence_audio as sa
    field = (mapping.fields or {}).get("audio") if mapping is not None else None
    out, cards = {}, {}
    for note in notes or ():
        if not isinstance(note, dict) or not isinstance(note.get("noteId"), int):
            continue
        nid = note["noteId"]
        why = sa._why_not(note, field) if field else NO_FIELD
        if why is not None:
            out[nid] = Source(NONE, why=why)
            continue
        fields = note.get("fields") or {}
        raw = (fields.get(mapping.sentence) or {}).get("value") if mapping.sentence else ""
        word = (fields.get(mapping.word) or {}).get("value") if mapping.word else ""
        cards[nid] = _Card(add_audio._text(raw), add_audio._text(word), raw)
    if not cards:
        return out
    import sqlite3
    from app.connect import runner
    try:
        lines = ledger.note_lines(ledger_path or ledger.path(), list(cards), language, strict=True)
    except sqlite3.Error:
        raise runner.Wait("Connect's ledger is busy just now") from None
    for step in (_own_lines, _audiobooks, _elsewhere):
        left = {n: c for n, c in cards.items() if n not in out}
        if not left:
            break
        out.update(step(language, steps, left, lines))
    for nid in cards:
        out.setdefault(nid, Source(NONE, why=AI if language == "ja" else SILENT))
    return out


def tally(sources):
    """*Needs you*'s count of a plan: how many cards each source gives, the AI voice's turn, none, sound already."""
    from app.connect import sentence_audio as sa
    out = {LINE: 0, AUDIOBOOK: 0, ELSEWHERE: 0, "ai": 0, "silent": 0, "has_sound": 0, "other": 0}
    for s in (sources or {}).values():
        if s.kind != NONE:
            out[s.kind] += 1
        else:
            out["ai" if s.why == AI else "silent" if s.why == SILENT else
                "has_sound" if s.why == sa.HAS_AUDIO else "other"] += 1
    return out


# --- the cues of one subtitle, kept as the look-ups need them ---------------------------------------------------- #
class _Said:
    """A subtitle's spoken cues (never a sung line, nor a line shown again: its first copy is the line) by start and
    by clean text — each look-up a dict's."""

    def __init__(self, found):
        from app.connect import lineup
        self.by_start, self.by_text = {}, {}
        for cue in found:
            if cue.sung or cue.repeats is not None:
                continue
            text = lineup.clean(cue.text)
            if text:
                self.by_start.setdefault(int(cue.start), []).append((cue, text))
                self.by_text.setdefault(text, []).append(cue)

    def at(self, ms, want):
        """The cue starting within NEAR_MS of `ms` that says `want` — word for word, or holding it whole (MIN_CHARS or
        longer, as `add_audio.place` finds a line) — nearest first; None. A line that says only part of it is never
        the card's (half its sentence's sound), nor a short line now at that start."""
        from app.connect import lineup
        for off in _NEAR:
            for cue, text in self.by_start.get(ms + off, ()):
                if text == want or (len(want) >= lineup.MIN_CHARS and want in text):
                    return cue
        return None

    def only(self, want):
        """The one cue that says `want` word for word; None for none or two (never a guess)."""
        found = self.by_text.get(want) or ()
        return found[0] if len(found) == 1 else None


def _ms(seconds):
    return int(round(float(seconds) * 1000))


def _line(language, steps, item_id):
    """(the episode's subtitle, its video) on this PC, or None: no subtitle (a book, a text), no video, gone."""
    from app import cues
    job = {"id": 0, "item_id": item_id}
    subtitle = steps.subtitle(language, job)
    if not subtitle or not str(subtitle).lower().endswith(cues.SUBTITLES) or not os.path.isfile(subtitle):
        return None
    video = steps.video(language, job)
    return (subtitle, video) if video and os.path.isfile(video) else None


def _read_cues(path, language):
    """`cues.read` of one subtitle (times only), or None when it can't be read (logged): its cards go on to the next
    step."""
    from app import cues
    try:
        return cues.read(path, language, clues=False)
    except (OSError, UnicodeError, ValueError):
        log.info("Card sound: a subtitle couldn't be read", exc_info=True)
        return None


def _own_lines(language, steps, cards, lines):
    """Step 1: each Connect card's own line in its own episode (one read of each episode's subtitle)."""
    from app.connect import lineup, swap
    by_item = {}
    for nid in cards:
        got = lines.get(nid)
        if got and got[0] is not None and got[1] is not None:
            by_item.setdefault(int(got[0]), []).append(nid)
    out = {}
    for item_id, nids in sorted(by_item.items()):
        here = _line(language, steps, item_id)
        if here is None:
            continue
        found = _read_cues(here[0], language)
        if found is None:
            continue
        said = _Said(found)
        for nid in nids:
            want = lineup.clean(cards[nid].sentence or lines[nid][3])
            if not want:
                continue
            cue = said.at(_ms(lines[nid][1]), want) or said.only(want)
            if cue is not None:
                out[nid] = Source(LINE, item_id, cue.start, cue.end, swap.line_id(item_id, cue.start / 1000.0))
    return out


def _audiobooks(language, steps, cards, lines):
    """Step 2: a card Connect made from a paired book, placed in that book's line-up (read once a book)."""
    from app.connect import add_audio, lineup
    books = []
    for epub, nids in _books(language, steps, set(cards)):
        lined = steps.lined_up(language, epub)
        if lined:
            books.append((lined, nids))
    out = {}
    for lined, nids in books:
        try:
            found = lineup.cues(lined["lineup"])
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            log.info("Card sound: a book's line-up couldn't be read", exc_info=True)
            continue
        by_text = {}
        for cue in found:
            by_text.setdefault(cue.text, []).append(cue)
        for nid in sorted(nids - set(out)):         # (a note two books claim: the first's)
            card = cards[nid]
            exact = by_text.get(lineup.clean(card.sentence))
            if exact:                           # (`place`'s first rule, as a look-up: two answers is none)
                cue = exact[0] if len(exact) == 1 else None
            else:
                cue = add_audio.place(card.sentence, add_audio._form(card.raw, card.word), found)
            if cue is not None:
                out[nid] = Source(AUDIOBOOK, lined.get("item_id"), _ms(cue.start), _ms(cue.end), cue=cue)
    return out


def _books(language, steps, nids):
    """[(a paired book's EPUB, the notes of `nids` Connect made from its parts)] — the store's made words, as *Add
    audio* finds a book's cards (`add_audio.book_items` / `made_notes`)."""
    import json
    from app.connect import add_audio, library
    with steps._open(language) as store:
        book_of = {}
        for epub, _audiobook, _sha in library.paired_books(store):
            for item in add_audio.book_items(store, epub):
                book_of.setdefault(item, epub)
        if not book_of or not store._has_table("made_words"):
            return []
        mine = {}
        with store._reading():              # the made words read once for every book (`made_notes`' rows)
            for item_id, ids in store.conn.execute("SELECT item_id, note_ids FROM made_words"):
                epub = book_of.get(item_id)
                if epub is None:
                    continue
                try:
                    held = {int(n) for n in json.loads(ids)} & nids
                except (TypeError, ValueError):
                    continue
                if held:
                    mine.setdefault(epub, set()).update(held)
    return [(epub, mine[epub]) for epub in dict.fromkeys(book_of.values()) if epub in mine]


def _elsewhere(language, steps, cards, lines):
    """Step 3: the same sentence word for word in another episode, its video here (the first in the library's order)."""
    from app.connect import lineup, swap
    want, words = {}, set()
    for nid, card in cards.items():
        text = lineup.clean(card.sentence)
        if text and card.word:
            want.setdefault(text, []).append(nid)
            words.add(card.word)
    if not want:
        return {}
    files = _sound_files(language, steps)
    if not files:
        return {}
    own = {nid: int(lines[nid][0]) for nid in cards if lines.get(nid) and lines[nid][0] is not None}
    out = {}
    for path in _holding(language, list(files), [[w] for w in sorted(words)]):
        item_id = files[path]
        if _line(language, steps, item_id) is None:         # (no video here: its subtitle isn't even read)
            continue
        hits = {}
        for cue in _read_cues(path, language) or ():
            if cue.sung or cue.repeats is not None:
                continue
            for nid in want.get(lineup.clean(cue.text), ()):
                if nid not in out and nid not in hits and own.get(nid) != item_id:
                    hits[nid] = cue
        if not hits:
            continue
        for nid, cue in hits.items():
            out[nid] = Source(ELSEWHERE, item_id, cue.start, cue.end, swap.line_id(item_id, cue.start / 1000.0))
        if len(out) == len(cards):
            break
    return out


def _sound_files(language, steps):
    """{a subtitle's path: its item id} of the library's subtitles, in the library's order (one read of the store)."""
    from app import cues
    from app.path_utils import get_data_path
    with steps._open(language) as store:
        with store._reading():
            rows = store.conn.execute("SELECT id, rel_path FROM items ORDER BY tier, ord, id").fetchall()
    root = get_data_path(language)
    return {os.path.join(root, *str(rel).replace("\\", "/").split("/")): int(item_id) for item_id, rel in rows
            if rel and str(rel).lower().endswith(cues.SUBTITLES)}


def _holding(language, paths, runs):
    """The `paths` (in their order) whose counted words hold one of `runs`' words (`TokenStore.holding`)."""
    from app import token_index
    store = token_index.open_store(language)
    try:
        return store.holding(paths, runs=runs)
    finally:
        store.close()


# --- the due window -------------------------------------------------------------------------------------------- #
def due_days(url, deck, days, per_day=None):
    """{note id: the first day (0 = today) one of its unsuspended cards falls due within `days` days} in `deck` (and
    its subdecks; None: every deck). Learning cards: today. Review cards: Anki's own due day (`prop:due`, overdue as
    today). New cards: the first `per_day` × `days` of the new queue in Anki's order (its positions, which Junban
    writes), `per_day` a day — the deck's *New cards/day* when not given (Anki's default when it can't be read)."""
    from app import anki_connect
    from app.connect import anki_session
    days = min(MAX_DAYS, max(0, int(days or 0)))
    if not days:
        return {}
    scope = (f'deck:"{anki_connect.escape_query(deck)}" ' if deck else "") + "-is:suspended"
    out = {}
    for nid in anki_connect.find_notes(url, f"{scope} is:learn"):
        out.setdefault(nid, 0)
    for day in range(days):
        for nid in anki_connect.find_notes(url, f"{scope} -is:new prop:due{'<=' if day == 0 else '='}{day}"):
            out.setdefault(nid, day)
    if per_day is None and deck:
        per_day = anki_session.per_day(url, deck)
    per_day = per_day if isinstance(per_day, int) and per_day > 0 else NEW_PER_DAY
    window = _first_new(url, f"{scope} is:new", per_day * days)
    if window:
        info = [c for c in anki_connect.cards_info(url, window) or () if isinstance(c, dict)]
        info.sort(key=lambda c: (c.get("due", 0), c.get("cardId", 0)))
        for rank, card in enumerate(info[:per_day * days]):
            if isinstance(card.get("note"), int):          # (a note's review card may be due later: the soonest)
                out[card["note"]] = min(out.get(card["note"], days), rank // per_day)
    return out


def _first_new(url, query, k):
    """The card ids of the first `k` new cards `query` finds, by their place in the new queue: the place cut where
    `prop:pos<=` first holds `k` (halving, id-only searches: ~2·log₂ of the queue's last place), never `cardsInfo` over
    the whole queue."""
    from app import anki_connect
    every = anki_connect.find_cards(url, query)
    if len(every) <= k:
        return every

    asked = {}

    def upto(pos):
        if pos not in asked:
            asked[pos] = anki_connect.find_cards(url, f"{query} prop:pos<={pos}")
        return asked[pos]
    lo, hi = -1, max(k, 1)
    while len(upto(hi)) < k:
        if hi > _LAST_POS:              # (a queue Anki can't place: never a search without end)
            return []
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if len(upto(mid)) >= k:
            hi = mid
        else:
            lo = mid
    return upto(hi)
