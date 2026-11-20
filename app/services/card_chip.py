"""The ✓ chip's count (Michi-CK2; Sonic's ruling 2, 2026-11-17, on the lead's route 2026-11-18): an episode in Anki
shows how many of its words have a card — wherever the card was made: from this episode, another episode or show, or
by hand in Anki. Its hover: *9 from this episode · 22 from other episodes and shows*. A row of several files counts
its words once (`view_rows`). Qt-free (`tests/test_import_guard.py`); the rows say what this counts.

- **Only mined files are counted** (the chip shows only on a row in Anki): each one's words from the token store's
  per-file counts (`token_index` `files.counts`: every lemma, known words too — a studied card's word is a known word,
  so the plan doesn't hold it), interned to ints, and one inverted index word -> the files holding it. Cost follows
  the mined files, never the library (Michi-CK's measure: 300 mined in a 20,000-file library 12 ms a full recount,
  1,000 mined 37–42 ms; a Connect batch's few new words < 0.2 ms).
- **The cards:** the known-words sync's new cards (`anki_backlog.json`, rebuilt from Anki's note ids at each sync),
  the studied cards Anki last said (`anki_words.word_states`, never read here: the window's word card reads it on its
  own worker — at the first frame, to the front at most once a minute, after a sync — and hands its words on,
  `studied`), and the words Connect made cards for that still have a note in Anki (the store's `made_words`, before
  the next sync puts them in the backlog). A hand-made card is counted once it is studied or synced; a card deleted
  in Anki leaves at the next read or sync. A card's word is the token's lemma, exactly — and a card written in kana
  alone is also the word its own sentence says it is (Kyou-KN, 2026-11-20: Junban's one rule,
  `anki_match.card_word_in_sentence` — a まく card in 水をまく counts for 撒く; read once per card and sentence on this
  worker, kept on disk as `reads`, so the tagger loads only for a card not read before). A kana card with no sentence
  that places it counts by its letters alone, as before.
- **On disk** (`card_chip_<lang>.json`, the local data folder): the studied words Anki last said and the last
  answers — Anki closed at the window's open, the chip keeps its count (PROVISIONAL: never jumps to 0), and the
  reader's first build after the first screen reads the last answers until this one answers. Written only when the
  studied words changed, else at most every `SAVE_S` while answers move, and at the close.
- **Answers:** {item_id: other} for an episode and {(item ids…): other} for a row of several — *other* is how many of
  its words have a card not made from it (its own cards are the row's count already). Beside them, {("level", key):
  (at, below)}: of the cards Connect made from it, how many words were on the list (*at your level*) and how many
  were i+1 words below it (Sonic's lean A, 2026-11-18: *Only i+1* makes both; the hover says so honestly) — from the
  job's pick (`ledger.listed_of`), only where every made word says which. Handed on (`on_change`) only
  when one moved, as one new dict; the reader rebuilds only the rows whose answer moved (S19).

Everything runs on this counter's own worker — never the window's thread, nor the reader's — and, in the window's
process, only while the window rests (`window_idle`: a round starts when it is idle, and the cold read of the mined
files waits out a young window stretch between files, as the reader's build does between rows).
"""
import json
import os
import threading
import time
from array import array

from app.services import window_idle

SAVE_S = 30.0                 # answers moving: written at most this often (the studied words: whenever they change)
RETRY_S = 5.0                 # the token store couldn't be read (locked, busy): the round is tried again this much later
CACHE_VERSION = 1


def cache_path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"card_chip_{language}.json")


def _backlog_words(language):
    """The known-words sync's new cards' words (`anki_backlog.json`), or None when it can't be read — and, for a card
    written in kana alone that kept its sentence (`anki_sync._note_sentence`), `(word, sentence)` beside its word."""
    from app import anki_sync
    notes = anki_sync.load_backlog(language).get("notes")
    if not isinstance(notes, dict):
        return set()
    entries = [e for e in notes.values() if isinstance(e, dict) and e.get("word")]
    return ({str(e["word"]) for e in entries}
            | {(str(e["word"]), e["sentence"]) for e in entries if isinstance(e.get("sentence"), str) and e["sentence"]})


def _backlog_stamp(language):
    from app import anki_sync
    try:
        st = os.stat(anki_sync._backlog_path(language))
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _listed_words(language, ids):
    """{item_id: {word: on the list then}} from Connect's ledger (read-only), or None when it can't be read now."""
    try:
        from app.connect import ledger
        return ledger.listed_of(language, ids)
    except Exception as e:
        print(f"Card chip: the picks' list marks couldn't be read ({e!r})")
        return None


