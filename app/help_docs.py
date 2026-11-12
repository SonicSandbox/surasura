"""Surasura's help, for Piyo's help tools (app/cli/mcp_server.py): the user docs that ship with Surasura as topics the
learner's AI reads one at a time. Qt-free, standard library only; nothing here goes online.

**What's in it** — only what a user already reads: the README, the guide (docs/Tutorial.md), the FAQ, *How Parsing
Works*, *How to Update*, the newest release notes and, in a built program, the window's own words: each Settings row's
label, one-line help and tooltip, and the help cards (`app/qt/help_words.py` gathers them at packaging time — nothing
outside the window imports it). Nothing else.

**Its shape** — a short list of topics (`topics_text`); a topic is a section, or a group that lists its own sections
(`topic_text`); `search` returns the few sections that best match a question, with where each sits.

**When it's made** — a built program carries the index made from the docs as it was packaged (`app/help_index.json`,
`package_app.py`'s `write_help`), so its answers are that version's; a source checkout makes it from its own docs the
first time it's asked for (the docs alone). Either way it is read once per process.
"""
import functools
import json
import math
import os
import re

FILE = os.path.join("app", "help_index.json")             # in a built program's _internal: the app's part (an update
#                                                         carries it with the program, so it is always this version's)
FORMAT = 1
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_SKIP = ("Q&A / FAQ", "Motivation", "Credits")       # a pointer to another page, or no help to anyone
NOTES_SKIP = ("Download",)
NOTES_KEPT = 3                                              # the newest release notes in the help
TEXT_MAX = 1000                                             # a search hit's text is cut here (its topic has it whole)
SEARCH_MAX = 5
MORE = "▸"
STOP = frozenset("a an and are as at be by can do does for from how i if in is it its me my of on or so that the "
                 "this to what when where which why will with you your surasura".split())


# --- making it -------------------------------------------------------------------------------------------------------- #
def build(root=ROOT, window=()):
    """The help index from the files under `root` (a checkout or the packaging's) and `window`, the window's own topics
    (groups in the same shape, `help_words.topics()`) -> {"format", "version", "topics"}: each topic {"title", "text"}
    or a group {"title", "text" (its opening lines), "topics": [{"title", "text", "under"}]}. Titles are unique: a
    second one gets its group's name after it."""
    from app import __version__
    topics = []
    topics += _sections(_read(root, "README.md"), skip=README_SKIP)
    topics.append(_group("The guide", _read(root, "docs", "Tutorial.md")))
    topics.append(_faq(_read(root, "docs", "Surasura FAQ.md")))
    topics.append(_group("How parsing works", _read(root, "docs", "How Parsing Works.md")))
    topics += [dict(t) for t in window]
    for version, text in _notes(root):
        topics.append(_group(f"What's new in {version}", text, skip=NOTES_SKIP))
    topics.append(_group("Updating Surasura", _read(root, "docs", "UPDATE_INSTRUCTIONS.md")))
    topics = [t for t in topics if t.get("text") or t.get("topics")]
    _unique(topics)
    return {"format": FORMAT, "version": __version__, "topics": topics}


def write(path, root=ROOT, window=()):
    """`build(root, window)` written to `path` (its folder made) -> the index."""
    index = build(root, window)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    return index


def _read(root, *parts):
    try:
        with open(os.path.join(root, *parts), "r", encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return ""


_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _split(md):
    """Markdown -> (opening lines, [(level, heading, lines)]), headings inside a code block left as text."""
    head, out, fenced = [], [], False
    for line in md.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        m = None if fenced else _HEADING.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2), []))
        elif out:
            out[-1][2].append(line)
        else:
            head.append(line)
    return head, out


_NUMBER = re.compile(r"^(?:\d+\s*[.·]\s*)")
_EMOJI = re.compile("[←-⯿☀-➿\U0001f000-\U0001faff️‍]")


def _title(heading):
    """A heading as a topic's title: its numbering, emoji and markup gone."""
    t = _plain(heading).replace("`", "")
    t = _EMOJI.sub("", t)
    return _NUMBER.sub("", t.strip()).strip(" ·—-")


