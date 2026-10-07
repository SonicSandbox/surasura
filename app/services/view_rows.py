"""What the window derives from the library (W2.2; the window's spec 02 §2.2–2.4): pure functions, Qt-free, so every
rule is tested without a window and the window only paints the answers.

From the store's feed rows (items and works by id, `FEED_ITEM_FIELDS` / `FEED_WORK_FIELDS`) and its options (the Soon
line, the mine line), the plan's numbers per item, each item's cards and the items being mined now, `build` makes one
frozen `View`:
- **Current** = NOW then Soon, in `(ord, id)`; **a row is a piece**: one contiguous run of one work's items in one tier
  (by `piece_id`; a run without one by its work, then its folder: 3.0-dev's stores before L3.1 seeded pieces).
- **The hero** is Current's first row, its *Up next* the first episode not watched (02 §2.2).
- **The top-20 line** follows the store's mine line: the top *n* **available** files of Current mine themselves
  (`_mine_ids`); the line is drawn after the row holding the *n*-th, and not at all with fewer (the mock: none under 20).
  **The Soon line** is drawn where Soon starts (the store keeps the tiers on its line, a count of files).
- ***% known*** is one number everywhere (QT-E8, G1.2-4): known tokens ÷ counted tokens, summed over the piece (never a
  mean of per-file percents); none before a Generate (an em dash, never 0 %). ***N new*** is the list words the piece is
  first to bring (summed).
- **One status vocabulary** for a row, the hero's next episode and an open row's episodes (the mock's `stHTML`, in its
  order): ✓ *N in Anki* · *Mining* · *Waiting* · ✓ *k/n · Mine rest* · *Mine* · *No video* / *Video removed* — and the
  on-disk mark (⌀ N) beside it when something isn't there. Status is a glyph and a label (and a tone the painter maps
  to a colour), never colour alone.
- Goal's strip, Finished by month (newest first; no date → *Earlier*), Needs you's entries (each show with files the top
  20 waits on that aren't on disk), the badges, the header's subline, each row's accessible text, and the section's
  state (full · empty · loading · getting ready · read-only; busy beside any of them).

Every user-facing word is here or in the window's strings; nothing here imports Qt, Tk or pandas (the import guard).
"""
import re
from collections import namedtuple

CACHE_ROWS = 40                         # the first screen's rows kept in window_cache_<lang>.json
LANGUAGE_NAMES = {"ja": "日本語", "zh": "中文"}
HATO_FOLDER = "HighPriority/Hato/"
LEARNED_AT = 97                         # ≥ → the learned colour (research/09)
HEADS_UP_BELOW = 93                     # < → heads-up
CHIPS_SHOWN = 12
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")

# media words and verbs by the work's media type (`library_store.MEDIA_TYPES`; None → video: `media_type()`'s rule)
MEDIA_WORD = {"anime": "video", "drama": "video", "movie": "video", "youtube": "video", "podcast": "audio",
              "audiobook": "audio", "book": "EPUB", "lightnovel": "EPUB", "manga": "EPUB", "game": "file",
              "text": "file", None: "video"}
VERB = {"video": "Watch", "audio": "Listen", "EPUB": "Read", "file": "Open"}
EPISODIC = ("anime", "drama", "movie", None)

Status = namedtuple("Status", "kind label tip tone")          # tone: ok · accent · dim · ink · faint · warn
Mark = namedtuple("Mark", "count tone tip")                    # the on-disk mark (⌀ N)
Episode = namedtuple("Episode", "id label number title watched cards mining missing removed in_top pct n_new "
                                "status mark rel_path play_tip can_play")
Row = namedtuple("Row", "key index tier work_id piece_id media title title_ep line source n_files n_watched "
                        "pct pct_tone n_new status mark episodes next_index studying date cover_title accessible "
                        "description chips more_chips play_tip can_play")
Chip = namedtuple("Chip", "text watched next mined tip")
Line = namedtuple("Line", "kind after tip")                    # drawn after row `after` (0-based in Current)
Goal = namedtuple("Goal", "titles files covers line tip")
Month = namedtuple("Month", "label rows")
Need = namedtuple("Need", "key work_id title line episodes cover_title")
Counts = namedtuple("Counts", "current_rows current_files goal_titles goal_files finished arrivals arrival_files")
View = namedtuple("View", "language mode reason state busy loading cached rows lines goal finished needs counts "
                          "subline badges")

