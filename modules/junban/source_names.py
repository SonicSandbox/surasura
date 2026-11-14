# SPDX-License-Identifier: GPL-3.0-or-later
"""Which file an Anki Miner card came from — the one source-name rule (Michi-C, 2026-10-29; pipeline TRACK Inbox,
Mattias's note 13). Used by 順's *not in your library* footer (`reposition._banner`), *Study its cards first* and
*Take its new cards out* (`pins`), and the shows behind the backlog (`backlog_shows`): one rule, so the three never
disagree about a card.

**What Anki Miner writes** into `MiscInfo`: `"<source> @ <time>"`, the source in one of two forms —

- **bare**: the video's name, `[SubsPlease] Tetsunabe no Jan! - 04` (Junban_Module_Spec WP-L measured it) — every
  card before 3.5, and still Anki Miner 3.10's single-episode tab (`sanitize_source_label(video_file.stem)`, or the
  label typed there);
- **3.5 and later**: `"<the video's folder> — <the video's name>"`. 3.5.0 took the trailing release tags
  (`[WEBRip-1080p][JA]-Trix`) off the whole label; 3.10 cleans each part on its own (`episode_processor.
  sanitize_source_label`, `_source_label`): trailing `[…]` groups and a resolution paren (`(1080p)`), then one leading
  group tag without a space (`[SubsPlease]`), a part that cleans to nothing kept as written.

**Keys.** A card's source and every name a file can carry are reduced the same way (`key`): each `" — "` part NFKC,
lower case, letters and digits only, the parts joined by `/` — so `show/01` (folder `Show`, file `01`) is never the
bare `show01`. A card's key is its source with trailing release tags off (`card_key`); a file's keys (`names_of`) are
every form either Anki Miner could have written for it: folder + name in both cleanings, and the bare name (with and
without a language tag such as `.ja`) in both — the bare form only when the name says a show AND an episode and is
no special (`episode_names.identity`: `01`, `OVA`, `Movie`, `NCOP`, `Special 01`, `Part 1` name nothing — another
show has one too), or, with no episode, when the file is its folder's own title (a single video,
`<title>/<title> [id].srt`) of at least `BARE_TITLE_MIN` letters and digits, no special and no part (Junban-X3, based
on Mattias's #447; `Creditless Opening` in a show's folder, `Trailer`, `猫の動画` stay anyone's). A card names a file
when its key is one of the file's — **exact, never a substring** (`show1` is
not `show10`). A key two titles of the library share names neither (`shared_names`). A `MiscInfo` with no time after
` @ ` (a Migaku note's hint) names nothing. Anki Miner's fixed series (`Audio` for an audiobook, `YouTube` for a
fetched video) name no show of their own (`FIXED_SERIES`) — but they name an item, from its record (`names_of_record`):
an audiobook's own files as `Audio — <the file's name>` (only a name carrying its book's title: `01`, `Track 01` are
every audiobook's), a fetched video's title as `YouTube — <title>` and bare (by the title rule above). Like a bare
name they are only ever counted: `Audio` is every audiobook's folder.

**Where a stray match would write Anki** (*Study its cards first*, *Take its new cards out*: `pins`), only the folder
forms are used (`bare=False`): a bare name and the fixed series are only ever counted (the footer, the shows behind
the backlog), asked for when a card needs them (`only_counted`).

Pure: no Anki, no store, no settings, no files.
"""
import html
import os
import re
import unicodedata
from functools import lru_cache

