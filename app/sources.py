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
  stamp, so a quick look reads no exclusion), and a change to them lists everything once. **A text or book not in the
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
  listed too (its folder times kept as they were).

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
import sys
import threading
import time
import unicodedata

from app import episode_names as en
from app import library_store as ls
from app.path_utils import decode_text, restart_trash_clock, write_source_marker
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
CACHE_VERSION = 3               # 2: a folder's subtitle folders are listed with it; 3: a versions folder by its name
                                # alone (LF-1), never one guessed from what it holds
EPUB = ".epub"
MIN_SCRIPT = 20                 # a text holding fewer characters of the language's script is no content (K6)
BOOK_MIN_CHARS = 1000           # a loose .txt / .md holding fewer of the script's characters is no content (T2-B4)
HEAD = 1 << 20                  # a text over IN_MEMORY is judged by this much of its start, read with its hash (B4)
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
_GUARD = threading.Lock()
_RUNNING = set()                # stores a look is running on (their path keys): never two at once
_LOOKED = set()                 # (store, source) looked at in full this run: later looks list only what changed


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


def scan(store, language, root, first=False, progress=None, stop=None, full=False, rules=None):
    """One look at the source `root` (its id) -> {reachable, found, shows, added, attached, skipped, short, waiting,
    recopied, restored, paired, stopped, busy, ids} (`short`: of those skipped, the loose texts too short to be a book,
    T2-B4; `paired`: known texts whose video was found and recorded on them, `_late` — "12 episodes found their videos").
    `first`: setup's own first scan (SRC-1: Current, quiet); `full`: Refresh (S4); `progress(found, shows)` every
    PROGRESS_S; `stop()` is asked between files (a stopped look keeps what it took in, whole); `rules`: the placing
    rules `take_in` applies to an arrival. A source not being read raises NotASource.
    Another look at the same store running → {"busy": True}, nothing done."""
    key = _store_key(store)
    with _GUARD:
        if key in _RUNNING:
            return _result(busy=True)
        _RUNNING.add(key)
    try:
        return _Look(store, language, root, first, progress, stop, full, rules).run()
    finally:
        with _GUARD:
            _RUNNING.discard(key)


def _store_key(store):
    return ls.path_key(os.path.abspath(store.db_path))


def _result(**values):
    out = {"reachable": True, "found": 0, "shows": 0, "added": 0, "attached": 0, "skipped": 0, "short": 0,
           "waiting": 0, "recopied": 0, "restored": 0, "paired": 0, "stopped": False, "busy": False, "ids": []}
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


def in_versions_folder(path, language):
    """Is `path` in a versions folder of its show's (item 11: `synced/`, `retimed/`, by the folder's name alone)?"""
    folder = os.path.dirname(path)
    return _subtitle_folder(os.path.basename(folder), os.path.basename(os.path.dirname(folder)), language) == "versions"


def group_label(name):
    """LM2: a subtitle group as a learner reads it — its leading `[tag]` as written (`SubsPlease`), else the name before
    its episode marker (`星空喫茶`), else the file name."""
    m = re.match(r"\s*[\[［【]([^\]］】]+)[\]］】]", name)
    return m.group(1).strip() if m else (en.identity(name).show or os.path.splitext(name)[0])


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


def _show_of(root, parts, name):
    """`Library/<show>`'s show (§1, S12): the folder below the source as written (`Frieren/Season 1`); a season or
    specials folder alone gets the source folder's name in front; a loose file's show is K4's reading of its name,
    else the source folder's name."""
    from app.extract import clean_name
    root_name = clean_name(os.path.basename(os.path.normpath(root))) or "Source"
    if parts:
        if en.season_folder(parts[0]) is not None:
            parts = [root_name] + list(parts)
        return "/".join(parts)
    return clean_name(ls.show_of_name(name) or "") or root_name


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


def _drop(part):
    """Our own unfinished `.part`, or the trash copy of a copy never replaced (never anything else): removed."""
    try:
        os.remove(part)
    except OSError:
        pass


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


