"""The learner's own dictionaries, read for the journey (v3, SPEC §5.1 *Yours*, §5.2): Anki Miner's indexed
dictionaries (`~/.anki_miner/dicts/<id>/index.sqlite`) in the learner's chain order (`gui_config.json`'s
`dictionary_chain`, its enabled entries), the first hit a word's — as Anki Miner's MainDefinition takes it — and the
learner's own Kanjium pitch copy (`~/.anki_miner/pitch/kanjium-pitch/source.txt`), which fills the words unidic
doesn't know.

- **Read-only, always.** Each index is opened `mode=ro` (Charter S2) with `query_only`; nothing here writes into
  Anki Miner's folder.
- **A private format** (its `schema_version` 6: `entries(term, reading, content, score, sequence)`, `content` HTML).
  Any read that fails — no folder, another schema, a locked or damaged file — is no hit, quietly: the page falls back
  to English. Never raises.
- **The text never leaves the PC.** It goes into the learner's own page only, as plain text (never HTML: the page sets
  it as text, so a dictionary's markup never runs beside the door's token); Send report never carries it (SPEC §4).
- **Memoised** for the process by the chain and each dictionary's file stamp (`stamp`): a second render in one process
  looks up only words it hasn't seen.
"""
import html.parser
import json
import os
import pathlib
import sqlite3

TEXT_MAX = 1200                 # characters a definition keeps on the page
ROWS_MAX = 6                    # an entry's rows (its senses) read at most
REDIRECT = "⟶"                  # Anki Miner's redirect row: a negative sequence whose content holds the arrow
_BREAKS = frozenset(("br", "div", "li", "p", "tr", "ol", "ul", "dd", "dt"))


def home():
    """Anki Miner's folder, as Connect finds it (`app/connect/anki_miner.home`: ANKI_MINER_HOME, else ~/.anki_miner)."""
    from app.connect.anki_miner import home as anki_miner_home
    return anki_miner_home()


def chain(root=None):
    """[(dict_id, index path)] of the enabled dictionaries, in the learner's order; [] without Anki Miner."""
    root = root or home()
    try:
        with open(os.path.join(root, "gui_config.json"), encoding="utf-8") as handle:
            entries = json.load(handle).get("dictionary_chain") or []
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("enabled", True):
            continue
        dict_id = entry.get("dict_id")
        if isinstance(dict_id, str) and dict_id and os.sep not in dict_id and "/" not in dict_id and dict_id != "..":
            path = os.path.join(root, "dicts", dict_id, "index.sqlite")
            if os.path.isfile(path):
                out.append((dict_id, path))
    return out


def stamp(links):
    """The memo key: each dictionary's id, file time and size, in chain order."""
    out = []
    for dict_id, path in links:
        try:
            st = os.stat(path)
            out.append((dict_id, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((dict_id, None, None))
    return tuple(out)


class _Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in _BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _BREAKS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def to_text(content):
    """A stored definition (HTML, or a Yomitan JSON list of strings) -> plain text, its line breaks kept."""
    if not isinstance(content, str):
        return ""
    stripped = content.strip()
    if stripped.startswith("["):
        try:
            items = json.loads(stripped)
            if isinstance(items, list) and all(isinstance(i, str) for i in items):
                return "\n".join(i.strip() for i in items if i.strip())
        except ValueError:
            pass
    parser = _Text()
    try:
        parser.feed(content)
        parser.close()
    except Exception:
        return ""
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    return "\n".join(line for line in lines if line)


_TO_HIRA = {c: c - 0x60 for c in range(ord("ァ"), ord("ヶ") + 1)}


def _hira(text):
    return (text or "").translate(_TO_HIRA)


def _title(conn, dict_id):
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'source_name'").fetchone()
        return row[0] if row and row[0] else dict_id
    except sqlite3.Error:
        return dict_id


def _open(path):
    conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=0.5)
    conn.execute("PRAGMA query_only=1")
    return conn


def _entry(conn, word, reading):
    """The definition of `word` in one dictionary: the rows of its best entry (its term, the reading first, then
    Anki Miner's score and sequence), a redirect row followed one hop; "" when it has none."""
    rows = conn.execute("SELECT content, sequence, reading FROM entries WHERE term = ? "
                        "ORDER BY (reading = ?) DESC, score DESC, sequence, id LIMIT ?",
                        (word, reading, ROWS_MAX)).fetchall()
    if not rows:
        return ""
    first = rows[0]
    if first[1] is not None and first[1] < 0 and REDIRECT in (first[0] or ""):
        rows = conn.execute("SELECT content, sequence, reading FROM entries WHERE sequence = ? "
                            "ORDER BY score DESC, id LIMIT ?", (-first[1], ROWS_MAX)).fetchall()
        if not rows:
            return ""
        first = rows[0]
    kept = [r[0] for r in rows if r[1] == first[1] and r[2] == first[2]]
    text = "\n".join(t for t in (to_text(c) for c in kept) if t)
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX].rstrip() + "…"


_MEMO = {}                      # {(root, stamp): {(word, reading): (title, text) | None}}


def lookup(words, root=None):
    """{(word, reading): (dictionary title, text)} for each (word, reading) a dictionary of the chain holds — the first
    in chain order (MainDefinition's first hit). Words no dictionary holds are left out; without Anki Miner, {}."""
    links = chain(root)
    if not links:
        return {}
    memo = _MEMO.setdefault((root or home(), stamp(links)), {})
    wanted = [w for w in dict.fromkeys(words) if w not in memo]
    open_ = {}
    try:
        for word, reading in wanted:
            found = None
            for dict_id, path in links:
                conn = open_.get(dict_id)
                if conn is None:
                    try:
                        conn = open_[dict_id] = _open(path)
                    except sqlite3.Error:
                        open_[dict_id] = False
                        continue
                if conn is False:
                    continue
                try:
                    text = _entry(conn, word, _hira(reading))
                except sqlite3.Error:
                    continue
                if text:
                    found = (_title(conn, dict_id), text)
                    break
            memo[(word, reading)] = found
    finally:
        for conn in open_.values():
            if conn:
                conn.close()
    return {key: memo[key] for key in dict.fromkeys(words) if memo.get(key)}


def kanjium_path(root=None):
    """The learner's own Kanjium copy (Anki Miner's `pitch` download), or None when there is none."""
    path = os.path.join(root or home(), "pitch", "kanjium-pitch", "source.txt")
    return path if os.path.isfile(path) else None


def kanjium(root=None, words=None):
    """The learner's own Kanjium copy -> {word: {hiragana reading: "0,2"}} ({} without one), only for `words` when
    given (a page asks for the words unidic doesn't know). Read as it is (`word \\t reading \\t positions`), never
    written."""
    path = kanjium_path(root)
    if path is None:
        return {}
    out = {}
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                word, _tab, rest = line.partition("\t")
                if not word or (words is not None and word not in words):
                    continue
                parts = rest.rstrip("\r\n").split("\t")
                if len(parts) >= 2 and parts[1]:
                    out.setdefault(word, {}).setdefault(_hira(parts[0] or word), parts[1].strip())
    except OSError:
        return {}
    return out