STRINGS = {
    "dash": "—",
    # a status's words (its glyph is painted beside them: check · spinner · hourglass · card-plus · no-video)
    "in_anki": "{n} in Anki", "mined": "Mined", "mining_kn": "Mining · {k}/{n}", "mining": "Mining…",
    "waiting": "Waiting", "waiting_kn": "{k}/{n} · Waiting", "mine_rest": "{k}/{n} · Mine rest", "mine": "Mine",
    "no_media": "No {word}", "no_media_n": "No {word} · {n}", "removed": "{Word} removed",
    "tip_in_anki": "Mined · {n} cards in Anki", "tip_in_anki_k": "{k} mined · {n} cards in Anki",
    "tip_mining": "Making its cards now",
    "tip_waiting": "In your top {line}: it mines by itself, in turn",
    "tip_mine_rest": "{k}/{n} mined · the rest isn't in your top {line} yet",
    "tip_mine": "Not in your top {line}: it isn't mined yet",
    "tip_no_media": "No {word} on disk{top}. Link one for pictures and audio, or mine the text on its own",
    "tip_no_media_top": " — it's in your top {line}, so it's waiting for one",
    "tip_removed": "Its {word} was removed after it was mined. The cards keep their pictures and audio",
    "mark_missing": "No {word} on disk for {eps} — link one, or mine the text on its own",
    "mark_removed": "{Word} deleted after mining ({eps}). The cards keep their pictures and audio — only ▶ can't play it",
    "play": "{verb} {name} in your {player}", "play_youtube": "{verb} {name} on YouTube",
    "play_missing": "No {word} on disk — link one to {verb_l} it from here (Needs you, in a later build)",
    "play_removed": "Its {word} was removed — link it to {verb_l} it from here (Needs you, in a later build)",
    "player": {"video": "video player", "audio": "audio player", "EPUB": "e-book reader", "file": "default app"},
    "ep": "Ep {n}", "part": "Part {n}", "num": "#{n}", "eps": "Ep {a}–{b}", "parts": "Parts {a}–{b}",
    "nums": "#{a}–{b}", "videos": "{n} videos", "video": "1 video", "watched": "{k} of {n} watched",
    "channel_n": "{n} videos · {title}",
    "top_tip": "Everything above this line mines itself: your top {n} files",
    "soon_tip": "Soon: what's below this line comes after your first {n} files. It still counts toward your list",
    "soon_tip_nocount": "Soon: what's below this line comes after what's above it. It still counts toward your list",
    "goal_line": "{titles} titles · {files} files", "goal_one": "1 title · {files} files",
    "goal_empty": "Goal is empty",
    "goal_tip": "Someday, in no order: what you'll get to later. It counts toward your list",
    "earlier": "Earlier", "studying": "↑ Studying its cards first",
    "need_title_one": "{title} · {ep} has no {word}", "need_title_n": "{title} · {n} {unit} have no {word}",
    "need_line_one": "In your top {line}, so it's waiting on its {word} — each card's picture and audio come from it.",
    "need_line_n": "In your top {line}, so they're waiting on their {word} — each card's picture and audio come from it.",
    "need_ep": "no {word}", "unit_eps": "episodes", "unit_parts": "parts", "unit_files": "files",
    "subline": "{lang} · {rows} in Current · {files} files", "subline_empty": "{lang} · nothing added yet",
    "pct": "{pct}% known", "new": "{n} new", "hero_stats": "{pct}% known · {n} new words",
    "hero_stats_none": "not analysed yet",
    "acc_row": "{title} · {pct} · {new} · {status}", "acc_pct_none": "not analysed",
}

_EXT = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_YT_ID = re.compile(r"\s*\[[0-9A-Za-z_-]{6,11}\]$")
_EP_PATTERNS = (
    re.compile(r"[Ss]\d{1,2}[Ee](\d{1,4})"),
    re.compile(r"第\s*(\d{1,4})\s*[話话回集]"),
    re.compile(r"(?i)(?:^|[^A-Za-z])(?:ep|episode|e)\.?\s*(\d{1,4})(?!\d)"),
)
_NUMBER = re.compile(r"(?:^|[\s_\-\[\(（【#＃])(\d{1,4})(?:v\d)?(?=$|[\s_\-\]\)）】.])")


