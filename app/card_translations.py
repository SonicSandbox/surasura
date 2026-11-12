"""Card translations through Piyo (Piyo-TR, 2026-11-12; Sonic: card translations come from the learner's own AI over
Piyo's MCP, no key and no call from Surasura — 2026-11-05; "we have access to the sentences before and after because we
know the content. Is that worth it?" — measured: TheForge `tracks/pipeline/work/piyo-translate-eval-2026-11-12.md`).

    cards(...)  ->  the learner's AI translates  ->  write(...)        (and its one undo(...))

- **Which cards** (`cards`, read only): notes whose translation field is empty and whose sentence field isn't, the
  cards Surasura made (Connect's tag) first, then the newest. The translation field (`translation_field`) is the
  note type's `SentenceTranslation` / `Translation`, else — on the Lapis family (it has `Sentence`, `SentenceAudio`
  and `Hint`) — `Hint`, the field our card layout's 翻訳 toggle shows (`Anki_Card_Layout_Spec.md` row 4R); and only a
  field no FRONT template shows (stock Lapis shows its Hint on the front: a translation there would give every
  review away — review r1 B1); a note type with none is never offered. A note's sentence must be in the language's
  script (Japanese: kana in it; Chinese: Han, no kana) — asked of Anki's own search (`re:`) — and at most
  `SENTENCE_MOST` characters.
- **The lines around it** (`context`): for a card Connect made, the source it was cut from — the ledger's outcome
  (its job's item, its line's time and text) → the library's file → its neighbouring lines (a subtitle's counted cues,
  a book's or a text's sentences), `around` on each side, each cut to `LINE_MAX` characters; any other card gets its
  sentence alone. Read only: the ledger and the library store opened `mode=ro`.
- **The write** (`write`): each translation checked (`check`: one `<b>…</b>`, the bold the meaning and not the card's
  own language, no other markup, not empty, a sane length — Mattias's check in anki-sentence-translate, MIT,
  https://github.com/mattias/anki-sentence-translate), its text escaped, then ONE call of the one field writer
  (`connect/sentence_audio.fill`, `texts`: only an empty field, read again under Anki's write lock, tagged `TAG`, one
  Undo record in Connect's ledger) -> what was written, and each card refused with its why. `undo(id)` takes a batch
  back (only where the field still holds what was written).

Light: the standard library (+ the cue reader and the analyzer's text reader for a card's neighbours); Anki through
the adapters handed in (`AnkiReads`, `sentence_audio.AnkiConnectNotes`; tests hand fakes).
"""
import html
import os
import pathlib
import re
import sqlite3
import unicodedata

