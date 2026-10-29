"""Audiobooks (Hon, 3.0 E2, PROVISIONAL rules held by `tests/test_audiobooks.py`): which audio files in a folder are one
audiobook, in what order, what their tags say, and which book of the library it reads aloud.

Scope: `Surasura 3.0/tracks/books/work/audiobooks/scope.md`. The method is the planning's (next-session 2026-10-26):
cleaned names + the EPUB's metadata + the audio's tags + a length check, then ONE remembered question when unsure.

- **An audiobook** (`find`): each `.m4b` on its own (its chapters inside it); else a folder's other audio files
  together, its disc folders (`Disc 1`, `CD2`, `ディスク1`) joined in — those named with a title (`坊っちゃん CD1`)
  by title. A folder holding a video has no audiobook (its audio is the video's: an OST, a commentary); files whose
  album tags name two albums (a disc's mark aside) are two audiobooks; under MIN_SECONDS in all (MIN_BYTES when no
  length is read) is none (a song, a sample).
- **Order**: (disc, track) from the tags when every file has a track and none repeats; else the disc folder's number,
  then the name, numbers compared as numbers (`2.mp3` before `10.mp3`, 第二章 before 第十章).
- **Tags** without a new dependency (`read_tags`): ID3v2 (2.2–2.4) and an MP3's length (its Xing / Info / VBRI frame,
  else its size at the first frame's bit rate); an MP4's `ilst`, its `mvhd` length and its Nero `chpl` chapters. A
  file that can't be read has no tags and no length, never an error.
- **Pairing** (`decide`): every title the two sides carry (`clean`: one rule — NFKC, casefold, bracketed tags and words
  of the form out, letters and digits only; the volume read off first); volumes that differ are never a pair; the
  book's characters per second of audio must fall in LENGTH_FIT; an author tag naming the book's creator adds, never
  subtracts (a narrator differs); a nearer folder breaks a tie; a volume on one side only, or a title that only holds
  the other away from its folder (a sequel), is asked. *sure* is paired with no question, *ask* is the one question,
  and an answer (`answer_key`: it survives a move or a rename) always wins.

Nothing here writes anything, opens Anki or the network. Standard library (and `extract`'s EPUB reading) only.
"""
import difflib
import hashlib
import os
import re
import struct
import unicodedata
from collections import namedtuple