def _made_words(language, ids):
    """{item_id: {word}} Connect made a card for that still has a note in Anki, for `ids` — through one store open;
    None when the store can't be read just now (busy, read-only, not built: the last words stand)."""
    from app import library_store, path_utils
    data_dir = path_utils.get_data_path(language)
    try:
        if library_store.check_mode(language, data_dir, busy_wait=0.0)[0] != "store":
            return None
        store = library_store.open_store(language, data_dir, path_utils.get_user_files_path(language), role="reader")
        if store is None:
            return None
        with store:
            return store.made_words_of(ids)
    except Exception as e:
        print(f"Card chip: the words made couldn't be read ({e!r})")
        return None


class Chips:
    """The ✓ chip's counter for one language (the reader holds one; `want` from its thread after a build).

    - `want(asks)`: the episodes of the rows a build made anew — {item_id: (rel_path, disk, cards)} for one in Anki,
      None for one that isn't (forgotten) — and `rows(keys)`: the item-id tuples of the rows of several files in Anki.
      An ask unlike the last one is looked at: a new file read, its made words read again when its cards moved.
    - `studied(words)` (any thread): the studied cards' words Anki just said (the word card's read); an empty answer
      where there were words keeps them (another profile, renamed decks — as the backlog keeps its last).
    - `seeded()`: the last answers on disk (the reader's, before its first build); `answers()`; `close()`."""

    def __init__(self, language, on_change=None, worker=None, open_tokens=None, data_dir=None, read_made=None,
                 read_backlog=None, backlog_stamp=None, cache_file=None, clock=None, read_listed=None, tokenize=None):
        from app.services.automation import Worker
        self.language = language
        self.on_change = on_change
        self._worker = worker or Worker(f"card-chip-{language}")
        self._open_tokens = open_tokens
        self._data_dir = data_dir
        self._read_made = read_made or _made_words
        self._read_listed = read_listed or _listed_words
        self._read_backlog = read_backlog or _backlog_words
        self._backlog_stamp = backlog_stamp or _backlog_stamp
        self._cache_file = cache_file
        self._clock = clock or time.monotonic
        self._tokenize = tokenize                  # Kyou-KN: the analyzer's, made on this worker when a kana card asks
        self._lock = threading.Lock()
        self._asks = {}                    # item_id -> its newest ask (rel_path, disk, cards)
        self._row_asks = set()             # the rows of several files asked
        self._owed = False
        self._studied_new = None           # the newest studied words handed in, not yet counted
        self._said_new = None              # beside them: (word, sentence) of each kana card with its sentence
        self._busy = False
        self._closed = False
        self._loaded = False               # the disk's studied words read in (the worker's first round)
        # --- the worker's own (touched only there)
        self._ids = {}                     # word -> int
        self._files = {}                   # item_id -> array of its words' ints (sorted, each once)
        self._looked = {}                  # item_id -> the ask its file and made words were read for
        self._inv = {}                     # word int -> [item_id] (lists: a fifth of sets' memory)
        self._made = {}                    # item_id -> frozenset of the ints of its words with a card it made
        self._rows = {}                    # row key (item ids) -> frozenset of its items' made ints
        self._rows_of = {}                 # item_id -> {row key}
        self._ref = {}                     # word int -> how many sources hold a card of it (studied, backlog, made)
        self._studied = set()              # ints
        self._studied_words = None         # the words as Anki last said them (saved on disk)
        self._studied_said = frozenset()   # their kana cards' (word, sentence), as last said (saved on disk)
        self._reads = {}                   # (word, sentence) -> the word it is there, or "" (saved on disk: `reads`)
        self._backlog_said = frozenset()   # the backlog's kana cards' (word, sentence)
        self._backlog = set()              # ints
        self._backlog_at = None
        self._out = {}                     # item_id / row key -> other
        self._level = {}                   # item_id -> (at your level, below it) of the cards it made (lean A)
        self._tokens = None
        self._dirty_at = None              # when the answers on disk fell behind
        self._handed = {}
        self._counted = False              # a round with asks ran: its answers are this session's (never the seed's)
        self._failed = False               # this round's token store read failed (not a file it holds no count of)
        self._retry = None                 # the timer that tries a failed round again
        self.rounds = 0                    # (tests, the register's counts)
        self.read_files = 0

    # --- any thread ------------------------------------------------------------------------------------------ #
    def answers(self):
        with self._lock:
            return dict(self._handed)

    def seeded(self):
        """The last answers on disk ({} with none): the reader's until this counter answers."""
        got = self._read_cache()
        out = {}
        for k, n in (got.get("items") or {}).items():
            try:
                out[int(k)] = int(n)
            except (TypeError, ValueError):
                continue
        for k, n in (got.get("rows") or {}).items():
            try:
                out[tuple(int(x) for x in k.split(","))] = int(n)
            except (TypeError, ValueError):
                continue
        for k, n in (got.get("levels") or {}).items():
            try:
                ids = tuple(int(x) for x in k.split(","))
                out[("level", ids[0] if len(ids) == 1 else ids)] = (int(n[0]), int(n[1]))
            except (TypeError, ValueError, IndexError, KeyError):
                continue
        with self._lock:
            if not self._handed:
                self._handed = dict(out)
        return out

    def want(self, asks, rows=()):
        with self._lock:
            for item_id, ask in asks.items():
                if ask is None:
                    if self._asks.pop(item_id, None) is not None:
                        self._owed = True
                elif self._asks.get(item_id) != ask:
                    self._asks[item_id] = ask
                    self._owed = True
            fresh = set(rows) - self._row_asks
            if fresh:
                self._row_asks |= fresh
                self._owed = True
        self._kick()

    def forget(self, ids, rows=()):
        with self._lock:
            for item_id in ids:
                if self._asks.pop(item_id, None) is not None:
                    self._owed = True
            gone = self._row_asks & set(rows)
            if gone:
                self._row_asks -= gone
                self._owed = True
        self._kick()

    def studied(self, words):
        """`words`: the studied cards' words — or {word: Standing}, a kana card's sentence on its Standing (Kyou-KN)."""
        said = frozenset((str(w), s.sentence) for w, s in words.items()
                         if isinstance(getattr(s, "sentence", None), str) and s.sentence) \
            if isinstance(words, dict) else frozenset()
        words = frozenset(str(w) for w in words or ())
        with self._lock:
            if self._studied_new is None and words == self._studied_words and said == self._studied_said:
                return                                 # (review H-W4) the same words as last read: no round
            self._studied_new, self._said_new = words, said
            self._owed = True
        self._kick()

    def close(self):
        """The answers on disk, the token store closed on this worker (SQLite's thread rule), then the worker."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._retry is not None:
                self._retry.cancel()
        self._worker.put(self._shut)
        self._worker.close()

    def idle(self, timeout=None):
        return self._worker.idle(timeout)

    def _kick(self):
        with self._lock:
            if self._busy or self._closed or not self._owed:
                return
            self._busy = True
        if not self._worker.put(self._round):
            with self._lock:
                self._busy = False

    # --- the worker ------------------------------------------------------------------------------------------- #
    def _round(self):
        try:
            while True:
                with self._lock:
                    if self._closed or not self._owed:
                        self._busy = False
                        return
                    self._owed = False
                    asks, rows = dict(self._asks), set(self._row_asks)
                    studied, self._studied_new = self._studied_new, None
                    said, self._said_new = self._said_new, None
                try:
                    self._count(asks, rows, studied, said)
                except Exception as e:                 # (review H-F3) never half-applied: all counted again
                    print(f"Card chip: a count failed, counted again at the next ask ({e!r})")
                    self._reset()
        except BaseException:
            with self._lock:
                self._busy = False
            raise

    def _reset(self):
        """(The worker.) What was counted let go — the next round reads every asked file again and counts it whole;
        the studied words Anki last said are kept (handed in again), the answers handed on stay until then."""
        self._looked, self._files, self._inv, self._made = {}, {}, {}, {}
        self._rows, self._rows_of, self._ref, self._out, self._level = {}, {}, {}, {}, {}
        self._studied, self._backlog, self._backlog_at = set(), set(), None
        self._backlog_said = frozenset()
        if self._studied_words is not None:
            with self._lock:
                if self._studied_new is None:
                    self._studied_new, self._said_new = self._studied_words, self._studied_said
            self._studied_words, self._studied_said = None, frozenset()

    def _int(self, word):
        n = self._ids.get(word)
        if n is None:
            n = self._ids[word] = len(self._ids)
        return n

    def _read_in(self, said):
        """(The worker.) The words kana cards are in their own sentences — {(word, sentence)} -> {word} — by Junban's
        one rule (`anki_match.card_word_in_sentence`), each card and sentence read once (`reads`, kept on disk)."""
        out = set()
        for pair in said:
            if pair not in self._reads:
                from app import anki_match
                try:
                    token = anki_match.card_word_in_sentence(pair[0], pair[1], self._tokenizer())
                except Exception as e:                 # no tagger: the card counts by its letters, read again later
                    print(f"Card chip: a kana card's sentence couldn't be read ({e!r})")
                    continue
                self._reads[pair] = token[0] if token is not None else ""
            if self._reads[pair]:
                out.add(self._reads[pair])
        return out

    def _tokenizer(self):
        """(The worker.) The analyzer's Japanese tokenizer, as the token store read the library (made once)."""
        if self._tokenize is None:
            from app import analyzer
            analyzer.SANITIZE_JA = True
            self._tokenize = analyzer.JapaneseTokenizer().tokenize
        return self._tokenize

    def _count(self, asks, rows, studied, said=None):
        window_idle.wait()                             # Up next 2: a round starts while the window rests
        self.rounds += 1
        self._failed = False
        flips, full, full_rows = {}, set(), set()

        def ref(w, d):
            before = self._ref.get(w, 0)
            after = before + d
            if after:
                self._ref[w] = after
            else:
                self._ref.pop(w, None)
            if (before > 0) != (after > 0):
                flips[w] = flips.get(w, 0) + (1 if after > 0 else -1)

        def swap(old, new):
            for w in old - new:
                ref(w, -1)
            for w in new - old:
                ref(w, 1)

        if not self._loaded:                                   # the disk's studied words, once
            self._loaded = True
            cache = self._read_cache()
            for row in cache.get("reads") or ():
                if isinstance(row, list) and len(row) == 3 and all(isinstance(x, str) for x in row):
                    self._reads.setdefault((row[0], row[1]), row[2])
            if studied is None:
                kept = cache.get("studied")
                if isinstance(kept, list):
                    studied = frozenset(str(w) for w in kept)
                    said = frozenset((row[0], row[1]) for row in cache.get("studied_said") or ()
                                     if isinstance(row, list) and len(row) == 2 and all(isinstance(x, str) for x in row))
                    self._studied_words, self._studied_said = studied, said
                    new = {self._int(w) for w in studied | self._read_in(said)}     # (the memo: no tagger)
                    swap(self._studied, new)
                    self._studied = new
                    studied = None
        said = frozenset(said or ())
        if studied is not None and (studied or not self._studied_words) and \
                (studied != self._studied_words or said != self._studied_said):
            new = {self._int(w) for w in studied | self._read_in(said)}
            swap(self._studied, new)
            self._studied, self._studied_words, self._studied_said = new, studied, said
            self._save(studied_moved=True)
        stamp = self._backlog_stamp(self.language)
        if stamp != self._backlog_at:
            words = self._read_backlog(self.language)
            if words is not None:
                self._backlog_at = stamp
                pairs = frozenset(w for w in words if isinstance(w, tuple))
                self._backlog_said = pairs
                new = {self._int(w) for w in {w for w in words if isinstance(w, str)} | self._read_in(pairs)}
                swap(self._backlog, new)
                self._backlog = new
        # files that left (no longer mined, or no longer asked) — read or not: its made words held all the same
        for item_id in [i for i in {*self._looked, *self._files, *self._made} if i not in asks]:
            full_rows |= self._drop(item_id, ref)
        # files new or changed, and the made words of those whose cards moved
        reread, made_owed = [], []
        for item_id, ask in asks.items():
            looked = self._looked.get(item_id)
            if looked is None or looked[:2] != ask[:2] or item_id not in self._files:
                reread.append(item_id)
            if looked is None or looked[2] != ask[2]:
                made_owed.append(item_id)
        made = self._read_made(self.language, made_owed) if made_owed else {}
        listed = self._read_listed(self.language, made_owed) if made_owed and made is not None else None
        if made_owed and made is not None and listed is None:
            self._failed = True                        # (review L-S1) the ledger busy: its split read again later
        for item_id in reread:
            window_idle.pause()                        # (Up next 3: a young window stretch waited out, file by file)
            words = self._file_words(asks[item_id][0])
            self._unindex(item_id, self._files.pop(item_id, None))
            if words is None:
                self._out.pop(item_id, None)
                full_rows |= self._rows_of.get(item_id, set())     # its rows counted again without it
                continue
            self._files[item_id] = words
            inv = self._inv
            for w in words:
                held = inv.get(w)
                if held is None:
                    inv[w] = [item_id]
                else:
                    held.append(item_id)                       # (once a file: its words are each once)
            full.add(item_id)
        for item_id in made_owed:
            got = None if made is None else made.get(item_id)
            if got is None and made is None:
                continue                                       # the store can't be read now: asked again next time
            if listed is None:
                self._level.pop(item_id, None)                 # (L-S1) never a split from before its words moved
            else:                                              # lean A: each made word on the list or below it
                flags = listed.get(item_id) or {}
                at = sum(1 for w in got or () if flags.get(w) is True)
                below = sum(1 for w in got or () if flags.get(w) is False)
                if got and at + below == len(got):
                    self._level[item_id] = (at, below)
                else:
                    self._level.pop(item_id, None)             # a word picked before the pick said so: not split
            new = frozenset(self._int(w) for w in got or ())
            old = self._made.get(item_id, frozenset())
            if new != old:
                swap(old, new)
                self._made[item_id] = new
                full.add(item_id)
                full_rows |= self._rows_of.get(item_id, set())
        for item_id in set(reread) | set(made_owed):
            if item_id not in self._files:
                continue                                       # no count of it yet: looked at again at its next ask
            # its made words owed while the store (or the ledger's marks) can't be read: read again next round
            cards = None if (made is None or listed is None) and item_id in made_owed else asks[item_id][2]
            self._looked[item_id] = tuple(asks[item_id][:2]) + (cards,)
        # rows: the ones gone, the ones new
        for key in [k for k in self._rows if k not in rows]:
            del self._rows[key]
            self._out.pop(key, None)
            for i in key:
                held = self._rows_of.get(i)
                if held is not None:
                    held.discard(key)
                    if not held:
                        del self._rows_of[i]
        for key in rows:
            if key not in self._rows:
                for i in key:
                    self._rows_of.setdefault(i, set()).add(key)
                full_rows.add(key)
        for i in full:
            full_rows |= self._rows_of.get(i, set())
        # the cards that came or went: one step each through the index (never a full recount)
        out = self._out
        for w, d in flips.items():
            if not d:
                continue
            touched = set()
            for i in self._inv.get(w, ()):
                if i not in full and w not in self._made.get(i, ()):
                    out[i] = out.get(i, 0) + d
                touched |= self._rows_of.get(i, set())
            for key in touched - full_rows:
                if w not in self._rows.get(key, ()):
                    out[key] = out.get(key, 0) + d
        on = self._ref
        for i in full:
            words = self._files.get(i)
            if words is None:                                  # made words, no count of its file: no answer
                out.pop(i, None)
                continue
            mine = self._made.get(i, frozenset())
            out[i] = sum(1 for w in words if w in on and w not in mine)
        for key in full_rows:
            if key not in rows:
                continue
            window_idle.pause()
            have = [self._files[i] for i in key if i in self._files]
            mine = frozenset().union(*(self._made.get(i, frozenset()) for i in key))
            self._rows[key] = mine
            if not have:
                out.pop(key, None)
                continue
            words = set().union(*have)
            out[key] = sum(1 for w in words if w in on and w not in mine)
        if asks or self._counted:
            self._counted = True
            self._hand()
        if self._failed:
            self._again_later()

    def _again_later(self):
        """(Review H-F4) The token store couldn't be read this round: one more round `RETRY_S` later — never waiting for
        the next ask, which may not come this session."""
        with self._lock:
            if self._closed or (self._retry is not None and self._retry.is_alive()):
                return
            self._retry = threading.Timer(RETRY_S, self._again)
            self._retry.daemon = True
            self._retry.start()

    def _again(self):
        with self._lock:
            self._owed = True
        self._kick()

    def _drop(self, item_id, ref):
        """An item no longer asked: its file, its made words and its answer let go -> the rows holding it."""
        self._looked.pop(item_id, None)
        self._out.pop(item_id, None)
        self._level.pop(item_id, None)
        self._unindex(item_id, self._files.pop(item_id, None))
        for w in self._made.pop(item_id, frozenset()):
            ref(w, -1)
        return set(self._rows_of.get(item_id, ()))

    def _unindex(self, item_id, words):
        """A file's words out of the index (a file let go or read again: rare beside the index's reads)."""
        inv = self._inv
        for w in words or ():
            held = inv.get(w)
            if held is not None:
                try:
                    held.remove(item_id)
                except ValueError:
                    continue
                if not held:
                    del inv[w]

    def _file_words(self, rel):
        """The ints of a file's words (its lemmas, each once), from the token store's counts; None when the store
        holds no count of it (not read yet) or can't be read."""
        if not rel:
            return None
        store = self._token_store()
        if store is None:
            return None                                # (no token store yet: nothing to retry until one is built)
        from app import token_index
        path = os.path.join(self._data(), *str(rel).split("/"))
        try:
            row = store.conn.execute("SELECT counts FROM files WHERE path=?", (token_index._norm(path),)).fetchone()
        except Exception:
            self._failed = True                        # busy, locked: opened afresh and tried again later
            self._tokens = None
            try:
                store.close()
            except Exception:
                pass
            return None
        if row is None or not row[0]:
            return None
        self.read_files += 1
        ids, out = self._ids, []
        for lemma in {k.partition("|")[0] for k in token_index._decode_counts(row[0])}:   # each lemma once
            n = ids.get(lemma)
            if n is None:
                n = ids[lemma] = len(ids)
            out.append(n)
        out.sort()
        return array("i", out)

    def _data(self):
        if self._data_dir is None:
            from app import path_utils
            self._data_dir = path_utils.get_data_path(self.language)
        return self._data_dir

    def _token_store(self):
        if self._closed:
            return None
        if self._tokens is None:
            try:
                if self._open_tokens is not None:
                    self._tokens = self._open_tokens()
                else:
                    from app import token_index
                    self._tokens = token_index.open_reader(self.language)
            except Exception:
                self._tokens = None
        return self._tokens

    def _answers(self):
        """The answers handed on: each count, and each split (lean A) — a row's the sum of its files', only while every
        file of it says one."""
        out = dict(self._out)
        level = self._level
        for i, v in level.items():
            out[("level", i)] = v
        for key in self._rows:
            parts = [level.get(i) for i in key]
            if all(p is not None for p in parts):
                out[("level", key)] = (sum(p[0] for p in parts), sum(p[1] for p in parts))
        return out

    def _hand(self):
        answers = self._answers()
        with self._lock:
            if answers == self._handed:
                return
            self._handed = answers
            out = dict(answers)
        self._save()
        if self.on_change is not None and not self._closed:
            try:
                self.on_change(out)
            except Exception as e:
                print(f"Card chip: the answers couldn't be handed on ({e!r})")

    # --- on disk ---------------------------------------------------------------------------------------------- #
    def _path(self):
        if self._cache_file is None:
            try:
                self._cache_file = cache_path(self.language)
            except Exception:
                return None
        return self._cache_file

    def _read_cache(self):
        path = self._path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                got = json.load(f)
        except (OSError, ValueError, TypeError, UnicodeDecodeError):
            return {}
        return got if isinstance(got, dict) and got.get("v") == CACHE_VERSION else {}

    def _save(self, studied_moved=False, now=False):
        """The studied words and the answers on disk: at once when the studied words moved (or `now`), else at most
        every `SAVE_S` (a burst of Connect batches writes once)."""
        t = self._clock()
        if not studied_moved and not now:
            if self._dirty_at is None:
                self._dirty_at = t
            if t - self._dirty_at < SAVE_S:
                return
        path = self._path()
        if path is None:
            return
        with self._lock:
            handed = dict(self._handed)
        record = {"v": CACHE_VERSION,
                  "studied": sorted(self._studied_words or ()),
                  "studied_said": [list(pair) for pair in sorted(self._studied_said)],
                  "reads": [[w, s, self._reads[(w, s)]] for w, s in sorted(self._studied_said | self._backlog_said)
                            if (w, s) in self._reads],
                  "items": {str(k): n for k, n in handed.items() if not isinstance(k, tuple)},
                  "rows": {",".join(map(str, k)): n for k, n in handed.items()
                           if isinstance(k, tuple) and k[:1] != ("level",)},
                  "levels": {(str(k[1]) if not isinstance(k[1], tuple) else ",".join(map(str, k[1]))): list(n)
                             for k, n in handed.items() if isinstance(k, tuple) and k[:1] == ("level",)}}
        tmp = f"{path}.tmp"
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
            self._dirty_at = None
        except OSError as e:
            print(f"Card chip: the last count couldn't be saved ({e!r})")

    def _shut(self):
        if self._dirty_at is not None:
            self._save(now=True)
        store, self._tokens = self._tokens, None
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
