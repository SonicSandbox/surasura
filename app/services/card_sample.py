"""*Which words get a card?* — the picture Essentials and its picker draw (Mado-EZC; TheForge 3.0
`tracks/window/work/ez/SPEC-r2.md` §0.3, EZ2-7 redone; every learner-visible word PROVISIONAL).

The setting is `connect_mine_words` (*Words to make cards from*): which of an episode's new words Connect sends to Anki
Miner. The picture shows up to four lines of the learner's top episode and, for each choice, what each word on them
gets: a card from this episode (amber when its card's lines hold another new word), no card because it isn't on the
list (rare), a card **from another episode** (only *Only i+1 sentences*, and only when another episode of the
mine line has a line where it is the only new word), or none.

**Counted by Connect's own picker, never again here:** `sample` runs `app.connect.pick.pick` itself — through
`arrivals.pick_cues`, with the warm view's known words, its learning rule, its tokenizer, the list and the cards the
last sync saved — once per choice on the top episode, and *Only i+1 sentences* on the other episodes of the
mine line. So a card's span (`pick.others()`: the line and the lines its expansion adds), one card per word (a word with
a card is never sent again) and the list are the picker's. `picture` only reads those answers.

With no top episode yet (no library, no list, Connect's mine line empty), or one without a line of each kind the
picture needs (a word alone on its line and a line holding a second new word), the bundled sample is drawn
(`FALLBACK`: the shipped 喫茶店の朝, four lines; Chinese: 孔乙己's), marked `sample` so the window names it a sample.

Pure apart from `sample` / `top` (they read the episode files and the library store, write nothing).
"""
import os

MODES = ("list", "unknown", "i1")
LINES = 4                    # the picture's lines at most
OUTCOMES = ("card", "amber", "rare", "other", "none")

# The bundled picture (SPEC-r2 §0.3's table): each line's text, its new words (word, on the list?), its new-word count.
# 香り is on the list (round 3's fix: a common word); モカブレンド is the one rarer than the Level.
FALLBACK = {
    "ja": {"source": "喫茶店の朝", "lines": (
        ("ええ、駅まで歩いてきたら、急に雨が降ってきて。", (("急に", True),), 1),
        ("何回も出てくる言葉だけ、あとで調べるんです。", (("出てくる", True), ("調べる", True)), 2),
        ("いい香り。いただきます。", (("香り", True),), 1),
        ("いつものモカブレンドをお願いします。", (("モカブレンド", False),), 1))},
    # 孔乙己 (鲁迅, shipped in samples/zh): PROVISIONAL, the same four kinds
    "zh": {"source": "孔乙己", "lines": (
        ("孔乙己是站着喝酒而穿长衫的唯一的人。", (("长衫", True),), 1),
        ("青白脸色，皱纹间时常夹些伤痕。", (("皱纹", True), ("伤痕", True)), 2),
        ("我从此便整天的站在柜台里。", (("柜台", True),), 1),
        ("温两碗酒，要一碟茴香豆。", (("茴香豆", False),), 1))},
}


_FALLBACKS = {}


def fallback(language):
    """The bundled picture (`_fallback`), made once per language and handed out as the same object: never change it."""
    key = language if language in FALLBACK else "ja"
    if key not in _FALLBACKS:
        _FALLBACKS[key] = _fallback(key)
    return _FALLBACKS[key]


def _fallback(language):
    """The bundled picture for `language` (Japanese for any other): the same shape as `picture`'s, `sample` True. Its
    *another episode* is only "up to" (`elsewhere_exact` False): no library was read."""
    data = FALLBACK.get(language) or FALLBACK["ja"]
    lines, counts = [], {mode: 0 for mode in MODES}
    away = 0
    for text, words, new in data["lines"]:
        drawn = []
        for word, listed in words:
            outcome = {"list": "rare" if not listed else ("amber" if new > 1 else "card"),
                       "unknown": "amber" if new > 1 else "card",
                       "i1": "other" if new > 1 else "card"}
            for mode in MODES:
                counts[mode] += outcome[mode] in ("card", "amber")
            away += outcome["i1"] == "other"
            drawn.append({"word": word, "reading": None, "surface": word, "listed": listed, "outcome": outcome})
        lines.append({"text": text, "new": new, "words": drawn})
    return {"source": data["source"], "sample": True, "lines": lines,
            "counts": {mode: {"here": counts[mode], "elsewhere": away if mode == "i1" else 0} for mode in MODES},
            "elsewhere_exact": False}


def _key(word):
    return (word.get("word"), word.get("reading"))