AUDIO_EXTENSIONS = (".m4b", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav")   # Anki Miner's Z-16 list
MIN_SECONDS = 20 * 60           # an audiobook is at least this long in all (a song, a sample, an opening is not)
MIN_BYTES = 10 << 20            # ... or, when no length could be read, at least this big
LENGTH_FIT = (2.5, 14.0)        # a book's characters per second of its audio (narration: ~5–8); outside is another
                                # edition, an abridged reading or one volume of several: asked
CLOSE_SHARE = 0.6               # a title holding the other's clean name (4+ characters) for this much of its length
LIKE_RATIO = 0.8                # two titles this alike (difflib: one character in six, 銀河鐵道の夜) are a pairing to
                                # ask about, never a sure one
HEAD_BYTES = 256 << 10          # an MP3's start read for its tag and first frame
MOOV_MAX = 32 << 20             # an MP4's `moov` read up to this size (its tags, length and chapters)

EXACT, CLOSE, LIKE = 3, 2, 1    # title levels (`score`)
AUDIO_MARK = " (audio)"         # an audiobook alone's title folder (`<title> (audio)`: never a book's of that name)
SURE, ASK, ANSWERED = "sure", "ask", "answered"

Tags = namedtuple("Tags", "title album artist album_artist composer track disc seconds chapters",
                  defaults=(None,) * 9)
# One audiobook: its folder; its files in order (absolute paths); the titles and authors its tags and names carry; its
# volume (`volume`); its length in seconds (None unless every file's was read); its bytes, and each file's; its chapters
# [{"title", "start_ms", "end_ms"}] (an m4b's own, else one per file once every length is known)
Audiobook = namedtuple("Audiobook", "folder files title titles authors volume seconds size sizes chapters")
# A book of the library as `decide` weighs it: its id (the store's title, or anything), its EPUB's path, its titles
# (`dc:title`, its file name), its creators, its characters and its EPUB's sha256 (the answer's key)
Book = namedtuple("Book", "id path titles authors chars sha256", defaults=((), (), None, None))
Score = namedtuple("Score", "title volumes length author near")
Pair = namedtuple("Pair", "book how key")


def is_audio(name):
    """Can a file of this name be an audiobook's? One of AUDIO_EXTENSIONS, and never a Mac's `._` copy."""
    from app.connect.runner import mac_copy
    return not mac_copy(name) and name.lower().endswith(AUDIO_EXTENSIONS)


# --- names --------------------------------------------------------------------------------------------------------- #
_DISC = re.compile(r"(?:^|[\s_\-.])(?:disc|disk|cd|ディスク)\s*[_\-.#]?\s*(\d{1,3})(?:\s*(?:of|/)\s*\d+)?$")
# a disc's mark anywhere in a name or an album tag (`銀河鉄道の夜 (Disc 1)`): never part of its title
_DISC_MARK = re.compile(r"[\[(【]?\s*(?<![a-z])(?:disc|disk|cd|ディスク)\s*[_\-.#]?\s*\d{1,3}"
                        r"(?:\s*(?:of|/)\s*\d+)?\s*[\])】]?", re.IGNORECASE)
_BRACKETS = re.compile(r"\[[^\]]*\]|【[^】]*】|\([^)]*\)|（[^）]*）|〔[^〕]*〕|［[^］]*］")
_BRACKET_MARKS = re.compile(r"[\[\]【】()（）〔〕［］]")
_FORM_WORDS = re.compile(r"オーディオブック|朗読(?:版)?(?!者)|audio\s*books?|unabridged|abridged|audible|"
                         r"\b(?:mp3|m4b|m4a|aac|flac)\b|\d+\s*kbps|完全版")
_TRACK_WORDS = re.compile(r"\b(?:track|trk|chapter|ch)\s*\.?\s*\d+\b|第\s*\d+\s*(?:章|話|回|トラック)")
_SET = re.compile(r"全\s*\d+\s*巻")                         # 全10巻: a set of ten, never a volume
# a volume: 1巻 · 第2巻 · Vol.3 (`SAO_vol03` too) · (2) · 上 / 中 / 下 (巻) · 前編 / 後編, or a name's trailing number
_VOLUME = (
    re.compile(r"(?<!\d)第?\s*(\d{1,3})\s*巻"),
    re.compile(r"(?<![a-z])vol(?:ume)?\s*\.?\s*(\d{1,3})(?!\d)"),
    re.compile(r"[(\[【]\s*(\d{1,3})\s*[)\]】]"),             # (NFKC: （ is ( ); a year's four digits are none
    re.compile(r"(?:^|[\s(\[【_\-])([上中下])\s*巻?[)\]】]?(?=(?:\s|【[^】]*】|\[[^\]]*\])*$)|([上中下])巻"),
    re.compile(r"(前|後)編(?!集)"),
)
# a folder named only for what it holds (`吾輩は猫である/audio/`): its audiobook takes the name of the folder above
_GENERIC = frozenset({"audio", "sound", "sounds", "mp3", "音声", "朗読", "オーディオブック", "audiobook", "audiobooks"})
# a name's trailing number, bracketed tags after it allowed (`<title> ０３ (<author>) (<site>)`)
_TRAILING_NUMBER = re.compile(r"(?<=\D)[\s_\-]+(\d{1,3})\s*((?:[(\[【][^)\]】]*[)\]】]\s*)*)$")
_LETTER = re.compile(r"[^\W\d_]")
_KANJI_DIGITS = dict(zip("〇一二三四五六七八九", range(10)))
_KANJI_NUMBER = re.compile(r"[〇一二三四五六七八九十百]+")


def _nfkc(text):
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def disc_number(name):
    """A disc folder's number (`Disc 1`, `CD2`, `ディスク 3`, `吾輩は猫である CD1`), else None."""
    m = _DISC.search(_nfkc(name).strip())
    return int(m.group(1)) if m else None


def disc_title(name):
    """What a disc folder's name says besides its disc (`吾輩は猫である CD1` → its clean title; `Disc 1` → '')."""
    return "".join(sorted(clean(_DISC.sub(" ", _nfkc(name).strip()))[0]))


def volume(name):
    """The volume a name holds, as a short string (`"2"`, `"上"`, `"前"`), else None (`clean` reads it off first)."""
    return clean(name)[1]


def _volume(text):
    text = _SET.sub(" ", text)
    for pattern in _VOLUME:
        m = pattern.search(text)
        if m:
            found = next(g for g in m.groups() if g)
            vol = str(int(found)) if found.isdigit() else found
            text = text[:m.start()] + " " + text[m.end():]
            t = _TRAILING_NUMBER.search(text)               # said twice (`[2巻] <title> 02`): never part of the title
            if t and str(int(t.group(1))) == vol:
                text = text[:t.start()] + " " + t.group(2)
            return vol, text
    m = _TRAILING_NUMBER.search(text)
    if m and _LETTER.search(text[:m.start()]):              # `86` alone is a title, `SAO 3` a volume
        return str(int(m.group(1))), text[:m.start()] + " " + m.group(2)
    return None, text


def clean(name):
    """-> (the clean names a title carries {..}, its volume or None): NFKC, casefold, the words of the form out
    (オーディオブック, 朗読, unabridged, mp3, kbps, a track's or a disc's number), the volume read off (a set's 全10巻 is
    none), then letters and digits only — once with every bracketed part dropped (`[Audible]`, `（朗読）`) and once with
    only the brackets' marks dropped (a title in brackets). A name with no letter (`01`, `Track 01`) names no title."""
    text = _DISC_MARK.sub(" ", _TRACK_WORDS.sub(" ", _FORM_WORDS.sub(" ", _nfkc(name))))
    vol, text = _volume(text.strip())
    out = set()
    for form in (_BRACKETS.sub(" ", text), _BRACKET_MARKS.sub(" ", text)):
        form = re.sub(r"[\W_]+", "", form)
        if _LETTER.search(form):
            out.add(form)
    return out, vol


def _kanji_number(run):
    """一 → 1, 十二 → 12, 二十 → 20, 百五 → 105, 一〇 → 10 (digits written one by one)."""
    if "十" not in run and "百" not in run:
        return int("".join(str(_KANJI_DIGITS[c]) for c in run))
    total, digit = 0, 0
    for c in run:
        if c in _KANJI_DIGITS:
            digit = _KANJI_DIGITS[c]
        else:
            total += (digit or 1) * (10 if c == "十" else 100)
            digit = 0
    return total + digit


def _natural(text):
    """A name's sort key, numbers compared as numbers (full-width digits, and kanji numerals: 第二章 before 第十章)."""
    text = _KANJI_NUMBER.sub(lambda m: str(_kanji_number(m.group())), _nfkc(text))
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"(\d+)", text) if p)