def _sections(md, skip=()):
    """Each `##` section a topic (its `###` parts in its text)."""
    _head, parts = _split(md)
    out, current = [], None
    for level, heading, lines in parts:
        if level <= 1:
            current = None
            continue
        if level == 2:
            title = _title(heading)
            current = None if title in skip else {"title": title, "lines": list(lines)}
            if current is not None:
                out.append(current)
        elif current is not None:
            current["lines"] += ["", heading] + lines
    return [{"title": t["title"], "text": _plain("\n".join(t["lines"]))} for t in out if _plain("\n".join(t["lines"]))]


def _group(title, md, skip=()):
    """A document as a group: its opening lines its text; each `###` a topic (`under` its `##`), each `##` without
    any its own topic; a `##`'s lines before its first `###` a topic of their own."""
    head, parts = _split(md)
    topics, under, skipping = [], None, False
    for level, heading, lines in parts:
        if level <= 1:
            head += lines
            continue
        name = _title(heading)
        if level == 2:
            under, skipping = name, name in skip
            if not skipping:
                topics.append({"title": name, "text": _plain("\n".join(lines))})
        elif not skipping:
            topics.append({"title": name, "text": _plain("\n".join(lines)), "under": under})
    topics = [t for t in topics if t["text"]]
    return {"title": title, "text": _plain("\n".join(head)), "topics": topics}


_QUESTION = re.compile(r"^\*\*(.+\?)\*\*\s*$")


def _faq(md):
    """The FAQ: each question a topic, under its `###` heading."""
    head, parts = _split(md)
    topics = []
    for level, heading, lines in parts:
        if level <= 2:
            continue
        for line in lines:
            m = _QUESTION.match(line.strip())
            if m:
                topics.append({"title": _plain(m.group(1)), "lines": [], "under": _title(heading)})
            elif topics and topics[-1]["under"] == _title(heading):
                topics[-1]["lines"].append(line)
    topics = [{"title": t["title"], "text": _plain("\n".join(t["lines"])), "under": t["under"]} for t in topics]
    intro = _plain("\n".join(line for line in head if not line.startswith("#")))
    return {"title": "Questions", "text": intro, "topics": [t for t in topics if t["text"]]}


_NOTES = re.compile(r"^RELEASE_v(\d+(?:\.\d+)*)\.md$")


def _notes(root):
    """The newest NOTES_KEPT release notes -> [(version, text)], the newest first."""
    folder = os.path.join(root, "docs", "releases")
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = []
    for name in names:
        m = _NOTES.match(name)
        if m:
            found.append((tuple(int(p) for p in m.group(1).split(".")), m.group(1), name))
    found.sort(reverse=True)
    return [(version, _read(folder, name)) for _key, version, name in found[:NOTES_KEPT]]


def _unique(topics):
    seen = set()
    for group in topics:
        for t in [group] + list(group.get("topics") or ()):
            key = _key(t["title"])
            if key in seen and t is not group:
                t["title"] = f"{t['title']} ({group['title']})"
                key = _key(t["title"])
            seen.add(key)


_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)[^)]*\)")
_TAG = re.compile(r"<!--.*?-->|<[^>\n]+>", re.DOTALL)
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])")


def _plain(md):
    """Markdown as plain lines: no pictures, no HTML, a link its words (and its address when it's a web page), no bold."""
    text = _TAG.sub("", _IMAGE.sub("", md))
    text = _LINK.sub(lambda m: m.group(1) if not m.group(2).startswith("http") else f"{m.group(1)} ({m.group(2)})",
                     text)
    text = _ITALIC.sub(r"\1", text.replace("**", ""))
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line.strip() not in ("---", "***", "___")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# --- reading it ------------------------------------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=1)
def index():
    """The help index: the packaged one in a built program, else made from this checkout (once a process). Raises
    OSError when a built program has none."""
    from app import path_utils
    if path_utils.is_frozen():
        with open(path_utils.get_resource(FILE), "r", encoding="utf-8") as f:
            return json.load(f)
    return build()


def _key(title):
    return "".join(c for c in str(title).casefold() if c.isalnum())


def _leaves():
    """[(group title or None, topic)] for every section, in order."""
    out = []
    for t in index()["topics"]:
        if t.get("topics"):
            out += [(t["title"], s) for s in t["topics"]]
        else:
            out.append((None, t))
    return out