def picture(picks, elsewhere=(), source=""):
    """The picture of one episode from Connect's picker's answers: `picks` {mode: pick()'s "words"} for the episode
    (each mode's), `elsewhere` the keys ((word, reading)) another episode of the mine line would card from a line where
    it is the only new word (pick() in `i1` there). -> {"source", "sample": False, "lines": [{"text", "new", "words":
    [{"word", "reading", "surface", "listed", "outcome": {mode: one of OUTCOMES}}]}], "counts": {mode: {"here",
    "elsewhere"}}, "elsewhere_exact": True}, or None when the episode has no line of each kind the picture needs (a word alone on its
    line, and a line holding a second new word: the fallback is drawn instead).

    A word's outcome under a mode is that mode's answer: in its pick → "card" (`other_new` 0) or "amber"; else under
    `list` a word not on the list → "rare"; under `i1` a word another episode cards → "other"; else "none". A line is
    drawn where the list's pick (else every new word's) cuts the word's card, its count of new words that card's."""
    by_mode = {mode: {_key(w): w for w in picks.get(mode) or ()} for mode in MODES}
    every = by_mode["unknown"]
    elsewhere = {tuple(k) for k in elsewhere or ()}

    def outcome(key, listed):
        out = {}
        for mode in MODES:
            got = by_mode[mode].get(key)
            if got is not None:
                out[mode] = "amber" if got.get("other_new") else "card"
            elif mode == "list" and not listed:
                out[mode] = "rare"
            elif mode == "i1" and key in elsewhere:
                out[mode] = "other"
            else:
                out[mode] = "none"
        return out

    def drawn_at(key):
        """The word as the picture draws it: the list's line when the list cards it, else every new word's."""
        return by_mode["list"].get(key) or every.get(key)

    # The kinds the picture shows, each the first the picker met (its order: the list's, then the episode's)
    order = list(by_mode["list"]) + [k for k in every if k not in by_mode["list"]]
    one = next((k for k in order if drawn_at(k).get("listed") and not drawn_at(k).get("other_new")), None)
    two = next((k for k in order if drawn_at(k).get("listed") and drawn_at(k).get("other_new")), None)
    if one is None or two is None:
        return None
    rare = next((k for k in every if every[k].get("listed") is False and not every[k].get("other_new")), None)
    more = next((k for k in order if k not in (one, two) and drawn_at(k).get("listed")
                 and not drawn_at(k).get("other_new") and drawn_at(k).get("line_start")
                 not in {drawn_at(one).get("line_start"), drawn_at(two).get("line_start")}), None)
    chosen = [k for k in (one, two, more, rare) if k is not None]
    starts = {}
    for key in chosen:
        starts.setdefault(drawn_at(key).get("line_start"), [])
    # every drawn word whose card's line is one of the chosen lines (a two-new-word line's other carded word too)
    for key in order:
        at = drawn_at(key).get("line_start")
        if at in starts and key not in starts[at]:
            starts[at].append(key)
    lines = []
    for at, keys in sorted(starts.items(), key=lambda kv: kv[0] or 0)[:LINES]:
        first = drawn_at(keys[0])
        words = []
        for k in keys:
            w = drawn_at(k)
            # each mode's own sentence for the word (two modes may cut its card from different lines)
            texts = {mode: by_mode[mode][k].get("line_text") for mode in MODES if k in by_mode[mode]}
            words.append({"word": w.get("word"), "reading": w.get("reading"), "surface": w.get("surface") or w.get("word"),
                          "listed": bool(w.get("listed")), "outcome": outcome(k, bool(w.get("listed"))),
                          "texts": texts})
        lines.append({"text": first.get("line_text") or "", "new": 1 + int(first.get("other_new") or 0),
                      "words": words})
    counts = {mode: {"here": len(by_mode[mode]), "elsewhere": 0} for mode in MODES}
    counts["i1"]["elsewhere"] = len([k for k in every if k not in by_mode["i1"] and k in elsewhere])
    return {"source": source, "sample": False, "lines": lines, "counts": counts, "elsewhere_exact": True}


