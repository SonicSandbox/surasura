"""Sources (3.0, SRC K1b): a look at a folder Surasura reads where it is — headless, called on a worker.

A source (`Store.add_source`) is where Surasura *finds* text and videos; its own copy of every text lives in the data
folder, `Library/<show>/<file>` (SRC-4). One look (`scan`):

- **Lists** the folder with `os.scandir` (names and stats from the listing: nothing opened), skipping what no show
  lives in (`library_store.skip_dir`: dot folders, recycle bins, folder links — never followed) and cloud placeholders
  (`library_store.is_placeholder`: never read, a video's key neither, B3). **Only what changed is listed again** (S4):
  each folder's time is kept beside Connect's video index (`cache_path`), stamped with the store's `store_id` and
  `epoch` and written only after the look's take-ins committed, and only when it changed; a folder whose time didn't
  move is not listed (one with an entry that couldn't be read is listed again). The first look at a folder each run,
  setup's first scan and Refresh (`full=True`) list everything; a listed folder's known files are compared by the
  stats its listing brought. A `Subs` / `Subtitles` folder (and a language's inside one, `Subs/ja`) is listed with the
  folder above it: its subtitles are that folder's show's, paired with its videos by name. So is a folder of
  versions of the episodes above it (item 11: `synced/`, a release group's folder — only subtitles, every one an
  episode the folder above holds, no videos, no folders, never a season's): one show, one subtitle per episode.
- **Never a duplicate** (SRC-7, S7): one subtitle per episode per language (`.ja.ass`, then `.ja.srt`, then untagged;
  an `.sdh` / `.hi` / `.cc` one after the plain one, a `.forced` one and another language's tag skipped — each name
  read by LM1a's one rule, `episode_names.identity`: its marks, its episode and "the same episode"), one per video
  in a look, the latest release of an episode (`- 05v2` over `- 05`). LM1b (PROVISIONAL): ONE episode per key per
  show (`Library/<show>`, from any folder or source, A9); a subtitle finds its video by name, else by its episode's
  number among the folder's videos (`_video_for`, A4; one of several videos of an episode, A5); `Subs/<video>/` is
  that video's (A11); every other file of an episode is another VERSION — an origin on the same item flagged
  `version`, never an item, a count, the item's text or any reader's (`_version`, `library_store._VERSION_ROW`); a
  pick under a quarter of its episode's fullest candidate's lines gives way (A6); a known subtitle's video come
  later, or renamed, is recorded on it (`_late`, A19, A20); creditless openings and the like never wait (A32). LM2
  (PROVISIONAL, Sonic 2026-10-21: LM-1a, T2-A1, A29): ONE subtitle group per show (`episode_names.identity`'s
  `group`: the leading `[tag]` and the name before the episode marker), recorded on its title at the first take-in
  that reads it (`Store.show_groups`) and never decided again by a look — the group its earliest episode in was
  picked from, else the earliest episode's pick in that look; the look's order takes it right after the file named
  like its video (`subtitle_rank`); Connect's first cards may switch it once (`Store.switch_group`, T2-A2). Then,
  cheapest first, (a) a video beside it
  already paired → that item, (b) an item holding the same bytes → that item, a `v2` of an episode already in → that
  item, its copy followed (S5), else (c) a copy (`.part`, then renamed; a file changed in the last SETTLE_S seconds, or
  while copied, waits for the next look). A removed item's path, bytes, video, or its episode's re-release stay out
  (S6).
- **Hands each show's files to `Store.take_in`**, at most BATCH at a time (an EPUB's parts all in one: S11): each
  take-in holds the write lock briefly, so a window's move waits little (G1); a PASSIVE checkpoint every
  CHECKPOINT_EVERY of them keeps the write-ahead log short.
- **A changed original** (in a folder listed): copied again over Surasura's copy — only a copy in `Library`, never
  from an empty file, one under half the copy's size or one that changed while read; the old copy *copied* into the
  data folder's `.trash` first (its clock restarted), then the new one put in its place at once (`os.replace`, S5);
  a `v2`'s text only once `take_in` recorded it on its episode.
- **A skipped folder** (K6, *Never read this folder*: `Store.skip_folder`): never listed, nor anything under it, and
  its files never counted as found; the cache keeps the skips it was written with (and the store's `folder_skips`
  stamp, so a quick look reads no exclusion), and a move of that stamp lists everything once. **A text or book not in the
  library's language** (`_refusal`, ONE rule: Japanese needs MIN_SCRIPT kana letters — Han alone is Chinese; Chinese
  MIN_SCRIPT Han and fewer than MIN_SCRIPT kana letters) is no content — a backup's skin config, an untagged English
  `.srt`, a Chinese fansub beside the Japanese subtitle, an English EPUB — nor is a loose `.txt` / `.md` with fewer
  than BOOK_MIN_CHARS characters of the script (T2-B4: counted `short` too); a text over IN_MEMORY is judged by its
  first HEAD bytes (B4), an EPUB whose encryption.xml locks more than its fonts is never split (B6). Each is skipped,
  never copied — a text unless an item already holds its bytes or video (check a / b) — and remembered by its stats
  like an EPUB with no text, so an unchanged one is never read again. A Mac's `._*` twins are never listed
  (`runner.mac_copy`: the one dot rule — a `.hack` title is a name, LF-21), and a video is what `runner.video_file`
  says (never a `.ts` under its TS_MIN: B7, S9).
- **An unreachable folder** (SRC-3): `{"reachable": False}`, nothing written or marked — one that goes while it is
  listed too (its folder times kept as they were). T6: with `"gone": True` when it is GONE (moved or deleted: the
  folder above it reads and holds nothing of its name, on the volume it was last read on — `reach`), else it is AWAY
  (an unplugged drive, a share down, a parent that can't be read). A gone folder's originals found in a new place moved
  (D5), as a folder's still there do; an away one's never (whether they left is unknown, G5).

`due` is the cadence the shell asks (SRC-9); `local_or_network` tells it which folders a watch can follow (D5).
Nothing is ever written under a source folder. Standard library only.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import sys
import threading
import time
import unicodedata
from collections import namedtuple

from app import audiobooks
from app import episode_names as en
from app import library_store as ls
from app.path_utils import BOOK_EXTENSIONS, decode_text, restart_trash_clock, write_source_marker
from app.unicode_ranges import HAN, KANA_LETTERS

log = logging.getLogger("surasura-cli")

SETTLE_S = 5                    # a file (or the video beside it) modified this recently may still be being written
PROGRESS_S = 0.2                # `progress` at most this often
BATCH = 25                      # files per `take_in`, per show: a take-in holds the write lock ~50 ms at most
LATE_BATCH = 200                # known subtitles' late videos recorded per write (`_late`: a row's UPDATE, ~0.1 ms)
CHECKPOINT_EVERY = 5            # take-ins between a look's PASSIVE checkpoints (a window never checkpoints by itself)
IN_MEMORY = 16 << 20            # a new text up to this size is read once: hashed and copied from memory
FOCUS_S = 5 * 60                # a look on the window's focus: at most this often
HOURLY_S = 60 * 60              # else, while a window is in front
CACHE_VERSION = 4               # 2: a folder's subtitle folders are listed with it; 3: a versions folder by its name;
                                # 4: a folder link is followed, and each root keeps its folders' notes (`notes`)
                                # alone (LF-1), never one guessed from what it holds
EPUB = BOOK_EXTENSIONS[0]                       # (path_utils.file_kind's book)
MIN_SCRIPT = 20                 # a text holding fewer characters of the language's script is no content (K6)
BOOK_MIN_CHARS = 1000           # a loose .txt / .md holding fewer of the script's characters is no content (T2-B4)
HEAD = 1 << 20                  # a text over IN_MEMORY is judged by this much of its start, read with its hash (B4)
SPLIT_AHEAD = 2                 # K5 C2: books split ahead of the look, per worker (their parts held: bounded memory)
_KANA = re.compile(f"[{KANA_LETTERS}]")      # kana letters: never ・ or ー (a Chinese name's separator, a dash)
_HAN = re.compile(f"[{HAN}]")
_BOOK_SCRIPT = {"ja": re.compile(f"[{KANA_LETTERS}{HAN}]"), "zh": _HAN}
_LOOSE = (".txt", ".md")        # a loose text: a book's worth or nothing; subtitles (.srt .ass .ssa) need no length
# a book's font obfuscation (IDPF's, Adobe's) hides only its fonts: no lock (B6)
_FONT_OBFUSCATION = ("http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC")
_FONTS = (".otf", ".ttf", ".woff", ".woff2")
_XMLENC = "{http://www.w3.org/2001/04/xmlenc#}"
_SUBS = frozenset({"subs", "subtitles", "subtitle", "sub", "字幕"})   # a folder of the subtitles of the videos above
# it (A11: `sub`, `字幕` too); inside one, a folder named like one of those videos holds that video's (`Subs/<video>/`)
# Item 11 (LF-1 / LF-2): a folder of other versions of the episodes above it, known by its NAME alone (casefolded,
# NFKC) — always listed with the folder above; any other subfolder (`Part 2`, `2期`, `Movie`) is never joined. The
# re-timer's words also end a subtitle's name as a versions mark (LF-17: `<video>.ja.synced.srt`); `.alt` on a file
# stays an unknown tag (an alternative translation is its own release)
_VERSIONS = en.RETIMED | {"versions", "alt", "alternate"}
_FOLDER_MARKS = re.compile(r"[\[\]()（）【】「」]|\b(?:subs?|subtitles?)\b|字幕")   # around a named folder's words
_SUB_WORDS = frozenset({"sub", "subs", "subtitle", "subtitles"})                      # a word's piece: `JPN_Subs`
# a language word's region or script code (`ja-JP`, `zh_CN`, `zh-Hant`: D2) — never any short word (`Chi-Bi`)
_CODES = frozenset({"jp", "cn", "tw", "hk", "sg", "mo", "hans", "hant", "jpan", "chs", "cht"})

_LANGS = en.LANGS                # LM1a: the one language table (`episode_names`), the folder rule's too
_RANK = {".ass": 0, ".ssa": 0, ".srt": 1}           # of one episode's subtitles in one language: the first taken
_OVERRIDE = re.compile(r"\{[^}]*\}")          # an .ass line's override tags (`{\\pos(…)}`, `{\\k20}`)
THIN = 4                        # A6: a pick holding under 1/THIN of its episode's fullest candidate's lines (a signs
                                # track) is never the episode's text while that one is
# Alpha 4 (Mattias's report: six show folders never arrived, nothing said): why a folder in a source isn't read — a
# look says it (`notes`), never drops a folder silently. A folder link (a junction, a symlink) is followed (`_link`).
NOT_READ_LINK_GONE = "It links to a folder that isn't there."
NOT_READ_LINK_OWN = ("It links to a folder Surasura doesn't read as a library (its own, a whole drive or your user "
                     "folder).")
NOT_READ_LINK_HOLDS = "It links to a folder that holds a folder Surasura reads already."
NOT_READ_SHORTCUT = ("It's a Windows shortcut: Surasura doesn't follow shortcuts. If it points to a folder of shows or "
                     "books, add that folder.")
NOT_READ_LOCKED = "Surasura couldn't open it (locked, busy or offline); the next look tries again."
NOT_READ_CLOUD = "It's in the cloud and not on this computer yet."
_GUARD = threading.Lock()
_RUNNING = set()                # stores a look is running on (their path keys): never two at once
_LOOKED = set()                 # (store, source) looked at in full this run: later looks list only what changed
_EMPTIED = set()                # A5K-2: the stores whose library folder this run's first look checked


def cache_path(language):
    """The folder-time cache, beside Connect's video index (`videos.index_path`'s folder)."""
    from app.connect import ledger
    return os.path.join(ledger.folder(), f"sources_{language}.json")


def due(now, focused, refreshed, last, shown=True):
    """Is a look due (SRC-9)? Pure: the shell asks on Refresh (`refreshed`), when its window comes to the front
    (`focused`) and on its hourly tick (neither); `last` = when the last look started (None: none yet this run);
    `shown` = False while the window is behind another or minimized. Refresh → now; the window's focus → at most once
    per FOCUS_S; else hourly; never while it is behind or minimized. A clock gone back counts as due."""
    if refreshed:
        return True
    if not shown:
        return False
    if last is None or now < last:
        return True
    return now - last >= (FOCUS_S if focused else HOURLY_S)


def local_or_network(path):
    """'local' (a watch follows it: S10 / D5) or 'network' (the cadence looks at it): a UNC path, a mapped share, a
    CD or a drive Windows can't name is 'network'. Elsewhere than Windows: 'local'."""
    if sys.platform != "win32":
        return "local"
    full = os.path.abspath(path)
    if full.startswith("\\\\"):
        return "network"
    drive = os.path.splitdrive(full)[0]
    if not drive:
        return "network"
    try:
        import ctypes
        kind = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
    except (AttributeError, OSError):
        return "network"
    return "local" if kind in (2, 3, 6) else "network"   # REMOVABLE · FIXED · RAMDISK


def scan(store, language, root, first=False, progress=None, stop=None, full=False, rules=None, copying=None):
    """One look at the source `root` (its id) -> {reachable, found, shows, added, attached, skipped, short, waiting,
    recopied, restored, paired, switched, switched_works, stopped, busy, ids} (`short`: of those skipped, the loose
    texts too short to be a book, T2-B4; `paired`: known texts whose video was found and recorded on them, `_late` —
    "12 episodes found their videos"; `switched`: items that took a better version or a book's new edition in place,
    LM3; `switched_works`: their titles — each one's switch is its last switch, `Store.last_switch`, undone by
    `Store.undo_switch(work)`: the window's note "1 book updated to its new edition · Undo").
    `first`: setup's own first scan (SRC-1: Current, quiet); `full`: Refresh (S4); `progress(found, shows)` every
    PROGRESS_S; `stop()` is asked between files (a stopped look keeps what it took in, whole); `rules`: the placing
    rules `take_in` applies to an arrival. A source not being read raises NotASource. `copying(done, total)` (K5: a
    25,000-book first look said nothing for hours once its listing was done) every PROGRESS_S while the new files and
    books found are checked, copied and taken in: how many of them are done.
    Another look at the same store running → {"busy": True}, nothing done."""
    key = _store_key(store)
    with _GUARD:
        if key in _RUNNING:
            return _result(busy=True)
        _RUNNING.add(key)
    try:
        if key not in _EMPTIED:                 # A5K-2: before this run's first look puts any copy back (item 8a)
            try:
                store.note_emptied()
                _EMPTIED.add(key)               # (a check that failed — the store busy — is tried at the next look)
            except Exception as e:              # (never in the look's way: the card just isn't asked)
                print(f"Sources: the library folder couldn't be checked: {e!r}")
        return _Look(store, language, root, first, progress, stop, full, rules, copying).run()
    finally:
        with _GUARD:
            _RUNNING.discard(key)


def _store_key(store):
    return ls.path_key(os.path.abspath(store.db_path))


def _result(**values):
    out = {"reachable": True, "gone": False, "found": 0, "shows": 0, "added": 0, "attached": 0, "skipped": 0,
           "short": 0, "waiting": 0, "recopied": 0, "restored": 0, "paired": 0, "switched": 0, "stopped": False,
           "busy": False, "ids": [], "switched_works": []}
    out.update(values)
    return out


def _key(path):
    """An origin's key in `origins()` / `excluded()`: the path key of its absolute path."""
    return ls.origin_key(path)[len(ls.SOURCE_KEY):]


def _tag(name):
    """(the name's stem without its marks, its language: 'ja', 'zh', 'other' or None, its flags) — LM1a's one reading
    (`episode_names.identity`): dot tags from the right (`ep01.ja.forced.srt` → ('ep01', 'ja', {'forced'}); `.hi` is
    Bazarr's hearing-impaired, never Hindi), a bracket of marks (`[CHS]`, `[jpn]`), `_track3_[jpn]`, `3_Japanese`; a
    tag no list holds stays part of the stem (untagged); two languages in one mark (`.chs&jpn`) read None here (see
    `_episodes`). A versions mark (`.synced`, `.retimed`, either side of the language, LF-17) is no flag: it comes off
    the stem, so the file is that video's episode (`_marked` says it was there)."""
    n = en.identity(name)
    return n.stem, n.language, set(n.flags)


def _marked(name):
    """LF-17: does the name end in a versions mark (`<video>.ja.synced.srt`, `<video>.synced.ja.srt`)? Ranked as a
    versions folder's file is (`_episodes`' order)."""
    return en.identity(name).retimed


def _episode_of(name):
    """(the episode number LM1a's rule reads in a file name — K4's markers, a range's first, a special's own — or
    None; its version: 2 for `- 05v2`, else 1)."""
    n = en.identity(name)
    return n.episode, n.version


def _release(name):
    """H13: a file name without its release's marks (`[group]`, `(1080p)`, a resolution or hash, a version, its
    language tag and extension), folded: two releases of one episode whose names differ only there have the same."""
    return en.identity(name).release


def _kind(name):
    """I9: a subtitle file's kind as the one rule reads it, lower the better — (bilingual, flagged: a signs-only track,
    karaoke): a plain one-language file first. The one order of kinds: the look's pick (`_episodes`' order) and a later
    version (`_new`: it replaces a file of its own kind or a worse one, never a better) both read it."""
    n = en.identity(name)
    return n.bilingual, bool(n.flags)


def subtitle_rank(name, language, named=False, folder_language=None, versions_folder=False, group=None):
    """The ONE order of one episode's subtitles (Sonic, the library model 2, T2-A1, LM2; PROVISIONAL, to be checked in
    use), lower first: a bilingual file after every one-language file (LM1a-Q1); named exactly like its video
    (`named`: made for it, timed to it) and plain; then, among the rest, the show's `group` (LM2: once the show has
    one; a flagged track is never helped by it); our language's tag (`folder_language`: the language its folder
    names); plain before flagged; a versions folder's (`synced/`) or a re-timer's mark; `.ass` / `.ssa` before
    `.srt`; the name. The look's pick (`_Look._episodes`) and the store's choice of a group's copy for an episode
    (`Store.other_subtitles`, `Store.switch_group`) both read it."""
    n, (bilingual, flagged) = en.identity(name), _kind(name)
    return (bilingual, flagged or not named,
            group is not None and (flagged or _group(name) != tuple(group)),
            (n.language or folder_language) != language, flagged, not n.retimed and not versions_folder,
            _RANK.get(os.path.splitext(name)[1].lower(), 2), name)


def version_rank(name, language, named=False, folder_language=None, versions_folder=False, group=None):
    """`subtitle_rank` after the release: the latest first (`- 05v2` over `- 05`, as the look keeps an episode's latest
    version, D6) — the best of one group's files of an episode (`Store.other_subtitles`, `Store.switch_group`) and the
    pick that decides a show's group (`_Look._decide_groups`)."""
    return (-en.identity(name).version,) + subtitle_rank(name, language, named, folder_language, versions_folder, group)


def video_names(paths):
    """The names a subtitle is "named like" (`named_like`): each video's name without its extension, in NFC, lowered."""
    return {_nfc(os.path.splitext(os.path.basename(v))[0]).lower() for v in paths}


def named_like(name, like, folder=None):
    """T2-A1: is the subtitle `name` named exactly like one of the videos `like` (`video_names`) — the names Connect
    pairs (`video_stems`: `ep01.alt.srt`, a language tag or nothing added), or in the folder named as it
    (`Subs/<video>/`, A11)? The look's order and the store's choice of a group's copy both ask it."""
    return any(_nfc(s).lower() in like for s in en.video_stems(name)) or         (folder is not None and _nfc(folder).lower() in like)


def in_versions_folder(path, language):
    """Is `path` in a versions folder of its show's (item 11: `synced/`, `retimed/`, by the folder's name alone)?"""
    folder = os.path.dirname(path)
    return _subtitle_folder(os.path.basename(folder), os.path.basename(os.path.dirname(folder)), language) == "versions"


def group_copies(picks, versions, language):
    """LM2 / LM3, the ONE reading of an episode's copies by group (pure: the store's `_group_copies` and the look's
    better-version check both ask it): `picks` / `versions` = [(key, record)] of the item's own origins and of its
    other versions (a record's `origin`, `sha256`, `video_path`) -> (the pick's group, the pick's rank, {group: (key,
    rank)} — of each group the version the look would pick: `version_rank` against the pick's video, never a flagged
    track (signs, karaoke), a bilingual file, a double-episode file, the pick's own bytes or one the switch passes
    over while its file is as judged — the learner's Undo declined it, or it was too thin: `passed_over`, LM3)."""
    pick = next((r for _k, r in picks if r.get("video_path")), picks[0][1])
    video = pick.get("video_path")
    like = video_names([video] if video else ())
    shas = {r.get("sha256") for _k, r in picks}

    def rank(origin):
        name, folder = os.path.basename(origin), os.path.basename(os.path.dirname(origin))
        return version_rank(name, language, named_like(name, like, folder), _folder_language(folder),
                            in_versions_folder(origin, language))
    best = {}
    for key, record in versions:
        origin = str(record.get("origin") or "")
        if not origin or record.get("sha256") in shas or passed_over(record):
            continue
        n = en.identity(os.path.basename(origin))
        if n.flags or n.bilingual or len(n.episodes) > 1:
            continue                                 # never the text: a signs track, two languages, two episodes
        r, group = rank(origin), _group(os.path.basename(origin))
        if group not in best or r < best[group][1]:
            best[group] = (key, r)
    origin = str(pick.get("origin") or "")
    return _group(os.path.basename(origin)), rank(origin), best


def passed_over(record):
    """LM3 (S19): a version the switch passes over while it holds the bytes it was judged on — the learner's Undo
    declined it (`declined`) or it held too few lines (`thin`, A6): the flag holds those bytes' sha256 (A4: a file
    only touched keeps it; its bytes changed, the record's sha follows them — `_Look._changed` — and it is judged
    again)."""
    sha = record.get("sha256")
    return bool(sha) and any(record.get(flag) == sha for flag in ("declined", "thin"))


def better(rank, than):
    """LM3 (answer 3; PROVISIONAL, to be checked in use): does a version ranked `rank` beat the item's text ranked
    `than` in the look's own order (`version_rank`: a later release, named like its video, our tag, plain, a versions
    folder or mark, `.ass` before `.srt`) — on more than the order's last step, its name, so two copies told apart by
    their names alone never switch?"""
    return tuple(rank[:-1]) < tuple(than[:-1])


def dialogue_lines(text):
    """A6: a subtitle's dialogue lines — the distinct texts of its `Dialogue:` lines (.ass / .ssa: override tags `{…}`
    off, a sign drawn frame by frame once) or of its cues (.srt), by what it holds; 0 for none (a text, not a
    subtitle). The look's thin rule (`_Look._lines`) and the store's better-version switch count with it."""
    said = set()
    for line in text.splitlines():
        if line.lstrip().startswith("Dialogue:"):
            said.add(_OVERRIDE.sub("", line.split(",", 9)[-1]).strip())
    if not said and "-->" in text:
        for cue in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
            lines = cue.strip().split("\n")
            at = next((i for i, x in enumerate(lines) if "-->" in x), None)
            if at is not None:
                said.add(" ".join(x.strip() for x in lines[at + 1:]))
    said.discard("")
    return len(said)


# T2-B6 (LM3, PROVISIONAL; IK-L3-4): an edition vs a volume is one name reading, beside the others
edition_name = en.edition_name


def book_parts(path, language, by=None):
    """K8 / T2-B6 (LM3; LM7 calls it too), the ONE EPUB → parts splitter: the parts as a book's copies hold them
    (Extract's reader and its default split, UTF-8; by its chapters unless `by` — else the `split_books_by` setting —
    says "even") -> ([BookPart], None), or (None, why): "locked" (its encryption.xml
    locks more than its fonts: a shop's DRM, B6) or "text" (no text, or none of the library's language: K6, an English
    translation). A new book (`_Look._book`), a book's new edition and a book whose parts' copies are lost (split again
    from its EPUB when the EPUB's sha256 is the record's, LM7) all read their parts here."""
    from app import extract
    if _locked(path):
        return None, "locked"
    parts, error = extract.parts_of(path, language, by=by)
    if error or not parts or _refusal("".join(p.text for p in parts), language):
        return None, "text"
    return [BookPart(p.text.encode("utf-8"), extract.part_label(p.chapter), p.chapter) for p in parts], None