def topics_text():
    """The list of topics, one line each (a group: its title, ▸ and how many it holds)."""
    idx = index()
    lines = [f"Surasura {idx.get('version', '')} help topics. surasura_help(\"<topic>\") reads one; a topic marked "
             f"{MORE} lists its own. For a question in words, surasura_help_search(\"<question>\")."]
    for t in idx["topics"]:
        lines.append(f"{t['title']} {MORE} {len(t['topics'])}" if t.get("topics") else t["title"])
    return "\n".join(lines)


def find(topic):
    """The topic `topic` names -> (group title or None, the topic), or None. Its title, its group's › its title, or the
    same in any case or spacing."""
    want = _key(topic)
    if not want:
        return None
    for t in index()["topics"]:
        if _key(t["title"]) == want:
            return None, t
    for group, t in _leaves():                             # its title, its group › title, or the place a search names
        if want in (_key(t["title"]), _key(f"{group}{t['title']}") if group else None, _key(_where(group, t))):
            return group, t
    if len(want) >= 4:                                     # the start of a title, or a title's words in it
        for t in index()["topics"]:
            if want in _key(t["title"]):
                return None, t
        for group, t in _leaves():
            if want in _key(t["title"]):
                return group, t
    return None


def topic_text(topic):
    """One topic's words: a section whole, with where it sits; a group's opening lines and its topics, one a line.
    -> the text, or None (no such topic)."""
    found = find(topic)
    if found is None:
        return None
    group, t = found
    if t.get("topics"):
        lines = [t["title"]] + ([t["text"]] if t.get("text") else []) + [f"Its {len(t['topics'])} topics:"]
        lines += [s["title"] for s in t["topics"]]
        return "\n".join(lines)
    return f"{_where(group, t)}\n{t['text']}"


def _where(group, t):
    return " › ".join(p for p in (group, t.get("under"), t["title"]) if p)


# The search: BM25 over the sections, their title counted three times; English words lightly stemmed, Japanese and
# Chinese read as pairs of characters (no tokenizer: help is read before any is loaded).
_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ]+")


def _stem(w):
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def terms(text):
    t = str(text).casefold().replace("’", "'").replace("'s", "")
    out = [_stem(w) for w in _WORD.findall(t) if w not in STOP]
    for run in _CJK.findall(t):                            # each character and each pair (訳 finds 翻訳)
        out += list(run) + [run[i:i + 2] for i in range(len(run) - 1)]
    return out


@functools.lru_cache(maxsize=1)
def _search_table():
    docs = []
    for group, t in _leaves():
        words = terms(t["title"]) * 3 + terms(t.get("under") or "") + terms(t["text"])
        counts = {}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
        docs.append((group, t, counts, len(words)))
    df = {}
    for _g, _t, counts, _n in docs:
        for w in counts:
            df[w] = df.get(w, 0) + 1
    avg = sum(n for *_x, n in docs) / max(1, len(docs))
    return docs, df, avg


def search(query, limit=3):
    """The sections that best match `query` -> [(where, text)], the best first, at most `limit` (1-SEARCH_MAX)."""
    want = set(terms(query))
    if not want:
        return []
    docs, df, avg = _search_table()
    n = len(docs)
    scored = []
    for group, t, counts, length in docs:
        score = 0.0
        for w in want:
            f = counts.get(w)
            if f:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                score += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * length / avg))
        if score > 0:
            scored.append((score, group, t))
    scored.sort(key=lambda s: -s[0])
    limit = max(1, min(SEARCH_MAX, int(limit or 3)))
    return [(_where(g, t), t["text"]) for _s, g, t in scored[:limit]]


def search_text(query, limit=3):
    """`search` as the tool's words: each hit's place and text (cut at TEXT_MAX), or None when nothing matches."""
    hits = search(query, limit)
    if not hits:
        return None
    parts = []
    for where, text in hits:
        if len(text) > TEXT_MAX:
            text = text[:TEXT_MAX].rsplit("\n", 1)[0] + f"\n… (the rest: surasura_help(\"{where.split(' › ')[-1]}\"))"
        parts.append(f"## {where}\n{text}")
    return "\n\n".join(parts)