def result(picture, mode):
    """What `mode` makes of the picture, as the picker draws it (round 2: one idea per screen — the cards you'd get):
    {"cards": [{"word", "surface", "text", "outcome", "others"}], "skipped": [{"word", "surface", "why"}], "here",
    "elsewhere", "skipped_all", "exact", "source", "sample"}. A card is a drawn word whose outcome is a card here
    (`card`; `amber`: its sentence holds another new word, `others` their surfaces) or from a later episode (`other`:
    no sentence of its own here). A card here whose line holds another new word although its card doesn't (`card` on a
    two-new line: the picker took another line of this episode) is drawn without that line (`text` ""). A skipped word's
    `why`: `rare` (not on the list), `no-i1` (Only i+1 sentences: no sentence where it's the only new word), `none`.
    `skipped_all` counts the episode's (the counts'), not only the drawn ones'."""
    cards, skipped = [], []
    for line in picture.get("lines") or ():
        for w in line["words"]:
            got = w["outcome"][mode]
            surface = w.get("surface") or w.get("word") or ""
            if got in ("card", "amber", "other"):
                own = (w.get("texts") or {}).get(mode)      # this mode's own sentence, when the picker named it
                if own is not None and own != line["text"]:
                    text, others = (own, []) if got != "other" else ("", [])
                else:
                    text = line["text"] if got == "amber" or (got == "card" and line["new"] == 1) else ""
                    others = [x.get("surface") or x.get("word") or "" for x in line["words"] if x is not w] \
                        if got == "amber" else []
                cards.append({"word": w.get("word"), "surface": surface, "text": text, "outcome": got,
                              "others": others})
            else:
                skipped.append({"word": w.get("word"), "surface": surface,
                                "why": "rare" if got == "rare" else ("no-i1" if mode == "i1" else "none")})
    counts = picture["counts"]
    here, away = counts[mode]["here"], counts[mode]["elsewhere"]
    return {"cards": cards, "skipped": skipped, "here": here, "elsewhere": away,
            "skipped_all": max(0, counts["unknown"]["here"] - here - away, len(skipped)),
            "exact": bool(picture.get("elsewhere_exact")), "source": picture.get("source") or "",
            "sample": bool(picture.get("sample"))}


def sample(view, paths, listed, carded=None, send_grammar=True, read=None):
    """(Inside the warm arrivals worker.) The picture of the mine line's first episode `paths[0]` (subtitle files, in
    Connect's order), each choice counted by `pick.pick` (`arrivals.pick_cues`, the view's rules), *another episode* by
    pick() in `i1` over `paths[1:]` — or None (no path, the first can't be read, or `picture`'s None). `listed`: the
    list ({(Word, Reading): place}); `carded`: the card keys of the words with a card (the last sync's backlog: one card
    per word). `read(path)`: a subtitle's cues (`cues.read`; a test's)."""
    from app import arrivals, cues
    if not paths:
        return None
    read = read or (lambda path: cues.read(path, view.language))
    try:
        first = read(paths[0])
    except (OSError, UnicodeDecodeError, ValueError):
        return None                                 # the first episode can't be read: the bundled sample is drawn
    tokens = cues.tokens(first, view.language, view.script, view.tokenizer)        # read once, picked three times
    picks = {mode: arrivals.pick_cues(view, first, listed, send_grammar, mode=mode, carded=carded,
                                      tokens=tokens)["words"] for mode in MODES}
    here = {_key(w) for w in picks["i1"]}
    wanted = {_key(w) for w in picks["unknown"]} - here
    elsewhere, missed = set(), False
    for path in paths[1:]:
        if not wanted - elsewhere:
            break                                   # every word left has its other episode already
        try:
            other = arrivals.pick_cues(view, read(path), listed, send_grammar, mode="i1", carded=carded)["words"]
        except Exception:                           # an episode that can't be read or picked: it carries nothing,
            missed = True                           # and the rest of the picture stands (its count only "up to")
            continue
        elsewhere |= {_key(w) for w in other} & wanted
    out = picture(picks, elsewhere, source=os.path.splitext(os.path.basename(paths[0]))[0])
    if out is not None and missed:
        out["elsewhere_exact"] = False
    return out


def top(language):
    """(the subtitle files of Connect's mine line for `language`, in its order — `connect.library.mine_line`: Current's
    top N available items not mined yet, a book, a text or an audiobook left out: Anki Miner mines none of them from a subtitle —,
    every word Connect has made a card for: `library.made_words_all`, never made again) -> ([], set()) with no store.
    Reads the store only (role `reader`)."""
    import sqlite3
    from app import cues, library_store
    from app.connect import library
    from app.path_utils import get_data_path, get_user_files_path
    try:
        store = library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                         role="reader", busy_wait=0.5)
    except (library_store.StoreError, sqlite3.Error):
        return [], set()
    if store is None:
        return [], set()
    try:
        with store:                                 # (closed at its end)
            # (an item mined already is never mined again: Connect queues only the line's unmined ones, `inbox`)
            items = [store.item(i) for i in library.mine_line(store) if library.mined_at(store, i) is None]
            made = library.made_words_all(store)
    except (library_store.StoreError, sqlite3.Error):
        return [], set()                            # a busy or damaged store: no line read (the sample is drawn)
    data = get_data_path(language)
    out = []
    for item in items:
        rel = (item or {}).get("rel_path") or ""
        if not rel.lower().endswith(cues.SUBTITLES) or library.waits_for(item):
            continue
        out.append(os.path.join(data, *str(rel).replace("\\", "/").split("/")))
    return out, set(made)