# A book's part (`book_parts`): its bytes, its name's label after its number (`extract.part_label`: None for an even
# part) and its place in the book (`extract.book_split`'s record, kept on its origin record as "chapter")
BookPart = namedtuple("BookPart", "data label chapter")
_CHAPTER_TAIL = re.compile(r" \(\d+(?:-\d+)?\)(?: .*)?")       # a chapter's label after a part's `_NN`


def _part_stem(stem, number):
    """A book's part's file stem whose part number is `number` -> (its book's base, named by a chapter?), or None:
    the last `_NN` that is that number with nothing, or a chapter's label (`extract.part_label`), after it."""
    for m in reversed(list(re.finditer(r"_([0-9]{2,})", stem))):
        rest = stem[m.end():]
        if int(m.group(1)) == number and (not rest or _CHAPTER_TAIL.fullmatch(rest)):
            return stem[:m.start()], bool(rest)
    return None


def part_names(base, count, labels=None):
    """A book's parts' file names (`book_parts`' order, `extract.part_name`): `<base>.txt` for one part, else
    `<base>_01.txt` …, a chapter's part `<base>_01 (1) プロローグ.txt`."""
    from app import extract
    return [extract.part_name(base, i, count, labels[i - 1] if labels else None) for i in range(1, count + 1)]


def group_label(name):
    """LM2: a subtitle group as a learner reads it — its leading `[tag]` as written (`SubsPlease`), else the name before
    its episode marker (`星空喫茶`), else the file name."""
    m = re.match(r"\s*\[([^\]]*)\]", unicodedata.normalize("NFKC", name))   # the leading tag `identity` reads
    return m.group(1).strip() if m and m.group(1).strip() else (en.identity(name).show or os.path.splitext(name)[0])


def _key_order(key):
    """An episode key's place among a show's (LM2's "earliest episode"): numbered episodes by season, number and part
    before specials; mixed types never compared."""
    _show, season, episode, part, special = key
    return (special is not False, str(special), season if isinstance(season, int) else 0,
            episode if isinstance(episode, (int, float)) else 0, part or 0, str(key))


def _show_key(show):
    """A show's `Library/<show>` folder key (as the store groups a show's title)."""
    return ls.folder_key_of(f"{ls.CONTENT_FOLDER}/{show}/x")


def _video_rank(low, vids):
    """A5 (PROVISIONAL): of several videos of one episode, the one Connect uses — not marked Dual / Dub / Multi
    (`episode_names.dubbed`), then the largest, then the first by name."""
    return en.dubbed(low), -vids[low][1].st_size, low


def episode_key(name, language, years=None):
    """LM1a: the episode a file name reads (`episode_names.identity`'s key: show without its season, season, episode,
    part, special), its show folded for the library's language (`search_fold`: Chinese Traditional as Simplified too)
    — two releases of one episode have the same; None when it reads no episode. A3 (PROVISIONAL): a year the name
    writes keeps it apart only in a show whose names write two years or more (`years()`: those years — the look's,
    `_Look._years`) — two remakes; else, and with no `years`, `Show (2019) - 05` is `Show - 05`."""
    n = en.identity(name)
    if n.episode is None:
        return None
    k = n.key
    if n.year and years is not None and len(years()) < 2:
        k = (k[0][:-len(f" ({n.year})")],) + k[1:]
    return (ls.search_fold(k[0], language),) + k[1:]


def video_keys(vids, language):
    """A4: [(video, its episode key)] of a folder's videos (`vids`: {listing key: (path, stat)}) — never a special's
    nor an extra's (`episode_names.extra`)."""
    return [(v, vk) for v, vk in ((v, episode_key(v, language)) for v in sorted(vids))
            if vk and not vk[4] and not en.extra(v)]


def video_for(name, vids, language, keyed=None):
    """LM1b, the ONE pairing rule: the video a text found in a folder goes with -> (its key in `vids` — {listing key:
    (path, stat)}, `_listing`'s —, 'name' | 'number') or (None, None). A loose `.txt` / `.md` only by its exact stem
    (T2-B3); a subtitle by its name — its stem, then the names Connect pairs (`videos.names_for`) — else by its
    episode's key among the folder's videos (A4: never a special's, and only where the names' shows agree or the
    folder's videos carry one show). Of several videos of one episode (A5, their keys alike; never an extra's,
    `episode_names.extra`): one not marked Dual / Dub / Multi, then the largest, then the first by name
    (`_video_rank`). `keyed()`: the folder's `video_keys` (the look reads them once). The look's rule (`_Look`, which
    also reads `Subs/<video>/`, A11) and setup's video file (`subtitles_for_video`). PROVISIONAL (Sonic 2026-10-21:
    accepted for building, to be checked in use)."""
    from app.connect import runner, videos
    if not vids:
        return None, None
    if name.lower().endswith(_LOOSE):
        stem = os.path.splitext(name)[0]
        v = next((c.lower() for c in (stem + e for e in runner.VIDEO_EXTENSIONS) if c.lower() in vids), None)
        return (v, "name") if v else (None, None)
    for candidate in [_tag(name)[0] + e for e in runner.VIDEO_EXTENSIONS] + videos.names_for(name):
        if candidate.lower() in vids:
            return candidate.lower(), "name"
    k = episode_key(name, language)
    if k is None or k[4]:
        return None, None
    keyed = keyed() if keyed is not None else video_keys(vids, language)
    one = len({vk[0] for _v, vk in keyed}) == 1
    same = [v for v, vk in keyed if vk[1:] == k[1:] and (one or vk[0] == k[0])]
    return (min(same, key=lambda v: _video_rank(v, vids)), "number") if same else (None, None)


def subtitles_for_video(path, language):
    """(A worker; alpha 8, setup's *Choose a file…* given a video.) The subtitles beside the video `path` that the one
    pairing rule (`video_for`) gives to it, best first (`subtitle_rank`: named like it, our language, plain…); a
    loose text or one tagged for another language is never one. None given to it, but its episode's subtitles given
    to another release of the same episode (A5: the plain one, never a Dual / Dub copy) -> those (the learner picked
    the copy they watch). Only the video's own folder is read (its `Subs/` folder: *Choose its folder*). -> [paths];
    [] when none (or the folder can't be read)."""
    folder = os.path.dirname(os.path.abspath(path))
    listed = _listing(folder)
    if listed is None:
        return []
    texts, _epubs, vids, _subs, _ghosts, _unread = listed
    me = os.path.basename(path).lower()
    if me not in vids:
        try:
            vids = dict(vids, **{me: (path, os.stat(path))})     # a small file Connect's rule passes over: still it
        except OSError:
            return []
    stem = os.path.splitext(os.path.basename(path))[0]
    keys = video_keys(vids, language)                    # read once for the folder (as the look keeps them)
    mine = episode_key(me, language)
    found, episode = [], []
    for name, full, _st in texts:
        if name.lower().endswith(_LOOSE) or _tag(name)[1] not in (None, language):
            continue
        v, _by = video_for(name, vids, language, keyed=lambda: keys)
        rank = (subtitle_rank(name, language, named=_tag(name)[0] == stem), full)
        if v == me:
            found.append(rank)
        elif v is not None and mine is not None and episode_key(v, language) == mine:
            episode.append(rank)
    return [full for _rank, full in sorted(found or episode)]


def _group(name):
    """A8 (LM1a's `group`): a file's release group — its leading `[tag]` and the name before its episode marker,
    folded: a later release follows the pick of its own group only."""
    return en.identity(name).group[:2]


def _nfc(name):
    """A name in NFC, as names are compared (A24: a Mac's or a zip's NFD name is the same name)."""
    return unicodedata.normalize("NFC", name)


def _subtitle_folder(name, parent, language):
    """The ONE named-folder rule (item 11, LF-1, LF-15, LF-16): is the subfolder `name` of the folder `parent` (its
    name) listed with it — its texts the folder's own — by its NAME alone (NFKC, casefolded), never by what it holds?
    -> "versions" (`_VERSIONS`: `synced`, `retimed`, `alt`…: other versions of the episodes above), "subs" (`Subs`,
    `Subtitles`; the show folder's own name — a download unpacked into it, LF-16), the library's language (a folder
    named only for it — `JP`, `[Japanese]`, `Japanese Subs`, `中文字幕`, `CHS&CHT`, `Chinese (Simplified)` — by the
    language names `Subs/<language>/` reads, `_LANGS`: its untagged texts are that language's, LF-15), or None:
    `Part 2`, `Movie`, `English`, `<Show> [archive]`, `JP-Story` — a folder of its own.
    The name is read WHOLE (D2, D3): brackets and Subs / 字幕 off (`_FOLDER_MARKS`), split into words at spaces and
    `& + ,`, each word into pieces at `-` / `_`. A versions folder: a versions word, the rest versions, language or
    subtitle words (`Synced Subs`, `[Synced]`, `synced_ja`, `Retimed (JP)`). Our language's: every word ours — a
    language word, alone or with region / script codes (`ja-JP`, `zh_CN`, `zh-Hant`, `JPN_Subs`: `_CODES`)."""
    folded = unicodedata.normalize("NFKC", name).strip().casefold()
    if folded in _SUBS or folded == unicodedata.normalize("NFKC", parent).strip().casefold():
        return "subs"
    words = [w for w in re.split(r"[\s&+,]+", _FOLDER_MARKS.sub(" ", folded)) if w]
    pieces = [p for w in words for p in re.split(r"[-_]", w) if p]
    if any(p in _VERSIONS for p in pieces) and all(p in _VERSIONS or p in _LANGS or p in _SUB_WORDS for p in pieces):
        return "versions"
    return language if words and all(_word_language(w) == language for w in words) else None


def _video_named(name, vids):
    """A11: the video (its listing key) a subtitle folder's subfolder is named like (`Subs/<video name>/`: the name in
    NFC, case-folded, against the video's without its extension), or None."""
    want = _nfc(name).strip().casefold()
    return next((v for v in sorted(vids) if _nfc(os.path.splitext(v)[0]).casefold() == want), None)


def _word_language(word):
    """The language one word of a folder's name names (`japanese`, `ja-jp`, `jpn_subs`, `中文`), or None — a word with
    any piece that is no language, region / script code or subtitle word (`jp-story`, `chi-bi`) names none."""
    head, *rest = re.split(r"[-_]", word)
    if head in _LANGS and all(r in _CODES or r in _SUB_WORDS for r in rest):
        return _LANGS[head]
    return _LANGS.get(word)


def _folder_language(name):
    """The language a folder inside a subtitle folder is named for (`Subs/ja`, `Subs/English`, `Subs/zh-Hans`):
    'ja', 'zh', 'other', or None (no language: an ordinary folder)."""
    return en.language_of(name)


def _show_of(root, parts, name, folders=()):
    """`Library/<show>`'s show (§1, S12): the folder below the source as written (`Frieren/Season 1`); a season or
    specials folder alone gets the source folder's name in front; a loose file's show is K4's reading of its name,
    else the source folder's name. a8 (Sonic 2026-10-31; PROVISIONAL): a loose EPISODE (its name holds an episode
    number: never a book, whose show is its name) whose show is one of the source's own top folders by the one "same
    show?" key (`folders`: `_show_folders`' (name, key) pairs; `episode_names.show_key`: `Show!/` and `Show - 02.mkv`)
    is that folder's show, so its copy lands in that folder's `Library/<show>` (one folder key, one title): the one
    folder of that key — two or more (`Show!/`, `Show~/`): its own show, as before (a folder named exactly as it is
    its own show's folder key already). A title of `episode_names.SHOW_KEY_EXCEPTIONS` (`Gintama'`) has a key of its
    own. New copies only: nothing already copied moves."""
    from app.extract import clean_name
    root_name = clean_name(os.path.basename(os.path.normpath(root))) or "Source"
    if parts:
        if en.season_folder(parts[0]) is not None:
            parts = [root_name] + list(parts)
        return "/".join(parts)
    show = clean_name(ls.show_of_name(name) or "")
    key = en.show_key(show) if folders and en.identity(name).key[2] is not None else ""
    same = [f for f, k in folders if k == key] if key else []
    if len(same) == 1:
        return same[0]
    return show or root_name


def _show_folders(subs):
    """a8: a source's top folders a loose episode may be the show of (`_show_of`) -> [(name, `show_key`)], each folded
    once a look: never a season or specials folder (no show of its own), never one with no letter or digit."""
    out = []
    for path in subs:
        name = os.path.basename(os.path.normpath(path))
        key = en.show_key(name) if en.season_folder(name) is None else ""
        if key:
            out.append((name, key))
    return out


def _library_show(rel):
    """D3: the show of an item's copy `Library/<show>/<file>` (its folder below Library), or None (a 2.x tier's)."""
    parts = str(rel or "").split("/")
    if len(parts) < 3 or ls.path_key(parts[0]) != ls.path_key(ls.CONTENT_FOLDER):
        return None
    return "/".join(parts[1:-1])


def _copy_part(origin, part, size=None):
    """The original's bytes into `part` (ours: a `.part` in the data folder) -> their sha256; None when `size` is given
    and the bytes read are not that many (the record names the listing's size: a copy of another length never matches
    it)."""
    h = hashlib.sha256()
    count = 0
    with open(origin, "rb") as src, open(part, "wb") as dst:
        for block in iter(lambda: src.read(1 << 20), b""):
            h.update(block)
            dst.write(block)
            count += len(block)
        dst.flush()
        os.fsync(dst.fileno())
    return None if size is not None and count != size else h.hexdigest()


def _lost(root):
    """Is the source folder itself gone (offline, renamed away)? Asked when a folder below it can't be read."""
    return not os.path.isdir(root)


REACHED, AWAY, GONE = "reached", "away", "gone"
_SEPARATORS = os.sep + (os.altsep or "")


def _not_found(e):
    """A plain *not found* (Windows' 2 / 3): the folder isn't there. A share's own answer (53 *the network path was not
    found*, 67, 1231…) is Python's FileNotFoundError too, but it says nothing about the folder: away."""
    return isinstance(e, FileNotFoundError) and getattr(e, "winerror", None) in (None, 2, 3)


def _volume_at(path):
    """The volume `path` is on (its `st_dev`: Windows' volume serial)."""
    return os.stat(path).st_dev


def _system_volume(dev):
    """Is `dev` Windows' own volume (`%SystemDrive%`) — the one volume no stick or share can take the place of?"""
    if sys.platform != "win32":
        return False
    try:
        return os.stat(os.environ.get("SystemDrive", "C:") + os.sep).st_dev == dev
    except OSError:
        return False


def reach(path, dev=None, error=None):
    """T6 (Sonic 2026-10-24: the lean, exactly): a source folder's reach -> REACHED (a folder there: what it holds is
    the look's — this rule judges only a folder that ISN'T there), GONE (moved or deleted while its drive is there) or
    AWAY (anything else: an unplugged drive, a share or NAS down, a parent that can't be read — it may come back).
    When unsure, AWAY (a wrong *gone* offers *Stop reading it* and lets D5 mark; a wrong *away* only
    waits). GONE only when the first folder above it that still exists (the folder above, or higher when that moved
    too) LISTS, holds nothing of its name, and is on the volume the folder was last read on (`dev`, the look's record:
    another stick or USB disk at the same letter, a folder that was a mounted volume, is away) — with no volume
    recorded yet (a folder last read before this rule), only on Windows' own volume (`_system_volume`: no stick or
    share takes its place; off Windows, away). Never for a drive's or a share's root (nothing above it), never for a
    name still listed but unreadable (a folder link to a drive that's away). Any answer but a plain *not found*
    (`_not_found`: a share down, access denied) is away at once — one wait (G5); `error`: the look's own failed stat
    of the folder, never asked again. A file where the folder was is no folder: gone."""
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    if not rest.strip(_SEPARATORS):
        return AWAY                                  # a drive's or a share's root: nothing above it to read
    folder = drive + rest.rstrip(_SEPARATORS)
    st = None
    if error is None:
        try:
            st = os.stat(folder)
        except OSError as e:
            error = e
    if error is not None and not _not_found(error):
        return AWAY
    if st is not None and stat.S_ISDIR(st.st_mode):
        return REACHED
    child, parent = folder, os.path.dirname(folder)
    while True:                                      # the first folder above that is there
        try:
            with os.scandir(parent) as listing:
                listed = any(ls.path_key(e.name) == ls.path_key(os.path.basename(child)) for e in listing)
            here = _volume_at(parent)
            break
        except OSError as e:
            up = os.path.dirname(parent)
            if not _not_found(e) or ls.path_key(up) == ls.path_key(parent):
                return AWAY                          # unreadable, or the drive's root not there: away
            child, parent = parent, up
    if listed and (child != folder or st is None):
        return AWAY                                  # listed, yet not found: a link to a drive that's away
    return GONE if (here == dev if dev is not None else _system_volume(here)) else AWAY


def _volume(held, path):
    """The volume a cache entry says its folder was last read on (`reach`'s `dev`), when it is `path`'s, else None."""
    if isinstance(held, dict) and path and held.get("path") == ls.path_key(path) and isinstance(held.get("dev"), int):
        return held["dev"]
    return None


def volume_of(store, language, root_id, path):
    """T6: the volume the source `root_id` (at `path`) was last read on — the folder-time cache's record — or None."""
    meta = store.meta()
    cache = _load_cache(language, (meta.get("store_id"), meta.get("epoch")))
    return _volume(cache["roots"].get(str(root_id)), path)


def _read_text(path, st):
    """(the new text's bytes when it is small enough to keep in memory, else None; its sha256; the bytes `_refusal`
    judges — all of them, or a text over IN_MEMORY's first HEAD, B4): read once, a big one hashed block by block.
    (None, None, None) when the bytes read are not as many as the listing's size (the record names that size): it
    waits."""
    if st.st_size > IN_MEMORY:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            head = f.read(HEAD)
            h.update(head)
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return None, h.hexdigest(), head
    with open(path, "rb") as f:
        data = f.read()
    if len(data) != st.st_size:
        return None, None, None
    return data, hashlib.sha256(data).hexdigest(), data


def _count(pattern, text, most):
    """How many of `pattern`'s characters `text` holds, counted up to `most` (no further: a book is never counted
    whole)."""
    return sum(1 for _m in zip(range(most), pattern.finditer(text)))


def _refusal(data, language, loose=False, head=False):
    """K6, the ONE rule every text and book a look finds passes: why it is not the library's content, or None when it
    is. `data`: a new text's bytes (`head`: a big text's first HEAD bytes, a character cut at their end no damage), or
    an EPUB's extracted text.
    - "script": Japanese needs at least MIN_SCRIPT kana letters — Han without kana is Chinese (a Chinese fansub, a
      Chinese novel: B5); Chinese at least MIN_SCRIPT Han and fewer than MIN_SCRIPT kana letters (a text holding
      kana is Japanese). A loader's skin config, an English `.srt` or log, an English EPUB: neither.
    - "short" (`loose`: a `.txt` / `.md`, T2-B4): fewer than BOOK_MIN_CHARS characters of the script (ja: kana + Han;
      zh: Han) — a readme, a lyric sheet, a note; a big text's first megabyte counting that many is enough.
      Subtitles and EPUBs: the first rule alone.
    Bytes are decoded by `path_utils.decode_text` (the rule a file he supplies is read by); bytes all ASCII never."""
    if data.isascii():
        return "script"
    text = data if isinstance(data, str) else decode_text(data, language, head=head)
    if language == "zh":
        ours = _count(_KANA, text, MIN_SCRIPT) < MIN_SCRIPT and _count(_HAN, text, MIN_SCRIPT) >= MIN_SCRIPT
    else:
        ours = _count(_KANA, text, MIN_SCRIPT) >= MIN_SCRIPT
    if not ours:
        return "script"
    if loose and _count(_BOOK_SCRIPT.get(language, _BOOK_SCRIPT["ja"]), text, BOOK_MIN_CHARS) < BOOK_MIN_CHARS:
        return "short"
    return None


def _locked(path):
    """B6: does the EPUB's `META-INF/encryption.xml` encrypt anything beyond its fonts — a shop's DRM (Adobe's,
    Readium LCP, Apple's)? Its text read as text would be mojibake words. A font obfuscated (IDPF's, Adobe's way) or
    a font file encrypted is no lock; one whose encryption.xml can't be read is locked. Not a zip: no (Extract says
    it has no text)."""
    import zipfile
    from xml.etree import ElementTree
    try:
        with zipfile.ZipFile(path) as z:
            try:
                raw = z.read("META-INF/encryption.xml")
            except KeyError:
                return False
    except (OSError, zipfile.BadZipFile):
        return False
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return True
    for data in root.iter(_XMLENC + "EncryptedData"):
        method = data.find(_XMLENC + "EncryptionMethod")
        ref = data.find(f".//{_XMLENC}CipherReference")
        uri = (ref.get("URI") if ref is not None else None) or ""
        if (method.get("Algorithm") if method is not None else None) not in _FONT_OBFUSCATION \
                and not uri.lower().endswith(_FONTS):
            return True
    return False


def _write_part(part, data):
    """`data` into `part` (ours: a `.part` in the data folder), flushed to the disk before it is renamed."""
    with open(part, "wb") as dst:
        dst.write(data)
        dst.flush()
        os.fsync(dst.fileno())


def _dated(part, st):
    """(a7) The copy keeps its original's date, as every copy the store makes does (`moves._copy_whole`'s `copystat`):
    when an episode appeared is the original's time, never the look's — a first look at a weekly show reads as weekly
    (`view_rows.still_arriving`). A copy whose date can't be set keeps the look's (as before)."""
    try:
        os.utime(part, ns=(st.st_mtime_ns, st.st_mtime_ns))
    except (OSError, AttributeError):
        pass


def _write_parts_at_once(pool, jobs):
    """K5 C2: [(a `.part`, its bytes)] each written and flushed (`_write_part`), by `pool`'s threads when there is one
    (a file's write and flush let go of the GIL). Every write has ended before this returns or raises (the first
    error, in `jobs`' order), so a `.part` dropped after a failure is never written again behind the caller's back; after
    a failure the writes not started yet are cancelled (the book waits whole); a pool that shut meanwhile (the app
    closing) leaves the rest to this thread."""
    if pool is None or len(jobs) < 2:
        for part, data in jobs:
            _write_part(part, data)
        return
    import concurrent.futures
    futures = []
    try:
        for part, data in jobs:
            futures.append(pool.submit(_write_part, part, data))
    except RuntimeError:                                     # shut: the rest written here, after the pool's
        pass
    concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)
    for f in futures:
        f.cancel()                                           # a failure: the rest needn't be written
    concurrent.futures.wait(futures)
    for f in futures:
        if not f.cancelled():
            f.result()
    if any(f.cancelled() for f in futures):                  # cancelled only after an error raised above
        raise OSError("a part's write was cancelled")
    for part, data in jobs[len(futures):]:
        _write_part(part, data)


_SPLIT_KNOWN = frozenset()      # K5 C2, in a splitting worker: the sha256s of the books in or kept out (`_split_start`)


def _split_start(known):
    """A splitting worker's start (K5 C2): the books' sha256s it needn't split, given once; it never outlives the
    look's process — on Windows a killed parent leaves the pool's pipe open (as the indexer's workers,
    `token_index._pool_start`)."""
    global _SPLIT_KNOWN
    _SPLIT_KNOWN = frozenset(known)
    import multiprocessing
    parent = multiprocessing.parent_process()
    if parent is not None:
        def watch():
            parent.join()
            os._exit(1)
        threading.Thread(target=watch, name="split-parent-watch", daemon=True).start()