def _listing(folder):
    """(texts, epubs, videos {name lower: (path, stat)}, subfolders, placeholders, unread) of one folder, from the
    listing alone; `unread`: an entry whose stat failed (held by another program, a share's hiccup) was passed over, so
    the folder's time is not kept (H1). None when it can't be listed (gone, offline)."""
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
                        continue
                    if entry.is_symlink():
                        continue
                    low = entry.name.lower()
                    kind = "text" if ls.is_content_name(low) else "epub" if low.endswith(EPUB) else \
                        "video" if runner.video_name(entry.name) else None
                    if kind is None:
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


class _Look:
    def __init__(self, store, language, root, first, progress, stop, full, rules):
        self.store, self.language, self.root_id = store, language, root
        self.first, self.progress, self.stop, self.rules = first, progress, stop, rules
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
        self.hashes = {}
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

    # --- the look ------------------------------------------------------------------------------------------------- #

    def run(self):
        held_sources = self.store.sources(all=True, counts=False)   # one read of the roots, no origin read
        path = next((s["path"] for s in held_sources if s["id"] == self.root_id and s["on"]), None)
        if path is None:
            raise ls.NotASource("That folder isn't being read any more.")
        meta = self.store.meta()
        stamp = (meta.get("store_id"), meta.get("epoch"))
        looked = (_store_key(self.store), self.root_id)
        cache = _load_cache(self.language, stamp)
        held = cache["roots"].get(str(self.root_id)) or {}
        mine = held.get("path") == ls.path_key(path)
        dirs = held.get("dirs") if mine and isinstance(held.get("dirs"), dict) else {}
        # K6: the folders no look reads (*Never read this folder*) inside this one — read from the store only when its
        # skips moved since this cache was written (meta `folder_skips`, read above: a quick look reads no exclusion);
        # a change to them lists everything once (a folder read again is listed whatever its time)
        self.skip_stamp = meta.get("folder_skips")
        if mine and held.get("skip_stamp") == self.skip_stamp:
            self.skip = set(held.get("skipped") or ())
        else:
            top = ls.path_key(path).rstrip("/")
            self.skip = {f["key"] for f in self.store.skipped_folders() if ls._under(f["key"], top)}
        self.full = self.full or looked not in _LOOKED or not dirs or (held.get("skipped") or []) != sorted(self.skip)
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
        if walked is None:
            return _result(reachable=False)
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
            self._restore(known)                             # before check (b): an item back holds its bytes again
            texts = [c[2].st_size for c in new if len(c) == 6]
            self.sizes = self.store.items_of_size(texts) if texts else {}
            self._take(new, books)
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
        if self.skip:
            entry["skipped"] = sorted(self.skip)
        if self.skip_stamp is not None:
            entry["skip_stamp"] = self.skip_stamp
        if self.shown_kept:
            entry["shown"] = self.shown_kept
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
            except OSError:
                if folder == root or _lost(root):            # the source went mid-look: unreachable, as at its
                    return None                              # start; the cache kept as it was
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
            listed = _listing(folder)
            if listed is None:
                if folder == root or _lost(root):
                    return None
                continue
            self._load()
            texts, epubs, vids, subs, ghosts, unread = listed
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
            episodes = self._episodes(self.base, parts, texts, epubs, langs, vids, self.versions.get(fkey, ()))
            for name, path, st, show, kind, *item in episodes:
                self.out["found"] += 1
                self.shows.add(ls.search_fold(show, self.language))
                where = os.path.dirname(path)                # this folder, or a subtitle folder listed with it
                if ls.path_key(where) in self.versions.get(fkey, ()):
                    where = folder                           # a versions folder's: the folder's releases (S7, H12)
                if kind == "known":
                    known.append((where, path, st))
                    self.late.append((where, path, name, vids))     # A19 / A20: its video asked after the changes
                elif kind == "book":
                    books.append((where, name, path, st, show))
                elif kind == "version":                      # LM1b: beside a file of its episode already in
                    new.append((where, path, st, name, show, vids, item[0]))
                else:
                    new.append((where, path, st, name, show, vids))
            waits = [(folder, path, st, _show_of(self.base, parts, os.path.basename(path)))
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

    def _episodes(self, root, parts, texts, epubs, langs=None, vids=None, versions=()):
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
        file of one language is; names are compared in NFC (A24)."""
        like = {_nfc(os.path.splitext(v)[0]) for v in (vids or ())}      # their names, lowered

        def order(name, path):
            # PROVISIONAL (Sonic 2026-10-21: accepted for building, to be checked in use): this order (`subtitle_rank`)
            # and the grouping by the key below. "Named like a video" asks the names Connect pairs (`video_stems`:
            # `ep01.alt.srt`); LM2: the show's group, once it has one (`_show_group`), after that step
            named = path in self.video_of or any(_nfc(s).lower() in like for s in en.video_stems(name))   # made for it
            return subtitle_rank(name, self.language, named, (langs or {}).get(path),
                                 ls.path_key(os.path.dirname(path)) in versions,
                                 self.groups.get(_show_key(_show_of(root, parts, name))))
        out, groups = [], {}
        for t in texts:
            k = _key(t[1]) if self.no_text else None
            if k is not None and (self.no_text.get(k) or [])[:2] == [t[2].st_size, t[2].st_mtime_ns]:
                self.no_text_kept[k] = self.no_text[k]       # none of our script in it, or short, unchanged (K6)
                self.out["skipped"] += 1
                self.out["short"] += self.no_text[k][2:] == ["short"]
                continue
            if _key(t[1]) in self.ex_paths:                  # kept out (S6) — never a pick, never a version
                self.out["skipped"] += 1
                continue
            n = en.identity(t[0])
            if n.year:
                self.years.setdefault(_show_key(_show_of(root, parts, t[0])), set()).add(n.year)
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
                out.extend((n, p, st, _show_of(root, parts, n), "known") for n, p, st in mine)
                out.extend((n, p, st, _show_of(root, parts, n), "version", item) for _l, _f, (n, p, st) in members
                           if _key(p) not in self.origins)
                continue
            members.sort(key=lambda m: order(m[2][0], m[2][1]))
            self.out["skipped"] += len(members) - 1
            n, p, st = members[0][2]
            out.append((n, p, st, _show_of(root, parts, n), "new"))
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
            if k in self._book_keys():                       # a known EPUB is never split again
                continue
            if self.no_text.get(k) == [st.st_size, st.st_mtime_ns]:   # no text in it, and unchanged (K5)
                self.no_text_kept[k] = self.no_text[k]
                self.out["skipped"] += 1
                continue
            out.append((n, p, st, _show_of(root, parts, n), "book"))
        return out

    def _decide_groups(self, out, read, ep, rank):
        """LM2 (PROVISIONAL, Sonic 2026-10-21: LM-1a, A29): the group of each show this folder's new episodes belong to
        that has none yet — the group its earliest episode in was picked from (`_held`), else the group of this look's
        pick for its earliest episode here (ranked with no group: named like its video first, T2-A1) — kept for the
        look (`groups`) and handed to `take_in` with the show's files (`decided`), which records it on the show's
        title; a show's recorded group is never decided again (an earlier episode arriving later changes nothing)."""
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
            else:
                first = min((ep[e[1]] for e in entries), key=_key_order)
                name = min((e for e in entries if ep[e[1]] == first), key=rank)[0]
            self.groups[fk] = _group(name)
            self.decided[fk] = {"group": list(_group(name)), "label": group_label(name)}

    def _show_group(self, show):
        """LM2: the show's group as the look knows it (recorded, or decided this look), or None."""
        return self.groups.get(_show_key(show))

    def _episode_key(self, name, show=None):
        """LM1a: the episode a file name reads (`episode_names.identity`'s key: show without its season, season,
        episode, part, special), its show folded for the library's language (`search_fold`: Chinese Traditional as
        Simplified too) — two releases of one episode have the same; None when it reads no episode. A3 (PROVISIONAL):
        a year the name writes keeps it apart only in a show (`show`, its `Library` folder) whose names
        write two years or more — two remakes; else `Show (2019) - 05` is `Show - 05`."""
        n = en.identity(name)
        if n.episode is None:
            return None
        k = n.key
        if n.year and show is not None and len(self._years(show)) < 2:
            k = (k[0][:-len(f" ({n.year})")],) + k[1:]
        return (ls.search_fold(k[0], self.language),) + k[1:]

    def _years(self, show):
        """A3: the years the names of a show's files write — its new ones this look and its origins'."""
        fk = _show_key(show)
        if fk not in self.origin_years:
            self.origin_years[fk] = {y for y in (en.identity(os.path.basename(o.origin or "")).year
                                                 for o in self._show_origins(fk)) if y}
        return self.origin_years[fk] | self.years.get(fk, set())

    def _removed(self, show, episode, name):
        """K2 (S6): a removed episode's key — its show and number as recorded (the exclusion's note) or read from the
        new file's place, the rest of the key (show of the name, season, part, special) from its name."""
        _show, season, _episode, part, special = en.identity(name).key
        return (ls.search_fold(show, self.language), episode, ls.search_fold(_show, self.language), season, part,
                special)

    def _book_keys(self):
        """The EPUBs already in or kept out (their parts' origins, `<epub>#<n>`): gathered once a look (H20)."""
        if self.book_keys is None:
            self.book_keys = {k.rsplit("#", 1)[0] for k in list(self.origins) + list(self.ex_paths) if "#" in k}
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
        for b in books:
            by_show.setdefault(clean_name(os.path.splitext(b[1])[0]) or "Book", []).append(b)
        for show in sorted(by_show, key=lambda s: (ls.search_fold(s, self.language), s)):
            batch = []
            for c in by_show[show]:
                if self.stopped():
                    break
                if len(c) == 5:                              # a book: taken in on its own, all its parts at once
                    try:
                        self._book(*c)
                    except OSError:                          # locked, or its Library folder unreadable: next look
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
        self._refused_only()

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

    def _commit(self, found):
        """`take_in` of one batch; a copy no item holds (the source stopped meanwhile — this batch's copies — or the
        store's `unused`: a file known or kept out after all, a second file of the same bytes) goes to the trash, never
        left in Library untracked (N3)."""
        if not found:
            return
        made = [f["rel"] for f in found if f.get("rel") in self.made]
        follow = {f["origin"]: self.follow.pop(f["origin"]) for f in found if f["origin"] in self.follow}
        try:
            change = self.store.take_in(self.root_id, found, first=self.first, rules=self.rules)
        except ls.NotASource:
            self.out["stopped"] = True                       # stopped reading meanwhile: no v2 followed either
            for rel in made:
                self._trash(rel)
            return
        if change is None:
            return
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
        self.out["attached"] += len(change.attached)
        self.out["skipped"] += sum(len(v) for v in change.skipped.values())
        for rel in change.unused:
            self._trash(rel)
        skipped = {o for v in change.skipped.values() for o in v}
        for origin, held in follow.items():
            if origin not in skipped:
                self._follow(origin, *held)

    def _videos_taken(self, found, change):
        """The look's video map (`_video_item`) after a take-in: each recorded text's video is its item's (the lowest
        id); a video waiting for its text is no item's yet (K5)."""
        if self.videos is None:
            return
        for f in found:
            item, vkey = change.recorded.get(os.path.abspath(f["origin"])), f.get("video_key")
            if item is None or not vkey:
                continue
            if f.get("item_id") is None and not ls.is_content_name(str(f.get("rel") or "").lower()):
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
        from app.connect import videos
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
        if held is not None and not (held[0] < version and _kind(name) <= _kind(held_name) and  # I9: a worse kind's
                                     _group(name) == _group(held_name)):   # v2, A8: another group's, is a version
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
            vkey = videos.content_key(video[0])
            if vkey is None:                                 # changed while read
                self._wait(folder)
                return None
            if vkey in self.ex_videos:
                self.out["skipped"] += 1
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
        else:
            copy = name                                      # A11: a `Subs/<video>/` file is named as its video
            if path in self.video_of and video:
                copy = os.path.splitext(os.path.basename(video[0]))[0] + os.path.splitext(name)[1]
            rel = self._copy(path, st, show, copy, sha, data)
            if rel is None:
                self._wait(folder)
                return None
            f["rel"] = rel
        self.this_look.add(sha)
        if track is not None:
            self.this_videos.add(track)
        for n, p, s in self.runners_up.pop(path, []):        # LM1b: the episode's other files are its versions
            self.pending.append((os.path.dirname(p), p, s, show, n, item, f["origin"]))
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
        if self._recent(st):
            self.unsettled.add(ls.path_key(folder))
            return None
        data, sha, head = self.read.pop(path, None) or _read_text(path, st)
        if sha is None or not self._same(path, st):
            self.unsettled.add(ls.path_key(folder))
            return None
        if sha in self.ex_shas:
            return None
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
        text = decode_text(head, self.language, head=data is None)
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
        return len(said) or None

    def _video_for(self, path, name, vids):
        """LM1b, the ONE pairing rule of a look: the video a text found in a folder goes with -> (its key in `vids`,
        'name' | 'number') or (None, None). A text in `Subs/<video>/` is that video's (A11); a loose `.txt` / `.md`
        only by its exact stem (T2-B3); a subtitle by its name — its stem, then the names Connect pairs
        (`videos.names_for`) — else by its episode's key among the folder's videos (A4: never a special's, and only
        where the names' shows agree or the folder's videos carry one show). Of several videos of one episode (A5,
        their keys alike; never an extra's, `episode_names.extra`): one not marked Dual / Dub / Multi, then the
        largest, then the first by name (`_video_rank`). PROVISIONAL (Sonic 2026-10-21: accepted for building,
        to be checked in use)."""
        from app.connect import runner, videos
        if not vids:
            return None, None
        if path in self.video_of:
            v = self.video_of[path]
            return (v, "name") if v in vids else (None, None)
        if name.lower().endswith(_LOOSE):
            stem = os.path.splitext(name)[0]
            v = next((c.lower() for c in (stem + e for e in runner.VIDEO_EXTENSIONS) if c.lower() in vids), None)
            return (v, "name") if v else (None, None)
        for candidate in [_tag(name)[0] + e for e in runner.VIDEO_EXTENSIONS] + videos.names_for(name):
            if candidate.lower() in vids:
                return candidate.lower(), "name"
        k = self._episode_key(name)
        if k is None or k[4]:
            return None, None
        held = self.vkeys.get(id(vids))                      # the folder's videos' keys, read once a look
        if held is None or held[0] is not vids or held[1] != len(vids):
            keyed = [(v, vk) for v, vk in ((v, self._episode_key(v)) for v in sorted(vids))
                     if vk and not vk[4] and not en.extra(v)]   # an extra's video is no episode's
            held = self.vkeys[id(vids)] = (vids, len(vids), keyed)
        keyed = held[2]
        one = len({vk[0] for _v, vk in keyed}) == 1
        same = [v for v, vk in keyed if vk[1:] == k[1:] and (one or vk[0] == k[0])]
        return (min(same, key=lambda v: _video_rank(v, vids)), "number") if same else (None, None)

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
        """The origins of the show whose `Library` folder key is `fk` (all of them grouped by it once a look)."""
        if self.by_show is None:
            self.by_show, self.show_origins = {}, {}
            for o in self.origins.values():
                self.show_origins.setdefault(ls.folder_key_of(o.rel_path or ""), []).append(o)
        return self.show_origins.get(fk, ())

    def _video_only(self, folder, path, st, show):
        """A video in a folder with none of our text yet (K5, SRC-2 (video)) -> its found-record for `take_in`: one
        item per video, waiting in New arrivals (*no subtitles yet*) at `Library/<show>/<video name>`, no file made,
        until its subtitle fills the gap in place — or None: recorded already, paired already (hato's), of a show
        already shown (its subtitles will join it), kept out (S6), or waiting for the next look."""
        from app.connect import videos
        if _key(path) in self.origins:
            return None
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return None
        stats = [st.st_size, st.st_mtime_ns]
        k = self._episode_key(os.path.basename(path), show)
        if k is not None and k in self._waits(show):         # A5: its episode waits already, on another video
            return None
        if self.shown_videos.get(_key(path)) == stats or self._is_shown(show):
            self.shown_kept[_key(path)] = stats              # asked about once (H21): until the video changes
            return None
        name = os.path.basename(path)
        f = {"origin": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "show": show,
             "rel": f"{ls.CONTENT_FOLDER}/{show}/{name}", "video_path": os.path.abspath(path), "video_size": st.st_size}
        if not ls.is_placeholder(st):                        # a placeholder's key is never read (B3): by its path
            if self._recent(st):
                self._wait(folder)
                return None
            vkey = videos.content_key(path)
            if vkey is None:                                 # changed while read
                self._wait(folder)
                return None
            if vkey in self.ex_videos:
                self.out["skipped"] += 1
                return None
            if self._video_item(vkey) is not None:
                return None
            f["video_key"] = vkey
        episode, _version = _episode_of(name)
        if episode is not None:
            f["episode"] = episode
        return f

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
        """(b) An item of this size whose file holds these bytes, or None."""
        for item_id, rel in (self.sizes if sizes is None else sizes).get(size, ()):
            if rel not in self.hashes:
                try:
                    self.hashes[rel] = ls.sha256_of(os.path.join(self.data_dir, *rel.split("/")))
                except OSError:
                    self.hashes[rel] = None
            if self.hashes[rel] == sha:
                return item_id
        return None

    def _held(self, show):
        """S7, LM1b (A9): the episodes of this show already in — `Library/<show>`, from any folder or source -> {an
        episode key: (version, Origin)}, the latest pick of each (never a version, A8) under every key it answers to
        (`_keys`: its name's numbers, its video's). A `v2` found is that episode (followed, S5), an earlier one or
        another group's found later is a version. Worked out per show, once a look, from that show's origins alone
        (a look that found one new file read the names of every origin, 1.3 s at 20k): the origins grouped by
        their copies' folder once, only names of the show asked read."""
        fk = _show_key(show)
        origins = self._show_origins(fk)
        if fk in self.by_show:
            return self.by_show[fk]
        releases = self.by_show[fk] = {}
        for o in origins:
            name = os.path.basename(o.origin or "")
            if o.version or not ls.is_content_name(name.lower()):   # a version, a book's part, a waiting video (K5)
                continue
            version = _episode_of(name)[1]
            keys = self._keys(name, os.path.basename(o.video_path) if o.video_path else None, show)
            for k in dict.fromkeys(keys + self._claims(name, show)):   # a double held under each of its numbers
                if k not in releases or releases[k][0] < version:
                    releases[k] = (version, o)
        return releases

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
        if o is None or o.version or (st.st_size, st.st_mtime_ns) == (o.size, o.mtime_ns):
            return                                           # LM1b: a version changed is never copied over the item
        if self._recent(st):
            self._wait(folder)
            return
        outcome, sha = self._recopy(o.rel_path, o.sha256, path, st)
        if outcome == "wait":
            self._wait(folder)
        elif outcome in ("done", "same"):
            self.store.update_origin(o.origin or path, st.st_size, st.st_mtime_ns, sha)
            self.out["recopied"] += outcome == "done"

    # --- an EPUB (S11) --------------------------------------------------------------------------------------------- #

    def _book(self, folder, name, path, st, show):
        """An EPUB split by Extract's reader and default split into a free `Library/<book>` folder (each part via a
        `.part`), each part's origin `<epub>#<n>`, all taken in at once — or none (a part that can't be written: the
        parts already written to the trash, the book waits). Each part's record holds the EPUB file's sha256, so the
        same book renamed or moved is known by its bytes — its parts recorded on the items already in, nothing read
        or written — and a removed one's bytes stay out (K4, S6); a part whose text an item already holds is that
        item (check b). A book that gave no text is remembered by its stats and not read again until it changes (K5)."""
        from app import extract
        if self._recent(st):
            self._wait(folder)
            return
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return
        sha = ls.sha256_of(path)
        if not self._same(path, st):
            self._wait(folder)
            return
        if sha in self.ex_shas:
            self.out["skipped"] += 1
            return
        origin = os.path.abspath(path)
        known = self._books().get(sha)
        if known:
            self._commit([{"origin": f"{origin}#{i}", "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
                           "show": rel.split("/")[1] if rel.count("/") >= 2 else show, "item_id": item, "episode": i}
                          for i, (item, rel) in sorted(known.items())])
            return
        if _locked(path):                                    # a shop's DRM: never split (B6)
            self._pass_over(path, st)
            return
        chunks, error = extract.chunks_of(path, self.language)
        if error or not chunks or _refusal("".join(chunks), self.language):   # no text, or none of the language
            self._pass_over(path, st)                        # (an English translation, B6): until it changes
            return
        if not self._same(path, st):
            self._wait(folder)
            return
        base = extract.clean_name(os.path.splitext(name)[0]) or "Book"
        data = [c.encode("utf-8") for c in chunks]
        names = [f"{base}_{i:02d}.txt" if len(data) > 1 else f"{base}.txt" for i in range(1, len(data) + 1)]
        shas = [hashlib.sha256(d).hexdigest() for d in data]
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
        written, parts = [], []
        try:
            for i in todo:
                full = self._inside(rels[i])
                if full is None:
                    raise OSError(f"outside the content folder: {rels[i]}")
                os.makedirs(os.path.dirname(full), exist_ok=True)
                if os.path.isfile(full):
                    continue                                 # the same bytes, left by a crash
                with open(full + ".part", "wb") as f:
                    parts.append(full + ".part")
                    f.write(data[i])
                    f.flush()
                    os.fsync(f.fileno())
            for p in parts:
                ls.rename_no_overwrite(p, p[:-len(".part")])
                written.append(p[:-len(".part")])
        except OSError:
            for p in parts:
                _drop(p)
            for w in written:
                self._trash(ls.library_rel(self.data_dir, w))
            self._wait(folder)
            return
        if todo:
            write_source_marker(os.path.join(self.data_dir, ls.CONTENT_FOLDER, book), "epub", origin=name)
        self.made.update(rels[i] for i in todo)
        found = []
        for i, (rel, item) in enumerate(zip(rels, held), 1):
            f = {"origin": f"{origin}#{i}", "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
                 "show": book, "episode": i}
            if item is None:
                f["rel"] = rel
            else:
                f["item_id"] = item
            found.append(f)
        self._commit(found)

    def _pass_over(self, path, st, why=None):
        """A file that is no content — an EPUB with no text or locked (K5, B6), a text none of the language's (K6), a
        loose text too short (`why` "short", T2-B4) — counted skipped (and `short`), and remembered by its stats in
        the cache's `books`: never read again until it changes."""
        self.no_text_kept[_key(path)] = [st.st_size, st.st_mtime_ns] + (["short"] if why == "short" else [])
        self.out["skipped"] += 1
        self.out["short"] += why == "short"

    def _books(self):
        """{an EPUB's sha256: {part number: (item_id, rel)}} of the books already in (their parts' records)."""
        if self.books_in is None:
            self.books_in = {}
            for o in self.origins.values():
                head, _sep, number = (o.origin or "").rpartition("#")
                if head and number.isdigit() and o.sha256:
                    self.books_in.setdefault(o.sha256, {})[int(number)] = (o.item_id, o.rel_path or "")
        return self.books_in