# 3.5.0's strip, the whole label at once: a run of `[…]` groups, then an optional `-Group`, at the end.
_RELEASE_TAGS = re.compile(r"\s*(?:\[[^\]]*\]\s*)+(?:-\S+)?\s*$")
# 3.10's `_ARR_METADATA_RE`: trailing `[…]` groups and resolution parens (`(1080p)`, `(1920x1080)`), then `-Group`.
_ARR_TAGS = re.compile(r"\s*(?:(?:\[[^\]]*\]|\((?=[^()]*(?<!\d)\d{3,4}(?:[pP]|[xX×]\d{3,4}))[^()]*\))\s*)+(?:-\S+)?\s*$")
# 3.10's `_LEADING_GROUP_RE`: one leading group tag without a space (`[SubsPlease] Title`).
_LEADING_GROUP = re.compile(r"^\s*\[[^\]\s]*\]\s*")
# "<source> @ h:mm:ss" (or mm:ss, or a fraction of a second): the time is required.
_SOURCE = re.compile(r"^(?P<source>.*\S)\s+@\s+\d{1,3}:\d{2}(?::\d{2})?(?:\.\d+)?\s*$", re.S)
# A subtitle's language tag before its extension (`Show - 05.ja.ass`): taken off to reach the video's own name.
_LANGUAGE_TAG = re.compile(r"\.(?:ja|jp|jpn|japanese|zh|chi|zho|chs|cht|sc|tc|cn|tw|zh-hans|zh-hant)$", re.I)
DASH = " — "                    # Anki Miner's separator between the folder and the name
FIXED_SERIES = ("audio", "youtube")     # Anki Miner's own series names (an audiobook's, a fetched video's), `plain`
AUDIO, YOUTUBE = "Audio", "YouTube"      # ... as Anki Miner writes them before DASH
# A name with no episode is a title of its own from this many letters and digits (`plain`): `Opening`, `Vlog`, `猫の動画`
# are anyone's (Junban-X3, Mattias's #447: his single video's cards named `笑い過ぎて一生忘れられないTRPG` bare)
BARE_TITLE_MIN = 10
_NOT_ALNUM = re.compile(r"[\W_]+")       # what `str.isalnum` refuses (`\w` is alnum and `_`)


def plain(text):
    """Letters and digits only: NFKC, lower case, spaces, punctuation and brackets gone."""
    return _plain(str(text or ""))


@lru_cache(maxsize=65536)
def _plain(text):
    # (a show's folder repeats on every episode: 20,000 items' names in about a second, not eight)
    return _NOT_ALNUM.sub("", unicodedata.normalize("NFKC", text).lower())


def key(source):
    """A source as a key: each `" — "` part reduced (`plain`), the empty ones dropped, joined by `/`; None if empty."""
    parts = [plain(part) for part in str(source or "").split(DASH)]
    joined = "/".join(part for part in parts if part)
    return joined or None


@lru_cache(maxsize=65536)
def clean(part):
    """Anki Miner 3.10's `sanitize_source_label` for one part (a part that cleans to nothing is kept as written)."""
    label = _ARR_TAGS.sub("", part).strip()
    rest = _LEADING_GROUP.sub("", label, count=1)
    cleaned = rest if rest and rest[0] not in "-–—" else label
    return cleaned or part.strip()


def source_text(misc_info):
    """A card's Anki Miner source as written (HTML entities read, the time cut off), or None when `MiscInfo` isn't in
    its shape."""
    found = _SOURCE.match(html.unescape(str(misc_info or "")).replace("\xa0", " ").strip())
    return found.group("source").strip() if found else None


def card_key(misc_info):
    """A card's source as a key (`key` of the source, trailing release tags off), or None."""
    source = source_text(misc_info)
    if source is None:
        return None
    return key(_RELEASE_TAGS.sub("", source).strip())


def is_folder_form(misc_info):
    """Does the card's source carry a folder (Anki Miner 3.5's `folder — name`)?"""
    return DASH in (source_text(misc_info) or "")


def series_of(misc_info):
    """The folder part of a 3.5-form source, cleaned as Anki Miner cleans it (a show's name when the card names no
    file of the library), else None."""
    source = source_text(misc_info)
    if not source or DASH not in source:
        return None
    return clean(source.split(DASH, 1)[0]) or None


@lru_cache(maxsize=65536)
def _bare_ok(stem, folder=None):
    """Does a name stand alone as a bare name: a show and its episode, no special (LM1a's one reading,
    `episode_names.identity`) — or, with no episode, a title of its own: no special, no part, `BARE_TITLE_MIN` letters
    and digits, and the file its folder's own title (`folder`; None for a record's title, its own already)? Asked once
    per name."""
    from app import episode_names
    try:
        name = episode_names.identity(stem)
    except Exception:
        return False
    if not name.show or name.special:
        return False
    if name.episode is not None:
        return True
    return (name.part is None and len(plain(name.show)) >= BARE_TITLE_MIN and
            (folder is None or plain(clean(folder)) == plain(clean(stem))))