def _split(path, language, by):
    """K5 C2, in a worker process: an EPUB as it stood -> (size, mtime_ns, sha256, its parts (`book_parts`, the one
    splitter) or None, the parts' sha256s, split?) — not split when its bytes are a book in or kept out already
    (`_SPLIT_KNOWN`: the look needs only its hash then); None when it changed while read or couldn't be read (the look reads
    it itself)."""
    try:
        st = os.stat(path)
        sha = ls.sha256_of(path)
        data = shas = None
        split = sha not in _SPLIT_KNOWN
        if split:
            data, _why = book_parts(path, language, by=by)
            shas = [hashlib.sha256(p.data).hexdigest() for p in data] if data else None
        now = os.stat(path)
    except Exception:
        return None
    if (now.st_size, now.st_mtime_ns) != (st.st_size, st.st_mtime_ns):
        return None
    return st.st_size, st.st_mtime_ns, sha, data, shas, split


class _Splitter:
    """K5 C2 (the large-library copy): the new books' EPUBs, in the look's own order, hashed and split by worker
    processes a few ahead of it (SPLIT_AHEAD per worker); the look — ONE writer — still checks, writes and takes
    each book in, asking `take` for the work done. Anything a worker couldn't do, the look does itself."""

    def __init__(self, paths, language, size, known):
        import concurrent.futures
        import multiprocessing
        from app import extract
        self.paths, self.language, self.by = list(paths), language, extract._settings_by()
        self.where = {p: i for i, p in enumerate(self.paths)}
        self.ahead, self.next, self.futures = size * SPLIT_AHEAD, 0, {}
        self.pool = concurrent.futures.ProcessPoolExecutor(size, mp_context=multiprocessing.get_context("spawn"),
                                                           initializer=_split_start, initargs=(sorted(known),))
        self._fill(0)

    def _fill(self, at):
        self.next = max(self.next, at)                       # never a book the look has passed (skipped ones)
        try:
            while self.next < len(self.paths) and self.next < at + self.ahead:
                path = self.paths[self.next]
                self.futures[path] = self.pool.submit(_split, path, self.language, self.by)
                self.next += 1
        except Exception as e:                               # a pool that broke: the look reads the rest itself
            log.info("Splitting books ahead stopped (the look reads them itself): %r", e)
            self.next = len(self.paths)

    def take(self, path):
        """This EPUB's work, once its worker is done -> `_split`'s answer, or None (none asked, or it failed)."""
        future = self.futures.pop(path, None)
        if path in self.where:
            at = self.where[path]
            for early in [p for p in self.futures if self.where[p] < at]:   # books the look passed by: let go of
                self.futures.pop(early).cancel()                             # their parts (bounded memory)
            self._fill(at + 1)
        if future is None:
            return None
        try:
            return future.result()
        except Exception as e:
            log.info("A book split ahead failed (the look reads it itself): %r", e)
            return None

    def close(self, wait=True):
        """The pool shut, the books not started let go of; `wait=False` (a Stop): the splits under way end in their
        workers by themselves, the look doesn't wait for them (each worker then exits)."""
        self.futures.clear()
        self.pool.shutdown(wait=wait, cancel_futures=True)


def _drop(part):
    """Our own unfinished `.part`, or the trash copy of a copy never replaced (never anything else): removed."""
    try:
        os.remove(part)
    except OSError:
        pass


def _stat_of(path):
    """(size, mtime_ns) of a file, or None (gone, unreadable)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _load_cache(language, stamp):
    """The folder times, dropped whole when another store (or a rebuilt one: a new epoch) wrote them."""
    try:
        with open(cache_path(language), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == CACHE_VERSION and isinstance(data.get("roots"), dict) \
                and (data.get("store_id"), data.get("epoch")) == stamp:
            return data
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "store_id": stamp[0], "epoch": stamp[1], "roots": {}}


def _save_cache(language, data):
    """Written whole (a temp file, then replaced); a cache that can't be written only means a fuller look next time."""
    path = cache_path(language)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError:
        log.warning("The source folders' times couldn't be saved (%s); they're listed again next look", path)


def _listing(folder, links=None, audio=None):
    """(texts, epubs, videos {name lower: (path, stat)}, subfolders, placeholders, unread) of one folder, from the
    listing alone; `unread`: an entry whose stat failed (held by another program, a share's hiccup) was passed over, so
    the folder's time is not kept (H1). None when it can't be listed (gone, offline). `links` (alpha 4, a look's own
    folder): a list given gets [(path, why)] of what isn't a subfolder to read as it is — a folder link (why None:
    the look decides, `_Look._link`), a cloud folder not on this computer, a Windows shortcut (`.lnk`). `audio` (Hon,
    H-7): a list given gets the names of its audio files (`audiobooks.is_audio`, never stat'd here)."""
    from app.connect import runner
    texts, epubs, vids, subs, ghosts, unread = [], [], {}, [], 0, False
    try:
        with os.scandir(folder) as found:
            for entry in found:
                if runner.mac_copy(entry.name):              # a Mac's AppleDouble twin `._Show - 01.mkv` (B7, LF-21)
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)  # first: `skip_dir` takes a failed stat for a skip
                        # a folder the cloud hasn't brought down: listing it could download it (B3)
                        if not (ls.skip_dir(entry.name, entry) or ls.is_placeholder(st)):
                            subs.append(entry.path)
                        elif links is not None and ls.is_placeholder(st) and not _junk(entry.name):
                            links.append((entry.path, NOT_READ_CLOUD))
                        elif links is not None and ls.is_link(st) and not _junk(entry.name):
                            links.append((entry.path, None))
                        continue
                    if entry.is_symlink():
                        if links is not None and not _junk(entry.name):
                            if entry.is_dir():                   # a folder's symlink
                                links.append((entry.path, None))
                            elif not os.path.exists(entry.path):  # a link to nothing: said, never dropped silently
                                links.append((entry.path, NOT_READ_LINK_GONE))
                        continue
                    low = entry.name.lower()
                    if links is not None and low.endswith(".lnk"):
                        links.append((entry.path, NOT_READ_SHORTCUT))
                        continue
                    kind = "text" if ls.is_content_name(low) else "epub" if low.endswith(EPUB) else \
                        "video" if runner.video_name(entry.name) else None
                    if kind is None:
                        if audio is not None and audiobooks.is_audio(entry.name):
                            audio.append(entry.name)
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    unread = True
                    continue
                if kind == "video" and not runner.video_file(entry.name, st.st_size):
                    continue                                 # Connect's one video-file rule (a small `.ts`: S9)
                if kind == "video":
                    vids[low] = (entry.path, st)             # a placeholder too: it is beside, its key never read
                elif ls.is_placeholder(st):
                    ghosts += 1
                else:
                    (texts if kind == "text" else epubs).append((entry.name, entry.path, st))
    except OSError:
        return None
    return sorted(texts), sorted(epubs), vids, sorted(subs), ghosts, unread


def _junk(name):
    """A folder `skip_dir` skips by its name alone (a recycle bin, a snapshot, a Mac's): never followed nor said."""
    return unicodedata.normalize("NFKC", name).casefold() in ls.SKIP_DIRS


def notes(language, store):
    """Alpha 4: what the looks found to say about each source, from the look cache (one read, no folder looked at) ->
    {root id: {"not_read": [{"path", "why"}], "kept_out": {a file's path key: [the removed origins' keys it matches]}}}
    — `not_read`: a folder in it no look reads (`NOT_READ_*`: a link to nothing, a shortcut, one Windows wouldn't
    open…); `kept_out`: a new file left out because its bytes or its video are an item's he removed (a copy in another
    folder: Remove keeps its bytes out, S6). The window's lines: `source_looks._publish`."""
    meta = store.meta()
    cache = _load_cache(language, (meta.get("store_id"), meta.get("epoch")))
    out = {}
    for root, entry in (cache.get("roots") or {}).items():
        held = entry.get("notes") if isinstance(entry, dict) else None
        if not isinstance(held, dict):
            continue
        said = {"not_read": [], "kept_out": {}}
        for folder in sorted(held):
            for path, (kind, what) in sorted((held[folder] or {}).items()):
                if kind == "not_read":
                    said["not_read"].append({"path": path, "why": what})
                elif kind == "kept_out":
                    said["kept_out"][path] = list(what)
        try:
            out[int(root)] = said
        except ValueError:
            continue
    return out


