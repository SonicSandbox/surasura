"""Hover-W: a title's word card (Sonic's idea, QUESTIONS 2026-11-13; his yes to the look, 2026-11-14: "It's good for
hover"). Hovering a Current row's *N new* shows its new words, its words in Anki not mature yet and the words earlier
titles teach first; a click keeps it open, every part whole, and a word there shows its sentence from this title.
Qt-free (`tests/test_import_guard.py`); the window paints what this says (`app/qt/word_peek.py`).

- **The words** are the window's own numbers' (`moves.Numbers.words`: the plan engine whose *N new* the rows show —
  `len(card.new)` is always the row's figure; while the figures are faded, the last plan's, and the card says so).
- **In Anki, not mature yet**: the title's every word from the token store's per-file counts (young cards count as
  known, so the plan doesn't hold them), matched to Anki's standing (`anki_words.word_states`: read once on this
  worker — at the window's open, after a known-words sync, as the window comes to the front — never on a hover) by
  the card's word: a token's lemma or the list's spelling, exactly; a miss shows one word fewer, never a wrong one.
- **A word's sentence** (kept open, Sonic 2026-11-14): its first sentence in this title, from the plan's per-file first
  sentences (`plan_engine.first_sentences`, read once per plan, F7's `fs` / `firsts`) and the token store's cached
  text — shown only when that text's hash is the plan's; an older plan, a word the list doesn't hold or a word from
  Anki only has none, and nothing is shown.

Everything runs on this provider's own worker; `ask` / `sentences` answer through a callback (the window bridges it
to its thread). Measured on 2k / 20k files: Hover-W's register (TheForge tracks/window/reviews/hover-w-register.md).
"""
import json
import os
import threading
import zlib
from collections import namedtuple

from app.services.automation import Worker

TIER_LABELS = {"now": "Current", "soon": "Soon", "goal": "Goal"}     # (library_store.TIER_LABELS: 3.0's names)

CardWord = namedtuple("CardWord", "label word reading phrase at f")
#   label: the spelling shown; (word, reading): the plan's key; at: the title's item where it is first met; f: plan file
AnkiWord = namedtuple("AnkiWord", "word leech lapses young uses")
Group = namedtuple("Group", "title words")          # Learned on the way: the title that teaches them, in journey order
Card = namedtuple("Card", "key title tier n_files n_new today new anki before kept episode items")
#   anki: a tuple of AnkiWord (struggling first, then young), or "closed" (Anki didn't answer), or None (no decks
#   chosen / switched off: the part isn't shown); episode: the row's way into the journey (`journey_episode`)
Sentence = namedtuple("Sentence", "text start end place")
#   text: the sentence as the token store keeps it; [start, end): the word in it (start == end: not found in it);
#   place: the episode or part it is from (None when the title is one file)

ANKI_CLOSED = "closed"
ANKI_EVERY_S = 60.0          # at most one standing read a minute from the window's moments (a known sync's: always)


def places(view):
    """{item id: (row title, episode label, files in the row)} of the view's Current rows — learned-on-the-way words
    grouped under the title that teaches them, a sentence's place."""
    out = {}
    for row in getattr(view, "rows", None) or ():
        eps = getattr(row, "episodes", None) or ()
        for ep in eps:
            out[ep.id] = (row.title, ep.label, len(eps))
    return out