TAG = "surasura::translated"
BY = "piyo-translate"
VERB = "Adding translations"
NAMED = ("SentenceTranslation", "Sentence Translation", "Translation")   # a translation field by its name
HINT = "Hint"                                   # Lapis: the 翻訳 toggle — only on a note type of the Lapis family
LAPIS = ("Sentence", "SentenceAudio", HINT)     # the fields that say a note type is of it
SENTENCE = ("Sentence",)
WORD = ("Expression", "Word", "Vocab")
CONNECT_TAG = "surasura::connect::*"           # every card Connect made (ledger.tag_id)
LIMIT, MOST = 10, 50                            # cards a call: by default, at most
AROUND, AROUND_MOST = 1, 2                      # lines on each side: by default (the eval's verdict), at most
NEAR_S = 3                                      # a subtitle's line found by its text: within this of the card's time
LINE_MAX = 60                                   # characters a neighbouring line keeps (the nearer end)
SCAN = 500                                      # notes looked at in one `cards` call, at most
SENTENCE_MOST, WORD_MOST = 400, 40              # a card offered: its sentence at most (else skipped), its word cut to
SCRIPT = {"ja": ("[ぁ-ゖァ-ヺ]", None), "zh": ("[一-鿿]", "[ぁ-ゖァ-ヺ]")}   # Anki's search: (must match, must not)
TEXT_MOST, PER_CHAR = 400, 3                    # a translation's characters, at most: 400, or 3 a sentence's character
#                                                 (the eval: a 237-character book sentence took 405–591 in English)
CJK_INTO = ("ja", "zh", "ko", "yue")            # a translation INTO one of these keeps CJK in its bold
_TAG = re.compile(r"<[^>]*>")
_RUBY = re.compile(r"<(rt|rp)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_BRACKETS = re.compile(r"\[[ぁ-ゖァ-ヺー]+\]")                     # Anki's 彼[かれ] furigana
_BOLD = re.compile(r"<b\s*>(.*?)</b\s*>", re.I | re.S)
_KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_CJK = re.compile(r"[ぁ-ゖァ-ヺ㐀-䶿一-鿿豈-﫿가-힯]")
_ENDS = re.compile(r"(?<=[。！？!?…])(?![」』）)〉》”’。！？!?…])|(?<=[」』])(?=[^。！？!?、，,」』）)]|$)|\n+")

# How the learner's AI translates (the tools' words; the eval's translators were handed exactly these)
HOW = ("Translate each card's sentence into natural, everyday English (or the learner's own language, if they said "
       "another) as one line about as long as the original. Put the card's word, as its meaning in the translation, "
       "in <b>…</b> exactly once — never the Japanese or Chinese word itself. `before` and `after` are the lines said "
       "just before and after it: use them only to tell who or what the sentence is about (the subject, pronouns, "
       "names, who is speaking, the tone), and never translate them. Names stay names (in the Latin alphabet). Keep "
       "the sentence's own quotation marks; add no notes and no other markup.")

# Why a translation is refused (`check`) or a card isn't written — each said to the learner's AI, which asks again
EMPTY = "it's empty"
ONE_BOLD = "it needs the card's word in bold exactly once: one <b>…</b>"
BOLD_EMPTY = "its <b></b> is empty"
BOLD_CJK = "its bold is still in the card's language: bold the word's meaning in the translation"
NOT_TRANSLATED = "it isn't translated: it still has the card's language in it"
MARKUP = "only <b>…</b> may be in it, no other markup (no [sound:…], no {{…}})"
TOO_LONG = "it's too long for this card (at most {most} characters)"
NO_FIELD = "its note type has no translation field (one the card's back shows)"
NOT_OFFERED = "it isn't one of the cards to translate (surasura_cards_to_translate lists them)"
_MEDIA = re.compile(r"\[sound:|\{\{", re.I)


class AnkiReads:
    """The read-only AnkiConnect reads `cards` needs, at `url` (loopback, `anki_connect`)."""

    def __init__(self, url):
        self.url = url

    def _invoke(self, action, **params):
        from app import anki_connect
        return anki_connect.invoke(action, self.url, timeout=15, **params)

    def note_types(self):
        return [str(m) for m in self._invoke("modelNames") or ()]

    def fields(self, note_type):
        return [str(f) for f in self._invoke("modelFieldNames", modelName=note_type) or ()]

    def templates(self, note_type):
        """{card type: {"Front": html, "Back": html}}."""
        got = self._invoke("modelTemplates", modelName=note_type) or {}
        return got if isinstance(got, dict) else {}

    def find(self, query):
        return [int(n) for n in self._invoke("findNotes", query=query) or ()]

    def notes(self, ids):
        from app import anki_connect
        return anki_connect.notes_info(self.url, ids)


def plain(value):
    """A field's text as read: furigana (ruby, Anki's brackets) and markup out, entities read."""
    text = _BRACKETS.sub("", _TAG.sub("", _RUBY.sub("", str(value or ""))))
    return html.unescape(text).replace("\xa0", " ").strip()


def _key(text):
    """A line as matched against another: plain, NFKC, no spaces."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", plain(text)))


def _by_name(names, wanted):
    lower = {n.lower(): n for n in names}
    return next((lower[w.lower()] for w in wanted if w.lower() in lower), None)


def _shows(field, templates, side, sections=True):
    """True when any card type's `side` template names `field` ({{Hint}}, {{text:Hint}}, {{tts ja_JP voices=X:Hint}}
    … and, with `sections`, {{#Hint}} / {{^Hint}}); outside an HTML comment unless `sections` (a front fails closed)."""
    ref = re.compile(r"\{\{\s*" + ("[#^/]?" if sections else "") + r"\s*(?:[^{}:#^/][^{}:]*:\s*)*" + re.escape(field)
                     + r"\s*\}\}", re.I)
    texts = (str((sides or {}).get(side) or "") for sides in (templates or {}).values())
    return any(ref.search(t if sections else re.sub(r"<!--.*?-->", "", t, flags=re.S)) for t in texts)


def on_front(field, templates):
    """True when any card type's front template shows `field`: a translation there gives every review away."""
    return _shows(field, templates, "Front")


def translation_field(field_names, templates=None):
    """The field a note type's translation goes in, or None (module docstring): by name, else Hint on the Lapis
    family — the first no front template shows and a back does (`templates`: the note type's, None = not looked
    at)."""
    named = [_by_name(field_names, (n,)) for n in NAMED]
    if all(_by_name(field_names, (f,)) for f in LAPIS):
        named.append(_by_name(field_names, (HINT,)))
    if templates is not None and not templates:
        return None                             # its templates unread: never guessed (r2 #5)
    return next((f for f in named if f and (templates is None or (not on_front(f, templates)
                                                                  and _shows(f, templates, "Back", False)))), None)


def in_language(sentence, language):
    """True when `sentence` (plain) is in the language's script."""
    if language == "zh":
        return bool(_HAN.search(sentence)) and not _KANA.search(sentence)
    return bool(_KANA.search(sentence))


def _quote(term):
    from app import anki_connect
    return '"' + anki_connect.escape_query(term) + '"'


def _named(kind, name):
    """A `note:` / `deck:` term naming exactly `name` (its _ and * read as themselves, not wildcards: r2 #6)."""
    from app import anki_connect
    return '"' + kind + ":" + anki_connect.escape_query(name).replace("_", "\\_").replace("*", "\\*") + '"'


def _type(anki, model):
    """(translation field, sentence field, word field or None) of a note type a translation fits, else None."""
    names = anki.fields(model)
    sf = _by_name(names, SENTENCE)
    if not sf or not translation_field(names):
        return None
    tf = translation_field(names, anki.templates(model))
    return (tf, sf, _by_name(names, WORD)) if tf and tf != sf else None


def _types(anki):
    """{note type: (translation field, sentence field, word field or None)} for every note type a translation fits."""
    out = {}
    for model in anki.note_types():
        got = _type(anki, model)
        if got:
            out[model] = got
    return out


def _query(model, tf, sf, deck=None, language="ja", extra=""):
    query = f"{_named('note', model)} {_quote(tf + ':')} {_quote(sf + ':_*')}"
    must, never = SCRIPT.get(language, SCRIPT["ja"])
    query += " " + _quote(f"{sf}:re:{must}") + (" -" + _quote(f"{sf}:re:{never}") if never else "")
    if deck:
        query += " " + _named("deck", deck)
    return query + (" " + extra if extra else "")


def wanting(anki, deck=None, language="ja"):
    """(the ids of every note wanting a translation — Connect's first, then the newest —, {note type: fields})."""
    types, made, rest = _types(anki), [], []
    for model, (tf, sf, _w) in types.items():
        ids = anki.find(_query(model, tf, sf, deck, language))
        ours = set(anki.find(_query(model, tf, sf, deck, language, _quote("tag:" + CONNECT_TAG)))) if ids else set()
        made += [n for n in ids if n in ours]
        rest += [n for n in ids if n not in ours]
    return sorted(set(made), reverse=True) + sorted(set(rest) - set(made), reverse=True), types


def count(anki, deck=None, language="ja"):
    """How many notes want a translation (Backfill's line)."""
    return len(wanting(anki, deck, language)[0])


def _value(note, field):
    got = (note.get("fields") or {}).get(field)
    return got.get("value") if isinstance(got, dict) else got


def _word(sentence_value, note, word_field):
    """The card's word as its sentence writes it (its bold), else its word field."""
    bold = _BOLD.search(str(sentence_value or ""))
    if bold and plain(bold.group(1)):
        return plain(bold.group(1))
    return plain(_value(note, word_field)) if word_field else ""


def cards(anki, language="ja", deck=None, limit=LIMIT, around=AROUND, only=None, sources=None, skip=()):
    """The next `limit` cards wanting a translation -> {"cards": [{id, sentence, word, before?, after?}], "left"}.
    `around`: neighbouring lines on each side for a card Connect made (0: none); `only`: these note ids alone (a
    title's cards); `skip`: note ids left out (the ones this session's answers kept failing, r2 #3); `sources`:
    (ledger path, data folder) for the neighbours, None = this install's."""
    limit = max(1, min(int(limit or LIMIT), MOST))
    around = max(0, min(int(around if around is not None else AROUND), AROUND_MOST))
    ids, types = wanting(anki, deck, language)
    if only is not None:
        keep = {int(n) for n in only}
        ids = [n for n in ids if n in keep]
    held = 0
    if skip:
        skip = set(skip)
        held = sum(1 for n in ids if n in skip)
        ids = [n for n in ids if n not in skip]
    out, looked = [], 0
    for at in range(0, min(len(ids), SCAN), MOST):
        part = ids[at:at + MOST]
        looked = at + len(part)
        for note in anki.notes(part) or ():
            if not isinstance(note, dict) or note.get("modelName") not in types:
                continue
            tf, sf, wf = types[note["modelName"]]
            sentence = plain(_value(note, sf))
            if (_value(note, tf) != "" or not sentence or len(sentence) > SENTENCE_MOST
                    or not in_language(sentence, language)):
                continue
            out.append({"id": int(note["noteId"]), "sentence": sentence,
                        "word": _word(_value(note, sf), note, wf)[:WORD_MOST]})
            if len(out) >= limit:
                break
        if len(out) >= limit:
            looked = at + next(i for i, n in enumerate(part) if n == out[-1]["id"]) + 1
            break
    if around and out:
        lines = context([c["id"] for c in out], language, around, *(sources or (None, None)))
        for c in out:
            got = lines.get(c["id"])
            if got:
                c.update({k: v for k, v in zip(("before", "after"), got) if v})
    got = {"cards": out, "left": max(0, len(ids) - looked)}
    if held:
        got["held"] = held
    return got


# --- the lines around a card's sentence ------------------------------------------------------------------------- #
def _outcomes(ledger_path, ids, language="ja"):
    """{note id: (item id, line start s, sentence)} from Connect's ledger (this language's jobs: item ids are the
    language's store's), read only; {} when there's none."""
    if not ledger_path or not os.path.isfile(ledger_path) or not ids:
        return {}
    conn = sqlite3.connect(pathlib.Path(ledger_path).as_uri() + "?mode=ro", uri=True, timeout=2.0,
                           isolation_level=None)
    try:
        conn.execute("PRAGMA query_only=1")
        ids, out = sorted(set(ids)), {}
        for at in range(0, len(ids), 500):
            part = ids[at:at + 500]
            for note, item, start, sentence in conn.execute(
                    "SELECT o.note_id, j.item_id, o.line_start, o.sentence FROM outcomes o JOIN jobs j "
                    "ON j.id = o.job_id WHERE o.outcome = 'made' AND j.language = ? AND o.note_id IN "
                    f"({','.join('?' * len(part))})", [language] + part):
                out[int(note)] = (item, start, sentence)
        return out
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _files(language, data_dir, items):
    """{item id: its file in the library}, read only; {} when the store can't be read."""
    from app import library_store
    db = library_store.library_db_path(language, data_dir)
    if not items or not os.path.isfile(db):
        return {}
    conn = sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True, timeout=2.0, isolation_level=None)
    try:
        conn.execute("PRAGMA query_only=1")
        items = sorted(set(items))
        rows = conn.execute(f"SELECT id, rel_path FROM items WHERE id IN ({','.join('?' * len(items))})", items)
        return {i: os.path.join(data_dir, *str(rel).replace("\\", "/").split("/")) for i, rel in rows if rel}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def lines_of(path, language):
    """A source's lines as a card's neighbours are counted: a subtitle's counted cues [(start ms, text)]; a book's or
    a text's sentences [(None, text)] (as a Generate reads the file, cut after 。！？ and at line breaks)."""
    from app import cues
    if str(path).lower().endswith(cues.SUBTITLES):
        return [(c.start, c.text) for c in cues.read(path, language) if c.counted and c.text.strip()]
    from app import analyzer
    text = analyzer.extract_text(str(path), language) or ""
    return [(None, s.strip()) for s in _ENDS.split(text) if s and s.strip()]


def _index(lines):
    """A source's lines made ready to be searched once a file (review r1 N9): (keys, their start in `joined`, joined)."""
    keys = [_key(t) for _s, t in lines]
    starts, at = [], 0
    for k in keys:
        starts.append(at)
        at += len(k)
    return keys, starts, "".join(keys)


def _place(lines, start, sentence, index=None):
    """(first, last) index of the lines holding `sentence`, or None (its sentence goes alone, never a guess): by its
    text — a subtitle's place nearest its line's start (a short line said twice); a book's (no times) only where the
    text starts and ends on its lines' bounds and only one such place (review r1 S7: はい。 twice, はい inside これはいけ
    ない) —, else the lines its text is made of, else its line's start alone."""
    import bisect
    timed = any(s is not None for s, _t in lines)               # a book's cards are recorded at 0.0 (r2 #1)
    ms = float(start) * 1000 if start is not None and timed else None
    far = lambda i: abs(lines[i][0] - ms) if lines[i][0] is not None else 0     # noqa: E731

    def span(first, last):
        """How far the card's time is from the lines first..last: 0 inside them (its anchor may be any of them, r3 B1)."""
        lo, hi = lines[first][0], lines[last][0]
        if lo is not None and hi is not None and lo <= ms <= hi:
            return 0
        return min(far(first), far(last))

    def close(first, last):                     # a subtitle's match: by its time too (r2 #2)
        return ms is None or span(first, last) <= NEAR_S * 1000
    keys, starts, joined = index or _index(lines)
    want = _key(sentence)
    if want:
        places, found = [], -1
        while True:
            found = joined.find(want, found + 1)
            if found < 0:
                break
            first = bisect.bisect_right(starts, found) - 1
            last = bisect.bisect_right(starts, found + len(want) - 1) - 1
            bounds = found == starts[first] and found + len(want) == starts[last] + len(keys[last])
            places.append((first, last, bounds))
        if ms is not None and places:
            first, last, _b = min(places, key=lambda p: span(p[0], p[1]))
            if close(first, last):
                return first, last
        bound = [(f, l) for f, l, b in places if b]
        if ms is None and places:
            return bound[0] if len(bound) == 1 else None
        hits = [i for i, k in enumerate(keys) if len(k) >= 4 and k in want]
        if (hits and hits[-1] - hits[0] <= 3 and hits == list(range(hits[0], hits[-1] + 1))     # one run of lines
                and close(hits[0], hits[-1])):
            return hits[0], hits[-1]
    if ms is not None:
        at = [i for i, (s, _t) in enumerate(lines) if s is not None and abs(s - ms) <= 50]
        if at:
            return at[0], at[0]
    return None


def _cut(text, keep_end):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= LINE_MAX:
        return text
    return "…" + text[-(LINE_MAX - 1):] if keep_end else text[:LINE_MAX - 1] + "…"


def context(ids, language="ja", around=AROUND, ledger_path=None, data_dir=None):
    """{note id: ([lines before], [lines after])} for the cards Connect made of `ids`; the rest are left out."""
    if around <= 0:
        return {}
    if ledger_path is None:
        from app.connect import ledger
        ledger_path = ledger.path()
    if data_dir is None:
        from app.path_utils import get_data_path
        data_dir = get_data_path(language)
    made = _outcomes(ledger_path, ids, language)
    files = _files(language, data_dir, {item for item, _s, _t in made.values()})
    read, out = {}, {}
    for note, (item, start, sentence) in made.items():
        path = files.get(item)
        if not path or not os.path.isfile(path):
            continue
        if path not in read:
            try:
                got = lines_of(path, language)
                read[path] = (got, _index(got))
            except Exception:                   # one odd file (an .ass with no Style column): its cards go alone (S5)
                read[path] = ([], None)
        lines, index = read[path]
        where = _place(lines, start, sentence, index) if lines else None
        if where is None:
            continue
        first, last = where
        out[note] = ([_cut(t, True) for _s, t in lines[max(0, first - around):first]],
                     [_cut(t, False) for _s, t in lines[last + 1:last + 1 + around]])
    return out


def source_notes(language, title, data_dir=None):
    """The note ids Surasura made from the shows or books whose title (or file) holds `title` (any case), read only
    from the library store's made words; [] when none or the store can't be read."""
    import json
    from app import library_store
    if data_dir is None:
        from app.path_utils import get_data_path
        data_dir = get_data_path(language)
    want = str(title or "").strip().casefold()
    db = library_store.library_db_path(language, data_dir)
    if not want or not os.path.isfile(db):
        return []
    conn = sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True, timeout=2.0, isolation_level=None)
    out = set()
    try:
        conn.execute("PRAGMA query_only=1")
        items = set()
        for item, rel, entry in conn.execute("SELECT id, rel_path, entry FROM items"):
            try:
                name = str((json.loads(entry) or {}).get("title") or "")
            except (ValueError, TypeError, AttributeError):
                name = ""
            if want in name.casefold() or want in str(rel or "").casefold():
                items.add(item)
        if items and conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'made_words'").fetchone():
            for item, notes in conn.execute("SELECT item_id, note_ids FROM made_words"):
                if item in items:
                    out.update(int(n) for n in library_store._json_list(notes) if str(n).lstrip("-").isdigit())
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return sorted(out)


# --- checking and writing ----------------------------------------------------------------------------------------- #
def check(text, language="ja", into="en", most=TEXT_MOST):
    """(the field's value, None) for a translation that passes, else (None, why) — after Mattias's check
    (anki-sentence-translate, MIT): one bold, the bold the meaning (not CJK when translating into a language that
    isn't), nothing but text and that bold, at most `most` characters; escaped for Anki's field."""
    text = re.sub(r"\s*[\r\n]+\s*", " ", html.unescape(str(text or "")).replace("\xa0", " ")).strip()   # one line
    if not text:
        return None, EMPTY
    if len(text) > most:
        return None, TOO_LONG.format(most=most)
    bolds = list(_BOLD.finditer(text))
    if len(bolds) != 1 or len(re.findall(r"<\s*/?\s*b\b", text, re.I)) != 2:
        return None, ONE_BOLD
    before, bold, after = text[:bolds[0].start()], bolds[0].group(1), text[bolds[0].end():]
    if _TAG.search(before + bold + after) or _MEDIA.search(text):     # [sound:…] would play; {{c1::…}} a cloze (N10)
        return None, MARKUP
    if not bold.strip():
        return None, BOLD_EMPTY
    cjk_into = str(into or "en").lower().split("-")[0] in CJK_INTO
    if not cjk_into:
        if _CJK.search(bold):
            return None, BOLD_CJK
        if (language == "ja" and _KANA.search(text)) or len(_CJK.findall(text)) * 2 > len(text.replace(" ", "")):
            return None, NOT_TRANSLATED
    esc = lambda s: html.escape(s, quote=False)       # noqa: E731
    return esc(before) + "<b>" + esc(bold.strip()) + "</b>" + esc(after), None


def write(anki_reads, anki, ledger, items, language="ja", into="en"):
    """`items` [{id, translation}] (at most MOST) -> {"undo": the batch's id or None, "written": [ids], "refused": {id:
    why}}. Each translation checked against its note (its sentence's length), then one `sentence_audio.fill` for the
    batch (only an empty field: read again there, under Anki's write lock). A note is written only by the rules a card
    is offered by (a fitting note type, a sentence in the language's script: review r1 S2 — an id the AI made up, or
    one a card's text talked it into, lands nowhere else)."""
    from app.connect import sentence_audio as sa
    given = {}
    for item in list(items or ())[:MOST]:
        try:
            given[int(item.get("id"))] = item.get("translation")
        except (TypeError, ValueError, AttributeError):
            continue
    refused, texts, fields, seen, types = {}, {}, {}, set(), {}
    for note in (anki_reads.notes(sorted(given)) if given else None) or ():
        if not isinstance(note, dict) or not note.get("noteId") or int(note["noteId"]) not in given:
            continue
        nid, model = int(note["noteId"]), note.get("modelName")
        seen.add(nid)
        if model not in types:
            types[model] = _type(anki_reads, model) if model else None
        if not types[model]:
            refused[nid] = NO_FIELD
            continue
        tf, sf, _wf = types[model]
        sentence = plain(_value(note, sf))
        if not sentence or len(sentence) > SENTENCE_MOST or not in_language(sentence, language):
            refused[nid] = NOT_OFFERED
            continue
        most = max(TEXT_MOST, PER_CHAR * len(sentence))
        value, why = check(given[nid], language, into, most)
        if why:
            refused[nid] = why
        else:
            texts[nid], fields[nid] = value, tf
    refused.update({n: sa.GONE for n in given if n not in seen})
    if not texts:
        return {"undo": None, "written": [], "refused": refused}
    got = sa.fill(anki, ledger, None, field=fields, tag=TAG, by=BY, texts=texts, verb=VERB)
    refused.update({int(n): why for n, why in got["skipped"].items()})
    return {"undo": got["id"], "written": got["filled"], "refused": refused}


def undo(anki, ledger, rid):
    """A translation batch's Undo -> sentence_audio.undo's answer; another path's record is never undone here."""
    from app.connect import sentence_audio as sa
    rec = sa.record(ledger, rid)
    if rec is None or rec.get("by") != BY:
        return {"emptied": [], "kept": {}, "deleted": [], "refused": "nothing to undo"}
    return sa.undo(anki, ledger, rid, verb=VERB)