# --- tags ---------------------------------------------------------------------------------------------------------- #
def read_tags(path):
    """The file's Tags (MP3: ID3v2 + its length; MP4 / M4B / M4A: `ilst`, `mvhd`, `chpl`); empty Tags for any other
    file or one that can't be read."""
    low = path.lower()
    try:
        if low.endswith(".mp3"):
            return _mp3_tags(path)
        if low.endswith((".m4b", ".m4a", ".mp4", ".aac")):
            tags = _mp4_tags(path)
            if tags is not None or not low.endswith(".aac"):
                return tags or Tags()
    except (OSError, ValueError, struct.error, IndexError):
        pass
    return Tags()


def _int_of(text):
    m = re.match(r"\s*(\d+)", str(text or ""))
    return int(m.group(1)) if m else None


def _syncsafe(b):
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _id3_text(data):
    if not data:
        return None
    enc, body = data[0], data[1:]
    codec, nul = {0: ("latin-1", b"\0"), 1: ("utf-16", b"\0\0"), 2: ("utf-16-be", b"\0\0"),
                  3: ("utf-8", b"\0")}.get(enc, ("latin-1", b"\0"))
    if len(nul) == 2:                                   # a UTF-16 terminator sits on a code unit's boundary
        cut = next((i for i in range(0, len(body) - 1, 2) if body[i:i + 2] == nul), len(body))
        body = body[:cut]
    else:
        body = body.split(nul, 1)[0]
    text = body.decode(codec, "replace").strip().strip("﻿")
    return text or None


_ID3_IDS = {"TIT2": "title", "TT2": "title", "TALB": "album", "TAL": "album", "TPE1": "artist", "TP1": "artist",
            "TPE2": "album_artist", "TP2": "album_artist", "TCOM": "composer", "TCM": "composer", "TRCK": "track",
            "TRK": "track", "TPOS": "disc", "TPA": "disc"}
_BITRATES = {1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),        # MPEG-1 layer III
             2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)}             # MPEG-2 / 2.5 layer III