# --- small pieces ---------------------------------------------------------------------------------------------------- #
def stem(name):
    """A file's name without its extension or a YouTube id in brackets."""
    return _YT_ID.sub("", _EXT.sub("", name or "")).strip()


def episode_number(name):
    """The episode (or part) number a file's name gives, or None: `S01E05`, `第5話`, `ep05`, `Show - 05`, `Show 05 …`."""
    s = _EXT.sub("", name or "")
    for pat in _EP_PATTERNS:
        m = pat.search(s)
        if m:
            return int(m.group(1))
    found = [m for m in _NUMBER.finditer(s)]
    return int(found[-1].group(1)) if found else None


def runs(numbers):
    """[3, 4, 5, 7] -> [(3, 5), (7, 7)]."""
    out = []
    for n in sorted(set(numbers)):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def range_text(media, numbers, count):
    """The row's range: *Ep 1–8*, *Ep 1–4, 6*, *#28–34, 36*, *Parts 5–12*, *3 videos*; without numbers for every file,
    the count (*8 episodes*)."""
    if media == "youtube":
        return STRINGS["video"] if count == 1 else STRINGS["videos"].format(n=count)
    if media in EPISODIC:
        one, many, unit = STRINGS["ep"], STRINGS["eps"], STRINGS["unit_eps"]
    elif media == "podcast":
        one, many, unit = STRINGS["num"], STRINGS["nums"], STRINGS["unit_eps"]
    else:
        one, many, unit = STRINGS["part"], STRINGS["parts"], STRINGS["unit_parts"]
    if not numbers or len(numbers) != count:
        return f"{count} {unit}"
    rs = runs(numbers)
    if len(rs) == 1:
        a, b = rs[0]
        return one.format(n=a) if a == b else many.format(a=a, b=b)
    head = many.split("{")[0]
    return head + ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in rs)


def pct_of(known, counted):
    return None if not counted else 100.0 * known / counted


def pct_tone(pct):
    """The *% known* colour (status colours, never themed): learned · heads-up · plain."""
    if pct is None:
        return "plain"
    r = round(pct)
    if r >= LEARNED_AT:
        return "ok"
    if r < HEADS_UP_BELOW:
        return "warn"
    return "plain"


def pct_text(pct):
    return STRINGS["dash"] if pct is None else f"{round(pct)}%"


def thousands(n):
    return f"{n:,}"


def month_label(stamp):
    """`2026-09-02T…` -> *September 2026*; None -> *Earlier*."""
    if not stamp or len(stamp) < 7:
        return STRINGS["earlier"]
    try:
        y, m = int(stamp[:4]), int(stamp[5:7])
        return f"{MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        return STRINGS["earlier"]


def day_label(stamp):
    """`2026-09-02T…` -> *Sep 2*."""
    if not stamp or len(stamp) < 10:
        return ""
    try:
        return f"{MONTHS[int(stamp[5:7]) - 1][:3]} {int(stamp[8:10])}"
    except (ValueError, IndexError):
        return ""


def source_of(item, work):
    """hato · youtube · anilist · None: where an item came from (its chip's colour)."""
    if (item.get("rel_path") or "").startswith(HATO_FOLDER):
        return "hato"
    if item.get("source_type") in ("youtube", "bilibili") or (work or {}).get("media_type") == "youtube":
        return "youtube"
    if (work or {}).get("anilist_id"):
        return "anilist"
    return None


# --- pieces ------------------------------------------------------------------------------------------------------- #
def ordered_tier(items, tier):
    rows = [r for r in items.values() if r.get("tier") == tier]
    rows.sort(key=lambda r: (r.get("ord") or 0.0, r["id"]))
    return rows


def pieces(rows):
    """Contiguous runs of one piece (`piece_id`; without one: one work, then one folder) -> [[item, …], …]."""
    out = []
    last = None
    for r in rows:
        key = ("p", r["piece_id"]) if r.get("piece_id") is not None else \
            ("w", r["work_id"]) if r.get("work_id") is not None else ("f", r.get("parent_folder") or r["id"])
        if out and key == last:
            out[-1].append(r)
        else:
            out.append([r])
            last = key
    return out


# --- statuses ---------------------------------------------------------------------------------------------------- #
def _eps_list(eps):
    labels = [e.label for e in eps[:3]]
    more = len(eps) - 3
    return ", ".join(labels) + (f" (+{more})" if more > 0 else "")