def card(answer, row, where, standing=None, counts=None, language="ja"):
    """The card's model (pure). `answer`: `Numbers.words`'s; `row`: the view's Row; `where`: `places(view)`;
    `standing`: Anki's {card word: Standing}, `ANKI_CLOSED` or None; `counts`: {lemma: uses} of the title's files (the
    token store's), or None when unread."""
    from app.services import view_rows
    new = tuple(_word(w) for w in answer.new)
    groups, last = [], None
    for w in answer.before:
        title = (where.get(w.taught) or (None,))[0] or _stem(answer.rel.get(w.f, ""))
        if title != last:
            groups.append(Group(title, []))
            last = title
        groups[-1].words.append(_word(w))
    before = tuple(Group(g.title, tuple(g.words)) for g in groups)
    eps = getattr(row, "episodes", None) or ()
    return Card(key=row.key, title=row.title, tier=TIER_LABELS.get(getattr(row, "tier", None), ""),
                n_files=len(eps), n_new=len(new), today=len(new) + len(answer.before), new=new,
                anki=anki_part(standing, counts, answer, language), before=before, kept=bool(answer.kept),
                episode=view_rows.journey_episode(row), items=tuple(e.id for e in eps))


def anki_part(standing, counts, answer=None, language="ja"):
    """In Anki, not mature yet: the title's words with a card that is struggling (a leech, or forgotten) or young —
    struggling first (a leech, then the most forgotten), then young; each by its uses in the title. `ANKI_CLOSED` /
    None as `standing` is; () when none."""
    if standing is None or standing == ANKI_CLOSED:
        return standing
    if not counts:
        return ()
    spelled = {}
    for w in (answer.new + answer.before) if answer is not None else ():
        spelled.setdefault(w.word, w.label)
    out = []
    for lemma, uses in counts.items():
        s = standing.get(lemma)
        if s is None:
            label = spelled.get(lemma)
            s = standing.get(label) if label else None
            lemma = label if s is not None else lemma
        if s is None or not (s.leech or s.lapses or s.young) or (s.mature and not s.leech):
            continue                                 # mature (a lapse long ago too), or no studied card: not this part's
        out.append(AnkiWord(lemma, bool(s.leech), int(s.lapses or 0), bool(s.young), uses))
    out.sort(key=lambda a: (not (a.leech or a.lapses), not a.leech, -a.lapses, -a.uses, a.word))
    return tuple(out)


def counts_of(store, paths):
    """{lemma: uses} of the files at `paths`, from the token store's counts (an unread or missing file adds none)."""
    out = {}
    for path in paths:
        try:
            from app import token_index
            row = store.conn.execute("SELECT counts FROM files WHERE path=?", (token_index._norm(path),)).fetchone()
            got = json.loads(zlib.decompress(row[0]).decode("utf-8")) if row and row[0] else {}
        except Exception:
            got = {}
        for key, n in got.items():
            lemma = key.split("|", 1)[0]
            out[lemma] = out.get(lemma, 0) + n
    return out


def sentence_of(sentences, number, text_hash, word, reading, phrase):
    """The word's sentence from a file's cached sentences (`Store.file_tokens`' shape): the plan's `number`, shown only
    when its text's hash is the plan's (`plan_rules.text_hash_of`) — else None, never another sentence. The word's span:
    its tokens (a phrase: the run of tokens whose lemmas make its Word), else the whole word's own spelling, else none."""
    from app import plan_rules
    if not 0 <= number < len(sentences):
        return None
    raw, tokens = sentences[number][0], sentences[number][1]
    text = (raw or "").strip()
    if not text or plan_rules.text_hash_of(text) != text_hash:
        return None
    start, end = _span(text, tokens, word, reading, phrase)
    return Sentence(text, start, end, None)


def _span(text, tokens, word, reading, phrase):
    surfaces, at = [], 0
    for t in tokens:                                # each token's place in the text (the surfaces, in order)
        surface = t[2] if len(t) > 2 else t[0]
        i = text.find(surface, at) if surface else -1
        surfaces.append((t[0], t[1] if len(t) > 1 else "", i, i + len(surface) if i >= 0 else -1))
        if i >= 0:
            at = i + len(surface)
    for i, (lemma, rd, s, e) in enumerate(surfaces):
        if s < 0:
            continue
        if not phrase and lemma == word and (not reading or not rd or rd == reading):
            return s, e
        if phrase and word.startswith(lemma):
            joined, j, end = lemma, i, e
            while joined != word and j + 1 < len(surfaces) and word.startswith(joined + surfaces[j + 1][0]):
                j += 1
                joined += surfaces[j][0]
                end = surfaces[j][3] if surfaces[j][3] >= 0 else end
            if joined == word:
                return s, end
    i = text.find(word)
    return (i, i + len(word)) if i >= 0 else (0, 0)


