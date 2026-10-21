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
  an `.sdh` / `.hi` / `.cc` one after the plain one, a `.forced` one and another language's tag skipped), one per video
  in a look, the latest release of an episode (`- 05v2` over `- 05`); then, cheapest first, (a) a video beside it
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
  like an EPUB with no text, so an unchanged one is never read again. Dot files (a Mac's `._*` twins, `.DS_Store`)
  are never listed, nor a `.ts` under TS_MIN as a video (B7, S9).
- **An unreachable folder** (SRC-3): `{"reachable": False}`, nothing written or marked — one that goes while it is
  listed too (its folder times kept as they were).

`due` is the cadence the shell asks (SRC-9); `local_or_network` tells it which folders a watch can follow (D5).
Nothing is ever written under a source folder. Standard library only.
"""
import bisect
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

from app import library_store as ls
from app.path_utils import decode_text, restart_trash_clock, write_source_marker
from app.unicode_ranges import HAN, KANA_LETTERS

log = logging.getLogger("surasura-cli")

SETTLE_S = 5                    # a file (or the video beside it) modified this recently may still be being written
PROGRESS_S = 0.2                # `progress` at most this often
BATCH = 25                      # files per `take_in`, per show: a take-in holds the write lock ~50 ms at most
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
TS_MIN = 1 << 20                # a `.ts` under this size is TypeScript, not a video (S9: by the listing's stat)
_KANA = re.compile(f"[{KANA_LETTERS}]")      # kana letters: never ・ or ー (a Chinese name's separator, a dash)
_HAN = re.compile(f"[{HAN}]")
_BOOK_SCRIPT = {"ja": re.compile(f"[{KANA_LETTERS}{HAN}]"), "zh": _HAN}
_LOOSE = (".txt", ".md")        # a loose text: a book's worth or nothing; subtitles (.srt .ass .ssa) need no length
# a book's font obfuscation (IDPF's, Adobe's) hides only its fonts: no lock (B6)
_FONT_OBFUSCATION = ("http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC")
_FONTS = (".otf", ".ttf", ".woff", ".woff2")
_XMLENC = "{http://www.w3.org/2001/04/xmlenc#}"
_SUBS = frozenset({"subs", "subtitles", "subtitle"})   # a folder of the subtitles of the videos above it
# Item 11 (LF-1 / LF-2): a folder of other versions of the episodes above it, known by its NAME alone (casefolded,
# NFKC) — always listed with the folder above; any other subfolder (`Part 2`, `2期`, `Movie`) is never joined. The
# re-timer's words also end a subtitle's name as a versions mark (LF-17: `<video>.ja.synced.srt`); `.alt` on a file
# stays an unknown tag (an alternative translation is its own release)
_RETIMED = frozenset({"synced", "sync", "resync", "resynced", "retimed", "timed"})
_VERSIONS = _RETIMED | {"versions", "alt", "alternate"}
_FOLDER_MARKS = re.compile(r"[\[\]()（）【】「」]|\b(?:subs?|subtitles?)\b|字幕")   # around a language folder's name

# A subtitle's language tag (`Show - 05.ja.srt`, `.pt-BR`): ours is taken, another language's skipped (S7). ISO 639-1
# and 639-2 (B and T), a few names; `sc` / `tc` are Chinese here, never Sardinian; a tag not listed is no tag.
_ISO_639_1 = ("aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de "
              "dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he ho hr ht hu hy hz ia id ie "
              "ig ii ik in io is it iu iw jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu "
              "lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu "
              "rm rn ro ru rw sa sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts "
              "tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zu")
_ISO_639_2 = ("aar abk ave afr aka amh arg ara asm ava aym aze bak bel bul bih bis bam ben tib bod bre bos cat che "
              "cha cos cre cze ces chu chv wel cym dan ger deu div dzo ewe gre ell eng epo spa est baq eus per fas "
              "ful fin fij fao fre fra fry gle gla glg grn guj glv hau heb hin hmo hrv hat hun arm hye her ina ind "
              "ile ibo iii ipk ido ice isl ita iku jav geo kat kon kik kua kaz kal khm kan kor kau kas kur kom cor "
              "kir lat ltz lug lim lin lao lit lub lav mlg mah mao mri mac mkd mal mon mar may msa mlt bur mya nau "
              "nob nde nep ndo dut nld nno nor nbl nav nya oci oji orm ori oss pan pli pol pus por que roh run rum "
              "ron rus kin san srd snd sme sag sin slo slk slv smo sna som alb sqi srp ssw sot sun swe swa tam tel "
              "tgk tha tir tuk tgl tsn ton tur tso tat twi tah uig ukr urd uzb ven vie vol wln wol xho yid yor zha "
              "zul fil scc scr")
_LANGS = dict.fromkeys((_ISO_639_1 + " " + _ISO_639_2 + " english korean spanish french german portuguese russian "
                        "italian arabic vietnamese thai indonesian").split(), "other")
_LANGS.update(dict.fromkeys("ja jp jpn jap japanese 日本語 日本语 日语 日文".split(), "ja"))
_LANGS.update(dict.fromkeys("zh zho chi chs cht sc tc gb big5 chinese cmn yue 中文 简体 繁体 繁體 简中 繁中".split(), "zh"))
_FLAGS = frozenset({"forced", "sdh", "hi", "cc"})   # a track's flags (Plex, Jellyfin, Bazarr), never a language
_RANK = {".ass": 0, ".ssa": 0, ".srt": 1}           # of one episode's subtitles in one language: the first taken
# A folder that is only a season or the specials (S12): the source folder's name goes in front
_SEASON = re.compile(r"(?:season|series|s)\s*\d{1,2}|\d{1,2}(?:st|nd|rd|th)\s+season|specials?|sps?|extras?|"
                     r"ova|oad|第\s*\d{1,2}\s*[期季部]", re.I)

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
    recopied, restored, stopped, busy, ids} (`short`: of those skipped, the loose texts too short to be a book, T2-B4).
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
           "waiting": 0, "recopied": 0, "restored": 0, "stopped": False, "busy": False, "ids": []}
    out.update(values)
    return out


def _key(path):
    """An origin's key in `origins()` / `excluded()`: the path key of its absolute path."""
    return ls.origin_key(path)[len(ls.SOURCE_KEY):]


def _tag(name):
    """(the name's stem without its tags, the tag's language: 'ja', 'zh', 'other' or None, its flags), read from the
    right: `ep01.ja.forced.srt` → ('ep01', 'ja', {'forced'}); a flag either side of the language (`.hi` is Bazarr's
    hearing-impaired, never Hindi); a tag no list holds stays part of the stem (untagged). A versions mark
    (`_RETIMED`: `.synced`, `.retimed`, either side of the language, LF-17) is no flag: it comes off the stem, so the
    file is that video's episode (`_marked` says it was there)."""
    return _tags(name)[:3]


def _marked(name):
    """LF-17: does the name end in a versions mark (`<video>.ja.synced.srt`, `<video>.synced.ja.srt`)? Ranked as a
    versions folder's file is (`_episodes`' order)."""
    return _tags(name)[3]


def _tags(name):
    stem, language, flags, marked = os.path.splitext(name)[0], None, set(), False
    while True:
        base, tag = os.path.splitext(stem)
        tag = unicodedata.normalize("NFKC", tag[1:]).casefold()
        if not base or not tag:
            break
        if tag in _RETIMED:
            marked = True
        elif tag in _FLAGS:
            flags.add(tag)
        elif language is None and (_LANGS.get(tag) or _LANGS.get(re.split(r"[-_]", tag)[0])):
            language = _LANGS.get(tag) or _LANGS[re.split(r"[-_]", tag)[0]]
        else:
            break
        stem = base
    return stem, language, flags, marked


def _episode_of(name):
    """(the episode number K4's patterns read in a file name, or None; its version: 2 for `- 05v2`, else 1)."""
    text = unicodedata.normalize("NFKC", name)
    text = ls._NAME_EXT.sub("", text)
    while ls._NAME_LANG.search(text):
        text = ls._NAME_LANG.sub("", text)
    text = ls._NAME_TAGS.sub(" ", text).replace("_", " ")
    if " " not in text.strip() and text.count(".") >= 2:
        text = text.replace(".", " ")
    m = ls._NAME_SEASON_EP.search(text)
    if m:
        number = re.search(r"E(\d{1,4})", m.group(0), re.I).group(1)
        rest = text[m.end():]
    else:
        m = ls._NAME_EPISODE.search(text)
        if not m:
            return None, 1
        number = re.search(r"\d{1,4}(?:\.\d)?", m.group(0)).group(0)
        rest = m.group(0)[m.group(0).index(number) + len(number):] + text[m.end():]
    version = re.match(r"\s?v(\d+)", rest, re.I)
    value = float(number)
    return (int(value) if value.is_integer() else value), (int(version.group(1)) if version else 1)


def _release(name):
    """H13: a file name without its release's marks (`[group]`, `(1080p)`, a resolution or hash, a version, its
    language tag and extension), folded: two releases of one episode whose names differ only there have the same."""
    text = unicodedata.normalize("NFKC", _tag(name)[0])
    text = ls._NAME_JUNK.sub(" ", ls._NAME_TAGS.sub(" ", text))
    text = re.sub(r"(?<=\d)v\d+\b", "", text, flags=re.I)
    return " ".join(text.replace("_", " ").split()).casefold()


def _subtitle_folder(name, parent, language):
    """The ONE named-folder rule (item 11, LF-1, LF-15, LF-16): is the subfolder `name` of the folder `parent` (its
    name) listed with it — its texts the folder's own — by its NAME alone (NFKC, casefolded), never by what it holds?
    -> "versions" (`_VERSIONS`: `synced`, `retimed`, `alt`…: other versions of the episodes above), "subs" (`Subs`,
    `Subtitles`; the show folder's own name — a download unpacked into it, LF-16), the library's language (a folder
    named only for it — `JP`, `[Japanese]`, `Japanese Subs`, `中文字幕` — by the language names `Subs/<language>/`
    reads, `_folder_language`, brackets and "Subs" / 字幕 around them allowed: its untagged texts are that language's,
    LF-15), or None: `Part 2`, `Movie`, `English`, `<Show> [archive]` — a folder of its own."""
    folded = unicodedata.normalize("NFKC", name).strip().casefold()
    if folded in _VERSIONS:
        return "versions"
    if folded in _SUBS or folded == unicodedata.normalize("NFKC", parent).strip().casefold():
        return "subs"
    bare = " ".join(_FOLDER_MARKS.sub(" ", folded).split())
    return language if bare and _folder_language(bare) == language else None


def _folder_language(name):
    """The language a folder inside a subtitle folder is named for (`Subs/ja`, `Subs/English`, `Subs/zh-Hans`):
    'ja', 'zh', 'other', or None (no language: an ordinary folder)."""
    tag = unicodedata.normalize("NFKC", name).strip().casefold()
    return _LANGS.get(tag) or _LANGS.get(re.split(r"[-_]", tag)[0])


def _show_of(root, parts, name):
    """`Library/<show>`'s show (§1, S12): the folder below the source as written (`Frieren/Season 1`); a season or
    specials folder alone gets the source folder's name in front; a loose file's show is K4's reading of its name,
    else the source folder's name."""
    from app.extract import clean_name
    root_name = clean_name(os.path.basename(os.path.normpath(root))) or "Source"
    if parts:
        if _SEASON.fullmatch(unicodedata.normalize("NFKC", parts[0]).strip()):
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
                if entry.name.startswith("."):               # a dot folder (`skip_dir`) or a dot file: a Mac's
                    continue                                 # AppleDouble twin `._Show - 01.mkv`, `.DS_Store` (B7)
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
                        "video" if low.endswith(runner.VIDEO_EXTENSIONS) else None
                    if kind is None:
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    unread = True
                    continue
                if kind == "video" and low.endswith(".ts") and st.st_size < TS_MIN:
                    continue                                 # TypeScript, not MPEG-TS (S9)
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
        excluded = self.store.excluded()
        self.ex_paths = set(excluded)
        self.ex_shas = {n["sha256"] for n in excluded.values() if n.get("sha256")}
        self.ex_videos = {n["video_key"] for n in excluded.values() if n.get("video_key")}
        self.ex_episodes, self.ex_releases = set(), set()
        for p, n in excluded.items():
            if n.get("show") and n.get("episode") is not None:
                name = os.path.basename(p)
                episode = (ls.search_fold(n["show"], self.language), n["episode"], self._name_show(name))
                self.ex_episodes.add(episode)
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
            for name, path, st, show, kind in episodes:
                self.out["found"] += 1
                self.shows.add(ls.search_fold(show, self.language))
                where = os.path.dirname(path)                # this folder, or a subtitle folder listed with it
                if ls.path_key(where) in self.versions.get(fkey, ()):
                    where = folder                           # a versions folder's: the folder's releases (S7, H12)
                if kind == "known":
                    known.append((where, path, st))
                elif kind == "book":
                    books.append((where, name, path, st, show))
                else:
                    new.append((where, path, st, name, show, vids))
            if vids and not episodes and not epubs:          # videos and none of our text yet: they wait (K5)
                for path, st in sorted(vids.values()):
                    show = _show_of(self.base, parts, os.path.basename(path))
                    self.out["found"] += 1
                    self.shows.add(ls.search_fold(show, self.language))
                    new.append((folder, path, st, show))
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
        todo = [(s, kinds[s] if kinds[s] not in ("subs", "versions") else None) for s in subs
                if kinds[s] and not self._skips(s)]
        others = [s for s in subs if not kinds[s]]
        for s in subs:
            if kinds[s] == "versions":
                self.versions.setdefault(ls.path_key(folder), set()).add(ls.path_key(s))
        listed_with = []
        while todo:
            path, language = todo.pop(0)
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
            for child in children:
                if self._skips(child):
                    continue
                tongue = None if language else _folder_language(os.path.basename(child))
                if tongue:
                    todo.append((child, tongue))
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
        never keeps the `.ja.srt` out) -> [(name, path, stat, show, 'new' | 'known' | 'book')]."""
        like = {os.path.splitext(v)[0] for v in (vids or ())}            # their names, lowered

        def order(name, path):
            base, language, flags, marked = _tags(name)
            return (bool(flags) or base.lower() not in like, (language or (langs or {}).get(path)) != self.language,
                    bool(flags), not marked and ls.path_key(os.path.dirname(path)) not in versions,
                    _RANK.get(os.path.splitext(name)[1].lower(), 2), name)
        out, groups = [], {}
        for t in texts:
            k = _key(t[1]) if self.no_text else None
            if k is not None and (self.no_text.get(k) or [])[:2] == [t[2].st_size, t[2].st_mtime_ns]:
                self.no_text_kept[k] = self.no_text[k]       # none of our script in it, or short, unchanged (K6)
                self.out["skipped"] += 1
                self.out["short"] += self.no_text[k][2:] == ["short"]
                continue
            base, language, flags = _tag(t[0])
            language = language or (langs or {}).get(t[1])
            if language not in (None, self.language) or "forced" in flags:   # a forced track holds only the signs
                self.out["skipped"] += 1
                continue
            groups.setdefault(base.casefold(), []).append((language, bool(flags), t))
        for members in groups.values():
            mine = [t for _l, _f, t in members if _key(t[1]) in self.origins]
            if mine:
                self.out["skipped"] += len(members) - len(mine)
                out.extend((n, p, st, _show_of(root, parts, n), "known") for n, p, st in mine)
                continue
            members.sort(key=lambda m: order(m[2][0], m[2][1]))
            self.out["skipped"] += len(members) - 1
            n, p, st = members[0][2]
            out.append((n, p, st, _show_of(root, parts, n), "new"))
            if len(members) > 1:                             # the next in its place if this one isn't ours (B5)
                self.runners_up[p] = [m[2] for m in members[1:]]
        # K1: of one episode's releases found new here (`- 05`, `- 05v2`), only the latest is taken; H13: of its
        # releases of that version whose names differ only in their marks (`[A] Show - 05`, `[B] Show - 05 (720p)`),
        # only the first in the order above — a name that says more (`Show - 05 特別編`) is its own
        read = {}
        for n, p, _st, _show, kind in out:
            episode, version = _episode_of(n)
            if kind == "new" and episode is not None:
                read[p] = ((self._name_show(n), episode), version, _release(n))
        if read:
            latest, first = {}, {}
            for k, version, _r in read.values():
                latest[k] = max(latest.get(k, 0), version)
            for n, p, *_rest in sorted(out, key=lambda e: order(e[0], e[1]) + (e[1],)):
                if p in read and read[p][1] == latest[read[p][0]]:
                    first.setdefault(read[p][0] + (read[p][2],), p)
            kept = []
            for e in sorted(out, key=lambda e: order(e[0], e[1]) + (e[1],)):
                r = read.get(e[1])
                if r is not None and (r[1] < latest[r[0]] or first[r[0] + (r[2],)] != e[1]):
                    self.out["skipped"] += 1
                    if r[1] == latest[r[0]]:                 # LF-9: the first's runner-up — the one language rule
                        self.runners_up.setdefault(first[r[0] + (r[2],)], []).extend(   # (`_refusal`, at `_new`)
                            [e[:3]] + self.runners_up.pop(e[1], []))                    # passes on it if it isn't ours
                else:
                    kept.append(e)
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

    def _name_show(self, name):
        """K4's show of a file name, folded: two releases of one show's episode have the same."""
        return ls.search_fold(ls.show_of_name(name) or "", self.language)

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
        for c in new:                                        # a text (6), a video waiting for its text (4)
            by_show.setdefault(c[4] if len(c) == 6 else c[3], []).append(c)
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
                    f = self._new(*c) if len(c) == 6 else self._video_only(*c)
                except OSError:                              # gone or locked meanwhile: the next look
                    self._wait(c[0])
                    f = None
                if f is not None:
                    batch.append(f)
                if len(batch) >= BATCH:
                    self._commit(batch)
                    batch = []
            self._commit(batch)
            if self.out["stopped"]:
                return

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
        copy's `rel`), or None (skipped, or waiting for the next look)."""
        from app.connect import runner, videos
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return None
        episode, version = _episode_of(name)
        held = self._held(folder).get((self._name_show(name), episode)) if episode is not None else None
        if held is not None and (held[0] > version or (held[0] == version and  # an earlier release (K1), or
                                 _release(os.path.basename(held[1].origin or "")) == _release(name))):  # another (H13)
            self.out["skipped"] += 1                         # of an episode already in
            return None
        removed = (ls.search_fold(show, self.language), episode, self._name_show(ls.path_key(name)))
        release = removed + (_release(ls.path_key(name)),)
        if (version > 1 and removed in self.ex_episodes) or release in self.ex_releases:
            self.out["skipped"] += 1                         # a re-release, or another release, of one removed (K2)
            return None
        if self._recent(st):
            self._wait(folder)
            return None
        video, vkey = None, None
        stem = _tag(name)[0]
        for candidate in [stem + e for e in runner.VIDEO_EXTENSIONS] + videos.names_for(name):
            video = vids.get(candidate.lower())
            if video:
                break
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
        data, sha, head = _read_text(path, st)               # read once: hashed now, copied from memory
        if sha is None or not self._same(path, st):
            self._wait(folder)
            return None
        if sha in self.ex_shas:
            self.out["skipped"] += 1
            return None
        if sha in self.this_look:                            # the same bytes twice: the next look attaches it
            self._wait(folder)
            return None
        f = {"origin": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
             "show": show}
        if episode is not None:
            f["episode"] = episode
        if video:
            f["video_path"], f["video_size"] = os.path.abspath(video[0]), video[1].st_size
            if vkey:
                f["video_key"] = vkey
        item = (self._video_item(vkey) if vkey else None) or self._same_bytes(st.st_size, sha)
        why = None if item is not None else _refusal(head, self.language, name.lower().endswith(_LOOSE), data is None)
        if why:                                              # K6: a skin config, an English .srt, a Chinese fansub,
            self._pass_over(path, st, why)                   # a readme: no new text and no v2's — not read again
            rest = self.runners_up.pop(path, None)           # until it changes; B5: the episode's next file (the
            if not rest:                                     # Japanese `.srt` after a Chinese `.ass`) in its place
                return None
            self.out["skipped"] -= 1
            if rest[1:]:
                self.runners_up[rest[0][1]] = rest[1:]
            n, p, s = rest[0]
            return self._new(os.path.dirname(p), p, s, n, show, vids)
        if item is None and held is not None and held[0] < version:   # a v2 of an episode already in (S7)
            earlier = held[1]
            if self._refuses(earlier.rel_path, st):          # not followed: nor recorded (its bytes aren't the item's)
                self.out["skipped"] += 1
                return None
            item = earlier.item_id
            self.follow[f["origin"]] = (earlier, path, st, folder)   # its text followed once take_in records it (H12)
        if item is not None:
            f["item_id"] = item
        else:
            rel = self._copy(path, st, show, name, sha, data)
            if rel is None:
                self._wait(folder)
                return None
            f["rel"] = rel
        self.this_look.add(sha)
        if track is not None:
            self.this_videos.add(track)
        return f

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

    def _held(self, folder):
        """S7: the releases already in from this folder -> {(K4's show of the name, episode): (version, Origin)}, the
        latest of each — a `v2` found is that episode (followed, S5), an earlier one found later is skipped. Worked
        out per folder, once a look, from that folder's origins alone (F13: a look that found one new file read the
        names of every origin, 1.3 s at 20k, stretching a window's save meanwhile): the origins' keys sorted once, the
        folder's found by its prefix. A versions folder listed with it (item 11) is the folder's own here too: a
        version found later under another name is the episode already in, never a second item."""
        fkey = ls.path_key(os.path.abspath(folder))
        versions = {fkey} | self.versions.get(fkey, set())
        if self.by_folder is None:
            self.by_folder, self.keys = {}, sorted(self.origins)
        if fkey in self.by_folder:
            return self.by_folder[fkey]
        releases = self.by_folder[fkey] = {}
        prefix = fkey.rstrip("/") + "/"
        at = bisect.bisect_left(self.keys, prefix)
        while at < len(self.keys) and self.keys[at].startswith(prefix):
            o = self.origins[self.keys[at]]
            at += 1
            name = os.path.basename(o.origin or "")
            if not ls.is_content_name(name.lower()):         # a book's part, or a video waiting for its text (K5)
                continue
            if ls.path_key(os.path.dirname(os.path.abspath(o.origin))) not in versions:   # a subfolder's
                continue
            episode, version = _episode_of(name)
            if episode is None:
                continue
            k = (self._name_show(name), episode)
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
            if o is None or o.availability != "missing" or _key(path) in self.ex_paths:
                continue
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