def status_of(eps, word, line_n):
    """One status for a set of episodes (a row's, or one episode's), in the mock's order, and the on-disk mark."""
    n = len(eps)
    mined = [e for e in eps if e.cards or e.mined]
    k = len(mined)
    cards = sum(e.cards for e in eps)
    unmined = [e for e in eps if not (e.cards or e.mined)]
    ready = [e for e in unmined if not e.missing]
    missing = [e for e in eps if e.missing and not e.removed]
    removed = [e for e in eps if e.removed]
    top_missing = [e for e in missing if e.in_top]
    Word = word[:1].upper() + word[1:]
    if unmined and not ready:                                      # nothing left that could be mined
        if all(e.removed for e in unmined):
            st = Status("no_media", STRINGS["removed"].format(Word=Word), STRINGS["tip_removed"].format(word=word),
                        "faint")
        else:
            top = any(e.in_top for e in unmined)
            label = STRINGS["no_media"].format(word=word) if len(unmined) == 1 else \
                STRINGS["no_media_n"].format(word=word, n=len(unmined))
            tip = STRINGS["tip_no_media"].format(word=word, top=STRINGS["tip_no_media_top"].format(line=line_n)
                                                 if top else "")
            st = Status("no_media", label, tip, "warn" if top else "faint")
        mark = None
        if mined and removed:
            mark = Mark(len(removed), "faint", STRINGS["mark_removed"].format(Word=Word, eps=_eps_list(removed)))
        return st, mark
    if not unmined:                                                # every item mined
        label = STRINGS["in_anki"].format(n=cards) if cards else STRINGS["mined"]
        tip = STRINGS["tip_in_anki"].format(n=cards) if n == 1 else STRINGS["tip_in_anki_k"].format(k=k, n=cards)
        st = Status("in_anki", label, tip, "ok")
    elif any(e.mining for e in eps):
        label = STRINGS["mining"] if n == 1 else STRINGS["mining_kn"].format(k=k, n=n)
        st = Status("mining", label, STRINGS["tip_mining"], "accent")
    elif any(e.in_top for e in ready):
        label = STRINGS["waiting"] if not k else STRINGS["waiting_kn"].format(k=k, n=n)
        st = Status("waiting", label, STRINGS["tip_waiting"].format(line=line_n), "dim")
    elif k:
        st = Status("mine_rest", STRINGS["mine_rest"].format(k=k, n=n),
                    STRINGS["tip_mine_rest"].format(k=k, n=n, line=line_n), "ok")
    else:
        st = Status("mine", STRINGS["mine"], STRINGS["tip_mine"].format(line=line_n), "ink")
    mark = None
    if missing:
        mark = Mark(len(missing), "warn" if top_missing else "faint",
                    STRINGS["mark_missing"].format(word=word, eps=_eps_list(missing)))
    elif removed:
        mark = Mark(len(removed), "faint", STRINGS["mark_removed"].format(Word=Word, eps=_eps_list(removed)))
    return st, mark


# --- building ------------------------------------------------------------------------------------------------------ #
def _episode(item, work, media, numbers, cards, mining, in_top, line_n):
    name = item.get("title") or (item.get("rel_path") or "").rsplit("/", 1)[-1]
    number = None if media == "youtube" else episode_number(name)
    if media == "youtube":
        label = stem(name)
    elif number is None:
        label = stem(name)
    elif media in EPISODIC:
        label = STRINGS["ep"].format(n=number)
    elif media == "podcast":
        label = STRINGS["num"].format(n=number)
    else:
        label = STRINGS["part"].format(n=number)
    known, counted, n_new = numbers.get(item["id"], (0, 0, None))
    missing = item.get("availability") == "missing"
    c = cards.get(item["id"], 0)
    mined = bool(item.get("mined_at")) or c > 0
    word = MEDIA_WORD.get(media, "video")
    verb = VERB[word]
    ep = Episode(id=item["id"], label=label, number=number, title=stem(name), watched=bool(item.get("watched")),
                 cards=c, mining=item["id"] in mining and not mined, missing=missing, removed=missing and mined,
                 in_top=in_top, pct=pct_of(known, counted), n_new=n_new, status=None, mark=None,
                 rel_path=item.get("rel_path"), play_tip="", can_play=not missing)
    st, mark = status_of([_Shim(ep, mined)], word, line_n)
    if missing:
        tip = (STRINGS["play_removed"] if mined else STRINGS["play_missing"]).format(word=word, verb_l=verb.lower())
    elif media == "youtube" and item.get("source_type") in ("youtube", "bilibili"):
        tip = STRINGS["play_youtube"].format(verb=verb, name=label)
    else:
        tip = STRINGS["play"].format(verb=verb, name=label, player=STRINGS["player"][word])
    return ep._replace(status=st, mark=mark, play_tip=tip)