def _word(w):
    return CardWord(w.label, w.word, w.reading, w.phrase, w.at, w.f)


def _stem(rel):
    name = rel.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


class TitleWords:
    """The window's word-card provider (one per window and language), on its own worker. `numbers`: the window's
    `moves.Numbers`; `settings`: () -> the settings dict; `open_store`: () -> a token store reader (default:
    `token_index.open_reader`); `read_standing`: (language, settings) -> {word: Standing} (default:
    `anki_words.word_states`; Anki is never reached under `SURASURA_NO_ANKI_SYNC`)."""

    def __init__(self, numbers, language="ja", settings=None, open_store=None, read_standing=None, clock=None):
        import time
        self.numbers, self.language = numbers, language
        self._settings = settings or dict
        self._open_store = open_store
        self._read_standing = read_standing
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._standing = None                        # {word: Standing}, ANKI_CLOSED or None (none read / no decks)
        self._standing_at = None
        self._firsts = None                          # (plan path, key) -> FirstSentences: the last plan's, once read
        self._store = None
        self._closed = False
        self._counts = {}                            # (plan key, its files) -> {lemma: uses}: a title's, once a plan
        self._places = (None, {})                    # (the view, `places(view)`): once a view
        self.worker = Worker(f"window-title-words-{language}")
        self.reads = {"standing": 0, "firsts": 0}    # (tests, the register's counts)

    # --- the card --------------------------------------------------------------------------------------------- #
    def ask(self, row, view, done):
        """(Any thread.) `row`'s card -> `done(card)` on the worker; `done(None)` when the row shows no *N new*."""
        self.worker.put(lambda: done(self._card(row, view)))

    def _card(self, row, view):
        ids = [e.id for e in getattr(row, "episodes", None) or ()]
        answer = self.numbers.words(ids) if self.numbers is not None else None
        if answer is None:
            return None
        with self._lock:
            standing = self._standing
        counts = None
        if standing and standing != ANKI_CLOSED:             # ({}: Anki holds no studied card — nothing to match)
            store = self._token_store()
            if store is not None and answer.data_dir:
                key = (answer.key, tuple(sorted(answer.rel.values())))
                counts = self._counts.get(key)
                if counts is None:
                    rels = answer.rel.values()
                    counts = counts_of(store, [os.path.join(answer.data_dir, *r.split("/")) for r in rels])
                    if len(self._counts) > 16:
                        self._counts.clear()
                    self._counts[key] = counts
        if self._places[0] is not view:
            self._places = (view, places(view))
        return card(answer, row, self._places[1], standing, counts, self.language)

    # --- a word's sentence ------------------------------------------------------------------------------------- #
    def sentences(self, row, done):
        """(Any thread; the card kept open.) Each of the title's words' first sentence in the title -> `done({(word,
        reading): Sentence})` on the worker ({} when the plan keeps none: an older plan, another plan read since)."""
        self.worker.put(lambda: done(self._sentences(row)))

    def _sentences(self, row):
        ids = [e.id for e in getattr(row, "episodes", None) or ()]
        answer = self.numbers.words(ids) if self.numbers is not None else None
        if answer is None or not answer.data_dir:
            return {}
        firsts = self._first_sentences(answer.plan, answer.key)
        store = self._token_store()
        if firsts is None or store is None:
            return {}
        label = {e.id: (e.label if len(ids) > 1 else None) for e in getattr(row, "episodes", None) or ()}
        out, cached, tables = {}, {}, {}
        for w in answer.new + answer.before:
            rel = answer.rel.get(w.f)
            if rel is None or firsts.files[w.f] != rel:
                continue
            if w.f not in tables:
                tables[w.f] = firsts.of(w.f)           # (once a file, never once a word: review r1 #5)
            found = tables[w.f].get(w.k)
            if found is None:
                continue
            if w.f not in cached:
                try:
                    cached[w.f] = store.file_tokens(os.path.join(answer.data_dir, *rel.split("/")))
                except Exception:
                    cached[w.f] = []
            s = sentence_of(cached[w.f], found[0], found[1], w.word, w.reading, w.phrase)
            if s is not None:
                out[(w.word, w.reading)] = s._replace(place=label.get(w.at))
        return out

    def _first_sentences(self, plan, key):
        from app import plan_engine
        with self._lock:
            held = self._firsts
        if held is not None and held[0] == (plan, key):
            return held[1]
        try:
            st = os.stat(plan)
            if (st.st_mtime_ns, st.st_size) != key:
                return None                          # another plan is on disk now: its sentences aren't these words'
        except OSError:
            return None
        self.reads["firsts"] += 1
        found = plan_engine.first_sentences(plan)
        if found is not None and found.key != key:
            found = None
        with self._lock:
            self._firsts = ((plan, key), found)
        return found

    def _token_store(self):
        if self._closed:
            return None
        if self._store is None:
            try:
                if self._open_store is not None:
                    self._store = self._open_store()
                else:
                    from app import token_index
                    self._store = token_index.open_reader(self.language)
            except Exception:
                self._store = None
        return self._store

    # --- Anki's standing ---------------------------------------------------------------------------------------- #
    def refresh_anki(self, force=False):
        """(Any thread.) Anki's standing read again on the worker — at most every `ANKI_EVERY_S` unless `force` (a
        known-words sync just ended). Anki closed: `ANKI_CLOSED`; no decks chosen or switched off: None."""
        self.worker.put(lambda: self._refresh(force))

    def _refresh(self, force):
        now = self._clock()
        with self._lock:
            if not force and self._standing_at is not None and now - self._standing_at < ANKI_EVERY_S \
                    and self._standing != ANKI_CLOSED:   # a card that said "closed" is looked at again at once
                return
            self._standing_at = now
        self.reads["standing"] += 1
        read = self._read_standing
        if read is None:
            if os.environ.get("SURASURA_NO_ANKI_SYNC"):
                found = None
            else:
                from app import anki_words
                read = anki_words.word_states
        if read is not None:
            try:
                found = read(self.language, self._settings() or {})
            except Exception as e:                   # only Anki not answering is "closed" (review r1 #4, r2)
                name = e.__class__.__name__
                if name in ("NoneStudied", "NoWords"):
                    found = {}                       # Anki answers: no studied card / no word in them
                elif _anki_waits(e):
                    with self._lock:                 # busy (its own sync, Check Database) or slow: what it last
                        self._standing_at = None     # said stands, and it is asked again at the next moment
                    return
                elif name != "NoDecks" and _is_anki_error(e):
                    found = ANKI_CLOSED
                else:
                    found = None
        with self._lock:
            self._standing = found

    def standing(self):
        with self._lock:
            return self._standing

    def idle(self, timeout=None):
        return self.worker.idle(timeout)

    def close(self):
        """The store reader closed on the worker that opened it (SQLite's thread rule), then the worker."""
        self._closed = True

        def shut():
            store, self._store = self._store, None
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
        self.worker.put(shut)
        self.worker.close()
        with self._lock:
            self._firsts = None


def _is_anki_error(e):
    try:
        from app.anki_connect import AnkiError
    except Exception:
        return False
    return isinstance(e, AnkiError)


def _anki_waits(e):
    """Anki open but busy or answering late (`anki_connect.is_busy`): never "closed"."""
    try:
        from app.anki_connect import AnkiError, is_busy
    except Exception:
        return False
    return isinstance(e, AnkiError) and is_busy(e)