class _Look:
    def __init__(self, store, language, root, first, progress, stop, full, rules, copying=None):
        self.store, self.language, self.root_id = store, language, root
        self.first, self.progress, self.stop, self.rules = first, progress, stop, rules
        self.copying, self.copy_said, self.copied, self.to_copy = copying, 0.0, 0, 0   # K5: the take's progress
        self.full = bool(full or first)
        self.data_dir = store.data_dir
        self.out = _result()
        self.shows = set()
        self.unsettled = set()       # folders (path keys) a file in which waits: listed again next look
        self.this_look = set()       # the bytes taken this look (the same bytes twice wait for the next look)
        self.this_videos = set()     # the videos a subtitle was taken for this look (S7: one per video per language)
        self.runners_up = {}         # {a new subtitle's path: [its episode's other files, in S7's order]} (B5)
        self.held_videos = []        # LF-19: [(a folder's videos, its picks)]: they wait if the rule refuses every pick
        self.refused = set()         # LF-19: the picks K6's rule refused with no runner-up left (`_new`)
        self.chain = {}              # LF-19: {a runner-up's path: the pick it stands in for}
        self.made = set()            # the copies this look wrote (rels): trashed when take_in can't take them (N3)
        self.said = 0.0
        self.by_folder = None        # {folder key: {(show, episode): (version, Origin)}}: the releases already in
        self.books_in = None         # {an EPUB's sha256: {part: (item_id, rel)}}: the books already in
        self.book_keys = None        # the EPUBs known (their path keys, from their parts' origins and exclusions)
        self.shown = None            # the folder keys of the shows with an item that isn't waiting
        self.follow = {}             # {a v2's origin: (its episode's Origin, path, stat, folder)}: copied after take_in
        self.origins = None          # read when a folder is listed (`_load`)
        self.videos = None           # {video key: item id} of the origins' records, read once a look
        self.batches = 0             # take-ins this look (a checkpoint every CHECKPOINT_EVERY)
        self.hashes = {}             # {a copy's rel: its bytes' sha256 or None}: check (b)'s, once a look
        self.to_keep = []            # A4K-7: [(item_id, size, mtime_ns, sha256)] check (b) read, kept at the next commit
        self.versions = {}           # {a folder's key: the keys of its versions folders listed with it} (item 11)
        self.skip = set()            # K6: the keys of the folders skipped inside this source (`run`)
        self.skip_stamp = None
        self.video_of = {}           # LM1b (A11): {a text in `Subs/<video>/`: that video (its listing key)}
        self.by_show = None          # LM1b (A9): {a show's folder key: {episode key: (version, Origin)}} (`_held`)
        self.pending = []            # LM1b: the other versions of a pick just taken, read into its batch (`_take`)
        self.late = []               # LM1b (A19, A20): known texts of a listed folder, asked for a video (`_late`)
        self.read = {}               # A6: {a candidate's path: `_read_text`'s answer}: read once, for its lines too
        self.vkeys = {}              # A4: {id of a folder's videos: (them, how many, [(video, its key)])}
        self.years = {}              # A3: {a show's folder key: the years its new files' names write}
        self.origin_years = {}       # A3: {a show's folder key: the years its origins' names write}
        self.waits = None            # {video key or path key: item} of the items waiting for their text
        self.recorded = None         # the path keys of the videos the origins name
        self.groups = {}             # LM2: {a show's folder key: its group}, recorded (`_load`) or decided this look
        self.decided = {}            # LM2: {a show's folder key: {group, label} decided this look}: `take_in` records it
        self.deciding = {}           # LM2: {a show's folder key: the episode whose taken file decides its group}
        self.hato = None             # LM3 (A9): {a show's folder key: [Origin]} of hato's items (`Store.hato_items`)
        self.hato_ids = set()        # LM3: their item ids (hato's text is never followed nor rewritten by a look)
        self.better = set()          # LM3 (a): items a version was recorded on this look: a better one switched to
        self.listed = set()          # LM3 (a): items whose known version a folder listed holds (checked here first)
        self.by_item = None          # LM3: {item id: [its Origins]} (`_maybe_better`), grouped once a look
        self.book_origins = None     # LM3 (c): {an EPUB's key: {part number: Origin}} of the books' parts' records
        self.editions = None         # LM3 (W4): {(a folder's key, a book's name, edition marks off): {its EPUBs' keys}}
        self.members = None          # K5: {table: {bucket: {origin key}}} behind the tables above (`_members`)
        self.shows_asked = set()     # F13: the shows' folder keys `_show_origins` built (kept by `_refresh`)
        self.splitter = None         # K5 C2: the new books split ahead by worker processes (`_take`, `_prepared`)
        self.writers = None          # K5 C2: the threads a book's parts are written and flushed by (`_write_parts`)
        self.pending_books = set()   # LM3: the EPUBs whose new edition waits in the store (never hashed nor split)
        self.evidence = None         # D3: the origins' keys by text / video size, and each size's shows (`_evidence`)
        self.content_keys = {}       # D3: {a video's path: its content key}, read once a look (`_content_key`)
        self.waiting_named = None    # FIX1 (MV-A4): the waiting items' videos by name and size (`_waiting_named`)
        self.roots = {}              # D5: {a source's id: its folder} (`run`), and {its id: away?} asked once a look
        self.away_roots = {}
        self.cache_roots = {}        # T6: the folder-time cache's entries (each source's volume as last read)
        self.root_error = None       # T6: the look's failed stat of its own folder (`reach`'s `error`)
        self.back = []               # D5: known originals whose record says they moved, listed in their place again
        self.notes = {}              # alpha 4: {a folder's key: {path: [kind, why or patterns]}} found this look
        self.listed_now = set()      # alpha 4: the folders listed this look (their notes are this look's)
        self.heard = []              # Hon (H-7): the folders listed this look holding audio files or disc folders
        self.audio_in = None         # a6: the library's audiobooks and transcripts, read once a look (`_audio_records`)
        self.found_audio = {}        # a6: {a folder's key: (its audiobooks, an audio file not readable yet)} (`_found_in`)
        self.claimed = []            # a6: [(Audiobook, its item or None, (name, path, stat), the text's Origin or None)]
        self.transcribed = []        # a6: [(item, (name, path, stat), its transcript record)] listed this look
        self.read_roots = []         # alpha 4: the folders being read (their keys), for a link's target (`_link`)

    # --- the look ------------------------------------------------------------------------------------------------- #

    def run(self):
        held_sources = self.store.sources(all=True, counts=False)   # one read of the roots, no origin read
        self.roots = {s["id"]: s["path"] for s in held_sources}
        self.read_roots = sorted({ls.path_key(f(s["path"])).rstrip("/") for s in held_sources if s["on"]   # a source
                                  for f in (os.path.abspath, os.path.realpath)})       # reached through a link too
        path = next((s["path"] for s in held_sources if s["id"] == self.root_id and s["on"]), None)
        if path is None:
            raise ls.NotASource("That folder isn't being read any more.")
        meta = self.store.meta()
        if any(k.startswith(ls.SWITCH_PENDING) for k in meta):   # LM2: a crashed subtitle switch's files put back
            try:
                self.store.settle_switches()
            except ls.StoreError:                    # busy: the next look
                pass
        if any(k.startswith(ls.EDITION_PENDING) for k in meta):  # LM3: a book's new edition waiting, or a crash's
            try:
                for change in self.store.settle_editions():
                    self._switched(change)
            except Exception as e:                   # never the end of the look: the next one tries again
                log.warning("A book's waiting new edition couldn't be finished (the next look tries again): %r", e,
                            exc_info=True)
            try:                                     # read on its own: a settling that failed still waits
                self.pending_books = self.store.pending_editions()
            except Exception as e:
                log.warning("The books' waiting new editions couldn't be read: %r", e, exc_info=True)
        stamp = (meta.get("store_id"), meta.get("epoch"))
        looked = (_store_key(self.store), self.root_id)
        cache = _load_cache(self.language, stamp)
        self.cache_roots = cache["roots"]            # T6: each source's volume as last read (`_root_away`)
        held = cache["roots"].get(str(self.root_id)) or {}
        mine = held.get("path") == ls.path_key(path)
        dirs = held.get("dirs") if mine and isinstance(held.get("dirs"), dict) else {}
        # K6: the folders no look reads (*Never read this folder*) inside this one — read from the store only when its
        # skips moved since this cache was written (meta `folder_skips`, read above: a quick look reads no exclusion);
        # a move of them lists everything once (a folder read again is listed whatever its time) — the stamp, never the
        # list: a skip and its *Read again* (or Undo) between two looks leave the list as it was, its items gone
        self.skip_stamp = meta.get("folder_skips")
        if mine and held.get("skip_stamp") == self.skip_stamp:
            self.skip = set(held.get("skipped") or ())
        else:
            top = ls.path_key(path).rstrip("/")
            self.skip = {f["key"] for f in self.store.skipped_folders() if ls._under(f["key"], top)}
        self.full = self.full or looked not in _LOOKED or not dirs or held.get("skip_stamp") != self.skip_stamp
        # EPUBs that gave no text, by their stats (K5): never parsed again until they change; a full look keeps only
        # the ones it saw
        self.no_text = (held.get("books") if mine and isinstance(held.get("books"), dict) else None) or {}
        self.no_text_kept = {} if self.full else dict(self.no_text)
        # The videos of a show already shown, by their stats (H21): never asked about again until they change
        self.shown_videos = (held.get("shown") if mine and isinstance(held.get("shown"), dict) else None) or {}
        self.shown_kept = {} if self.full else dict(self.shown_videos)
        # A folder's show is read below the outermost source holding it, so overlapping sources never split it (K6)
        self.base = path
        for s in held_sources:
            k = ls.path_key(os.path.abspath(s["path"])).rstrip("/")
            if len(k) < len(ls.path_key(os.path.abspath(self.base)).rstrip("/")) and \
                    ls.path_key(os.path.abspath(path)).startswith(k + "/"):
                self.base = s["path"]
        walked = self._walk(path, dirs)
        if walked is None:                                   # T6: gone (moved, deleted) or away (`reach`)
            return _result(reachable=False, gone=reach(path, _volume(held, path), self.root_error) == GONE)
        seen, new, known, books = walked
        if not self.stopped():
            for item in known:                               # a listed folder's: its listing brought their stats (H2)
                if self.stopped():
                    break
                try:
                    self._changed(*item)
                except OSError:                              # gone or locked meanwhile: the next look
                    self._wait(item[0])
            self._late()                                     # LM1b (A19, A20): a known text's video, come or renamed
            self._back()                                     # D5: an original back in its old place: unmarked
            self._restore(known)                             # before check (b): an item back holds its bytes again
            texts = [c[2].st_size for c in new if len(c) == 6]
            self.sizes = self.store.items_of_size(texts) if texts else {}
            self._take(new, books)
            if self.to_copy:
                self._copy_done(final=True)
            if not self.stopped():
                try:                                         # Hon (H-6…H-8): never the end of the look
                    self._audiobooks(bool(books))
                except Exception as e:                       # busy, or anything: their folders listed again next look
                    for folder, _names in self.heard:
                        self.unsettled.add(ls.path_key(folder))
                    (log.info if isinstance(e, ls.StoreError) else log.warning)(
                        "Audiobooks wait for the next look: %r", e, exc_info=not isinstance(e, ls.StoreError))
        self._keep_hashes()
        self._say(final=True)
        self.out["shows"] = len(self.shows)
        if self.out["stopped"]:
            return self.out
        for k in self.unsettled:
            if k in seen:
                seen[k]["mtime_ns"] = None
        meta = self.store.meta()
        cache = _load_cache(self.language, (meta.get("store_id"), meta.get("epoch")))
        entry = {"path": ls.path_key(path), "dirs": seen, "books": self.no_text_kept}
        kept = (held.get("notes") if mine and not self.full else None) or {}    # a folder not listed: as last said
        said = {k: v for k, v in kept.items() if isinstance(v, dict) and k in seen and k not in self.listed_now}
        said.update(self.notes)
        said = {k: v for k, v in said.items() if v}
        if said:
            entry["notes"] = said
        if self.skip:
            entry["skipped"] = sorted(self.skip)
        if self.skip_stamp is not None:
            entry["skip_stamp"] = self.skip_stamp
        if self.shown_kept:
            entry["shown"] = self.shown_kept
        try:                                                 # T6: the volume it was read on (`reach`'s `dev`)
            entry["dev"] = os.stat(path).st_dev
        except OSError:                                      # A10: a stat that failed keeps the one recorded
            if _volume(held, path) is not None:
                entry["dev"] = held["dev"]
        if cache["roots"].get(str(self.root_id)) != entry:   # H15: written only when the look changed it
            cache["roots"][str(self.root_id)] = entry
            _save_cache(self.language, cache)
        _LOOKED.add(looked)
        return self.out

    def _load(self):
        """The origins and the exclusions, read once a look — when its first folder is listed (H16: a look that finds
        every folder as it was reads neither table)."""
        if self.origins is not None:
            return
        self.origins = self.store.origins()
        self.groups = dict(self.store.show_groups())
        excluded = self.store.excluded()
        self.ex_paths = set(excluded)
        self.ex_shas = {n["sha256"] for n in excluded.values() if n.get("sha256")}
        self.ex_videos = {n["video_key"] for n in excluded.values() if n.get("video_key")}
        self.ex_by_sha, self.ex_by_video = {}, {}           # alpha 4: the removed origins behind each (`_kept_out`)
        for p, n in excluded.items():
            if n.get("sha256"):
                self.ex_by_sha.setdefault(n["sha256"], []).append(p)
            if n.get("video_key"):
                self.ex_by_video.setdefault(n["video_key"], []).append(p)
        self.ex_episodes, self.ex_releases, self.ex_joined = set(), set(), set()
        for p, n in excluded.items():
            if n.get("show") and n.get("episode") is not None:
                name = os.path.basename(p)
                episode = self._removed(n["show"], n["episode"], name)
                self.ex_episodes.add(episode)
                self.ex_joined.add(episode[:2] + episode[3:])       # A12: whatever its name's show (a number's join)
                self.ex_releases.add(episode + (_release(name),))    # H13: its other releases of that version too

    def stopped(self):
        if not self.out["stopped"] and self.stop is not None and self.stop():
            self.out["stopped"] = True
        return self.out["stopped"]

    def _say(self, final=False):
        now = time.monotonic()
        if self.progress is not None and (final or now - self.said >= PROGRESS_S):
            self.said = now
            self.progress(self.out["found"], len(self.shows))

    def _copy_done(self, final=False):
        """K5: one more of the found files and books dealt with (copied and taken in, or passed over): told every
        PROGRESS_S, and at the end."""
        if not final:
            self.copied += 1
        now = time.monotonic()
        if self.copying is not None and (final or now - self.copy_said >= PROGRESS_S):
            self.copy_said = now
            self.copying(self.copied, self.to_copy)

    def _wait(self, folder):
        self.out["waiting"] += 1
        self.unsettled.add(ls.path_key(folder))

    def _recent(self, st):
        """Modified in the last SETTLE_S seconds (or as far ahead: a share whose clock runs ahead never blocks a file
        for good — the copy's own check still catches one being written)."""
        return abs(time.time() - st.st_mtime_ns / 1e9) < SETTLE_S

    # --- listing (S4) ---------------------------------------------------------------------------------------------- #

    def _walk(self, root, dirs):
        """-> (the folders seen {key: {path, mtime_ns, subs}}, new files, known files, EPUBs) or None (unreachable).
        A folder whose time didn't move (not a full look) is not listed: its subfolders come from the cache."""
        seen, new, known, books = {}, [], [], []
        stack, visited = [root], set()
        while stack:
            if self.stopped():
                break
            folder = stack.pop()
            fkey = ls.path_key(folder)
            if self._skips(folder):                          # K6: never listed, nor anything under it
                continue
            try:
                st = os.stat(folder)
            except OSError as e:
                if folder == root:
                    self.root_error = e                      # T6: `reach` reads it (the share asked once, G5)
                if folder == root or _lost(root):            # the source went mid-look: unreachable, as at its
                    return None                              # start; the cache kept as it was
                if not _not_found(e):                        # alpha 4: there, but not opened: said
                    self._note(folder, folder, "not_read", NOT_READ_LOCKED)
                continue
            mtime = st.st_mtime_ns
            if st.st_ino:                                    # a loop no link shows (a share following links): once
                if (st.st_dev, st.st_ino) in visited:
                    continue
                visited.add((st.st_dev, st.st_ino))
            held = dirs.get(fkey)
            if not self.full and held and held.get("mtime_ns") == mtime and self._kept(held, dirs, seen):
                seen[fkey] = held
                stack.extend(reversed(held.get("subs") or []))
                continue
            links, audio = [], []
            listed = _listing(folder, links, audio)
            if listed is None:
                if folder == root or _lost(root):
                    return None
                if os.path.isdir(folder):                    # alpha 4: there, but not listed: said
                    self._note(folder, folder, "not_read", NOT_READ_LOCKED)
                continue
            self._load()
            self.listed_now.add(fkey)
            texts, epubs, vids, subs, ghosts, unread = listed
            discs = any(audiobooks.disc_number(os.path.basename(s)) is not None for s in subs)
            if any(audiobooks.is_transcript(t[0]) for t in texts):     # a6: an audiobook's transcript, never its own
                texts = self._transcripts_here(folder, texts, audio, discs)
            if audio or discs:                               # its audiobooks read after the take-in (`_audiobooks`);
                self.heard.append((folder, None if discs else audio))   # its audio names (None: disc folders too)
            if links:                                        # alpha 4: its links are checked again every look
                self.unsettled.add(fkey)                     # (a target gone or back changes no folder's time)
            for link, why in links:                          # alpha 4: a folder link followed, else said
                why = self._link(link) if why is None else why
                if why is None:
                    subs.append(link)
                elif why:
                    self._note(folder, link, "not_read", why)
            subs.sort()
            langs = {}
            subs, with_it = self._subtitles(folder, subs, texts, epubs, vids, langs, seen)
            # a folder time in the last seconds may yet take a file in the same tick (FAT32, a coarse share): not kept
            seen[fkey] = {"path": folder, "mtime_ns": None if self._recent(st) or unread else mtime, "subs": subs}
            if with_it:
                seen[fkey]["subtitles"] = with_it
            stack.extend(reversed(subs))
            self.out["skipped"] += ghosts
            rel = os.path.relpath(folder, self.base)
            parts = [] if rel == "." else rel.replace("\\", "/").split("/")
            folders = () if parts else _show_folders(subs)   # a8: the top's folders, folded once
            show_of = self._shows_of(parts, texts, vids, folders)    # D3: a moved show's files are its show's
            episodes = self._episodes(self.base, parts, texts, epubs, langs, vids, self.versions.get(fkey, ()),
                                      show_of)
            for name, path, st, show, kind, *item in episodes:
                self.out["found"] += 1
                self.shows.add(ls.search_fold(show, self.language))
                where = os.path.dirname(path)                # this folder, or a subtitle folder listed with it
                if ls.path_key(where) in self.versions.get(fkey, ()):
                    where = folder                           # a versions folder's: the folder's releases (S7, H12)
                if kind == "known":
                    known.append((where, path, st))
                    o = self.origins.get(_key(path))
                    if o is not None and o.moved_to:         # D5: back where it was
                        self.back.append(path)
                    if o is not None and o.version:          # LM3 (a): a better version the switch held before
                        self.listed.add(o.item_id)
                    self.late.append((where, path, name, vids))     # A19 / A20: its video asked after the changes
                elif kind == "book":
                    books.append((where, name, path, st, show))
                elif kind == "version":                      # LM1b: beside a file of its episode already in
                    new.append((where, path, st, name, show, vids, item[0]))
                else:
                    new.append((where, path, st, name, show, vids))
            waits = [(folder, path, st, show_of(os.path.basename(path)))
                     for path, st in self._waiting(vids)] if vids and not epubs else []
            kept = any(_key(t[1]) in self.ex_paths for t in texts)   # a removed episode's text (kept out, never a
            if waits and not episodes and not kept:          # pick) still counts: its video never waits. Videos and
                for w in waits:                              # none of our text yet: they wait (K5)
                    self.out["found"] += 1
                    self.shows.add(ls.search_fold(w[3], self.language))
                    new.append(w)
            elif waits and episodes and all(e[4] == "new" for e in episodes):   # LF-19: wait too if the rule refuses every pick
                self.held_videos.append((waits, {e[1] for e in episodes}))
            self._say()
        return seen, new, known, books

    # --- audiobooks (Hon, 3.0 E2; H-6…H-8 PROVISIONAL; rules in `app/audiobooks.py`) ------------------------------- #

    def _audiobooks(self, books_came):
        """The audiobooks of the folders listed this look that hold audio (`audiobooks.find` — only where the listing
        named an audio file or a disc folder: never a second listing of every folder; a disc folder's by the one above;
        never a cloud placeholder's bytes, never a file still being written: that folder waits) taken in as ONE waiting
        item each (H-7) — paired with a library book when sure (H-6), asking about one when unsure (H-8) — in one
        batch; one already in, kept out (S6) or moved (its files' sizes the same, its old first file gone: recorded on
        its item, D5) is never a second. When a book came this look, or an answer said *No* (`AUDIOBOOKS_STALE`), the
        lone ones already in are weighed again from their records (no file opened). Nothing is moved, renamed or
        written in the learner's folders; only the audio's tags and a candidate book's package are read."""
        from app.extract import clean_name
        top = ls.path_key(self.roots.get(self.root_id) or self.base).rstrip("/")
        folders = []
        for folder, names in self.heard:
            if audiobooks.disc_number(os.path.basename(os.path.normpath(folder))) is not None and \
                    ls.path_key(folder).rstrip("/") != top:     # a disc folder's are the folder above's (never above
                folder, names = os.path.dirname(os.path.normpath(folder)), None     # the source's own folder)
            if all(f != folder for f, _n in folders):
                folders.append((folder, names))
        stale = books_came or self.store.meta().get(ls.AUDIOBOOKS_STALE) == "1"
        if not folders and not stale:
            self._transcripts()
            return
        self._load()
        held_in = self.store.audiobooks()                    # one per item
        records = {r["item_id"]: r["audiobook"] for r in held_in}
        by_file = {}                                         # {a recorded audiobook's file: (its item, its size)}
        for r in held_in:
            for f, n in zip(r["audiobook"].get("files") or (), r["audiobook"].get("sizes") or ()):
                by_file[ls.path_key(os.path.abspath(f))] = (r["item_id"], n)
        found = []
        for folder, names in folders:
            if self.stopped():
                return
            if names and self._known_audio(folder, names, by_file):
                continue                                     # S19: every file recorded as it is: no tag read again
            here, waits = self._found_in(folder)
            found += here
            if waits:                                        # listed again next look (a placeholder: until it is here)
                self.unsettled.add(ls.path_key(folder))
        fresh, grown = [], []
        for ab in found:
            k = _key(ab.files[0])
            same = next((by_file[ls.path_key(os.path.abspath(f))][0] for f in ab.files
                         if ls.path_key(os.path.abspath(f)) in by_file), None)
            if same is not None:                             # one in already: a file added, re-ordered or re-tagged
                old = records[same]
                if (list(ab.files), list(ab.sizes)) != (list(old.get("files") or ()), list(old.get("sizes") or ())):
                    grown.append((same, k, ab, old))
                continue
            if k in self.origins:
                continue
            if k in self.ex_paths or audiobooks.sizes_key(ab) in self.ex_shas:    # Removed (S6), here or moved
                self.out["skipped"] += 1
                continue
            fresh.append(ab)
        lone = [(r["item_id"], r["audiobook"]) for r in held_in       # a5-2: *It has no book* is never weighed again
                if not r["audiobook"].get("book") and not r["audiobook"].get("no_book")] if stale else []
        wanted = fresh + [audiobooks.from_record(rec) for _i, rec in lone]
        books = self._library_books(wanted) if wanted else []
        answers = self.store.audiobook_answers() if books else {}
        heard_at = {}                                        # a6: an item counted by its transcript is still found by
        for r in held_in:                                    # its audio's name (the same files in another source: one)
            said = r["audiobook"].get("transcript")
            if isinstance(said, dict) and said.get("heard"):
                heard_at[ls.path_key(said["heard"])] = r["item_id"]
        by_sizes = {}                                        # D5: a moved audiobook is its item's, by its files' sizes
        for r in held_in:
            sizes = tuple(r["audiobook"].get("sizes") or ())
            if sizes:
                by_sizes.setdefault(sizes, []).append((r["item_id"], r["key"]))
        batch = []
        for same, k, ab, old in grown:                       # a new first file: recorded on its item too
            if k not in self.origins:
                f = self._audio_found(ab, clean_name, item_id=same, pair=old)
                if f is not None:
                    batch.append(f)
        for ab in fresh:
            f = self._audio_found(ab, clean_name, pair=audiobooks.decide(ab, books, answers) if books else None)
            if f is None:
                continue
            if f.get("rel") and ls.path_key(f["rel"]) in heard_at:
                f["item_id"] = heard_at[ls.path_key(f.pop("rel"))]
                old = records.get(f["item_id"]) or {}        # its records kept alike (`pair_audiobook`'s rule)
                f["audiobook"].update(book=old.get("book"), ask=old.get("ask"),
                                      **{m: old[m] for m in ("said_no", "no_book", "transcript") if old.get(m)})
            gone = [(i, k) for i, k in by_sizes.get(tuple(ab.sizes), ())
                    if not self._origin_away(k) and not os.path.exists(self._origin_path(k))]
            if len({i for i, _k in gone}) == 1:              # moved or renamed: the same item (its answer kept too)
                f["item_id"] = gone[0][0]
                f["moved_from"] = [k[len(ls.SOURCE_KEY):] for _i, k in gone]
                old = records.get(gone[0][0]) or {}          # as it was paired (or asked, or alone): a move changes none
                f["audiobook"].update(book=old.get("book"), ask=old.get("ask"),     # and the learner's word on it
                                      **{m: old[m] for m in ("said_no", "no_book", "transcript") if old.get(m)})
                f.pop("rel", None)
            self.out["found"] += 1
            batch.append(f)
        self._commit(batch)
        for same, _k, ab, _old in grown:                     # its records say what it holds now (Connect's list)
            fields = {x: v for x, v in audiobooks.record(ab).items() if x not in ("book", "ask")}
            self.store.pair_audiobook(same, fields=fields)
        for item_id, rec in lone:                            # weighed again: the next book after a *No*, a new book
            if self.stopped():
                return
            pair = audiobooks.decide(audiobooks.from_record(rec), books, answers) if books else None
            said = audiobooks.set_pair(dict(rec), pair)
            if (said["book"], said["ask"]) != (rec.get("book"), rec.get("ask")):
                self.store.pair_audiobook(item_id, book=said["book"], ask=said["ask"])
        if stale and self.store.meta().get(ls.AUDIOBOOKS_STALE) == "1":
            self.store.audiobooks_weighed()
        self._transcripts()

    def _found_in(self, folder):
        """(the audiobooks of `folder`, an audio file there can't be read yet) — `audiobooks.find` once a look (the walk
        may have asked already, for the folder's transcripts: `_transcripts_here`). A cloud placeholder's audio, or one
        still being written, is never opened: the folder gives none until the next look."""
        key = ls.path_key(folder)
        if key not in self.found_audio:
            waits = []

            def held(st):
                if ls.is_placeholder(st) or self._recent(st):
                    waits.append(st)
                    return True
                return False
            self.found_audio[key] = (audiobooks.find(folder, held=held), bool(waits))
        return self.found_audio[key]

    # --- an audiobook's transcript (Hon a6: H-12 ✅ Sonic, H-13 PROVISIONAL; the store's `set_transcript`) ---------- #

    def _audio_records(self):
        """({a recorded audiobook's file's path key: (its item, its size, its record)}, {its transcript's path key:
        (its item, its record)}) — the library's audiobooks, read once a look (only when a folder holds a subtitle)."""
        if self.audio_in is None:
            files, texts = {}, {}
            for r in self.store.audiobooks():
                ab = r["audiobook"]
                for f, n in zip(ab.get("files") or (), ab.get("sizes") or ()):
                    files[ls.path_key(os.path.abspath(f))] = (r["item_id"], n, ab)
                said = ab.get("transcript")
                if isinstance(said, dict) and said.get("origin"):
                    texts[ls.path_key(os.path.abspath(said["origin"]))] = (r["item_id"], ab)
            self.audio_in = (files, texts)
        return self.audio_in

    def _transcripts_here(self, folder, texts, audio, discs):
        """a6 (H-12 ✅ Sonic): an audiobook's transcript is never a subtitle of its own. Of `folder`'s texts -> the
        ones left for the walk. A subtitle recorded as an audiobook's transcript is `_transcripts`' (its changes
        followed there). Where the folder holds audio, a subtitle its audiobooks claim (`audiobooks.transcripts`: by
        its name, or the one subtitle beside the one audiobook) goes with its audiobook — one already an item's own
        text (taken in before its audiobook was known) stays that item's for the walk until `_transcripts` makes that
        item the audiobook's; while an audio file there can't be read yet, every new subtitle there waits with it (the
        folder listed again). One passed over (another language's, K6), kept out (S6) or no transcript: as any."""
        self._load()
        files, mine = self._audio_records()
        left = []
        for t in texts:
            held = mine.get(ls.path_key(os.path.abspath(t[1])))
            if held is not None:
                self.transcribed.append((held[0], t, held[1].get("transcript") or {}))
            else:
                left.append(t)
        if not (audio or discs):
            return left
        cands = [t for t in left if audiobooks.is_transcript(t[0]) and _key(t[1]) not in self.ex_paths and
                 (self.no_text.get(_key(t[1])) or [])[:2] != [t[2].st_size, t[2].st_mtime_ns]]
        if not cands:
            return left
        here = []                                            # [(Audiobook, its item or None, its record or {})]
        if audio and self._known_audio(folder, audio, files):
            seen = set()                                     # every audio file recorded as it is: no tag read (S19)
            for n in audio:
                item, _n, ab = files[ls.path_key(os.path.abspath(os.path.join(folder, n)))]
                if item not in seen:
                    seen.add(item)
                    here.append((audiobooks.from_record(ab), item, ab))
        else:
            found, waits = self._found_in(folder)
            if waits:
                self.unsettled.add(ls.path_key(folder))
                new = {t[1] for t in cands if _key(t[1]) not in self.origins}
                return [t for t in left if t[1] not in new]
            for ab in found:
                held = next((files[k] for k in (ls.path_key(os.path.abspath(f)) for f in ab.files) if k in files),
                            None)
                here.append((ab, held[0] if held else None, held[2] if held else {}))
        claimed = audiobooks.transcripts([h[0] for h in here], [t[0] for t in cands])
        by_name = {t[0]: t for t in cands}
        gone = set()
        for i, name in sorted(claimed.items()):
            said = here[i][2].get("transcript") if isinstance(here[i][2].get("transcript"), dict) else {}
            t = by_name[name]
            o = self.origins.get(_key(t[1]))
            if said.get("origin") and os.path.exists(said["origin"]) and \
                    ls.path_key(os.path.abspath(said["origin"])) != ls.path_key(os.path.abspath(t[1])):
                if o is None:                                # its transcript is there still: a second (an `.ass`
                    gone.add(t[1])                           # beside its `.srt`, a copy of the folder elsewhere) is
                continue                                     # never recorded, nor a title of its own
            if o is not None and (o.version or o.moved_to):
                continue                                     # another item's version, or a moved one's: as any
            self.claimed.append((here[i][0], here[i][1], t, o))
            if o is None:
                gone.add(t[1])
        return [t for t in left if t[1] not in gone]

    def _transcripts(self):
        """a6: this look's transcripts written on their audiobooks' items (after the audiobooks were taken in, so a
        new one's item is there): a new one copied into the item's `Library` folder and recorded (`set_transcript`);
        one already an item's own text makes that item the audiobook's (`from_item`); one recorded whose file changed
        copied again over its copy (S5) and checked again; a check that couldn't be made yet, made. An audiobook
        kept out (Removed, S6) keeps its transcript out too: never a title of its own."""
        claimed, listed = self.claimed, self.transcribed
        self.claimed, self.transcribed = [], []
        held = self.store.audiobooks(every=True) if claimed or listed or self.heard else []
        by_file = {ls.path_key(os.path.abspath(f)): r for r in held for f in r["audiobook"].get("files") or ()}
        by_item = {}                                         # (each source's record: its files; one per item below)
        for r in held:
            by_item.setdefault(r["item_id"], r)
        for ab, item, text, origin in claimed:
            if self.stopped():
                return
            r = by_item.get(item) if item is not None else None
            r = r or next((by_file[k] for k in (ls.path_key(os.path.abspath(f)) for f in ab.files) if k in by_file),
                          None)
            if r is None:                                    # kept out (S6), or not taken in this look: never its own
                if _key(ab.files[0]) in self.ex_paths or audiobooks.sizes_key(ab) in self.ex_shas:
                    self.out["skipped"] += 1
                else:
                    self._wait(os.path.dirname(text[1]))
                continue
            try:
                self._transcript(r, text, origin)
            except (ls.StoreError, OSError) as e:            # held open, gone meanwhile, busy: that one, next look
                log.info("A transcript waits for the next look (%s): %r", text[1], e)
                self._wait(os.path.dirname(text[1]))
        for item, (name, path, st), said in listed:
            if self.stopped():
                return
            if not said.get("rel"):
                continue
            try:
                self._transcript_followed(item, path, st, said)
            except (ls.StoreError, OSError) as e:
                log.info("A transcript waits for the next look (%s): %r", path, e)
                self._wait(os.path.dirname(path))
        for r in by_item.values():                           # a check that waited (a book's copy unreadable then)
            if audiobooks.transcript_use(r["audiobook"]) == audiobooks.UNCHECKED and not self.stopped():
                self.store.set_transcript(r["item_id"])

    def _transcript_followed(self, item, path, st, said):
        """A recorded transcript listed this look: its copy written again when it is gone from `Library` (Item 8a's
        `_restore`, as a subtitle's is) or its original changed (S5: `_recopy`'s rules), then its record follows."""
        full = self._inside(said["rel"])
        if full is not None and not os.path.isfile(full):    # the copy gone: back from the original, in its place
            if self._recent(st) or st.st_size == 0:
                self._wait(os.path.dirname(path))
                return
            data, sha, _head = _read_text(path, st)
            if sha is None or not self._same(path, st):
                self._wait(os.path.dirname(path))
                return
            rel = self._copy(path, st, said["rel"].split("/")[1], said["rel"].rsplit("/", 1)[-1], sha, data)
            if rel is None:
                self._wait(os.path.dirname(path))
                return
            done = self.store.set_transcript(item, {"rel": rel, "sha256": sha, "size": st.st_size,
                                                    "mtime_ns": st.st_mtime_ns})
            self.out["restored"] += done is not None
            return
        if (st.st_size, st.st_mtime_ns) == (said.get("size"), said.get("mtime_ns")):
            return
        if self._recent(st):
            self._wait(os.path.dirname(path))
            return
        outcome, sha = self._recopy(said["rel"], said.get("sha256"), path, st)
        if outcome == "wait":
            self._wait(os.path.dirname(path))
        elif outcome in ("done", "same"):
            self.store.set_transcript(item, {"sha256": sha, "size": st.st_size, "mtime_ns": st.st_mtime_ns})
            self.out["recopied"] += outcome == "done"

    def _transcript(self, r, text, origin):
        """One transcript `text` (name, path, stat) written on the audiobook item `r` (`Store.audiobooks`' row)."""
        name, path, st = text
        item, ab = r["item_id"], r["audiobook"]
        if origin is not None:                               # already an item's own text: that item becomes the
            if origin.item_id != item:                       # audiobook's (it keeps its marks and cards)
                done = self.store.set_transcript(item, {"origin": os.path.abspath(path), "rel": origin.rel_path,
                                                        "sha256": origin.sha256, "size": origin.size,
                                                        "mtime_ns": origin.mtime_ns}, from_item=origin.item_id)
                self.out["attached"] += done is not None
            return
        if self._recent(st):
            self._wait(os.path.dirname(path))
            return
        data, sha, head = _read_text(path, st)
        if sha is None or not self._same(path, st):
            self._wait(os.path.dirname(path))
            return
        if sha in self.ex_shas:                              # its bytes removed before (S6): never its text
            self.out["skipped"] += 1
            self._kept_out(os.path.dirname(path), path, sha=sha)
            return
        why = _refusal(head, self.language, False, data is None)
        if why:                                              # another language's (K6): not read again until it changes
            self._pass_over(path, st, why)
            return
        old = ab.get("transcript") if isinstance(ab.get("transcript"), dict) else {}
        if old.get("origin") and os.path.exists(old["origin"]) and                 ls.path_key(os.path.abspath(old["origin"])) != ls.path_key(os.path.abspath(path)):
            return                                           # its transcript is there still: this one is a second
        rel = old.get("rel") if old.get("sha256") == sha and old.get("rel") and \
            os.path.isfile(os.path.join(self.data_dir, *old["rel"].split("/"))) else None    # moved: its copy kept
        made = None
        if rel is None:
            from app.extract import clean_name
            held = ((self.store.item(item) or {}).get("rel_path") or "").split("/")
            show = held[1] if len(held) >= 3 and ls.path_key(held[0]) == ls.path_key(ls.CONTENT_FOLDER) else \
                (clean_name(ab.get("title") or "") or "Audiobook") + audiobooks.AUDIO_MARK
            rel = made = self._copy(path, st, show, name, sha, data)
            if rel is None:
                self._wait(os.path.dirname(path))
                return
        done = self.store.set_transcript(item, {"origin": os.path.abspath(path), "rel": rel, "sha256": sha,
                                                "size": st.st_size, "mtime_ns": st.st_mtime_ns})
        if done is None and made:
            self._trash(made)
        elif done is not None:
            self.out["attached"] += 1
            gone = old.get("rel")                            # the transcript it replaced: its copy no item holds now
            if made and gone and gone != rel and (self.store.item(done) or {}).get("rel_path") != gone:
                self._trash(gone)

    def _audio_found(self, ab, clean_name, item_id=None, pair=None):
        """An audiobook's found-record for `take_in` (its first file's stats), or None (gone meanwhile). New: its item
        at `Library/<title> (audio)/<its sizes' key> <first file>` (no file made: one item per audiobook, the same files
        in two sources one); `item_id`: recorded on that item. `pair`: `decide`'s Pair, or a record's {book, ask}."""
        try:
            st = os.stat(ab.files[0])
        except OSError:
            return None
        key = audiobooks.sizes_key(ab)
        show = clean_name(ab.title) or "Audiobook"
        rec = audiobooks.record(ab, pair if not isinstance(pair, dict) else None)
        if isinstance(pair, dict):                           # as it was paired, and the learner's word on it
            rec.update(book=pair.get("book"), ask=pair.get("ask"),
                       **{m: pair[m] for m in ("said_no", "no_book", "transcript") if pair.get(m)})
        f = {"origin": ab.files[0], "size": st.st_size, "mtime_ns": st.st_mtime_ns, "show": show, "sha256": key,
             "audiobook": rec}
        if item_id is not None:
            f["item_id"] = item_id
        else:
            f["rel"] = f"{ls.CONTENT_FOLDER}/{show}{audiobooks.AUDIO_MARK}/{key[6:14]} {os.path.basename(ab.files[0])}"
        return f

    def _known_audio(self, folder, names, by_file):
        """Is every audio file of `folder` (its listing's `names`) recorded on an audiobook at its size? (One stat each,
        no tag read: an unchanged audiobook costs a full look nothing more.)"""
        for name in names:
            path = os.path.join(folder, name)
            held = by_file.get(ls.path_key(os.path.abspath(path)))
            try:
                if held is None or os.stat(path).st_size != held[1]:
                    return False
            except OSError:
                return False
        return True

    def _origin_away(self, key):
        """D5: is the source of an origin (its content key) away — whether its file left is unknown (G5)?"""
        o = self.origins.get(key[len(ls.SOURCE_KEY):]) if key.startswith(ls.SOURCE_KEY) else None
        return o is not None and self._root_away(o.root)

    def _origin_path(self, key):
        """The path an origin's content key names (`src:<path key>`), from the origins read this look, else the key's."""
        o = self.origins.get(key[len(ls.SOURCE_KEY):]) if key.startswith(ls.SOURCE_KEY) else None
        return o.origin if o is not None and o.origin else key[len(ls.SOURCE_KEY):]

    def _library_books(self, wanted):
        """The library's books as `audiobooks.decide` weighs them: one per EPUB among the origins (`<epub>#<n>`) — its
        sha256, one of its parts' items, its characters (its parts' copies' bytes / 3) — and only a book whose file name
        is like one of `wanted`'s titles, or that sits near one, has its package's titles read (a look never opens every
        EPUB; a cloud placeholder's never: its name stands for it)."""
        by_epub = {}
        for o in self.origins.values():
            if o.version or o.moved_to or not o.origin or not ls._EPUB_PART.search(o.origin):
                continue
            epub = o.origin.rsplit("#", 1)[0]
            by_epub.setdefault(ls.path_key(epub), [epub, o.sha256, o.item_id, []])[3].append(o.rel_path)
        if not by_epub:
            return []
        forms = set()
        for ab in wanted:
            forms |= audiobooks._forms(ab.titles)[0]
        alike, near = [], []                                 # a name like a title's; else, only then, the near ones
        for held in by_epub.values():
            stem = os.path.splitext(os.path.basename(held[0]))[0]
            if audiobooks._title_level(forms, audiobooks._forms([stem])[0]):
                alike.append(held)
            elif any(audiobooks._near(ab.folder, os.path.dirname(held[0])) < 2 for ab in wanted):
                near.append(held)
        out = []
        for epub, sha, item, rels in alike or near:
            stem = os.path.splitext(os.path.basename(epub))[0]
            chars = 0
            for rel in rels:
                try:
                    chars += os.path.getsize(os.path.join(self.data_dir, rel)) // 3
                except (OSError, TypeError):
                    pass
            try:
                placeholder = ls.is_placeholder(os.stat(epub))
            except OSError:
                placeholder = True                           # gone or away: its name only
            if placeholder:
                out.append(audiobooks.Book(id=item, path=os.path.abspath(epub), titles=(stem,), chars=chars or None,
                                           sha256=sha))
            else:
                out.append(audiobooks.book_of(epub, book_id=item, chars=chars or None, sha256=sha))
        return out

    def _note(self, folder, path, kind, what):
        """Alpha 4: one thing to say about `path`, found while `folder` was listed (`notes`): kept with the folder's
        others until it is listed again."""
        self.notes.setdefault(ls.path_key(folder), {})[path] = [kind, what]

    def _link(self, path):
        """Alpha 4 (Mattias: a show folder linked into his source never arrived, nothing said; ⭐ PROVISIONAL): a folder
        link (a junction, a symlink) inside a source is read as the folder it names — the walk's own guard
        (`_walk`'s `visited`, the folder's identity) reads it once a look and never loops — unless its folder is gone,
        one Surasura never reads as a library (`Store._not_a_source`: its own folders, a whole drive, the user folder:
        a link into the data folder would bring the library's own copies back) or one holding a folder being read ->
        None (followed) or why not (`NOT_READ_*`); "" for a folder inside one being read: read there, nothing to say."""
        try:
            target = os.path.realpath(path)
        except (OSError, ValueError):
            return NOT_READ_LINK_GONE
        if not os.path.isdir(target):
            return NOT_READ_LINK_GONE
        key = ls.path_key(target).rstrip("/")
        if any(key == k or key.startswith(k + "/") for k in self.read_roots):
            return ""                                        # read where it is (nested sources: any of them)
        if any(k.startswith(key + "/") for k in self.read_roots):
            return NOT_READ_LINK_HOLDS
        try:
            refused = self.store._not_a_source(target)
        except Exception:
            refused = NOT_READ_LINK_OWN
        return NOT_READ_LINK_OWN if refused else None

    def _kept_out(self, folder, path, sha=None, video=None):
        """Alpha 4 (Mattias: a copy of a removed book never arrived, nothing said): a new file left out because its
        bytes (`sha`) or its video's key (`video`) are an item's he removed — counted, with the removed origins it
        matches (`notes`), so New arrivals can say so and *Bring back* can put those back. Its own original (kept out
        by its path) is never counted: the Removed list holds it."""
        keys = sorted(set(self.ex_by_sha.get(sha, ()) if sha else ()) | set(self.ex_by_video.get(video, ()) if video
                                                                               else ()))
        if keys:
            self._note(folder, ls.path_key(os.path.abspath(path)), "kept_out", keys)

    def _shows_of(self, parts, texts, vids, folders=()):
        """D3 (PROVISIONAL; Sonic's MV-1: a moved show found where Surasura reads joins the show it is, never a
        duplicate) -> show_of(a file's name): the show of a folder's files. A folder below the source (`parts`) is one
        show; at the source's top each name's show is its own (S12) — a show folder picked as the source itself (MV-2's
        *Find its folder*) reads its files' names. Each is `_show_of`'s, unless that show has no items yet and its files
        are already items of ONE show (`_joined`) -> that show: `Downloads/Show` -> `NAS/2024 Fall/Show` stays `Show`.
        `folders`: the source's top folders (`_show_folders`; a8: a loose episode of one of their shows is that
        folder's)."""
        if parts:
            show = self._joined(_show_of(self.base, parts, ""), texts, list(vids.values()))
            return lambda _name: show
        names, groups = {}, {}

        def own(name):
            if name not in names:
                names[name] = _show_of(self.base, parts, name, folders)
            return names[name]
        for t in texts:
            groups.setdefault(own(t[0]), ([], []))[0].append(t)
        for v in vids.values():
            groups.setdefault(own(os.path.basename(v[0])), ([], []))[1].append(v)
        shows = {s: self._joined(s, ts, vs) for s, (ts, vs) in groups.items()}
        return lambda name: shows.get(own(name)) or own(name)

    def _joined(self, show, texts, vids):
        """D3: `show`, or — when it has no items yet — the ONE show whose items these files already are: their origins
        recorded (a later look's), else their bytes or videos as the origins record them (the look after the move: a
        text's size then its sha256, read once — `_new` takes it from `read`; a video's size then its content key).
        Files of two shows' items, or of none, keep `show`; a show already in never moves (a stray copy in another
        show's folder never pulls it away). FIX1 (MV-A1, PROVISIONAL): the one show is taken only when MOST of the
        folder's texts are its items (its videos, in a folder of videos alone), or when the folder's name ends in that
        show's (`2024 Fall/Show` -> `Show`) — one stray copy never decides, so a new show's folder or a mixed one
        (`NAS/Anime/`) holding one byte copy of another show's episode keeps its own show, and its episodes are never
        that show's versions (MV-A2: `_held` answers only for a folder joined by this rule). Never a book's part (a
        book's show is its name), never a text kept out or remembered as none (K6): those neither vote nor count."""
        if self._show_origins(_show_key(show)):
            return show
        texts = [t for t in texts if _key(t[1]) not in self.ex_paths and
                 (self.no_text.get(_key(t[1])) or [])[:2] != [t[2].st_size, t[2].st_mtime_ns]]
        votes = {t[1]: self._show_recorded(t[1]) for t in texts}
        votes.update((v[0], self._show_recorded(v[0])) for v in vids)
        picked = self._decides(show, texts, vids, votes)
        if picked is not False:
            return picked
        for _n, path, st in texts:                           # the recorded files decide nothing: their bytes
            shas = None if votes[path] else self._evidence("text", st.st_size)
            if votes[path] or not shas:
                continue
            try:
                got = self.read[path] = self.read.get(path) or _read_text(path, st)
            except OSError:
                continue
            votes[path] = shas.get(got[1], set())
        for path, st in vids:
            keys = None if votes[path] else self._evidence("video", st.st_size)
            if not votes[path] and keys and not ls.is_placeholder(st) and not self._recent(st):
                votes[path] = keys.get(self._content_key(path), set())
        picked = self._decides(show, texts, vids, votes)
        if picked is False and any(votes.values()):
            # the moves check (FC-1): a moved folder's texts the store never kept — another language's subtitles (K6),
            # a removed item's bytes — were recorded under the old path, so they'd outvote the moved episodes: only
            # the folder's texts of ours count (read once, only on this path: a vote found, no majority yet)
            texts = [t for t in texts if votes[t[1]] or self._ours(t[0], t[1], t[2])]
            picked = self._decides(show, texts, vids, votes)
        return show if picked is False else picked

    def _ours(self, name, path, st):
        """FC-1: could this text be an item of ours — not refused by the one rule (K6), not a removed item's bytes?
        True when it can't be read whole yet (never a guess against a vote)."""
        try:
            got = self.read[path] = self.read.get(path) or _read_text(path, st)
        except OSError:
            return True
        data, sha, head = got
        if sha is None:
            return True
        return sha not in self.ex_shas and not _refusal(head, self.language, name.lower().endswith(_LOOSE),
                                                         data is None)

    def _show_recorded(self, path):
        """D3: {the show} of the item this file's origin is recorded on (a `Library/<show>` copy), else empty."""
        o = self.origins.get(_key(path))
        show = _library_show(o.rel_path) if o is not None else None
        return {show} if show is not None else set()

    def _decides(self, show, texts, vids, votes):
        """D3, FIX1 (MV-A1): the show `votes` ({a file: the shows whose items it is}) join the folder to, `show` (two
        shows' items: neither), or False (none yet, or too few: one stray copy) — ONE show, named by most of the
        folder's texts (by its videos when it holds no text; a text that is no content of ours — another language's
        subtitle, a removed item's bytes — counts only when it votes), or by any of them when the folder's name ends in
        that show's whole name (`2024 Fall/Show` in `Show`; `Bocchi/Season 1` never in `Frieren/Season 1`)."""
        found = set().union(*votes.values()) if votes else set()
        if len(found) > 1:
            return show
        if not found:
            return False
        one = next(iter(found))
        mine, its = show.split("/"), one.split("/")          # the folder's name ends in the show's whole name
        if len(mine) >= len(its) and _show_key("/".join(mine[-len(its):])) == _show_key(one):
            return one
        base = [t[1] for t in texts] or [v[0] for v in vids]
        return one if 2 * sum(1 for p in base if votes.get(p)) > len(base) else False

    def _evidence(self, kind, size):
        """D3: the origins' texts of this size {sha256: shows} (`kind` "text") or their videos of this video size
        {video key: shows} ("video") — a version's too (its bytes are its episode's show's), never a book's part —
        empty when none. The origins are filed by size once a look; F13: each size's shows worked out only when it is
        asked (every origin's show and name read at once held the interpreter 0.4 s at 20k)."""
        if self.evidence is None:
            by_text, by_video = {}, {}
            for k, o in self.origins.items():
                if "#" in k:
                    continue
                if isinstance(o.size, int) and o.sha256:
                    by_text.setdefault(o.size, []).append((k, o))
                if isinstance(o.video_size, int) and o.video_key:
                    by_video.setdefault(o.video_size, []).append((k, o))
            self.evidence = {"text": by_text, "video": by_video}, {}
        filed, done = self.evidence
        if (kind, size) not in done:
            out = done[kind, size] = {}
            for k, o in filed[kind].get(size, ()):         # (as filed: the origins as first read)
                show = _library_show(o.rel_path)
                if show is None:
                    continue
                if kind == "text" and ls.is_content_name(os.path.basename(k)):
                    out.setdefault(o.sha256, set()).add(show)
                elif kind == "video":
                    out.setdefault(o.video_key, set()).add(show)
        return done[kind, size]

    def _content_key(self, path):
        """A video's content key (`videos.content_key`), read once a look (D3: a folder's show may ask it first)."""
        from app.connect import videos
        if path not in self.content_keys:
            self.content_keys[path] = videos.content_key(path)
        return self.content_keys[path]

    def _kept(self, held, dirs, seen):
        """A folder whose time didn't move: are its subtitle folders (listed with it) as they were too? Their
        entries are carried over when they are."""
        kept = {}
        for path in held.get("subtitles") or []:
            k = ls.path_key(path)
            try:
                mtime = os.stat(path).st_mtime_ns
            except OSError:
                return False
            if not dirs.get(k) or dirs[k].get("mtime_ns") != mtime:
                return False
            kept[k] = dirs[k]
        seen.update(kept)
        return True

    def _skips(self, folder):
        """A folder no look reads (K6: skipped; nothing under it is reached, its folder above never pushes it)."""
        return bool(self.skip) and ls.path_key(folder).rstrip("/") in self.skip

    def _subtitles(self, folder, subs, texts, epubs, vids, langs, seen):
        """The folder's subtitle folders — `Subs`, `Subtitles`, and a language's inside one (`Subs/ja`) — listed
        with it: their texts (and EPUBs, and videos) are the folder's own, so a subtitle there is its show's and pairs
        with its videos by name, and an untagged one in a language's folder is that language's (`langs`); each one's
        time kept beside the folder's (S4). One that can't be listed has the folder listed again next look.
        Which subfolders: `_subtitle_folder`, by name alone — `Subs`, the show's own name, a folder named for our
        language (its untagged texts ours, LF-15), and a versions folder (item 11: `synced/`, `retimed/`, LF-1),
        recorded in `versions`: its files are the folder's releases (the order, `_held`), and a number the folder lacks
        is the show's next episode (LF-2: never a show of its own, whatever it gains).
        -> (the folder's other subfolders, the subtitle folders listed)."""
        kinds = {s: _subtitle_folder(os.path.basename(s), os.path.basename(folder), self.language) for s in subs}
        todo = [(s, kinds[s] if kinds[s] not in ("subs", "versions") else None, None) for s in subs
                if kinds[s] and not self._skips(s)]
        others = [s for s in subs if not kinds[s]]
        for s in subs:
            if kinds[s] == "versions":
                self.versions.setdefault(ls.path_key(folder), set()).add(ls.path_key(s))
        listed_with = []
        while todo:
            path, language, owner = todo.pop(0)
            try:
                st = os.stat(path)
                listing = _listing(path)
            except OSError:
                listing = None
            if listing is None:
                self.unsettled.add(ls.path_key(folder))
                continue
            t, e, v, children, ghosts, unread = listing
            listed_with.append(path)
            self.listed_now.add(ls.path_key(path))
            seen[ls.path_key(path)] = {"path": path, "mtime_ns": None if self._recent(st) or unread else
                                       st.st_mtime_ns, "subs": []}
            self.out["skipped"] += ghosts
            texts.extend(t)
            epubs.extend(e)
            for name, video in v.items():
                vids.setdefault(name, video)
            if language:
                langs.update((x[1], language) for x in t)
            if owner:                                        # A11: the texts of `Subs/<video>/` are that video's
                self.video_of.update((x[1], owner) for x in t)
            for child in children:
                if self._skips(child):
                    continue
                tongue = None if language else _folder_language(os.path.basename(child))
                kind = _subtitle_folder(os.path.basename(child), os.path.basename(path), self.language)
                named = None if owner else _video_named(os.path.basename(child), vids)
                if named:                                    # A11 (LM1b): a folder named like a video beside it
                    todo.append((child, language, named))
                elif tongue:
                    todo.append((child, tongue, owner))
                elif kind:                                   # D1: the same named-folder rule all the way down
                    if kind == "versions":                   # (`<Show>/<Show>/Subs/`, `…/synced/`)
                        self.versions.setdefault(ls.path_key(folder), set()).add(ls.path_key(child))
                    todo.append((child, kind if kind not in ("subs", "versions") else language, owner))
                else:
                    others.append(child)
        return sorted(others), listed_with

    def _episodes(self, root, parts, texts, epubs, langs=None, vids=None, versions=(), show_of=None):
        """One folder's files as a look takes them (S7): another language's subtitles skipped (by the file's tag, else
        its language folder's: `langs`); one per episode — an episode already in keeps its own and the rest are
        skipped, else the first in the order of one episode's subtitles listed together (Sonic, the library model 2
        and T2-A1): named exactly like a video (`vids`, no flag: made for that video, so timed to it), then our
        language's tag, then (a flag after the plain one) in a versions folder listed with it (`versions`' keys, item
        11: `synced/`), then `.ass` / `.ssa` before `.srt`, then the first by name. Every pick passes K6's one language
        rule (`_refusal`, at `_new`): one that isn't ours is out and the next in this order takes its place — its
        group's, then the other releases of its episode (`runners_up`, LF-9: an English `.srt` named like the video
        never keeps the `.ja.srt` out) -> [(name, path, stat, show, 'new' | 'known' | 'book')]. A file of two
        languages in one mark (`.chs&jpn`, `[简日双语]`: LM1a) is ours when ours is one of them, taken only where no
        file of one language is; names are compared in NFC (A24). `show_of`: a file's show (`_shows_of`, D3), else
        `_show_of`'s."""
        like = video_names(vids or ())                                  # their names, lowered
        if show_of is None:
            def show_of(name):
                return _show_of(root, parts, name)

        def order(name, path):
            # PROVISIONAL (Sonic 2026-10-21: accepted for building, to be checked in use): this order (`subtitle_rank`)
            # and the grouping by the key below. "Named like a video" asks the names Connect pairs (`video_stems`:
            # `ep01.alt.srt`); LM2: the show's group, once it has one (`_show_group`), after that step
            named = path in self.video_of or named_like(name, like)                                  # made for it
            return subtitle_rank(name, self.language, named, (langs or {}).get(path),
                                 ls.path_key(os.path.dirname(path)) in versions,
                                 self.groups.get(_show_key(show_of(name))))
        out, groups = [], {}
        for t in texts:
            k = _key(t[1]) if self.no_text else None
            gone = (self.no_text.get(k) or []) if k is not None else []
            if gone[:2] == [t[2].st_size, t[2].st_mtime_ns] and (gone[2:3] != ["out"] or gone[3:4] and
                                                                  gone[3] in self.ex_shas):   # (LM1b N5: kept out)
                self.no_text_kept[k] = self.no_text[k]       # none of our script in it, or short, unchanged (K6)
                self.out["skipped"] += 1
                self.out["short"] += self.no_text[k][2:] == ["short"]
                continue
            if _key(t[1]) in self.ex_paths:                  # kept out (S6) — never a pick, never a version
                self.out["skipped"] += 1
                continue
            n = en.identity(t[0])
            if n.year:
                self.years.setdefault(_show_key(show_of(t[0])), set()).add(n.year)
            language = n.language or (langs or {}).get(t[1])
            if language not in (None, self.language) or "forced" in n.flags or (
                    n.bilingual and self.language not in n.languages):   # a forced track holds only the signs
                self.out["skipped"] += 1
                continue
            group = ("\0" + self.video_of[t[1]]) if t[1] in self.video_of else _nfc(n.stem).casefold()   # A11
            groups.setdefault(group, []).append((language, bool(n.flags), t))
        for members in groups.values():
            mine = [t for _l, _f, t in members if _key(t[1]) in self.origins]
            if mine:                                         # LM1b: the rest are its versions
                item = self.origins[_key(mine[0][1])].item_id
                out.extend((n, p, st, show_of(n), "known") for n, p, st in mine)
                out.extend((n, p, st, show_of(n), "version", item) for _l, _f, (n, p, st) in members
                           if _key(p) not in self.origins)
                continue
            members.sort(key=lambda m: order(m[2][0], m[2][1]))
            self.out["skipped"] += len(members) - 1
            n, p, st = members[0][2]
            out.append((n, p, st, show_of(n), "new"))
            if len(members) > 1:                             # the next in its place if this one isn't ours (B5)
                self.runners_up[p] = [m[2] for m in members[1:]]
        # K1, LM1b: ONE file per episode found new here — the episode its key says (`_keys`: its video's, by name or
        # number, A4, else its name's), so its releases (`[A] Show - 05`, `[B] Show - 05 (720p)`, `Show - 05 - Title`,
        # jimaku's `星空喫茶 第5話`) are one: of the latest version (`- 05v2` over `- 05`) the first in the order above;
        # every other file of the episode is behind it (`runners_up`: in its place if the language rule refuses it,
        # LF-9 — a lower version newest first, D6 — and else its versions). A double episode (`- 05-06`) is the
        # episode of its first number, and a version only where single files cover every number it claims (the singles
        # win wherever they are; PROVISIONAL)
        read = {}
        for n, p, _st, show, kind, *_item in out:
            keys = self._keys(n, self._video_for(p, n, vids)[0], show) if kind == "new" else []
            if keys:
                read[p] = (keys, _episode_of(n)[1], self._claims(n, show))
        if read:
            owner = {}
            for p, (keys, _v, claims) in read.items():
                if len(claims) < 2:
                    for k in keys:
                        owner.setdefault(k, keys[0])
            ep = {}
            for p, (keys, _v, claims) in read.items():
                ep[p] = keys[0]
                if len(claims) > 1 and all(k in owner for k in claims):
                    ep[p] = owner[claims[0]]                 # covered by single files: their version
            def rank(e):                                     # a double episode after the singles (PROVISIONAL)
                o = order(e[0], e[1])
                return o[:2] + (e[1] in read and len(read[e[1]][2]) > 1,) + o[2:] + (e[1],)
            self._decide_groups(out, read, ep, rank)          # LM2: a show's group, before its episodes are picked
            latest, first = {}, {}
            for p, (_keys, version, _c) in read.items():
                latest[ep[p]] = max(latest.get(ep[p], 0), version)
            for e in sorted(out, key=rank):
                if e[1] in read and read[e[1]][1] == latest[ep[e[1]]]:
                    first.setdefault(ep[e[1]], e[1])
            kept, lower = [], []
            for e in sorted(out, key=rank):
                r = read.get(e[1])
                if r is not None and (r[1] < latest[ep[e[1]]] or first[ep[e[1]]] != e[1]):
                    self.out["skipped"] += 1
                    behind = [e[:3]] + self.runners_up.pop(e[1], [])
                    if r[1] == latest[ep[e[1]]]:             # LF-9: the first's runner-up — the one language rule
                        self.runners_up.setdefault(first[ep[e[1]]], []).extend(behind)   # (`_refusal`, at `_new`)
                    else:                                    # passes on it if it isn't ours; D6: a lower version
                        lower.append((r[1], ep[e[1]], behind))   # waits behind the latest, newest first
                else:
                    kept.append(e)
            for _v, k, behind in sorted(lower, key=lambda x: -x[0]):
                self.runners_up.setdefault(first[k], []).extend(behind)
            kept = {id(e) for e in kept}
            out = [e for e in out if id(e) in kept]       # (in the listing's order, as before)
        for n, p, st in epubs:
            k = _key(p)
            if k in self.pending_books:                      # LM3: its new edition waits in the store (W1): never
                self._wait(os.path.dirname(p))               # hashed nor split again (`settle_editions` carries it)
                continue
            if self._edition_waits(k, st):                   # A7: a part it needs isn't there: until something changes
                self.out["waiting"] += 1
                continue
            if k in self._book_keys() and not self._book_moved(k, st):   # a known EPUB is never split again (LM3:
                continue                                     # one whose stats moved may be its new edition)
            if self.no_text.get(k) == [st.st_size, st.st_mtime_ns]:   # no text in it, and unchanged (K5)
                self.no_text_kept[k] = self.no_text[k]
                self.out["skipped"] += 1
                continue
            out.append((n, p, st, show_of(n), "book"))
        return out

    def _decide_groups(self, out, read, ep, rank):
        """LM2 (PROVISIONAL, Sonic 2026-10-21: LM-1a, A29): the group of each show this folder's new episodes belong to
        that has none yet — the group its earliest episode in was picked from (`_held`), else the group of the file
        this look takes for its earliest episode here (its latest release, ranked with no group: named like its video
        first, T2-A1; `_new` names it once the language and thin rules let it in: `deciding`) — kept for the look
        (`groups`) and handed to `take_in` with the show's files (`decided`), which records it on the show's title; a
        show's recorded group is never decided again (an earlier episode arriving later changes nothing)."""
        shows = {}
        for e in out:
            if e[1] in read:
                fk = _show_key(e[3])
                if fk not in self.groups:
                    shows.setdefault(fk, []).append(e)
        for fk, entries in shows.items():
            held = self._held(entries[0][3])
            if held:
                name = os.path.basename(held[min(held, key=_key_order)][1].origin or "")
                self.decided[fk] = {"group": list(_group(name)), "label": group_label(name)}
            else:                                    # its latest release first, as the pick (D6)
                first = min((ep[e[1]] for e in entries), key=_key_order)
                cands = [e for e in entries if ep[e[1]] == first]
                latest = max(read[e[1]][1] for e in cands)
                name = min((e for e in cands if read[e[1]][1] == latest), key=rank)[0]
                self.deciding[fk] = first            # recorded from the file `_new` takes for it (K6, A6 may refuse)
            self.groups[fk] = _group(name)

    def _episode_key(self, name, show=None):
        """LM1a: `episode_key`, with A3's years read from the show (`show`: its `Library` folder) the name is in."""
        return episode_key(name, self.language, years=None if show is None else lambda: self._years(show))

    def _years(self, show):
        """A3: the years the names of a show's files write — its new ones this look and its origins'."""
        fk = _show_key(show)
        if fk not in self.origin_years:
            self.origin_years[fk] = {y for y in (en.identity(os.path.basename(o.origin or "")).year
                                                 for o in self._show_origins(fk)) if y}
        return self.origin_years[fk] | self.years.get(fk, set())

    def _removed(self, show, episode, name):
        """K2 (S6): a removed episode's key — its show and number as recorded (the exclusion's note) or read from the
        new file's place, the rest of the key (show of the name, season, part, special) from its name. Each show by
        the one "same show?" key (a8: a removed `Show - 03`'s re-release copied for the folder `Show!/` stays out)."""
        _show, season, _episode, part, special = en.identity(name).key
        same = lambda s: en.show_key(ls.search_fold(s, self.language)) or ls.search_fold(s, self.language)  # noqa: E731
        return (same(show), episode, same(_show), season, part, special)

    def _book_keys(self):
        """The EPUBs already in or kept out (their parts' origins, `<epub>#<n>`): gathered once a look (H20), kept by
        `_refresh`."""
        if self.book_keys is None:
            self.book_keys = set(self._members("head")) | {k.rsplit("#", 1)[0] for k in self.ex_paths if "#" in k}
        return self.book_keys

    # --- new files (SRC-7) ----------------------------------------------------------------------------------------- #

    def _take(self, new, books=()):
        """Each show's new files, checked and copied, handed to `take_in` BATCH at a time, and each book (its own
        show, by its name) among them in name order (SRC-1); a stop ends the look after the files already copied are
        taken in."""
        from app.extract import clean_name
        by_show = {}
        for c in new:                                        # a text (6), a version (7), a video waiting for its text (4)
            by_show.setdefault(c[4] if len(c) >= 6 else c[3], []).append(c)
        editions = {}                                        # D1: a folder's editions of one book, newest first
        for b in books:                                      # (the newest is the book's text, the others versions)
            editions.setdefault((ls.path_key(os.path.dirname(b[2])), edition_name(b[1]) or b[1]), []).append(b)
        for group in editions.values():
            group.sort(key=lambda b: -b[3].st_mtime_ns)
            by_show.setdefault(clean_name(os.path.splitext(group[0][1])[0]) or "Book", []).extend(group)
        self.to_copy = sum(len(v) for v in by_show.values())
        order = sorted(by_show, key=lambda s: (ls.search_fold(s, self.language), s))
        self._pools([c[2] for show in order for c in by_show[show] if len(c) == 5 and c[1].lower().endswith(EPUB)])
        try:
            self._take_in(by_show, order)
        finally:
            self._pools(())
        if self.out["stopped"]:
            return
        self._refused_only()
        self._switch_better()

    def _pools(self, epubs):
        """K5 C2: the splitting processes and the writing threads for this look's new EPUBs — as many as the indexer
        would take for as many files (`token_index.pool_workers` with settings.json's `index_pool_workers`: none under
        POOL_MIN_FILES, half the cores, every core with *Use every core*); `()`: closed."""
        if not epubs:
            for pool in (self.splitter, self.writers):
                if pool is not None:
                    try:
                        if pool is self.splitter:
                            pool.close(wait=not self.out["stopped"])      # Stop ends now: splits under way not waited
                        else:
                            pool.shutdown()
                    except Exception as e:
                        log.info("A look's pool didn't close cleanly: %r", e)
            self.splitter = self.writers = None
            return
        try:
            from concurrent.futures import ThreadPoolExecutor
            from app import settings_manager
            from app.token_index import every_core, pool_workers
            try:
                setting = settings_manager.load_settings().get("index_pool_workers")
            except Exception:
                setting = None
            size = pool_workers(len(epubs), setting, every=every_core())
            if size < 2:
                return
            self.writers = ThreadPoolExecutor(size, thread_name_prefix="book-parts")
            self._load()
            known = set(self._books()) | set(self.ex_shas)
            self.splitter = _Splitter(epubs, self.language, size, known)
        except Exception as e:                               # no pool: the look reads and writes them itself
            log.info("No pool for this look's books (read here): %r", e)
            self._pools(())

    def _take_in(self, by_show, order):
        for show in order:
            batch = []
            for c in by_show[show]:
                if self.stopped():
                    break
                self._copy_done()
                if len(c) == 5:                              # a book: taken in on its own, all its parts at once
                    try:
                        self._book(*c)
                    except OSError:                          # locked, or its Library folder unreadable: next look
                        self._wait(c[0])
                    except Exception as e:                   # anything else (A6): logged, the next look
                        log.warning("A book couldn't be read in (the next look tries again): %s: %r", c[2], e,
                                    exc_info=True)
                        self._wait(c[0])
                    continue
                try:
                    if len(c) == 7:                          # LM1b: another version of an episode in (counted skipped)
                        self.out["skipped"] += 1
                        f = self._version(c[0], c[1], c[2], c[4], c[3], item_id=c[6])
                    else:
                        f = self._new(*c) if len(c) == 6 else self._video_only(*c)
                except OSError:                              # gone or locked meanwhile: the next look
                    self._wait(c[0])
                    f = None
                if f is not None:
                    batch.append(f)
                batch.extend(self._pending())                # its versions in the same batch, after it (`take_in`)
                decided = self.decided.get(_show_key(show))
                if decided is not None:                      # LM2: the show's title records it at this take-in
                    for f in batch:
                        f.setdefault("show_group", decided)
                if len(batch) >= BATCH:
                    self._commit(batch)
                    batch = []
            self._commit(batch)
            if self.out["stopped"]:
                return

    def _refused_only(self):
        """LF-19: a folder's videos whose every subtitle pick the one language rule refused (`_refusal` at `_new`: an
        English `.srt`, a short note) wait as the videos of a folder with none of our text do (K5) — the waiting check
        sees what the rule refuses, in this look; the next look skips those texts by their stats and finds the videos
        waiting already."""
        by_show = {}
        for waits, picks in self.held_videos:
            if picks <= self.refused:
                for w in waits:
                    by_show.setdefault(w[3], []).append(w)
        for show in sorted(by_show, key=lambda s: (ls.search_fold(s, self.language), s)):
            batch = []
            for w in by_show[show]:
                if self.stopped():
                    return
                self.out["found"] += 1
                self.shows.add(ls.search_fold(show, self.language))
                try:
                    f = self._video_only(*w)
                except OSError:                              # gone or locked meanwhile: the next look
                    self._wait(w[0])
                    f = None
                if f is not None:
                    batch.append(f)
            self._commit(batch)

    def _switch_better(self):
        """LM3 (a), answer 3 (PROVISIONAL): an item a version was recorded on this look — or whose version a folder
        listed holds (a switch held before, a version recorded before LM3; checked first from the origins read,
        `_maybe_better`) — switched to its better version IN PLACE when the look's own order ranks that above the
        item's text, as the look would have picked it had both been there at once (`Store.switch_versions`: the one
        rule `group_copies` / `better`, its own group's only, A6's thin rule; LM2's one swap path). A busy store, or a
        switch that fails: the next look (never the end of this one)."""
        todo = sorted(self.better | {i for i in self.listed - self.better if self._maybe_better(i)})
        if not todo or self.stopped():
            return
        try:
            self._switched(self.store.switch_versions(todo, stop=self.stopped))
            return
        except ls.StoreError as e:                   # busy: the next look
            log.info("A better version's switch waits (the next look tries again): %r", e)
            return
        except Exception as e:                       # anything: never the end of the look; item by item, so
            log.warning("A better version's switch failed (tried item by item): %r", e, exc_info=True)
        for item_id in todo:                         # one item failing never holds the others back
            if self.stopped():
                return
            try:
                self._switched(self.store.switch_versions([item_id], stop=self.stopped))
            except Exception as e:                   # left for the next look
                log.warning("Item %s's better version couldn't switch (the next look tries again): %r", item_id, e,
                            exc_info=True)

    def _switched(self, change):
        """A switch's Change counted in the look's result (`switched`, `switched_works`); an edition's Undo the
        look finished (kind `undo`) is none."""
        if change.kind == "undo":
            return
        self.out["switched"] += len(change.switched)
        added = [i for i in getattr(change, "added", None) or () if i not in self.out["ids"]]
        self.out["added"] += len(added)                  # (a new edition's extra parts: new items of the book)
        self.out["ids"].extend(added)
        for work in getattr(change, "switched_works", None) or ():
            if work not in self.out["switched_works"]:
                self.out["switched_works"].append(work)

    def _maybe_better(self, item_id):
        """Might the item take a better version (`switch_versions` decides)? From the origins read (no read of the
        store): its own text's group has a version the one rule ranks above it."""
        found = self._by_item().get(item_id) or []
        record = lambda o: (o.origin, {"origin": o.origin, "sha256": o.sha256, "video_path": o.video_path,  # noqa
                                       "size": o.size, "mtime_ns": o.mtime_ns, "declined": o.declined, "thin": o.thin})
        picks = [record(o) for o in found if not o.version]
        versions = [record(o) for o in found if o.version]
        if not picks or not versions or found[0].availability != "available" or \
                ls._EPUB_PART.search(str(picks[0][0] or "")) or \
                any(audiobooks.is_audio(str(p[0] or "")) for p in picks):   # a6: an audiobook's text is its transcript
            return False
        mine, rank, best = group_copies(picks, versions, self.language)
        return mine in best and better(best[mine][1], rank)

    def _commit(self, found):
        """`take_in` of one batch; a copy no item holds (the source stopped meanwhile — this batch's copies — or the
        store's `unused`: a file known or kept out after all, a second file of the same bytes) goes to the trash, never
        left in Library untracked (N3)."""
        self._keep_hashes()
        if not found:
            return None
        made = [f["rel"] for f in found if f.get("rel") in self.made]
        follow = {f["origin"]: self.follow.pop(f["origin"]) for f in found if f["origin"] in self.follow}
        try:
            change = self.store.take_in(self.root_id, found, first=self.first, rules=self.rules)
        except ls.NotASource:
            self.out["stopped"] = True                       # stopped reading meanwhile: no v2 followed either
            for rel in made:
                self._trash(rel)
            return None
        if change is None:
            return None
        self._videos_taken(found, change)
        self.batches += 1
        if self.batches % CHECKPOINT_EVERY == 0:             # the WAL kept short over a long look
            try:
                self.store.checkpoint(wait=0.1)
            except ls.StoreError:                            # busy: the next one
                pass
            except sqlite3.Error as e:                       # housekeeping: never the end of the look (the next retries)
                log.warning("A checkpoint of the library failed (the look goes on): %r", e)
        self.out["added"] += len(change.added)
        self.out["ids"].extend(change.added)
        added = set(change.added)                            # LM3 (a): an item in before took a version
        self.better.update(i for i in getattr(change, "versions", None) or () if i not in added)
        self.out["attached"] += len(change.attached)
        self.out["skipped"] += sum(len(v) for v in change.skipped.values())
        for rel in change.unused:
            self._trash(rel)
        skipped = {o for v in change.skipped.values() for o in v}
        for origin, held in follow.items():
            if origin not in skipped:
                self._follow(origin, *held)
        return change

    def _videos_taken(self, found, change):
        """The look's video map (`_video_item`) after a take-in: each recorded text's video is its item's (the lowest
        id); a video waiting for its text is no item's yet (K5)."""
        if self.videos is None:
            return
        for f in found:
            item, vkey = change.recorded.get(os.path.abspath(f["origin"])), f.get("video_key")
            if item is None or not vkey:
                continue
            if not ls.is_content_name(os.path.basename(f["origin"]).lower()):   # a video's own: a waiting item
                continue
            if vkey not in self.videos or item < self.videos[vkey]:
                self.videos[vkey] = item

    def _trash(self, rel):
        """A copy no item holds, to the trash; one the trash can't take (held open) is left as it is, logged — never
        the end of the look (H7)."""
        try:
            ls.trash_file(self.data_dir, rel)
        except OSError as e:
            log.warning("A copy no item holds couldn't go to the trash (%s): %s", rel, e)

    def _follow(self, origin, earlier, path, st, folder):
        """H12: a v2 now recorded on its episode — the episode's copy takes its text (S5). When that has to wait, its
        record names the copy's bytes and no time, so the next look listing its folder follows it."""
        outcome, sha = self._recopy(earlier.rel_path, earlier.sha256, path, st)
        if outcome in ("done", "same"):
            self.store.update_origin(origin, st.st_size, st.st_mtime_ns, sha)
            self.out["recopied"] += outcome == "done"
            return
        self.store.update_origin(origin, st.st_size, 0, earlier.sha256)
        self._wait(folder)

    def _new(self, folder, path, st, name, show, vids):
        """One new text file -> its `found` entry for `take_in` (an `item_id` for an episode already in, else the
        copy's `rel`; `version` for another version of one, LM1b), or None (skipped, or waiting for the next look).
        Its video is `_video_for`'s (its name, else its episode's number, A4); its episode is its show's (`_held`, A9:
        from any folder or source) — one already in takes it as another version (A8: a later release only from the
        pick's own group, of its kind or a better one, is followed instead, S5). A pick holding under a quarter of the
        lines of its episode's fullest candidate gives way to the next (`_thin`, A6)."""
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return None
        episode, version = _episode_of(name)
        vname, _by = self._video_for(path, name, vids)
        keys = self._keys(name, vname, show)
        held = next((h for h in map(self._held(show).get, keys) if h is not None), None) if keys else None
        claims = self._claims(name, show)
        if held is not None and len(claims) > 1 and not all(k in self._held(show) for k in claims):
            held = None                                      # a double episode of a number held by nothing
        held_name = os.path.basename(held[1].origin or "") if held is not None else ""
        forced = None
        if held is not None and (held[1].item_id in self.hato_ids or not (    # LM3: hato's text is never followed
                held[0] < version and _kind(name) <= _kind(held_name) and  # I9: a worse kind's v2, A8: another
                _group(name) == _group(held_name))):                       # group's, is a version
            got = self.read[path] = self.read.get(path) or _read_text(path, st)
            if got[1] is None or got[1] != held[1].sha256:   # (A26: the pick's own bytes found again — a moved
                self.out["skipped"] += 1                     # show — are its origin, with its video, never a version)
                return self._version(folder, path, st, show, name, item_id=held[1].item_id, chain=True)
            forced = held[1].item_id
        removed = self._removed(show, episode, ls.path_key(name))
        release = removed + (_release(ls.path_key(name)),)
        if forced is None and ((version > 1 and removed in self.ex_episodes) or release in self.ex_releases or
                               (episode is not None and removed[:2] + removed[3:] in self.ex_joined)):
            self.out["skipped"] += 1                         # K2, A12: every file of a removed episode stays out,
            return None                                      # whatever its group or title (PROVISIONAL)
        if self._recent(st):
            self._wait(folder)
            return None
        if self.runners_up.get(path):                        # A6: a signs track is never the episode's text
            thin = self._thin(path, st, name, show, vids)
            if thin is not False:
                return thin
        video, vkey = (vids.get(vname) if vname else None), None
        if video and not ls.is_placeholder(video[1]):
            if self._recent(video[1]):
                self._wait(folder)
                return None
            vkey = self._content_key(video[0])
            if vkey is None:                                 # changed while read
                self._wait(folder)
                return None
            if vkey in self.ex_videos:
                self.out["skipped"] += 1
                self._kept_out(folder, path, video=vkey)
                return None
        track = vkey or (ls.path_key(os.path.abspath(video[0])) if video else None)
        if track is not None and track in self.this_videos:  # one subtitle per video per language: the next look's
            self._wait(folder)
            return None
        data, sha, head = self.read.pop(path, None) or _read_text(path, st)   # read once: copied from memory
        if sha is None or not self._same(path, st):
            self._wait(folder)
            return None
        if sha in self.ex_shas:
            self.out["skipped"] += 1
            self._kept_out(folder, path, sha=sha)
            return None
        if sha in self.this_look:                            # the same bytes twice: the next look attaches it
            self._wait(folder)
            return None
        if episode is None and video:                        # A11: `Subs/<video>/2_Japanese.srt` is its video's
            episode = _episode_of(os.path.basename(video[0]))[0]
        f = {"origin": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
             "show": show}
        if episode is not None:
            f["episode"] = episode
        if video:
            f["video_path"], f["video_size"] = os.path.abspath(video[0]), video[1].st_size
            if vkey:
                f["video_key"] = vkey
        item = (self._video_item(vkey) if vkey else None) or self._same_bytes(st.st_size, sha) or forced
        if item is None:                                     # a waiting item of its episode (another release's
            gap = next((g for g in map(self._waits(show).get, keys) if g is not None), None)   # video) takes it in place
            if gap is not None:
                f["gap"] = gap
        why = None if item is not None else _refusal(head, self.language, name.lower().endswith(_LOOSE), data is None)
        if why:                                              # K6: a skin config, an English .srt, a Chinese fansub,
            self._pass_over(path, st, why)                   # a readme: no new text and no v2's — not read again
            rest = self.runners_up.pop(path, None)           # until it changes; B5: the episode's next file (the
            if not rest:                                     # Japanese `.srt` after a Chinese `.ass`) in its place
                self.refused.add(self.chain.get(path, path))     # LF-19: the pick and all behind it refused
                return None
            self.out["skipped"] -= 1
            if rest[1:]:
                self.runners_up[rest[0][1]] = rest[1:]
            self.chain[rest[0][1]] = self.chain.get(path, path)
            n, p, s = rest[0]
            return self._new(os.path.dirname(p), p, s, n, show, vids)
        if item is None and held is not None and held[0] < version:   # a v2 of an episode already in (S5)
            earlier = held[1]
            if self._refuses(earlier.rel_path, st):          # not followed: nor recorded (its bytes aren't the item's)
                self.out["skipped"] += 1
                return None
            item = earlier.item_id
            self.follow[f["origin"]] = (earlier, path, st, folder)   # its text followed once take_in records it (H12)
        if item is not None:
            f["item_id"] = item
            moved = self._moved_from(item, path, sha256=sha)
            if moved:
                f["moved_from"] = moved
        else:
            copy = name                                      # A11: a `Subs/<video>/` file is named as its video
            if path in self.video_of and video:
                copy = os.path.splitext(os.path.basename(video[0]))[0] + os.path.splitext(name)[1]
            rel = self._copy(path, st, show, copy, sha, data)
            if rel is None:
                self._wait(folder)
                return None
            f["rel"], f["copy_sha256"] = rel, sha
        self.this_look.add(sha)
        if track is not None:
            self.this_videos.add(track)
        for n, p, s in self.runners_up.pop(path, []):        # LM1b: the episode's other files are its versions
            self.pending.append((os.path.dirname(p), p, s, show, n, item, f["origin"]))
        fk = _show_key(show)
        if self.deciding.get(fk) in keys and fk not in self.decided:   # LM2: the file taken decides the show's group
            self.groups[fk] = _group(name)
            self.decided[fk] = {"group": list(_group(name)), "label": group_label(name)}
        return f

    def _version(self, folder, path, st, show, name, item_id=None, of=None, chain=False):
        """LM1b: another version of an episode in (of the item `item_id`, or of the pick `of` taken in this batch) ->
        its `found` entry (`version`: no copy, no video, never counted), or None — kept out, refused by the one
        language rule (remembered by its stats as K6's are; it was counted skipped already) or not settled (its
        folder listed again next look). `chain`: the episode's other files behind it are versions too. Read once, as
        any new text, so Remove keeps its bytes out and a switch (LM3) knows them."""
        if chain:
            for n, p, s in self.runners_up.pop(path, []):
                self.pending.append((os.path.dirname(p), p, s, show, n, item_id, of))
        if _key(path) in self.ex_paths:
            return None
        if self._recent(st):                                 # LM1b N5: it waits — counted waiting (every caller
            self.out["skipped"] -= 1                         # counted it skipped)
            self._wait(folder)
            return None
        data, sha, head = self.read.pop(path, None) or _read_text(path, st)
        if sha is None or not self._same(path, st):
            self.unsettled.add(ls.path_key(folder))
            return None
        if sha in self.ex_shas:                              # LM1b N5: a removed item's bytes — remembered by its
            self.no_text_kept[_key(path)] = [st.st_size, st.st_mtime_ns, "out", sha]   # stats, never read again
            return None                                      # while they stay out
        why = _refusal(head, self.language, name.lower().endswith(_LOOSE), data is None)
        if why:
            self.no_text_kept[_key(path)] = [st.st_size, st.st_mtime_ns] + (["short"] if why == "short" else [])
            self.out["short"] += why == "short"
            return None
        f = {"origin": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
             "show": show, "version": True}
        episode = _episode_of(name)[0]
        if episode is not None:
            f["episode"] = episode
        if item_id is not None:
            f["item_id"] = item_id
        else:
            f["version_of"] = of
        return f

    def _pending(self):
        """The versions `_new` / `_version` left for the batch of the pick they follow (`pending`), read now."""
        out = []
        while self.pending:
            folder, path, st, show, name, item_id, of = self.pending.pop(0)
            try:
                f = self._version(folder, path, st, show, name, item_id=item_id, of=of, chain=True)
            except OSError:                                  # gone or locked meanwhile: the next look
                self.unsettled.add(ls.path_key(folder))
                f = None
            if f is not None:
                out.append(f)
        return out

    def _thin(self, path, st, name, show, vids):
        """A6: is the pick `path` thin — under 1/THIN of the dialogue lines of the fullest of its peers (its episode's
        candidates in `runners_up` of its kind or a better one, `_kind`, each the language rule takes: a signs or songs
        track never out-counts a plain file)? Then the first peer that isn't thin stands in (`_new`'s
        answer on it) and this one goes behind the rest, a version; else False."""
        rest = self.runners_up.get(path) or []
        mine = self._lines(path, st, name)
        if mine is None:
            return False
        peers = [(x, p, s, n) for x, p, s in rest if _kind(x) <= _kind(name) and not self._recent(s)
                 for n in [self._lines(p, s, x)] if n is not None]
        most = max([mine] + [n for *_r, n in peers])
        if mine * THIN >= most:
            return False
        x, p, s, _n = next(c for c in peers if c[3] * THIN >= most)
        self.runners_up.pop(path)
        self.runners_up[p] = [c for c in rest if c[1] != p] + [(name, path, st)]
        self.chain[p] = self.chain.get(path, path)
        return self._new(os.path.dirname(p), p, s, x, show, vids)

    def _lines(self, path, st, name):
        """A6: a candidate's dialogue lines — the distinct texts of its `Dialogue:` lines (.ass / .ssa: override tags
        `{…}` off, a sign drawn frame by frame once) or of its cues (.srt), by what it holds — or None: none (a text,
        not a subtitle), it can't be read as listed, or the one language rule refuses it. Read once (`read`: `_new`
        and `_version` take it from there)."""
        if path not in self.read:
            try:
                self.read[path] = _read_text(path, st)
            except OSError:
                self.read[path] = (None, None, None)
        data, sha, head = self.read[path]
        if sha is None or _refusal(head, self.language, name.lower().endswith(_LOOSE), data is None):
            return None
        return dialogue_lines(decode_text(head, self.language, head=data is None)) or None

    def _video_for(self, path, name, vids):
        """LM1b, the ONE pairing rule of a look (`video_for`): a text in `Subs/<video>/` is that video's (A11); else
        `video_for`, the folder's videos' keys read once a look."""
        if not vids:
            return None, None
        if path in self.video_of:
            v = self.video_of[path]
            return (v, "name") if v in vids else (None, None)
        return video_for(name, vids, self.language, keyed=lambda: self._video_keys(vids))

    def _video_keys(self, vids):
        held = self.vkeys.get(id(vids))                      # the folder's videos' keys, read once a look
        if held is None or held[0] is not vids or held[1] != len(vids):
            held = self.vkeys[id(vids)] = (vids, len(vids), video_keys(vids, self.language))
        return held[2]

    def _keys(self, name, video=None, show=None):
        """LM1b: the episode keys a text answers to in its show (`show`: `_episode_key`'s years) — its video's first
        (`_video_for`), then its name's own (a double episode's first number: `_claims` holds the rest); [] when it
        reads none."""
        own = self._episode_key(name, show)
        first = self._episode_key(video, show) if video else None
        return list(dict.fromkeys(k for k in (first, own) if k))

    def _claims(self, name, show=None):
        """A13: the keys of every number a name claims — a double episode `05-06` claims 5 and 6; one key for a single
        number, [] for none."""
        n, own = en.identity(name), self._episode_key(name, show)
        return [] if own is None else [own[:2] + (e,) + own[3:] for e in (n.episodes or (n.episode,))]

    def _waiting(self, vids):
        """K5, LM1b: the videos of a folder with none of our text that wait for it — one per episode (A5: videos whose
        keys agree are releases of one episode: `_video_rank`'s first), never an extra's — a creditless opening or
        ending, a promotion, an advert, a trailer, a menu (A32: `episode_names.extra`) ->
        [(path, stat)] in name order."""
        out, seen = [], set()
        for low in sorted(vids, key=lambda v: _video_rank(v, vids)):
            if en.extra(low):
                continue
            k = self._episode_key(low)
            if k is not None and k in seen:
                continue
            seen.add(k)
            out.append(vids[low])
        return sorted(out)

    def _late(self):
        """LM1b (A19, A20): a known text of a folder listed, recorded with no video, whose video is there now (by
        `_video_for`'s rule) — or whose recorded video was renamed (gone, and one beside it of the same size and content
        key) — has it recorded on its origin (`update_origins`, LATE_BATCH a write; no new item). Never a version's,
        a waiting item's, a video another item holds or one kept out."""
        from app.connect import videos
        found = []
        for folder, path, name, vids in self.late:
            if self.stopped():
                break
            if len(found) >= LATE_BATCH:
                self._record_late(found)
            o = self.origins.get(_key(path))
            if o is None or o.version or not vids or o.availability == "waiting":
                continue
            video = None
            if o.video_path:                                 # A20: renamed beside it, its bytes the same
                if os.path.basename(o.video_path).lower() in vids or os.path.exists(o.video_path):
                    continue
                for _low, (vpath, vst) in sorted(vids.items()):
                    if vst.st_size == o.video_size and not ls.is_placeholder(vst) and not self._recent(vst) and \
                            videos.content_key(vpath) == o.video_key:
                        video = (vpath, vst, o.video_key)
                        break
            else:                                            # A19: its video came after it
                vname, _by = self._video_for(path, name, vids)
                if vname is None or ls.is_placeholder(vids[vname][1]):
                    continue
                vpath, vst = vids[vname]
                pk = ls.path_key(os.path.abspath(vpath))
                if pk in self._recorded() or pk in self._waiting_items() or pk in self.ex_paths:
                    continue                                 # another item's video, a waiting one's or one kept out:
                if self._recent(vst):                        # its content key is never read for it
                    self._wait(folder)
                    continue
                vkey = videos.content_key(vpath)
                if vkey is None:
                    self._wait(folder)
                    continue
                if vkey in self.ex_videos or self._video_item(vkey) not in (None, o.item_id) or \
                        vkey in self._waiting_items():
                    continue                                 # never a video a waiting item holds
                video = (vpath, vst, vkey)
            if video is None:
                continue
            found.append((o.origin or path, video))
            self._recorded().add(ls.path_key(os.path.abspath(video[0])))   # claimed now: a later text of this pass
            if self.videos is not None:                      # never takes it
                self.videos[video[2]] = min(o.item_id, self.videos.get(video[2], o.item_id))
        self._record_late(found)

    def _record_late(self, found):
        """`_late`'s finds written LATE_BATCH at a time (`update_origins`: one write each, never one per subtitle — a
        library's first look may pair hundreds); `found` is emptied."""
        if not found:
            return
        # (None: its stats as they are — a re-copy this look rewrote them)
        self.out["paired"] += len(self.store.update_origins([
            (origin, None, None, None, {"video_path": os.path.abspath(video[0]), "video_size": video[1].st_size,
                                        "video_key": video[2]}) for origin, video in found]))
        del found[:]

    def _recorded(self):
        """The path keys of the videos the origins' records name (read once a look)."""
        if self.recorded is None:
            self.recorded = {ls.path_key(os.path.abspath(o.video_path)) for o in self.origins.values() if o.video_path}
        return self.recorded

    def _waiting_items(self):
        """{video key or path key: item} of the items waiting for their text (read once a look)."""
        if self.waits is None:
            with self.store._reading():
                self.waits = self.store._waiting_videos()
        return self.waits

    def _waits(self, show):
        """A5: {episode key: item} of this show's items waiting for their text (a video's, K5) — one per episode:
        another release's video of it never waits beside it, and its subtitle fills it in place."""
        out = {}
        for o in self._show_origins(_show_key(show)):
            name = os.path.basename(o.origin or "")
            k = self._episode_key(name, show) if o.availability == "waiting" and not o.version and \
                not ls.is_content_name(name.lower()) else None
            if k is not None:
                out.setdefault(k, o.item_id)
        return out

    def _show_origins(self, fk):
        """The origins of the show whose `Library` folder key is `fk` (the origins grouped by it once a look; F13: a
        show's own list built when first asked, kept by `_refresh` from then on)."""
        if self.by_show is None:
            self.by_show, self.show_origins = {}, {}
        if fk not in self.shows_asked:
            self.shows_asked.add(fk)
            self._rebuild("show", fk)
        return self.show_origins.get(fk, ())

    def _video_only(self, folder, path, st, show):
        """A video in a folder with none of our text yet (K5, SRC-2 (video)) -> its found-record for `take_in`: one
        item per video, waiting in New arrivals (*no subtitles yet*) at `Library/<show>/<video name>`, no file made,
        until its subtitle fills the gap in place — or None: recorded already, paired already (hato's), of a show
        already shown (its subtitles will join it), kept out (S6), or waiting for the next look."""
        if _key(path) in self.origins:
            return None
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return None
        stats = [st.st_size, st.st_mtime_ns]
        name = os.path.basename(path)
        moved = self._moved_wait(path, st)
        if moved is not None:                                # D3 (a): a waiting item's video, moved — that item's
            f = {"origin": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "show": show,
                 "item_id": moved, "video_path": os.path.abspath(path), "video_size": st.st_size}
            if not ls.is_placeholder(st):                    # a placeholder's key is never read (B3, FIX1 MV-A4)
                f["video_key"] = self._content_key(path)
            if _episode_of(name)[0] is not None:
                f["episode"] = _episode_of(name)[0]
            gone = self._moved_from(moved, path, video_key=f.get("video_key"))
            if gone:
                f["moved_from"] = gone
            return f
        k = self._episode_key(name, show)
        if k is not None and k in self._waits(show):         # A5: its episode waits already, on another video
            return None
        if self.shown_videos.get(_key(path)) == stats or self._is_shown(show):
            self.shown_kept[_key(path)] = stats              # asked about once (H21): until the video changes
            return None
        f = {"origin": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "show": show,
             "rel": f"{ls.CONTENT_FOLDER}/{show}/{name}", "video_path": os.path.abspath(path), "video_size": st.st_size}
        if not ls.is_placeholder(st):                        # a placeholder's key is never read (B3): by its path
            if self._recent(st):
                self._wait(folder)
                return None
            vkey = self._content_key(path)
            if vkey is None:                                 # changed while read
                self._wait(folder)
                return None
            if vkey in self.ex_videos:
                self.out["skipped"] += 1
                self._kept_out(folder, path, video=vkey)
                return None
            if self._video_item(vkey) is not None:
                return None
            f["video_key"] = vkey
        episode, _version = _episode_of(name)
        if episode is not None:
            f["episode"] = episode
        return f

    def _moved_wait(self, path, st):
        """D3 (a): the item waiting for its text (K5) whose video this is — the same content key, read only for a
        settled video (no placeholder, B3) of a recorded video's size — or None: a waiting video moved stays its one
        waiting item, its new place recorded on it, wherever its folder's show is read. FIX1 (MV-A4, PROVISIONAL): a
        cloud placeholder (its key never read), or a video whose waiting item recorded no key (a placeholder when it
        was found), is that item by its name and size — the one waiting item whose video of that name and size is gone
        from its place (a copy beside a present one is a video of its own)."""
        placeholder = ls.is_placeholder(st)
        if not placeholder and self._recent(st):
            return None
        if not placeholder and self._evidence("video", st.st_size):
            vkey = self._content_key(path)
            item = self._waiting_items().get(vkey) if vkey else None
            if item is not None:
                return item
        hits = self._waiting_named().get((ls.path_key(os.path.basename(path)), st.st_size), ())
        if not placeholder:
            hits = [h for h in hits if not h[1]]             # a settled video's key, recorded, didn't match: another
        gone = []
        for item_id, _vkey, old, root in hits:
            if self._root_away(root):
                continue                                     # its source away: whether it left is unknown (G5)
            try:
                os.stat(old)
            except FileNotFoundError:
                gone.append(item_id)
            except OSError:
                return None                                  # unreadable: never a guess
        return gone[0] if len(set(gone)) == 1 else None

    def _waiting_named(self):
        """FIX1 (MV-A4): {(a video's name key, its size): [(item, its video key, its file, its source's root)]} of the
        waiting items' videos — from the origins read this look, gathered once."""
        if self.waiting_named is None:
            self.waiting_named = {}
            for o in self.origins.values():
                name = os.path.basename(o.origin or "")
                if o.availability == "waiting" and not o.version and o.origin and                         not ls.is_content_name(name.lower()) and isinstance(o.size, int):
                    self.waiting_named.setdefault((ls.path_key(name), o.size), []).append(
                        (o.item_id, o.video_key, o.origin, o.root))
        return self.waiting_named

    def _moved_from(self, item_id, path, sha256=None, video_key=None):
        """D5 (PROVISIONAL): the path keys of the item's other live origins whose originals are gone from a source
        folder still there — the file moved (to `path`, attached to the item now) — for `take_in` to mark. On this
        look's thread (outside any lock); an original whose folder is offline, unreadable or present is left unmarked
        (a copy, not a move; a drive unplugged). FIX1 (G5): its source folder's reach is asked FIRST — once a look
        per source — so an unplugged share costs one wait, never one per file; then its file's stat. FIX1 (MV-A5):
        only an original whose bytes (`sha256`) or video (`video_key`) are the new origin's: a file briefly gone while
        another of the item's turns up (a v2, a new subtitle of its video) is no move."""
        out = []
        for o in self._by_item().get(item_id, ()):
            if o.version or o.moved_to or not o.origin or ls.path_key(os.path.abspath(o.origin)) == _key(path):
                continue
            if sha256 is not None and o.sha256 and o.sha256 != sha256:
                continue
            if video_key is not None and sha256 is None and o.video_key and o.video_key != video_key:
                continue
            if self._root_away(o.root):
                continue
            try:
                os.stat(o.origin)
                continue
            except FileNotFoundError:
                pass
            except OSError:
                continue
            out.append(ls.path_key(os.path.abspath(o.origin)))
        return out

    def _root_away(self, root_id):
        """D5: is this source's folder AWAY — whether its files left is unknown (or it is no source any more)? Asked
        once a look per source. T6: a folder GONE (moved or deleted while the folder above it reads, `reach`) is not
        away: its originals are known not to be there, so one found in a new place moved (MV-1's rule, as for a
        folder still there)."""
        if root_id not in self.away_roots:
            path = self.roots.get(root_id)
            dev = _volume(self.cache_roots.get(str(root_id)), path)
            self.away_roots[root_id] = path is None or reach(path, dev) == AWAY
        return self.away_roots[root_id]

    def _back(self):
        """D5: the known originals listed in their old place again — their `moved_to` mark taken off (one write)."""
        if not self.back:
            return
        try:
            self.store.origins_back(self.back)
        except ls.StoreError:                                # busy: the next look lists them again
            pass
        self.back = []

    def _is_shown(self, show):
        """Has this show an item that isn't waiting (any place)? Its folder key, as the store groups a show's title
        (`Library/<show>` and a 2.x `HighPriority/<show>` are one). One read of the items per look, when needed."""
        if self.shown is None:
            self.shown = set()
            for tier in ls.TIERS:
                for _i, entry, availability in self.store.ordered(tier):
                    if availability != "waiting":
                        self.shown.add(ls.folder_key_of(str(entry.get("physical_path") or "")))
        return ls.folder_key_of(f"{ls.CONTENT_FOLDER}/{show}/x") in self.shown

    def _same(self, path, st):
        """The original as listed still (its size and time): else it is being written."""
        try:
            now = os.stat(path)
        except OSError:
            return False
        return (now.st_size, now.st_mtime_ns) == (st.st_size, st.st_mtime_ns)

    def _video_item(self, vkey):
        """(a) The live item whose record holds this video (hato's key, or an origin's `video_key`) — never a waiting
        one (K5: its gap is filled by `take_in` from the copy) — or None. The origins' videos are read once a look and
        kept up to date by its take-ins (`_commit`); hato's by their row, at each ask."""
        if self.videos is None:
            self.videos = self.store.origin_videos()
        return self.store.item_of_video_key(vkey, origins=self.videos)

    def _same_bytes(self, size, sha, sizes=None):
        """(b) An item of this size whose file holds these bytes, or None. A4K-7: an item's hash the store keeps is
        used instead of reading its file while the file's size and time are still its row's (one stat: 1.8 s for 60k
        copies); else, or with no hash kept, the file is read — hashed once a look, its hash kept for the next looks
        (`_keep_hashes`)."""
        for item_id, rel, mtime_ns, kept in (self.sizes if sizes is None else sizes).get(size, ()):
            if rel not in self.hashes:
                full = os.path.join(self.data_dir, *rel.split("/"))
                now = _stat_of(full)
                if kept is not None and now == (size, mtime_ns):
                    self.hashes[rel] = kept
                else:
                    self.hashes[rel] = self._read_hash(item_id, full, now, size, mtime_ns)
            if self.hashes[rel] == sha:
                return item_id
        return None

    def _read_hash(self, item_id, full, before, size, mtime_ns):
        """Check (b)'s read of an item's copy -> its sha256, or None (unreadable). A4K-7: kept for the item when the
        file was as its row records it (`size`, `mtime_ns`) before the read (`before`: its stat) and still is after it
        (never a file changed while it was read)."""
        try:
            sha = ls.sha256_of(full)
        except OSError:
            return None
        if before == (size, mtime_ns) == _stat_of(full):
            self.to_keep.append((item_id, size, mtime_ns, sha))
        return sha

    def _keep_hashes(self):
        """A4K-7: the hashes check (b) read, kept in the store (one write; `Store.keep_hashes`). A cache: a busy or
        failed write loses only work the next look does again."""
        rows, self.to_keep = self.to_keep, []
        if not rows:
            return
        try:
            self.store.keep_hashes(rows)
        except (ls.StoreError, sqlite3.Error) as e:
            log.info("The copies' hashes weren't kept (the next look reads them again): %r", e)

    def _held(self, show):
        """S7, LM1b (A9): the episodes of this show already in — `Library/<show>`, from any folder or source -> {an
        episode key: (version, Origin)}, the latest pick of each (never a version, A8) under every key it answers to
        (`_keys`: its name's numbers, its video's). A `v2` found is that episode (followed, S5), an earlier one or
        another group's found later is a version. Worked out per show, once a look, from that show's origins alone
        (a look that found one new file read the names of every origin, 1.3 s at 20k): the origins grouped by
        their copies' folder once, only names of the show asked read. LM3 (A9, LM1b deferred): hato's items of the show's
        title count as its episodes too (`_hato_origins`: their file's name and recorded video), so a folder file of
        an episode hato holds is that item's version, never a second item."""
        fk = _show_key(show)
        origins = self._show_origins(fk)
        if fk in self.by_show:
            return self.by_show[fk]
        releases = self.by_show[fk] = {}
        for o in list(origins) + self._hato_origins(fk):    # LM3 (A9, LM1b deferred): hato's items are its episodes too
            name = os.path.basename(o.origin or "")
            if o.version or not ls.is_content_name(name.lower()):   # a version, a book's part, a waiting video (K5)
                continue
            version = _episode_of(name)[1]
            keys = self._keys(name, os.path.basename(o.video_path) if o.video_path else None, show)
            for k in dict.fromkeys(keys + self._claims(name, show)):   # a double held under each of its numbers
                if k not in releases or releases[k][0] < version:
                    releases[k] = (version, o)
        return releases

    def _hato_origins(self, fk):
        """LM3 (A9): hato's items of the show whose `Library` folder key is `fk` — read once a look, when a show's
        episodes are first asked (`Store.hato_items`)."""
        if self.hato is None:
            self.hato = self.store.hato_items()
            self.hato_ids = {o.item_id for found in self.hato.values() for o in found}
        return self.hato.get(fk, [])

    # --- writing into Library -------------------------------------------------------------------------------------- #

    def _inside(self, rel):
        """The full path of `rel` when it is inside the data folder's `Library` (through any folder link too: a
        `Library` that leads elsewhere is never written), else None."""
        if not rel:
            return None
        parts = rel.split("/")
        if len(parts) < 2 or ls.path_key(parts[0]) != ls.path_key(ls.CONTENT_FOLDER) or ".." in parts:
            return None
        full = os.path.join(self.data_dir, *parts)
        home = ls.path_key(os.path.realpath(self.data_dir)).rstrip("/")
        lib = ls.path_key(os.path.realpath(os.path.join(self.data_dir, ls.CONTENT_FOLDER))).rstrip("/")
        real = ls.path_key(os.path.realpath(full))
        if not lib.startswith(home + "/") or not real.startswith(lib + "/"):
            return None
        return full

    def _checked_copy(self, path, st, part):
        """The original into `part`, as listed: its sha256, or None (it changed while copied: `part` removed)."""
        try:
            digest = _copy_part(path, part, st.st_size)
        except OSError:
            _drop(part)
            return None
        if digest is None or not self._same(path, st):   # a short or long read, or changed while copied
            _drop(part)
            return None
        _dated(part, st)
        return digest

    def _copy(self, path, st, show, name, sha, data=None):
        """(c) The original copied into `Library/<show>/` (`.part`, then renamed; never over another file: a free
        `name (2)` or, after a crash, the same bytes already there re-used) -> the copy's rel, or None. `data`: its
        bytes as read for `sha` (checked unchanged since: `_new`), written as they are; else read again here."""
        rel, reuse = ls.content_target(self.data_dir, f"{ls.CONTENT_FOLDER}/{show}/{name}", st.st_size, sha)
        if reuse:
            return rel
        full = self._inside(rel)
        if full is None:
            return None
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
        except OSError:
            return None
        part = full + ".part"
        if data is not None:
            try:
                _write_part(part, data)
            except OSError:
                _drop(part)
                return None
            _dated(part, st)
        elif self._checked_copy(path, st, part) != sha:
            _drop(part)
            return None
        try:
            ls.rename_no_overwrite(part, full)
        except OSError:
            _drop(part)
            return None
        self.made.add(rel)
        return rel

    def _trash_copy(self, full):
        """The old copy *copied* into the data folder's `.trash` (purged 30 days on: a fresh time — `copyfile`, never
        the old copy's own — and its clock restarted) -> the trash file's path."""
        trash = os.path.join(self.data_dir, ".trash")
        os.makedirs(trash, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(full))
        stamp = time.strftime("%Y%m%d%H%M%S")
        name, n = f"{base}_{stamp}{ext}", 1
        while os.path.exists(os.path.join(trash, name)):
            name, n = f"{base}_{stamp}_{n}{ext}", n + 1
        dst = os.path.join(trash, name)
        shutil.copyfile(full, dst)
        restart_trash_clock(dst)
        return dst

    def _refuses(self, rel, st):
        """S5's refusals, before anything is read: a copy outside `Library` (a hato / 2.x file is never rewritten),
        none there, an empty original or one under half the copy's size."""
        full = self._inside(rel)
        if full is None:
            return True
        try:
            held = os.stat(full).st_size
        except OSError:
            return True
        return st.st_size == 0 or st.st_size * 2 < held

    def _recopy(self, rel, old_sha, path, st):
        """S5: the original's new text over Surasura's copy at `rel` -> ('done' | 'same' | 'refused' | 'wait', sha).
        Refused (`_refuses`). Wait: it changed while read, or the trash couldn't take the old copy."""
        if self._refuses(rel, st):
            return "refused", None
        full = self._inside(rel)
        part = full + ".part"
        sha = self._checked_copy(path, st, part)
        if sha is None:
            return "wait", None
        if sha == old_sha:
            _drop(part)
            return "same", sha
        try:                                                 # (a7) new bytes dated as the copy they replace — a v2
            new, old = os.stat(part), os.stat(full)          # from the same archive, the same size — would read as
            if (new.st_size, new.st_mtime_ns) == (old.st_size, old.st_mtime_ns):    # unchanged to the disk sync:
                os.utime(part)                               # it keeps the copy's own time instead
        except OSError:
            pass
        try:
            kept = self._trash_copy(full)
        except OSError:
            _drop(part)
            return "wait", None
        try:
            os.replace(part, full)
        except OSError:                                      # the copy held open: it stays as it was, the trash too
            _drop(part)
            _drop(kept)
            return "wait", None
        return "done", sha

    def _restore(self, known):
        """Item 8a: a live item (any place) whose copy in `Library` is gone — the store says 'missing' (the data folder
        emptied and the store rebuilt from its JSON copy, or the copy deleted) — while its original is still there,
        found known in a folder this look listed: the original copied back into exactly the copy's place (`.part`,
        then renamed, never over a file — one there is the sync's to find), its record's stats and bytes rewritten
        when they moved, and the item available again in this same look (`Store.copies_back`). No stat but the copies
        written: the 'missing' comes with the origins' read and the original's stats with the listing (a quick look
        lists only folders whose time moved; the first look each run and Refresh list all). Never a removed item's
        (no live item holds its origin; S6), never a copy outside `Library` (a hato / 2.x file), never from an empty
        original or one written in the last seconds; an original gone too leaves its item missing (SRC-8). Of an
        item's several originals, the latest release (`_episode_of`'s version: a `v2` over its `v1`), then the one
        its records followed last (`paired_at`) — never by the files' times (an archive keeps an old one: LF-3). A
        place already holding a file is left before anything is copied (the sync's to find, H8). One cleanup path
        (H15): a copy placed but not recorded by the store — its stat failing, the store busy — is removed again, so
        the next look tries it again; the records' stats are rewritten in the same command (`copies_back`, H4)."""
        chosen = {}
        for folder, path, st in known:
            o = self.origins.get(_key(path))
            if o is None or o.version or o.availability != "missing" or _key(path) in self.ex_paths:
                continue                                     # LM1b: a version's bytes are never the item's copy
            rank = (_episode_of(os.path.basename(path))[1], o.paired_at or "")
            if o.item_id not in chosen or rank > chosen[o.item_id][0]:
                chosen[o.item_id] = (rank, o, folder, path, st)
        back, records, placed, handled = [], {}, {}, set()
        try:
            for _rank, o, folder, path, st in chosen.values():
                if self.stopped():
                    break
                full = self._inside(o.rel_path)
                if full is None or st.st_size == 0 or os.path.lexists(full):
                    continue
                if self._recent(st):
                    self._wait(folder)
                    continue
                try:
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                except OSError:
                    self._wait(folder)
                    continue
                part = full + ".part"
                sha = self._checked_copy(path, st, part)
                if sha is None:
                    self._wait(folder)
                    continue
                try:
                    ls.rename_no_overwrite(part, full)
                except OSError:
                    _drop(part)
                    continue
                placed[o.item_id] = full                     # ours from here until the store records it
                try:
                    written = os.stat(full)
                except OSError:                              # removed below: the next look tries again
                    continue
                back.append((o.item_id, o.rel_path, written.st_size, written.st_mtime_ns))
                if (st.st_size, st.st_mtime_ns, sha) != (o.size, o.mtime_ns, o.sha256):
                    records[o.item_id] = (o.origin or path, st.st_size, st.st_mtime_ns, sha)
            for at in range(0, len(back), BATCH):            # each command short, as a take-in's (G1)
                chunk = back[at:at + BATCH]
                done, unused = self.store.copies_back(chunk, records)
                handled.update(b[0] for b in chunk)          # made available, or its copy trashed below
                for rel in unused:
                    self._trash(rel)
                self.out["restored"] += len(done)
        finally:                                             # a store busy or failing: raised, the copies gone
            for item_id, full in placed.items():
                if item_id not in handled:
                    _drop(full)

    def _changed(self, folder, path, st):
        """A known original in a folder listed (its stats from the listing, H2): when its size or time moved, its text
        followed (S5) and its record's stats rewritten; a refused one is left as it is (looked at again the next time
        its folder is listed, by its stats alone)."""
        o = self.origins.get(_key(path))
        if o is None or (st.st_size, st.st_mtime_ns) == (o.size, o.mtime_ns):
            return
        if self._recent(st):
            self._wait(folder)
            return
        if o.version:                                        # LM1b: a version changed is never copied over the item;
            sha = _read_text(path, st)[1]                    # LM3: its record follows the file — one passed over is
            if sha is not None and self._same(path, st):     # judged again, a better one switched to (`_switch_better`)
                self.store.update_origin(o.origin or path, st.st_size, st.st_mtime_ns, sha)
                if sha != o.sha256:                          # A4: only touched (the same bytes) — judged already
                    self.better.add(o.item_id)
            return
        outcome, sha = self._recopy(o.rel_path, o.sha256, path, st)
        if outcome == "wait":
            self._wait(folder)
        elif outcome in ("done", "same"):
            self.store.update_origin(o.origin or path, st.st_size, st.st_mtime_ns, sha)
            self.out["recopied"] += outcome == "done"

    # --- an EPUB (S11) --------------------------------------------------------------------------------------------- #

    def _book(self, folder, name, path, st, show):
        """An EPUB split by the one splitter (`book_parts`: Extract's reader and default split) into a free
        `Library/<book>` folder (each part via a `.part`), each part's origin `<epub>#<n>`, all taken in at once — or
        none (a part that can't be written: the parts already written to the trash, the book waits). Each part's record
        holds the EPUB file's sha256, so the same book renamed or moved is known by its bytes — its parts recorded on
        the items already in (as versions where those bytes are an old edition's), nothing read or written — and a
        removed one's bytes stay out (K4, S6); a part whose text an item already holds is that item (check b). A book
        that gave no text is remembered by its stats and not read again until it changes (K5). LM3 (T2-B6 A): a known
        book's new edition — this EPUB at its path with new bytes, or in its folder under its name with the edition
        marks off (`edition_name`) — is switched to whole (`_edition`), never added beside it; the same bytes at its
        path with new stats only rewrite its records' stats."""
        if self._recent(st):
            self._wait(folder)
            return
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return
        pre = self._prepared(path, st)                       # K5 C2: hashed (and split) ahead by a worker
        sha = pre[0] if pre else ls.sha256_of(path)
        if not self._same(path, st):
            self._wait(folder)
            return
        if sha in self.ex_shas:
            self.out["skipped"] += 1
            self._kept_out(folder, path, sha=sha)
            return
        origin = os.path.abspath(path)
        known = self._books().get(sha)
        mine = self._book_origins().get(_key(path)) or {}
        touched = [(f"{origin}#{n}", st.st_size, st.st_mtime_ns, sha if mine[n].sha256 == sha else None, None)
                   for n in sorted(mine) if sha in (mine[n].sha256, mine[n].declined)]
        if touched:                                          # touched (LM3), or a declined edition's bytes still
            self.store.update_origins(touched)               # (A3): only its records' stats follow
            return
        if known:                                            # moved or renamed: each part's place kept (Hon)
            same = self._members("sha").get(sha, ())               # K5: its own bytes' parts, not every origin
            places = {o.item_id: o.chapter for o in (self.origins[k] for k in same) if o.chapter}
            change = self._commit([dict({"origin": f"{origin}#{i}", "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                                         "sha256": sha, "show": rel.split("/")[1] if rel.count("/") >= 2 else show,
                                         "item_id": item, "episode": i}, **({"version": True} if version else {}),
                                        **({"chapter": json.loads(places[item])} if item in places else {}))
                                   for i, (item, rel, version) in sorted(known.items())])
            self._refresh([item for item, _rel, _v in known.values()], change)
            return
        target, own = self._edition_of(path)
        if target and not own and st.st_mtime_ns < max(o.mtime_ns or 0 for o in target.values()):
            self._older(path, st, sha, target)               # D1: an older edition: versions, never the text
            return
        if target:                                           # LM3 (T2-B6 A): this book's new edition
            self._edition(folder, path, st, sha, target)
            return
        if pre and pre[3]:
            data, shas = pre[1], pre[2]
        else:
            data, _why = book_parts(path, self.language)    # a shop's DRM (B6), no text, or none of the language:
            shas = None
        if data is None:                                     # passed over until it changes (K5, K6)
            self._pass_over(path, st)
            return
        if not self._same(path, st):
            self._wait(folder)
            return
        from app import extract
        base = extract.clean_name(os.path.splitext(name)[0]) or "Book"
        names = part_names(base, len(data), [p.label for p in data])
        chapters = [p.chapter for p in data]
        data = [p.data for p in data]
        shas = shas or [hashlib.sha256(d).hexdigest() for d in data]
        sizes = self.store.items_of_size([len(d) for d in data])
        held = [self._same_bytes(len(d), s, sizes) for d, s in zip(data, shas)]
        todo = [i for i, item in enumerate(held) if item is None]
        book, n = base, 1
        while todo:                                          # a free folder, or one a crash left with these parts
            rels = [f"{ls.CONTENT_FOLDER}/{book}/{x}" for x in names]
            if not os.path.exists(os.path.join(self.data_dir, ls.CONTENT_FOLDER, book)) or all(
                    ls.content_target(self.data_dir, rels[i], len(data[i]), shas[i]) == (rels[i], True) for i in todo):
                break
            n += 1
            book = f"{base} ({n})"
        rels = [f"{ls.CONTENT_FOLDER}/{book}/{x}" for x in names]
        if not self._write_parts(folder, rels, data, todo):
            return
        for i in todo:                                       # K5: its bytes are known — check (b) never reads it again
            self.hashes[rels[i]] = shas[i]
        if todo:
            write_source_marker(os.path.join(self.data_dir, ls.CONTENT_FOLDER, book), "epub", origin=name)
        found = []
        for i, (rel, item) in enumerate(zip(rels, held), 1):
            f = {"origin": f"{origin}#{i}", "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
                 "show": book, "episode": i, "chapter": chapters[i - 1]}
            if item is None:
                f["rel"], f["copy_sha256"] = rel, shas[i - 1]
            else:
                f["item_id"] = item
            found.append(f)
        self._refresh([f["item_id"] for f in found if "item_id" in f], self._commit(found))

    def _prepared(self, path, st):
        """K5 C2: this EPUB's work done ahead by a worker (`_Splitter`), when it read the file as listed (its size and
        time) -> (sha256, its parts or None, their sha256s, split?), or None: the look reads it itself."""
        if self.splitter is None:
            return None
        got = self.splitter.take(path)
        if got is None or got[:2] != (st.st_size, st.st_mtime_ns):
            return None
        return got[2:]

    def _write_parts(self, folder, rels, data, todo):
        """A book's parts `todo` (their indexes) written at `rels` (each via a `.part`, then renamed; a file there
        already is taken only when it holds the part's bytes — a crash's) -> True; else every part written goes to the
        trash and the book waits (False), the folders this made for it removed when they are empty (a left one made the
        book's next look name its folder `<book> (2)`)."""
        written, parts, jobs, made = [], [], [], []
        try:
            for i in todo:
                full = self._inside(rels[i])
                if full is None:
                    raise OSError(f"outside the content folder: {rels[i]}")
                where = os.path.dirname(full)
                while where and not os.path.isdir(where) and where not in made:
                    made.append(where)
                    where = os.path.dirname(where)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                if os.path.isfile(full):                     # the same bytes, left by a crash; never another file's
                    if ls.content_target(self.data_dir, rels[i], len(data[i]),       # (B1, S5)
                                         hashlib.sha256(data[i]).hexdigest()) == (rels[i], True):
                        continue
                    raise OSError(f"another file is at {rels[i]}")
                parts.append(full + ".part")
                jobs.append((full + ".part", data[i]))
            _write_parts_at_once(self.writers, jobs)       # K5 C2: by the look's writing threads when it has them
            for p in parts:
                ls.rename_no_overwrite(p, p[:-len(".part")])
                written.append(p[:-len(".part")])
        except OSError:
            for p in parts:
                _drop(p)
            for w in written:
                self._trash(ls.library_rel(self.data_dir, w))
            for d in sorted(made, key=len, reverse=True):
                try:
                    os.rmdir(d)                              # only when empty: never anything in it
                except OSError:
                    pass
            self._wait(folder)
            return False
        self.made.update(rels[i] for i in todo)
        return True

    def _book_origins(self):
        """LM3: {an EPUB's key: {part number: Origin}} of every book part recorded (its own text's and its old
        editions', versions), gathered once a look."""
        if self.book_origins is None:
            self.book_origins = {}
            for b in self._members("book"):
                self._rebuild("book", b)
        return self.book_origins

    def _book_moved(self, key, st):
        """LM3 (T2-B6): is this known EPUB recorded with other stats (its bytes may be a new edition's)? Its text's
        records, else (an EPUB known only as an old or a declined edition: versions) its versions' — read again only
        once the file changed (S19)."""
        records = list((self._book_origins().get(key) or {}).values())
        picks = [o for o in records if not o.version] or records
        return bool(picks) and all((o.size, o.mtime_ns) != (st.st_size, st.st_mtime_ns) for o in picks)

    def _edition_of(self, path):
        """LM3 (T2-B6 A, PROVISIONAL): the known book this EPUB is the new edition of -> ({part number: Origin} of its
        parts — their own text's records —, at this very path?) or (None, False): the book recorded at this very path,
        else one in this EPUB's folder whose name reads the same with the edition marks off (`edition_name`: `<book>
        (第2版)` is `<book>`'s; `<book> 2` is a second volume, never) — from an index built once a look (W4), anew
        after a switch (`_refresh`)."""
        books = self._book_origins()
        own = {n: o for n, o in (books.get(_key(path)) or {}).items() if not o.version}
        if own:
            return own, True
        want = edition_name(os.path.basename(path))
        if not want:
            return None, False
        if self.editions is None:
            self.editions, self.edition_of = {}, {}
            for key in books:
                self._file_edition(key)
        heads = self.editions.get((ls.path_key(os.path.dirname(os.path.abspath(path))), want))
        if not heads:
            return None, False
        return {n: o for n, o in books[min(heads)].items() if not o.version}, False

    def _file_edition(self, key):
        """K5: the EPUB `key` filed under its name with the edition marks off (`_edition_of`), as its parts are now."""
        old = self.edition_of.pop(key, None)
        if old is not None:
            self.editions[old].discard(key)
            if not self.editions[old]:
                del self.editions[old]
        picks = [o for _n, o in sorted((self.book_origins.get(key) or {}).items()) if not o.version]
        if picks:
            epub = str(picks[0].origin or "").rpartition("#")[0]
            name = (ls.path_key(os.path.dirname(epub)), edition_name(os.path.basename(epub)))
            self.editions.setdefault(name, set()).add(key)
            self.edition_of[key] = name

    def _edition(self, folder, path, st, sha, target):
        """LM3 (T2-B6 A, PROVISIONAL): the EPUB at `path` is the book `target`'s new edition — split by the one
        splitter (`book_parts`) and switched WHOLE as ONE change (`Store.switch_parts`: one note for the edition; a
        crash, a file held or a failing write leaves the whole old edition or the whole new one, the next look
        finishing it). Its parts pair with the book's by NUMBER (A1): new part n goes to the item that holds part n —
        its place and cards kept; a part number the book has no item for is a new item of the book (named as the book's
        parts are, `part_names`), unless the learner removed that part (Remove keeps it out); the book's parts past the
        new edition's end are taken out (their copies to the trash: Put back brings them). A part not available (its
        copy gone outside the app, A7): the edition waits, remembered by the EPUB's stats and the parts' availability —
        neither hashed nor split again until one of them changes."""
        if any(o.availability != "available" for o in target.values()):
            self.no_text_kept[_key(path)] = [st.st_size, st.st_mtime_ns, "edition",
                                             [[o.item_id, o.availability] for _n, o in sorted(target.items())]]
            self.out["waiting"] += 1
            return
        numbers = sorted(target)
        first = target[numbers[0]].rel_path or ""
        stem = os.path.splitext(first.rsplit("/", 1)[-1])[0]
        named = _part_stem(stem, numbers[0])                 # `<base>_0n` (`part_names`), else one part's `<base>`
        # a book keeps the split it was made with (never the setting as it is now), so part n pairs with part n: a
        # book cut by its chapters names its parts by them; every other (each book from before chapters) is even
        by = "chapters" if named and named[1] else "even"
        data, _why = book_parts(path, self.language, by=by)
        if data is None:
            self._pass_over(path, st)
            return
        if not self._same(path, st):
            self._wait(folder)
            return
        origin = os.path.abspath(path)
        book = first.split("/")[1] if first.count("/") >= 2 else os.path.splitext(os.path.basename(path))[0]
        base = named[0] if named else stem
        names = part_names(base, len(data), [p.label for p in data])
        chapters = [p.chapter for p in data]
        data = [p.data for p in data]
        old = str(target[numbers[0]].origin or "").rpartition("#")[0]
        out = lambda n: _key(f"{old}#{n}") in self.ex_paths or _key(f"{origin}#{n}") in self.ex_paths   # noqa: E731
        entry = lambda n: {"data": data[n - 1], "origin": f"{origin}#{n}", "size": st.st_size,   # noqa: E731
                           "mtime_ns": st.st_mtime_ns, "sha256": sha, "show": book, "episode": n,
                           "chapter": chapters[n - 1]}
        parts = [dict(entry(n), item=target[n].item_id) for n in numbers if n <= len(data)]
        extras = [dict(entry(n), rel=f"{ls.CONTENT_FOLDER}/{book}/{names[n - 1]}")
                  for n in range(1, len(data) + 1) if n not in target and not out(n)]
        surplus = [target[n].item_id for n in numbers if n > len(data)]
        try:
            change = self.store.switch_parts(self.root_id, parts, extras, surplus, rules=self.rules,
                                             epub=_key(path))
        except ls.StoreError as e:                           # busy: the book waits for the next look
            log.info("A book's new edition waits (the next look tries again): %r", e)
            self._wait(folder)
            return
        except Exception as e:                               # anything (A6): never the end of the look
            log.warning("A book's new edition couldn't switch (the next look tries again): %r", e, exc_info=True)
            self._wait(folder)
            return
        self._switched(change)
        if not change.switched:                              # waits whole (a file held, the store busy)
            self._wait(folder)
        self._refresh([o.item_id for o in target.values()] + list(change.added))

    def _older(self, path, st, sha, target):
        """D1 (the lead, PROVISIONAL): an edition older than the book's text (its file's time before the one the book
        was read from) — recorded as versions on the book's parts by number, never split nor switched to: putting an
        old edition back never switches back."""
        origin = os.path.abspath(path)
        first = target[min(target)].rel_path or ""
        book = first.split("/")[1] if first.count("/") >= 2 else os.path.splitext(os.path.basename(path))[0]
        change = self._commit([{"origin": f"{origin}#{n}", "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                                "sha256": sha, "show": book, "item_id": o.item_id, "episode": n, "version": True}
                               for n, o in sorted(target.items())])
        self._refresh([o.item_id for o in target.values()], change)

    def _edition_waits(self, key, st):
        """A7: is this EPUB a new edition remembered waiting for a part (`_edition`) — its file and those parts'
        availability as they were then? (Kept for the next look.)"""
        memo = self.no_text.get(key)
        if not (isinstance(memo, list) and len(memo) == 4 and memo[2] == "edition" and
                memo[:2] == [st.st_size, st.st_mtime_ns]):
            return False
        now = self._by_item()
        if any((now.get(item) or [None])[0] is None or now[item][0].availability != was for item, was in memo[3]):
            return False
        self.no_text_kept[key] = memo
        return True

    def _by_item(self):
        """{item id: [its Origins]}, grouped once a look (anew after a switch, `_refresh`)."""
        if self.by_item is None:
            self.by_item = {}
            for b in self._members("item"):
                self._rebuild("item", b)
        return self.by_item

    def _members(self, table):
        """K5 (alpha 4): {bucket: {origin key}} — the keys behind the book table `table` (`_buckets`), grouped once a
        look and kept by `_refresh`, so a table is built bucket by bucket and a book's take-in rebuilds its own buckets
        only (every table rebuilt after every book made a first look of N books cost N²: 19 h at 25k). F13: each table
        grouped only when first asked — a look that takes in one episode asks the show table alone (all five, the
        shows' folder keys worked out per origin, held the interpreter 0.5 s at 20k, stretching a window's save)."""
        if self.members is None:
            self.members, self.folder_keys = {}, {}
            self.position = {k: i for i, k in enumerate(self.origins)}
            self.next_position = len(self.position)
        if table in self.members:
            return self.members[table]
        got = self.members[table] = {}
        if table == "show":                                  # the keys by their copies' folder first, in one pass
            folders = {}
            for k, o in self.origins.items():
                folders.setdefault((o.rel_path or "").rpartition("/")[0], []).append(k)
            for folder, keys in folders.items():
                got.setdefault(self._folder_key(folder), set()).update(keys)
        else:
            for k, o in self.origins.items():
                for _t, b in self._buckets(k, o, table):
                    got.setdefault(b, set()).add(k)
        return got

    def _folder_key(self, folder):
        """`folder_key_of` of a file in `folder` (its copy's path up to its last `/`; '' for a loose one), worked out
        once a look (F13: a show's episodes share theirs)."""
        if folder not in self.folder_keys:
            self.folder_keys[folder] = ls.folder_key_of(folder + "/x")
        return self.folder_keys[folder]

    def _buckets(self, k, o, table=None):
        """The (table, bucket)s the origin `o` (at key `k`) is filed under — each table's own rule, as it always read
        (`table`: that table's only)."""
        if table == "item":
            return [("item", o.item_id)]
        folder = (o.rel_path or "").rpartition("/")[0]
        if table == "show":
            return [("show", self._folder_key(folder))]
        head, _sep, number = k.rpartition("#")
        out = [] if table else [("item", o.item_id), ("show", self._folder_key(folder))]
        if head:
            out.append(("head", head))                       # `_book_keys`
        if head and number.isdigit() and ls._EPUB_PART.search(str(o.origin or "")):
            out.append(("book", head))                       # `_book_origins`
        own, _sep, n = (o.origin or "").rpartition("#")
        if own and n.isdigit() and o.sha256:
            out.append(("sha", o.sha256))                    # `_books`
        return [tb for tb in out if tb[0] == table] if table else out

    def _rebuild(self, table, b):
        """One bucket of one table built again from its keys, in the order the look holds its origins (the store's key
        order, a book read again after it: as the tables were always built)."""
        keys = sorted(self._members(table).get(b, ()), key=self.position.__getitem__)
        if table == "sha":
            got = {}
            for k in keys:
                o = self.origins[k]
                got[int(o.origin.rpartition("#")[2])] = (o.item_id, o.rel_path or "", o.version)
            target = self.books_in
        elif table == "book":
            got = {int(k.rpartition("#")[2]): self.origins[k] for k in keys}
            target = self.book_origins
        elif table == "item":
            got = [self.origins[k] for k in keys]
            target = self.by_item
        elif table == "show":
            got = [self.origins[k] for k in keys]
            target = self.show_origins
            self.by_show.pop(b, None)                        # its episodes worked out again when asked (`_held`)
        else:
            return
        if got:
            target[b] = got
        else:
            target.pop(b, None)

    def _refresh(self, item_ids, change=None):
        """LM3 (A10): after a book's take-in or switch, those items' origins read again (`Store.origins(items=…)`) —
        and the items it added — and the look's book tables updated for them, so a second edition of the same book in
        this look reads the book as it is now. K5: only their keys re-filed and the buckets they touch rebuilt."""
        ids = set(item_ids) | set(getattr(change, "added", None) or ())
        if not ids or self.origins is None:
            return
        fresh = self.store.origins(items=ids)
        self._members("item")
        members = self.members                               # F13: only the tables grouped so far are kept
        old = {k for i in ids for k in members["item"].get(i, ())}
        old |= {k for k in fresh if k in self.origins}       # a key another item held
        touched = set()
        for k in old:
            o = self.origins[k] if k in fresh else self.origins.pop(k)   # one read again keeps its place
            if k not in fresh:
                del self.position[k]
            for t, b in self._buckets(k, o):
                held = members.get(t, {}).get(b)
                if held is not None:
                    held.discard(k)
                    if not held:
                        del members[t][b]
                touched.add((t, b))
        for k, o in fresh.items():
            if k not in self.origins:
                self.position[k] = self.next_position         # read after every other: last, as `update` put it
                self.next_position += 1
            self.origins[k] = o
            for t, b in self._buckets(k, o):
                if t in members:
                    members[t].setdefault(b, set()).add(k)
                touched.add((t, b))
        built = {"sha": self.books_in is not None, "book": self.book_origins is not None,
                 "item": self.by_item is not None}
        for t, b in sorted(touched, key=repr):
            if built.get(t) or (t == "show" and b in self.shows_asked):
                self._rebuild(t, b)
        if self.book_keys is not None:
            for t, b in touched:
                if t == "head":
                    if b in members.get("head", ()):
                        self.book_keys.add(b)
                    elif not any(k.rsplit("#", 1)[0] == b for k in self.ex_paths if "#" in k):
                        self.book_keys.discard(b)
        if self.editions is not None:
            for t, b in touched:
                if t == "book":
                    self._file_edition(b)

    def _pass_over(self, path, st, why=None):
        """A file that is no content — an EPUB with no text or locked (K5, B6), a text none of the language's (K6), a
        loose text too short (`why` "short", T2-B4) — counted skipped (and `short`), and remembered by its stats in
        the cache's `books`: never read again until it changes."""
        self.no_text_kept[_key(path)] = [st.st_size, st.st_mtime_ns] + (["short"] if why == "short" else [])
        self.out["skipped"] += 1
        self.out["short"] += why == "short"

    def _books(self):
        """{an EPUB's sha256: {part number: (item_id, rel, version)}} of the books already in (their parts' records;
        `version`: an old edition's, LM3)."""
        if self.books_in is None:
            self.books_in = {}
            for b in self._members("sha"):
                self._rebuild("sha", b)
        return self.books_in