class _Shim:
    """An episode as `status_of` reads it (`mined` is the receipt or cards)."""
    __slots__ = ("label", "cards", "mined", "missing", "removed", "in_top", "mining")

    def __init__(self, ep, mined):
        self.label, self.cards, self.mined = ep.label, ep.cards, mined
        self.missing, self.removed, self.in_top, self.mining = ep.missing, ep.removed, ep.in_top, ep.mining


def _row(index, tier, piece, works, numbers, cards, mining, in_top_ids, line_n, finished=False):
    first = piece[0]
    work = works.get(first.get("work_id")) or {}
    media = work.get("media_type")
    if media is None and first.get("source_type") in ("youtube", "bilibili"):
        media = "youtube"
    word = MEDIA_WORD.get(media, "video")
    eps = [_episode(it, work, media, numbers, cards, mining, it["id"] in in_top_ids, line_n) for it in piece]
    shims = [_Shim(e, bool(e.cards) or bool(it.get("mined_at"))) for e, it in zip(eps, piece)]
    st, mark = status_of(shims, word, line_n)
    n = len(eps)
    n_watched = sum(1 for e in eps if e.watched)
    known = sum(numbers.get(it["id"], (0, 0, 0))[0] for it in piece)
    counted = sum(numbers.get(it["id"], (0, 0, 0))[1] for it in piece)
    news = [numbers[it["id"]][2] for it in piece if it["id"] in numbers and numbers[it["id"]][2] is not None]
    pct = pct_of(known, counted)
    n_new = sum(news) if news else None
    channel = work.get("youtube_channel") or work.get("title")
    single_video = media == "youtube" and n == 1
    if single_video:
        title = eps[0].title
        line = channel or ""
    elif media == "youtube":
        title = channel or eps[0].title
        nxt = next((e for e in eps if not e.watched), eps[-1])
        line = STRINGS["channel_n"].format(n=n, title=nxt.title)
    else:
        title = work.get("title") or first.get("parent_folder") or eps[0].title
        nums = [e.number for e in eps if e.number is not None]
        line = range_text(media, nums, n)
    if not finished and 0 < n_watched < n and not single_video:
        line = f"{line} · " + STRINGS["watched"].format(k=n_watched, n=n)
    next_index = next((i for i, e in enumerate(eps) if not e.watched), n - 1)
    nxt = eps[next_index]
    chips = ()
    more = 0
    if n > 1:
        chips = tuple(Chip(text=str(e.number) if e.number is not None else "•", watched=e.watched,
                           next=(i == next_index), mined=bool(e.cards) or e.removed or bool(piece[i].get("mined_at")),
                           tip=e.label + (f" · {e.cards} cards in Anki" if e.cards else ""))
                      for i, e in enumerate(eps[:CHIPS_SHOWN]))
        more = max(0, n - CHIPS_SHOWN)
    studying = bool(first.get("pinned")) and any(it.get("pinned") for it in piece)
    stamp = max((it.get("graduated_at") or "" for it in piece), default="") or None
    acc_pct = STRINGS["acc_pct_none"] if pct is None else STRINGS["pct"].format(pct=round(pct))
    acc_new = STRINGS["new"].format(n=n_new if n_new is not None else 0) if n_new is not None else STRINGS["dash"]
    accessible = STRINGS["acc_row"].format(title=title, pct=acc_pct, new=acc_new, status=st.label) if not finished \
        else f"{title} · {st.label if st.kind in ('in_anki', 'mining') else line}"
    key = f"p{first['piece_id']}" if first.get("piece_id") is not None else f"i{first['id']}"
    return Row(key=key, index=index, tier=tier, work_id=first.get("work_id"), piece_id=first.get("piece_id"),
               media=media, title=title, title_ep=nxt.label if (n > 1 or media in EPISODIC) and media != "youtube"
               else "", line=line, source=source_of(first, work), n_files=n, n_watched=n_watched, pct=pct,
               pct_tone=pct_tone(pct), n_new=n_new, status=st, mark=mark, episodes=tuple(eps), next_index=next_index,
               studying=studying, date=day_label(stamp) if finished else "", cover_title=work.get("title") or title,
               accessible=accessible, description=line, chips=chips, more_chips=more, play_tip=nxt.play_tip,
               can_play=nxt.can_play)