_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _mp3_tags(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(HEAD_BYTES)
        values, start = {}, 0
        if head[:3] == b"ID3" and len(head) >= 10:
            major, flags, tag_size = head[3], head[5], _syncsafe(head[6:10])
            start = 10 + tag_size + (10 if flags & 0x10 else 0)
            if start + 4096 > len(head):                    # a big tag (a cover picture): its end, then the frame
                f.seek(0)
                head = f.read(start + (64 << 10))
            pos = 10
            if flags & 0x40 and major >= 3:                 # an extended header
                pos += _syncsafe(head[10:14]) if major == 4 else 4 + struct.unpack(">I", head[10:14])[0]
            end = min(10 + tag_size, len(head))
            while pos < end:
                if major == 2:
                    fid, fsize, hdr = head[pos:pos + 3].decode("latin-1"), int.from_bytes(head[pos + 3:pos + 6],
                                                                                          "big"), 6
                else:
                    fid = head[pos:pos + 4].decode("latin-1")
                    raw = head[pos + 4:pos + 8]
                    fsize, hdr = (_syncsafe(raw) if major == 4 else struct.unpack(">I", raw)[0]), 10
                if not fid.strip("\0") or fsize <= 0 or pos + hdr + fsize > end:
                    break
                key = _ID3_IDS.get(fid)
                if key and key not in values:
                    values[key] = _id3_text(head[pos + hdr:pos + hdr + fsize])
                pos += hdr + fsize
        seconds = _mp3_seconds(head, start, size)
    return Tags(title=values.get("title"), album=values.get("album"), artist=values.get("artist"),
                album_artist=values.get("album_artist"), composer=values.get("composer"),
                track=_int_of(values.get("track")), disc=_int_of(values.get("disc")), seconds=seconds)


def _mp3_seconds(head, start, size):
    """An MP3's length: its Xing / Info or VBRI frame count, else its bytes at the first frame's bit rate (CBR)."""
    i = head.find(b"\xff", start)
    while 0 <= i < len(head) - 4:
        b1, b2, b3 = head[i + 1], head[i + 2], head[i + 3]
        if (b1 & 0xE0) == 0xE0 and (b1 >> 1) & 3 == 1 and (b2 >> 4) not in (0, 15) and (b2 >> 2) & 3 != 3:
            version = (b1 >> 3) & 3                          # 3: MPEG-1, 2: MPEG-2, 0: MPEG-2.5
            rate = _RATES[version][(b2 >> 2) & 3] if version in _RATES else None
            kbps = _BITRATES[1 if version == 3 else 2][b2 >> 4]
            if rate is None:
                return None
            mono = (b3 >> 6) == 3
            samples = 1152 if version == 3 else 576
            side = (17 if mono else 32) if version == 3 else (9 if mono else 17)
            for at in (i + 4 + side, i + 36):
                tag = head[at:at + 4]
                if tag in (b"Xing", b"Info") and len(head) >= at + 12 and head[at + 7] & 1:
                    frames = struct.unpack(">I", head[at + 8:at + 12])[0]
                    return frames * samples / rate if frames else None
                if tag == b"VBRI" and len(head) >= at + 18:
                    frames = struct.unpack(">I", head[at + 14:at + 18])[0]
                    return frames * samples / rate if frames else None
            return (size - i) * 8 / (kbps * 1000) if kbps else None
        i = head.find(b"\xff", i + 1)
    return None


_MP4_IDS = {b"\xa9nam": "title", b"\xa9alb": "album", b"\xa9ART": "artist", b"aART": "album_artist",
            b"\xa9wrt": "composer", b"trkn": "track", b"disk": "disc"}


def _atoms(data, pos, end):
    """[(type, payload start, payload end)] of the atoms in data[pos:end]."""
    out = []
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        hdr = 8
        if size == 1:
            size, hdr = struct.unpack(">Q", data[pos + 8:pos + 16])[0], 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            break
        out.append((kind, pos + hdr, pos + size))
        pos += size
    return out


def _mp4_tags(path):
    """An MP4's Tags, or None when it is no MP4 (no `moov` among its top atoms)."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        total = f.tell()
        pos, moov, hdr = 0, None, 8
        while pos + 8 <= total:                              # the top atoms by seeking: `mdat` is never read
            f.seek(pos)
            head = f.read(16)
            if len(head) < 8:
                break
            size, kind = struct.unpack(">I4s", head[:8])
            hdr = 8
            if size == 1 and len(head) == 16:
                size, hdr = struct.unpack(">Q", head[8:16])[0], 16
            elif size == 0:
                size = total - pos
            if size < 8:
                break
            if kind == b"moov":
                if size > MOOV_MAX:
                    return None
                f.seek(pos)
                moov = f.read(size)
                break
            pos += size
    if moov is None:
        return None
    values, seconds, chapters = {}, None, None
    for kind, a, b in _atoms(moov, hdr, len(moov)):
        if kind == b"mvhd":
            if moov[a] == 1:
                scale, length = struct.unpack(">IQ", moov[a + 20:a + 32])
            else:
                scale, length = struct.unpack(">II", moov[a + 12:a + 20])
            seconds = length / scale if scale else None
        elif kind == b"meta":                                # QuickTime's place for it, beside iTunes' `udta/meta`
            _ilst(moov, a, b, values)
        elif kind == b"udta":
            for k2, a2, b2 in _atoms(moov, a, b):
                if k2 == b"chpl":
                    try:
                        chapters = _chpl(moov[a2:b2])
                    except (IndexError, struct.error):       # a short chapter list: no chapters, the tags kept
                        chapters = None
                elif k2 == b"meta":
                    _ilst(moov, a2, b2, values)
    if chapters and seconds:
        chapters[-1]["end_ms"] = int(round(seconds * 1000))
    return Tags(title=values.get("title"), album=values.get("album"), artist=values.get("artist"),
                album_artist=values.get("album_artist"), composer=values.get("composer"), track=values.get("track"),
                disc=values.get("disc"), seconds=seconds, chapters=chapters or None)


def _ilst(moov, a, b, values):
    """A `meta` atom's `ilst` tags into `values` (iTunes' `meta` is a full atom, its 4 version bytes first;
    QuickTime's is not)."""
    start = a if moov[a + 4:a + 8] in (b"hdlr", b"ilst", b"keys") else a + 4
    for k3, a3, b3 in _atoms(moov, start, b):
        if k3 != b"ilst":
            continue
        for k4, a4, b4 in _atoms(moov, a3, b3):
            key = _MP4_IDS.get(k4)
            data = next(((x, y) for k5, x, y in _atoms(moov, a4, b4) if k5 == b"data"), None)
            if key and data and key not in values:
                body = moov[data[0] + 8:data[1]]
                if key in ("track", "disc"):
                    values[key] = struct.unpack(">H", body[2:4])[0] if len(body) >= 4 else None
                else:
                    values[key] = body.decode("utf-8", "replace").strip() or None


def _chpl(data):
    """Nero's chapter list: [{"title", "start_ms", "end_ms"}] (start in 100 ns units; each ends where the next
    starts)."""
    version, pos = data[0], 4 + (4 if data[0] == 1 else 0)
    if version > 1:
        return None
    count, pos = data[pos], pos + 1
    out = []
    for _ in range(count):
        start = struct.unpack(">Q", data[pos:pos + 8])[0]
        n = data[pos + 8]
        title = data[pos + 9:pos + 9 + n].decode("utf-8", "replace").strip()
        pos += 9 + n
        out.append({"title": title, "start_ms": start // 10000, "end_ms": None})
    for a, b in zip(out, out[1:]):
        a["end_ms"] = b["start_ms"]
    return out


# --- finding ------------------------------------------------------------------------------------------------------- #
def find(folder, root=None, held=None):
    """The audiobooks of one folder (its disc folders joined in) -> [Audiobook], in name order. A disc folder's own
    files are its parent's (none here) unless it is the `root` looked at; disc folders named with a title
    (`吾輩は猫である CD1`, `坊っちゃん CD1`) join by that title, each title one audiobook; a folder holding a video has
    none. `held(stat)`: True for an audio file that must not be opened yet (a cloud placeholder: its read would
    download it; one still being written) — the folder gives none until the next look."""
    from app.connect.runner import video_file, video_name
    if disc_number(os.path.basename(os.path.normpath(folder))) is not None and \
            (root is None or os.path.normpath(folder) != os.path.normpath(root)):
        return []
    own, discs, titled = [], {}, {}
    try:
        for entry in _entries(folder):
            if entry.is_dir(follow_symlinks=False):
                if disc_number(entry.name) is not None:
                    discs.setdefault(disc_title(entry.name), []).append(entry)
            elif video_name(entry.name) and video_file(entry.name, entry.stat().st_size):
                return []
            elif is_audio(entry.name):
                if held is not None and held(entry.stat()):
                    return []
                own.append((None, entry.path))
        for title, folders in discs.items():
            for disc in folders:
                for entry in _entries(disc.path):
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if video_name(entry.name) and video_file(entry.name, entry.stat().st_size):
                        return []
                    if is_audio(entry.name):
                        if held is not None and held(entry.stat()):
                            return []
                        into = own if not title else titled.setdefault(title, ([], disc.name))[0]
                        into.append((disc_number(disc.name), entry.path))
    except OSError:
        return []
    groups = []                                              # [(files, the folder's name as a title or None)]
    for files in [own] + [t[0] for t in titled.values()]:    # each m4b on its own
        groups += [([f], None) for f in sorted((f for f in files if f[1].lower().endswith(".m4b")),
                                               key=lambda f: _natural(os.path.basename(f[1])))]
    rest = [(d, p, read_tags(p)) for d, p in own if not p.lower().endswith(".m4b")]
    if rest:
        albums = {_album_key(t.album) for _, _, t in rest if t.album}
        if len(albums) > 1 and all(t.album for _, _, t in rest):     # two albums in one folder: two audiobooks
            groups += [([x for x in rest if _album_key(x[2].album) == album], None)
                       for album in sorted(albums, key=lambda k: _natural(k[0]))]
        else:
            groups.append((rest, _folder_title(folder)))
    for _title, (files, disc_name) in sorted(titled.items()):
        files = [f for f in files if not f[1].lower().endswith(".m4b")]
        if files:
            groups.append((files, _DISC.sub(" ", unicodedata.normalize("NFKC", disc_name).casefold()).strip()))
    if len(groups) > 1:                                      # the folder's name is a title of its one audiobook only
        own_name = _folder_title(folder)
        groups = [(g, None if name == own_name else name) for g, name in groups]
    out = [_audiobook(folder, g, name) for g, name in groups]
    return [a for a in out if a is not None]


def _entries(folder):
    with os.scandir(folder) as found:
        return list(found)


def _album_key(album):
    """An album tag's identity, its disc's mark and its form out (`銀河鉄道の夜 (Disc 1)` is `銀河鉄道の夜`'s)."""
    forms, vol = clean(album)
    return ("".join(sorted(forms)), vol or "")


def _folder_title(folder):
    """The folder's name as its audiobook's title; one named only for what it holds (`audio/`) gives the one above."""
    name = os.path.basename(os.path.normpath(folder))
    if _nfkc(name).strip() in _GENERIC or not clean(name)[0]:
        name = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    return name


def _ordered(files):
    """[(disc, path, Tags)] in reading order: the tags' (disc, track) when every file has a track and no two repeat,
    else the disc folder's number, then the name (numbers as numbers)."""
    keys = [((t.disc or d or 0), t.track) for d, p, t in files]
    if all(k[1] is not None for k in keys) and len(set(keys)) == len(keys):
        return [f for _, f in sorted(zip(keys, files), key=lambda x: (x[0], _natural(os.path.basename(x[1][1]))))]
    return sorted(files, key=lambda f: (f[0] or 0, _natural(os.path.basename(f[1]))))


def _audiobook(folder, files, name=None):
    """One audiobook of `files` [(disc, path) or (disc, path, Tags)], or None when it is too short to be one; `name`:
    a folder's name that is one of its titles."""
    files = _ordered([f if len(f) == 3 else (f[0], f[1], read_tags(f[1])) for f in files])
    sizes = []
    for _, p, _t in files:
        try:
            sizes.append(os.path.getsize(p))
        except OSError:
            sizes.append(0)
    size = sum(sizes)
    lengths = [t.seconds for _, _, t in files]
    seconds = sum(lengths) if all(s for s in lengths) else None
    if (seconds is not None and seconds < MIN_SECONDS) or (seconds is None and size < MIN_BYTES):
        return None
    first = files[0][2]
    one = len(files) == 1
    album = _DISC_MARK.sub(" ", unicodedata.normalize("NFKC", first.album)).strip() if first.album else None
    titles = [x for x in (album, first.title if one else None,
                          os.path.splitext(os.path.basename(files[0][1]))[0] if one else None, name) if x]
    titles = [t for t in titles if clean(t)[0]] or titles    # a name with no letter (`01`) is no title
    authors = sorted({x for _, _, t in files for x in (t.album_artist, t.composer, t.artist) if x})
    chapters = first.chapters if one else None
    if not chapters and not one and seconds is not None:     # one chapter per file, end to end
        chapters, at = [], 0
        for _, p, t in files:
            end = at + int(round(t.seconds * 1000))
            chapters.append({"title": t.title or os.path.splitext(os.path.basename(p))[0], "start_ms": at,
                             "end_ms": end})
            at = end
    vol = next((v for v in (volume(t) for t in titles) if v), None)
    return Audiobook(folder=os.path.abspath(folder), files=[os.path.abspath(p) for _, p, _t in files],
                     title=titles[0] if titles else os.path.basename(os.path.normpath(folder)), titles=titles,
                     authors=authors, volume=vol, seconds=seconds, size=size, sizes=tuple(sizes), chapters=chapters)


# --- the book's side ----------------------------------------------------------------------------------------------- #
def epub_meta(path):
    """An EPUB's (titles, creators) from its package document (`dc:title`, `dc:creator`); ((), ()) when unread."""
    import zipfile
    from app import extract
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            opf = None
            if "META-INF/container.xml" in names:
                container = extract._xml(extract._member(zf, "META-INF/container.xml") or b"")
                if container is not None:
                    opf = next((el.get("full-path") for el in container.iter()
                                if extract._local(el) == "rootfile" and el.get("full-path") in names), None)
            opf = opf or next((n for n in sorted(names) if n.lower().endswith(".opf")), None)
            root = extract._xml(extract._member(zf, opf) or b"") if opf else None
    except Exception:                                    # a damaged member (zlib, an unknown compression): unread
        return (), ()
    if root is None:
        return (), ()
    titles, authors = [], []
    for el in root.iter():
        name = extract._local(el)
        text = (el.text or "").strip() if isinstance(el.tag, str) else ""
        if name == "title" and text and text not in titles:
            titles.append(text)
        elif name == "creator" and text and text not in authors:
            authors.append(text)
    return tuple(titles), tuple(authors)


def book_of(epub, book_id=None, chars=None, sha256=None):
    """A Book for `decide` from an EPUB on disk: its metadata's titles and its file name, its creators."""
    titles, authors = epub_meta(epub)
    stem = os.path.splitext(os.path.basename(epub))[0]
    return Book(id=book_id, path=os.path.abspath(epub), titles=tuple(titles) + (stem,), authors=authors,
                chars=chars, sha256=sha256)


# --- pairing ------------------------------------------------------------------------------------------------------- #
SAME, NONE, ONE_SIDED, DIFFER = "same", "none", "one", "differ"     # what the two sides' volumes say (`score`)


def _forms(names):
    out, vols = set(), set()
    for n in names:
        forms, vol = clean(n)
        out |= forms
        if vol:
            vols.add(vol)
    return out, vols


def _title_level(a, b):
    best = 0
    for x in a:
        for y in b:
            if x == y:
                return EXACT
            short, long_ = (x, y) if len(x) <= len(y) else (y, x)
            if len(short) >= 4 and short in long_ and len(short) >= CLOSE_SHARE * len(long_):
                best = max(best, CLOSE)
            elif difflib.SequenceMatcher(None, x, y).ratio() >= LIKE_RATIO:
                best = max(best, LIKE)
    return best


def _near(a, b):
    """0: the same folder; 1: one holds the other, or they sit side by side; 2: farther."""
    a, b = os.path.normcase(os.path.abspath(a)), os.path.normcase(os.path.abspath(b))
    if a == b:
        return 0
    if os.path.dirname(a) == b or os.path.dirname(b) == a or os.path.dirname(a) == os.path.dirname(b):
        return 1
    return 2


def _volumes(a, b):
    if a and b:
        return SAME if a & b else DIFFER
    return ONE_SIDED if a or b else NONE


def score(audiobook, book):
    """How an audiobook and a book agree -> Score(title level, volumes (SAME / NONE / ONE_SIDED / DIFFER), length
    fits (True / False / None: unknown), an author tag names the creator, how near their folders are)."""
    a_forms, a_vols = _forms(audiobook.titles)
    b_forms, b_vols = _forms(book.titles)
    length = None
    if audiobook.seconds and book.chars:
        rate = book.chars / audiobook.seconds
        length = LENGTH_FIT[0] <= rate <= LENGTH_FIT[1]
    a_auth = {re.sub(r"[\W_]+", "", _nfkc(x)) for x in audiobook.authors} - {""}
    b_auth = {re.sub(r"[\W_]+", "", _nfkc(x)) for x in book.authors} - {""}
    author = any(x == y or (min(len(x), len(y)) >= 2 and (x in y or y in x)) for x in a_auth for y in b_auth)
    near = _near(audiobook.folder, os.path.dirname(book.path)) if book.path else 2
    return Score(_title_level(a_forms, b_forms), _volumes(a_vols, b_vols), length, author, near)


def answer_key(audiobook, book):
    """The remembered answer's key for this pair: the audiobook's files' sizes in order (never its names: the same
    after its folder is renamed or moved) and the book's sha256 (else its path, else its titles); a new edition of
    either is a new pair."""
    other = book.sha256 or (os.path.normcase(os.path.abspath(book.path)) if book.path else "|".join(book.titles))
    sizes = ",".join(str(n) for n in (audiobook.sizes or (audiobook.size,)))
    return hashlib.sha1(f"{sizes}|{other}".encode("utf-8")).hexdigest()


def _rank(s):
    return (s.title, {SAME: 2, NONE: 1, ONE_SIDED: 0}[s.volumes], s.author, {True: 2, None: 1, False: 0}[s.length])


def decide(audiobook, books, answers=None):
    """Which book `audiobook` reads aloud -> Pair(book, SURE | ASK | ANSWERED, its answer key) or None (alone).
    `answers` {answer key: True (the same book) / False (not)}: a yes wins at once, a no leaves that book out for good.
    Volumes that differ are never a pair. *sure*: an exact title (a close one only in the same folder: a sequel, 続・…,
    holds its first book's name), volumes the same or on neither side, a length that fits or is unknown, near (or an
    author tag naming the creator, or an exact title whose length fits), and no other book as good save farther away.
    Anything else with a title alike is the ONE question (*ask*), about the best book only: a *no* lets the next be
    asked."""
    answers = answers or {}
    weighed = []
    for book in books:
        key = answer_key(audiobook, book)
        said = answers.get(key)
        if said is True:
            return Pair(book, ANSWERED, key)
        if said is False:
            continue
        s = score(audiobook, book)
        if s.title and s.volumes != DIFFER:
            weighed.append((book, s, key))
    if not weighed:
        return None
    weighed.sort(key=lambda x: (tuple(-v for v in _rank(x[1])), x[1].near, os.path.normcase(x[0].path or "")))
    book, s, key = weighed[0]
    tie = any(_rank(o) == _rank(s) and o.near == s.near for _, o, _k in weighed[1:])
    sure = ((s.title == EXACT or (s.title == CLOSE and s.near == 0)) and s.volumes in (SAME, NONE) and
            s.length is not False and not tie and
            (s.near < 2 or s.author or (s.title == EXACT and s.length is True)))
    return Pair(book, SURE if sure else ASK, key)


# --- the library's record (PR 2: `sources` finds, `library_store` keeps) ------------------------------------------- #
def record(audiobook, pair=None):
    """An audiobook as its item's origin record holds it (`"audiobook"`): what Connect will need (its files in order,
    their sizes, the length, its chapters) and what `decide` weighs again without opening a file (`from_record`);
    `book` (paired: sure or answered) or `ask` (the one question) from `pair`."""
    rec = {"folder": audiobook.folder, "files": list(audiobook.files), "sizes": list(audiobook.sizes or ()),
           "size": audiobook.size, "seconds": audiobook.seconds, "chapters": audiobook.chapters,
           "title": audiobook.title, "titles": list(audiobook.titles), "authors": list(audiobook.authors),
           "volume": audiobook.volume, "book": None, "ask": None}
    if pair is not None:
        set_pair(rec, pair)
    return rec


def set_pair(rec, pair):
    """`decide`'s Pair written into a record: *sure* / *answered* -> `book`, *ask* -> `ask`; None -> neither. A book
    is named by its EPUB (path and sha256), one of its parts' item (`Book.id`) and its title."""
    rec["book"] = rec["ask"] = None
    if pair is None:
        return rec
    book = pair.book
    said = {"item": book.id, "epub": book.path, "sha256": book.sha256, "key": pair.key,
            "title": next(iter(book.titles), None)}
    if pair.how == ASK:
        rec["ask"] = said
    else:
        rec["book"] = dict(said, how=pair.how)
    return rec


def from_record(rec):
    """The Audiobook a record holds (`record`), its files never opened."""
    sizes = tuple(rec.get("sizes") or ())
    return Audiobook(folder=rec.get("folder") or os.path.dirname(next(iter(rec.get("files") or ()), "")),
                     files=list(rec.get("files") or ()), title=rec.get("title") or "",
                     titles=list(rec.get("titles") or ()), authors=list(rec.get("authors") or ()),
                     volume=rec.get("volume"), seconds=rec.get("seconds"),
                     size=rec.get("size") if rec.get("size") is not None else sum(sizes), sizes=sizes,
                     chapters=rec.get("chapters"))


def sizes_key(audiobook):
    """The audiobook's identity by its bytes' sizes in order (`audio:<sha1>`): its origin record's `sha256` (a Remove
    keeps it out by this after a rename or a move, S6) and its item's name; the same files copied elsewhere share it."""
    sizes = ",".join(str(n) for n in (audiobook.sizes or (audiobook.size,)))
    return "audio:" + hashlib.sha1(sizes.encode("utf-8")).hexdigest()


def length_text(seconds):
    """`9 h 12 min`, `48 min`; '' when unknown."""
    if not seconds:
        return ""
    minutes = int(round(seconds / 60))
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


# --- its transcript (Hon a6, H-12 ✅ Sonic, H-13 PROVISIONAL) ------------------------------------------------------- #
# A subtitle file beside an audiobook is its transcript, never a title of its own. Alone, the transcript is the
# audiobook's content (counted as a subtitle is); with its book, the book is the content and the transcript stays with
# the audio for its timing (Anki Miner's Z-16 `subtitle_file`), counting nothing — unless it isn't the book's (H-13).
TRANSCRIPT_EXTENSIONS = (".srt", ".ass", ".ssa")     # a timed subtitle the library reads (never a `.txt`: a book's)
CUE_MIN = 8                     # a cue this long (clean characters) or longer is looked for in the book
CONTENT_SHARE = 0.6             # this share of its cues found in the book, in order, and the transcript is the book's
TEXT, TIMING, OTHER, UNCHECKED = "text", "timing", "other", "unchecked"    # what a transcript is for (`transcript_use`)
_RUBY = re.compile(r"<rt>.*?</rt>|<rp>.*?</rp>", re.S | re.I)
_ASS_TAGS = re.compile(r"\{[^}]*\}")
_MARKUP = re.compile(r"<[^>]*>")
_ASS_BREAK = re.compile(r"\\[Nnh]")             # an `.ass` line's own breaks (`\N`, `\n`) and hard space (`\h`)


def is_transcript(name):
    """A timed subtitle's name (`.srt`, `.ass`, `.ssa`) — never a Mac `._` twin."""
    base = os.path.basename(str(name or ""))
    return base.lower().endswith(TRANSCRIPT_EXTENSIONS) and not base.startswith("._")


def transcripts(found, names):
    """Which of `names` (the subtitle files of one folder, as listed) is each audiobook's transcript -> {index in
    `found`: name}. `found`: the audiobooks of that folder. A name is an audiobook's when its clean title meets one of
    the audiobook's (the same, or one holding the other: `title_level` CLOSE or better) and their volumes agree (the
    same, or neither has one); else, a folder holding ONE audiobook and ONE subtitle: that one, whatever its name
    (`transcript.srt`, `01.srt`). Each name goes to one audiobook at most (the best title first, then the audiobook
    found first); one transcript per audiobook (the best title, then name order). A name no audiobook claims is left
    for the look (a subtitle as any)."""
    names = sorted({n for n in names if is_transcript(n)}, key=_natural)
    if not found or not names:
        return {}
    weighed = []
    for i, ab in enumerate(found):
        forms, vols = _forms(ab.titles or [ab.title])
        for n in names:
            n_forms, n_vols = _forms([os.path.splitext(n)[0]])
            level = _title_level(forms, n_forms) if forms and n_forms else 0
            if level >= CLOSE and _volumes(vols, n_vols) in (SAME, NONE):
                weighed.append((-level, i, _natural(n), n))
    out, taken = {}, set()
    for _level, i, _key, n in sorted(weighed):
        if i not in out and n not in taken:
            out[i] = n
            taken.add(n)
    if not out and len(found) == 1 and len(names) == 1:
        out[0] = names[0]
    return out


def clean_text(text):
    """A text as the content check compares it: NFKC, ruby readings and markup out, letters and digits only."""
    text = _MARKUP.sub("", _RUBY.sub("", unicodedata.normalize("NFKC", str(text or ""))))
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LN")


def cues(text):
    """A transcript's lines as the content check looks for them -> [clean text] of each cue of CUE_MIN characters or
    more: an `.srt`'s blocks (its numbers and times out), an `.ass` / `.ssa`'s `Dialogue:` lines (their style tags
    and line breaks out)."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    out = []
    if re.search(r"^\s*\[Script Info\]|^Dialogue:", text, re.M):
        lines = [ln.split(",", 9)[9] for ln in text.split("\n") if ln.startswith("Dialogue:") and ln.count(",") >= 9]
        blocks = [_ASS_BREAK.sub("", _ASS_TAGS.sub("", ln)) for ln in lines]
    else:
        blocks = ["".join(ln for ln in block.split("\n")
                          if ln.strip() and "-->" not in ln and not ln.strip().isdigit())
                  for block in re.split(r"\n\s*\n", text)]
    for b in blocks:
        t = clean_text(re.sub(r"<[^>]+>", "", b))
        if len(t) >= CUE_MIN:
            out.append(t)
    return out


def found_in_order(lines, book_text):
    """The share of a transcript's cues (`cues`) found in the book's text (`clean_text`'d), each after the one before
    -> 0.0–1.0; None when the transcript has no cue to look for."""
    if not lines:
        return None
    at, n = 0, 0
    for line in lines:
        i = book_text.find(line, at)
        if i >= 0:
            n += 1
            at = i + len(line)
    return n / len(lines)


def transcript_use(rec):
    """What an audiobook record's transcript is for -> None (it has none); TEXT (alone or asked about: its content);
    TIMING (paired, its cues found in that book: the book is the content, the transcript its timing); OTHER (paired,
    not that book's: never used, a *Needs you* line says so); UNCHECKED (paired, the check not made for this book yet:
    never counted)."""
    said = (rec or {}).get("transcript")
    if not isinstance(said, dict):
        return None
    book = rec.get("book")
    if not isinstance(book, dict):
        return TEXT
    found = said.get("found")
    if not isinstance(found, dict) or found.get("book") != _book_mark(book):
        return UNCHECKED
    share = found.get("share")
    return TIMING if isinstance(share, (int, float)) and share >= CONTENT_SHARE else OTHER


def _book_mark(book):
    """The book a check was made against: its EPUB's sha256, else its path (`set_pair`'s `book`)."""
    return book.get("sha256") or book.get("epub")