def names_of(path, video_path=None, bare=True):
    """Every key a card from this file can carry: for the paired video and the file itself (its name as is, and without
    a trailing language tag), folder + name in 3.5.0's and 3.10's cleaning, and the bare name in both (only when it
    says a show). `bare` False: the folder forms only — for a caller whose cards carry none of the old form (the bare
    name's show rule is most of the time at 20,000 files)."""
    pairs = []
    for one in (video_path, path):
        if not one:
            continue
        one = str(one).replace("\\", "/")
        folder, stem = os.path.basename(os.path.dirname(one)), os.path.splitext(os.path.basename(one))[0]
        pairs.append((folder, stem))
        untagged = _LANGUAGE_TAG.sub("", stem)
        if untagged != stem:
            pairs.append((folder, untagged))
    forms = set()
    for folder, stem in pairs:
        if not stem:
            continue
        if folder:
            forms.add(folder + DASH + stem)                         # 3.5.0: as is, then the whole label's tags off
            forms.add(clean(folder) + DASH + clean(stem))           # 3.10: each part cleaned
        if bare and _bare_ok(_LANGUAGE_TAG.sub("", stem), folder):
            forms.add(stem)                                         # before 3.5: the video's own name
            forms.add(_ARR_TAGS.sub("", stem).strip() or stem)
            forms.add(clean(stem))
    return _keys(forms)


def names_of_record(record, bare=True):
    """The keys Anki Miner's fixed series give an item, from one of its records (none with `bare` False: like a bare
    name they are only ever counted): each of an audiobook's own files (`audiobook.files`) as `Audio — <its name>`
    when the name carries the book's title (`title` / `titles`, never the file's own name: a lone `Track 01.mp3`'s
    titles hold `Track 01`), and a fetched video's title (the YouTube downloader's
    record) as `YouTube — <title>` and bare when it stands alone (`_bare_ok`)."""
    if not bare or not isinstance(record, dict):
        return set()
    forms = set()
    book = record.get("audiobook")
    if isinstance(book, dict):
        titles = {plain(t) for t in [book.get("title"), *(book.get("titles") or ())] if isinstance(t, str)} - {""}
        for one in book.get("files") or ():
            if not isinstance(one, str):
                continue
            stem = os.path.splitext(os.path.basename(one.replace("\\", "/")))[0]
            if any(t in plain(stem) for t in titles - {plain(stem)}):     # (a lone file's own name is a title too)
                forms |= {AUDIO + DASH + stem, AUDIO + DASH + clean(stem)}
    title = record.get("title")
    title = title.strip() if isinstance(title, str) else ""
    if "youtube" in (record.get("media_type"), record.get("producer")) and title and _bare_ok(title):
        forms |= {YOUTUBE + DASH + title, YOUTUBE + DASH + clean(title), title, clean(title)}
    return _keys(forms)


def _keys(forms):
    """Each form's key, as is and with 3.5.0's trailing release tags off."""
    names = set()
    for form in forms:
        for variant in (form, _RELEASE_TAGS.sub("", form).strip()):
            k = key(variant)
            if k:
                names.add(k)
    return names


def fixed_series(misc_info):
    """Is the card's folder part one of Anki Miner's fixed series (`Audio`, `YouTube`), no show's name?"""
    source = source_text(misc_info)
    return bool(source) and DASH in source and plain(source.split(DASH, 1)[0]) in FIXED_SERIES


def is_bare(card):
    """Is a card key (`card_key`) the old form — the video's name alone, no folder?"""
    return bool(card) and "/" not in card


def only_counted(card):
    """Can only the names that are only ever counted (`bare=True`) name this card key: the old bare form, or one of
    Anki Miner's fixed series (`audio/…`, `youtube/…`)?"""
    return is_bare(card) or (bool(card) and card.split("/", 1)[0] in FIXED_SERIES)


def shared_names(names_by_item, work_of=None):
    """The keys items of two or more titles carry (they name no item). `work_of(item_id)`: the item's title (the store's
    work id) — items of one title may share a key (a show split across two folders, a copy beside its original: the show
    is still named); without it, or for an item of no title, every item is its own."""
    owner, shared = {}, set()
    for item_id, names in names_by_item.items():
        mark = (work_of(item_id) if work_of is not None else None) or ("item", item_id)
        for name in names:
            if name in owner and owner[name] != mark:
                shared.add(name)
            owner.setdefault(name, mark)
    return shared