def _current_items(items):
    return ordered_tier(items, "now") + ordered_tier(items, "soon")


def _mine_ids(current, n):
    """The store's `_mine_ids`: the top `n` available files of Current, in order."""
    out = []
    for r in current:
        if len(out) >= n:
            break
        if r.get("availability") != "missing":
            out.append(r["id"])
    return out


def build(items, works, options, numbers=None, cards=None, mining=(), language="ja", mode="store", reason=None,
          loading=False, busy=False):
    """The window's view of the library (see the module's doc). `items` / `works`: {id: feed row}; `options`: the
    feed's {soon_line, mine_line, arrivals_on}; `numbers`: (version, {item_id: (known, counted, n_new)}) or the dict;
    `cards`: {item_id: count}; `mining`: item ids being mined now."""
    if isinstance(numbers, tuple):
        numbers = numbers[1]
    numbers = numbers or {}
    cards = cards or {}
    mining = set(mining or ())
    options = options or {}
    line_n = int(options.get("mine_line") or 20)
    current = _current_items(items)
    top_ids = _mine_ids(current, line_n)
    # every item above the line's place (missing ones included) is "in the top": the line falls after the n-th available
    in_top = set()
    if top_ids:
        last = top_ids[-1]
        for r in current:
            in_top.add(r["id"])
            if r["id"] == last:
                break
    rows = []
    for tier in ("now", "soon"):
        for piece in pieces(ordered_tier(items, tier)):
            rows.append(_row(len(rows) + 1, tier, piece, works, numbers, cards, mining, in_top, line_n))
    lines = []
    if len(top_ids) >= line_n and line_n > 0:
        last = top_ids[-1]
        at = next(i for i, row in enumerate(rows) if any(e.id == last for e in row.episodes))
        lines.append(Line("top", at, STRINGS["top_tip"].format(n=line_n)))
    first_soon = next((i for i, row in enumerate(rows) if row.tier == "soon"), None)
    if first_soon is not None and first_soon > 0:
        k = options.get("soon_line")
        tip = STRINGS["soon_tip"].format(n=k) if k else STRINGS["soon_tip_nocount"]
        lines.append(Line("soon", first_soon - 1, tip))
    # Goal: titles are works, files all their items
    goal_items = ordered_tier(items, "goal")
    goal_works = []
    for r in goal_items:
        if r.get("work_id") not in goal_works:
            goal_works.append(r.get("work_id"))
    covers = tuple((works.get(w) or {}).get("title") or "" for w in goal_works[:9])
    if goal_items:
        g_line = STRINGS["goal_one"].format(files=thousands(len(goal_items))) if len(goal_works) == 1 else \
            STRINGS["goal_line"].format(titles=len(goal_works), files=thousands(len(goal_items)))
    else:
        g_line = STRINGS["goal_empty"]
    goal = Goal(titles=len(goal_works), files=len(goal_items), covers=covers, line=g_line, tip=STRINGS["goal_tip"])
    # Finished: newest first, by month; no date last (*Earlier*)
    fin_rows = [_row(0, "graduated", p, works, numbers, cards, mining, set(), line_n, finished=True)
                for p in pieces(ordered_tier(items, "graduated"))]
    stamp_of = {}
    for p in pieces(ordered_tier(items, "graduated")):
        key = f"p{p[0]['piece_id']}" if p[0].get("piece_id") is not None else f"i{p[0]['id']}"
        stamp_of[key] = max((it.get("graduated_at") or "" for it in p), default="")
    fin_rows.sort(key=lambda r: stamp_of.get(r.key, ""), reverse=True)
    months, by_label = [], {}
    for r in fin_rows:
        label = month_label(stamp_of.get(r.key))
        if label not in by_label:
            by_label[label] = []
            months.append(label)
        by_label[label].append(r)
    if STRINGS["earlier"] in months:                 # *Earlier* always last
        months.remove(STRINGS["earlier"])
        months.append(STRINGS["earlier"])
    finished = tuple(Month(m, tuple(by_label[m])) for m in months)
    # Needs you: each show whose unmined files in the top wait on a missing file
    needs = []
    for row in rows:
        waiting = [e for e in row.episodes if e.missing and not e.removed and e.in_top]
        if not waiting:
            continue
        word = MEDIA_WORD.get(row.media, "video")
        unit = STRINGS["unit_eps"] if row.media in EPISODIC else STRINGS["unit_files"] \
            if row.media == "youtube" else STRINGS["unit_parts"]
        if len(waiting) == 1:
            title = STRINGS["need_title_one"].format(title=row.title, ep=waiting[0].label, word=word)
            line = STRINGS["need_line_one"].format(line=line_n, word=word)
        else:
            title = STRINGS["need_title_n"].format(title=row.title, n=len(waiting), unit=unit, word=word)
            line = STRINGS["need_line_n"].format(line=line_n, word=word)
        needs.append(Need(key=row.key, work_id=row.work_id, title=title, line=line,
                          episodes=tuple((e.label, STRINGS["need_ep"].format(word=word)) for e in waiting),
                          cover_title=row.cover_title))
    arrivals = ordered_tier(items, "arrivals")
    counts = Counts(current_rows=len(rows), current_files=len(current), goal_titles=len(goal_works),
                    goal_files=len(goal_items), finished=len(fin_rows),
                    arrivals=len(pieces(arrivals)), arrival_files=len(arrivals))
    lang = LANGUAGE_NAMES.get(language, "")
    if rows:
        subline = STRINGS["subline"].format(lang=lang, rows=counts.current_rows, files=counts.current_files)
    elif not items:
        subline = STRINGS["subline_empty"].format(lang=lang)
    else:
        subline = STRINGS["subline"].format(lang=lang, rows=0, files=0)
    if loading:
        state = "loading"
    elif mode == "json":
        state = "getting-ready"
    elif mode == "read-only":
        state = "read-only"
    else:
        state = "full" if rows else "empty"
    badges = {"needs": len(needs), "arrivals": counts.arrival_files, "finished": counts.finished}
    return View(language=language, mode=mode, reason=reason, state=state, busy=busy, loading=loading, cached=False,
                rows=tuple(rows), lines=tuple(lines), goal=goal, finished=finished, needs=tuple(needs), counts=counts,
                subline=subline, badges=badges)


# --- the first screen's cache (02 §2.1) ---------------------------------------------------------------------- #
def _plain(value):
    """namedtuples -> lists (JSON), recursively."""
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        return [_plain(v) for v in value]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def to_cache(view, rows=CACHE_ROWS):
    """The first `rows` rows of Current, the lines among them, the counts, the subline and the Goal strip: what the
    first frame shows before the store is read."""
    kept = view.rows[:rows]
    return {"rows": _plain(kept), "lines": _plain([ln for ln in view.lines if ln.after < len(kept)]),
            "goal": _plain(view.goal), "counts": _plain(view.counts), "subline": view.subline,
            "badges": dict(view.badges)}


def _row_from(data):
    r = Row(*data)
    st = Status(*r.status) if r.status else None
    mk = Mark(*r.mark) if r.mark else None
    eps = tuple(Episode(*e)._replace(status=Status(*e[12]) if e[12] else None, mark=Mark(*e[13]) if e[13] else None)
                for e in r.episodes)
    chips = tuple(Chip(*c) for c in r.chips)
    return r._replace(status=st, mark=mk, episodes=eps, chips=chips)


def from_cache(data, language="ja"):
    """A `View` of the cached first screen (state *loading*, `cached` True), or None when the data isn't ours."""
    try:
        rows = tuple(_row_from(r) for r in data["rows"])
        return View(language=language, mode="store", reason=None, state="loading", busy=False, loading=True,
                    cached=True, rows=rows, lines=tuple(Line(*ln) for ln in data["lines"]), goal=Goal(*data["goal"]),
                    finished=(), needs=(), counts=Counts(*data["counts"]), subline=data["subline"],
                    badges=dict(data.get("badges") or {}))
    except (KeyError, TypeError, ValueError):
        return None
