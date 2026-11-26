# SPDX-License-Identifier: GPL-3.0-or-later
"""Netflix and Disney+ subtitles from 鵜飼 Ukai become library items (Ukai SPEC §6 U-S2): Mattias's #474
(`app/online_receiver.py`, by mattias) — its parsing, checks, tidying and item kept as he wrote them; its listener,
token and Origin checks replaced by the one door's (`app/door.py`, Ukai's class, and the pairing).

The body Ukai posts (its CONTRACT.md v1: {"schema": 1, "site", "video_id", "url", "language", "title",
"show": {"title", "season", "episode"} (none for a film), "cues": [[start s, end s, text], …], "cover"?}) is checked
and tidied here (`subtitle`, `tidy_cues`), then written as a transcript the YouTube downloader's way and registered
through the window's writer (`take_in`). By then the door has checked the address, the Origin, the pairing's token
and the body's size (`Call.json`, 4 MB); the route (`modules/ukai/__init__.py`) asks this.

**The item** (`write`, `record`): a transcript as the YouTube downloader writes one — its `.txt` (the downloader's
header: `analyzer.transcript_body` reads it as one) and its cue sidecar (`<stem>.surasura.json`, each cue
[text, start, end]: the end too, which the later mining reads) — into the language's Processed folder, a loose drop
whose title is its record's show (a film: its own title). The file's name ends `[netflix-<id>]` /
`[disneyplus-<id>]` (`path_utils.SITE_ID_RE`), so its `source_type` is the site: an online item, ▶ its page.
**Never twice:** one item a pairing `content_key` (`netflix:<id>`); the same video sent again is that item.

**Never a video, never DRM.** Only the text the browser already shows comes in; nothing here contacts anything.

Standard library only (fugashi for a Japanese line's readings, when it's there); no Qt.
"""
import base64
import binascii
import json
import logging
import os
import re
import threading

log = logging.getLogger(__name__)

SCHEMA = 1
LANGUAGES = ("ja", "zh")
SITES = {"netflix": "Netflix", "disneyplus": "Disney+"}     # `source_type` -> the site's name (`play.SITES` too)
PRODUCER = "browser"                    # the pairing record's producer (`placing_rules`' `browser`)
MAX_CUES = 20000
MAX_COVER = 400 * 1024                  # the show's artwork as the page shows it (the contract's limit)
MAX_SECONDS = 24 * 3600                 # a cue's time: no episode or film is a day long (an endless one is a 400)
MAX_URL = 2048
_ID = re.compile(r"[A-Za-z0-9-]{1,64}")         # Netflix's digits, Disney+'s UUID-like ids
_RESERVED = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class Bad(ValueError):
    """A body the contract doesn't take: `why` in plain words (the 400's)."""


class Busy(Exception):
    """Surasura can't take it now (no library open, the store busy, read-only): the 503."""


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_SECONDS:
        raise Bad("a cue's times must be seconds")         # (NaN and an endless time fail the range too)
    return round(float(value), 3)


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def subtitle(got):
    """The posted body (a dict: the door's `Call.json` read it, within its 4 MB) -> the subtitle as the contract
    names it, checked and tidied; raises Bad."""
    if not isinstance(got, dict):
        raise Bad("the body isn't a JSON object")
    if got.get("schema") != SCHEMA:
        raise Bad(f"schema {SCHEMA} only")
    site = got.get("site")
    if site not in SITES:
        raise Bad(f"site must be one of {', '.join(SITES)}")
    video = str(got.get("video_id") or "")
    if not _ID.fullmatch(video):
        raise Bad("video_id is missing or not an id")
    url = got.get("url")
    if (not isinstance(url, str) or not url.startswith("https://") or len(url) > MAX_URL
            or any(c.isspace() or not c.isprintable() for c in url)):
        raise Bad("url must be the video's https page")     # (one line: it heads the transcript, ▶ opens it)
    language = got.get("language")
    if language not in LANGUAGES:
        raise Bad(f"language must be one of {', '.join(LANGUAGES)}")
    title = got.get("title")
    title = " ".join(title.split()) if isinstance(title, str) else ""
    show = got.get("show")
    if show is not None:
        if not isinstance(show, dict) or not isinstance(show.get("title"), str) or not show["title"].strip():
            raise Bad("show needs its title")
        show = {"title": " ".join(show["title"].split()), "season": _number(show.get("season")),
                "episode": _number(show.get("episode"))}
    if not title and not show:
        raise Bad("title is missing")
    cues = got.get("cues")
    if not isinstance(cues, list) or not cues:
        raise Bad("cues are missing")
    if len(cues) > MAX_CUES:
        raise Bad("too many cues")
    tidy = []
    for cue in cues:
        if not isinstance(cue, list) or len(cue) != 3 or not isinstance(cue[2], str):
            raise Bad("each cue is [start, end, text]")
        start, end, text = _seconds(cue[0]), _seconds(cue[1]), " ".join(cue[2].split())
        if end < start:
            raise Bad("a cue ends before it starts")
        if text:
            tidy.append([start, end, text])
    tidy = tidy_cues(tidy, language)
    if not tidy:
        raise Bad("every cue is empty")
    return {"site": site, "video_id": video, "url": url.split("#", 1)[0], "language": language,
            "title": title or show["title"], "show": show, "cues": tidy,
            "cover": got["cover"] if isinstance(got.get("cover"), str) else None}


_KANJI = re.compile(r"[㐀-䶿一-鿿豈-﫿々〆ヶ]+")
_HIRAGANA = re.compile(r"[ぁ-ゖー]+")


def tidy_cues(cues, language):
    """A streaming site's cues made what a subtitle file's are, before anything reads them (the item's text, its
    sidecar, the pick, the clips the extension records, Anki Miner's sentences):

    - **one line, one cue**: a player splits a line that is on screen while another starts (Netflix: the same text
      in two or three cues, back to back, the other speaker's line between them). Copies are joined into the first,
      by Generate's own rule (`analyzer.shown_again`: the same text spaces aside, touching or overlapping), its time
      the copies' together; the other line stays, overlapping it, so the pick sees two people talking at once;
    - **no reading written in** (Japanese): a reading the player shows as ruby, flattened into the text after its
      kanji (黒沼くろぬま → 黒沼; `unruby`).

    [[start s, end s, text]] in time order -> the same, tidied."""
    from app import analyzer
    if language == "ja":
        flat = {}                           # a line split into copies is unruby'd once, not once a copy
        cues = [[s, e, flat[t] if t in flat else flat.setdefault(t, unruby(t))] for s, e, t in cues]
    cues = sorted(cues, key=lambda c: (c[0], c[1]))
    again = analyzer.shown_again([(int(round(s * 1000)), int(round(e * 1000)), t) for s, e, t in cues])
    out, kept = [], {}
    for n, (cue, first) in enumerate(zip(cues, again)):
        if first is None or first not in kept:
            kept[n] = len(out)
            out.append(list(cue))
            continue
        joined = out[kept[first]]
        joined[0], joined[1] = min(joined[0], cue[0]), max(joined[1], cue[1])
    return out


def unruby(text):
    """Japanese text with the readings a player flattened into it taken out: a run of kanji followed at once by its
    own reading in hiragana (黒沼くろぬま, 善ぜんは → 黒沼, 善は). Taken out only where the tagger, reading the whole
    text, has no word that runs across the kanji's end into the kana (日にち stays as written), only the reading the
    tagger gives those kanji read alone, whole, and never kana the tagger reads as particles and endings alone
    (何なんだ: the sentence's own)."""
    if not _KANJI.search(text or ""):
        return text
    tagger = _tagger()
    if tagger is None:
        return text
    ends, grammar = set(), set()          # where the tagger's words end; the places a particle or ending covers
    at = 0
    for word in tagger(text):
        at = text.find(word.surface, at)
        if at < 0:
            return text
        if word.feature.pos1 in _GRAMMAR:
            grammar.update(range(at, at + len(word.surface)))
        at += len(word.surface)
        ends.add(at)
    out, last = [], 0
    for run in _KANJI.finditer(text):
        kanji, kana = run.group(), _HIRAGANA.match(text, run.end())
        if not kana or run.end() not in ends:
            continue
        if any(len(next(iter(tagger(piece)), kanji).surface) > len(kanji)       # 日にち, 嫌いや: the kanji and the
               for piece in (text[run.start():], kanji + kana.group()[0])):     # kana after it are one word
            continue
        reading = _reading(tagger(kanji))
        cut = _ruby_length(tagger, kanji, kana.group(), reading)
        short = len(kanji) == 1 and cut <= 2            # 何なんだ: one kanji and the sentence's own grammar after it
        if cut and run.end() + cut in ends and not (short and grammar.issuperset(range(run.end(), run.end() + cut))):
            out.append(text[last:run.end()])
            last = run.end() + cut
    return "".join(out) + text[last:] if out else text


def _reading(words):
    return _hiragana("".join(w.feature.kana for w in words if w.feature.kana not in (None, "*")))


def _ruby_length(tagger, kanji, kana, reading):
    """How much of `kana`, the hiragana right after `kanji`, is its reading -> its length, or 0: the whole reading
    the kanji have alone (黒沼くろぬま, 巻まきの, 読売よみうり), checked by reading the kanji again with it taken out;
    shorter only where the reading's last kana are a verb's or an adjective's own ending, written after it again
    (捧ささげられた: ささ — 捧げ, a verb read ささげ)."""
    if not reading or not kana.startswith(reading):
        return 0

    def held(cut):
        """The words that hold the kanji once `cut` kana are taken out, if they read as just those kana and the kana
        they bind (their ending)."""
        words, covered = [], ""
        for word in tagger(kanji + kana[cut:]):
            if len(covered) >= len(kanji):
                break
            words.append(word)
            covered += word.surface
        ok = covered.startswith(kanji) and _reading(words) == kana[:cut] + _hiragana(covered[len(kanji):])
        return words if ok else None
    for cut in range(len(reading) - 1, 0, -1):
        words = held(cut)
        if words and len("".join(w.surface for w in words)) > len(kanji) \
                and words[-1].feature.pos1 in ("動詞", "形容詞"):
            return cut
    return len(reading) if held(len(reading)) else 0


_GRAMMAR = ("助詞", "助動詞")       # a particle, an auxiliary: kana after kanji that is the sentence, not its reading


def _hiragana(katakana):
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in katakana)


_TAGGER = []


def _tagger():
    """fugashi's tagger, loaded once (None when it can't be: the text is kept as sent)."""
    if not _TAGGER:
        try:
            from fugashi import Tagger
            _TAGGER.append(Tagger())
        except Exception:               # no dictionary: never a reason to refuse a subtitle
            log.warning("Online subtitle: no Japanese tagger, readings written into lines are kept")
            _TAGGER.append(None)
    return _TAGGER[0]


def content_key(sub):
    """The pairing's key: one per site's video, so the same video is never a second item."""
    return f"{sub['site']}:{sub['video_id']}"


def _clean(name):
    return _RESERVED.sub("_", name).strip().rstrip(". ")[:80].rstrip(". ")


def file_name(sub):
    """`<Show> S01E03 <episode title> [netflix-<id>].txt`; a film `<title> [disneyplus-<id>].txt`."""
    show = sub["show"]
    parts = []
    if show:
        parts.append(_clean(show["title"]))
        if show["episode"]:
            parts.append(f"S{show['season'] or 1:02d}E{show['episode']:02d}")
        if sub["title"] != show["title"]:
            parts.append(_clean(sub["title"]))
    else:
        parts.append(_clean(sub["title"]))
    name = " ".join(p for p in parts if p) or sub["site"]
    return f"{name} [{sub['site']}-{sub['video_id']}].txt"


def text(sub):
    """The transcript: the downloader's header (`analyzer.transcript_body`), then a cue a line."""
    show = sub["show"]
    header = [sub["title"], f"{show['title'] if show else SITES[sub['site']]} |  | ",
              f"Captions: {sub['language']} (manual)", sub["url"], "", "-" * 60, ""]
    return "\n".join(header) + "\n".join(c[2] for c in sub["cues"]) + "\n"


def sidecar(sub):
    """The cue sidecar: what `cues._transcript` and ▶ read (`video_id`, `url`, `title`, cues [text, start, end] — the
    start first, as the downloader's [text, seconds]), the show for `record`."""
    return {"video_id": sub["video_id"], "url": sub["url"], "title": sub["title"], "site": sub["site"],
            "show": sub["show"], "cues": [[c[2], c[0], c[1]] for c in sub["cues"]]}


def write(folder, sub):
    """The transcript and its sidecar into `folder` (the language's Processed) -> the transcript's path. Written
    sidecar first, each through a temporary name, so the library never sees a transcript without its cues."""
    from app.path_utils import SIDECAR_SUFFIX
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, file_name(sub))
    for target, data in ((os.path.splitext(path)[0] + SIDECAR_SUFFIX, json.dumps(sidecar(sub), ensure_ascii=False)),
                         (path, text(sub))):
        tmp = target + ".part"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        os.replace(tmp, target)
    return path


def record(sub, language):
    """The pairing record `Store.register` takes for it: titled by its show (a film by its own title), the episode's
    season and number kept; `video_id` and `url` for ▶ (`play.online_link`)."""
    show = dict(sub["show"] or {"title": sub["title"]})
    show = {k: v for k, v in show.items() if v is not None}
    out = {"schema": 1, "producer": PRODUCER, "language": language, "content_key": content_key(sub),
           "video_id": sub["video_id"], "url": sub["url"], "title": sub["title"], "show": show}
    if not sub["show"]:
        out["media_type"] = "movie"
    return out


def keep_cover(writer, sub, item_id):
    """The show's artwork the extension sent (`cover`: base64 JPEG or PNG, at most MAX_COVER) as its title's cover —
    only while the title has none of its own (none, or the generated one: never its own art, an AniList or TMDB cover,
    nor your pick). Kept as *Choose an image…* keeps one (`covers.keep_user_bytes`' folder, name and checks) and
    recorded through the window's writer as nobody's choice (`auto`: never on the Undo stack), unlocked: *Change
    cover…* still replaces it, and an online fetch never does (`Store.set_cover`'s rule). -> its record's path, or
    None; never raises (a cover is never a reason for the subtitle to fail: the why is logged)."""
    raw = sub.get("cover")
    if not raw:
        return None
    try:
        data = base64.b64decode(raw, validate=True)
        if len(data) > MAX_COVER:
            raise ValueError(f"{len(data)} bytes, over {MAX_COVER}")
        from app.services import covers
        if covers.image_ext(data) is None:
            raise ValueError("not a JPEG or PNG")
        try:
            store = writer.opener.handle()
            with store._reading():
                row = store.conn.execute("SELECT w.id, w.cover_source, w.cover_locked FROM items i JOIN works w ON "
                                         "w.id = i.work_id WHERE i.id = ?", (item_id,)).fetchone()
        finally:
            writer.opener.close()
        if row is None or row[1] not in (None, "generated") or row[2]:
            return None                         # a title with a cover of its own keeps it
        kept = covers.keep_user_bytes(writer.language, row[0], data, writer, source="user",
                                      ref=f"browser:{sub['site']}", locked=False, auto=True)
        if kept is None:
            raise OSError("it couldn't be written, or the library can't be written now")
        return kept
    except (binascii.Error, ValueError, OSError) as e:
        log.warning("Ukai's cover wasn't kept: %s", e)
    except Exception:
        log.exception("Ukai's cover wasn't kept")
    return None


def _cover_later(writer, sub, item_id):
    """`keep_cover` on a thread of its own: the subtitle's answer never waits for it."""
    if sub.get("cover"):
        threading.Thread(target=keep_cover, args=(writer, sub, item_id), name="ukai-cover",
                         daemon=True).start()


def take_in(writer, sub, rules=None, timeout=30.0, cover=_cover_later):
    """(The listener's thread.) The subtitle into the library open now -> (added, item id): one video already in
    (its pairing's `content_key`) -> (False, its item), nothing written; else its files into Processed, registered
    through the window's writer (`Writer.register`: New arrivals unless the learner's `placing_rules` place it) and
    waited for. Raises Busy (the 503: the extension keeps it and sends it again) with no library open, another
    language's open, a read-only or busy store, or a write that didn't land within `timeout`."""
    if writer is None or getattr(writer.opener, "data_dir", None) is None:
        raise Busy("No library is open in Surasura")
    if writer.language != sub["language"]:
        raise Busy(f"Surasura's open library isn't the {sub['language']} one: it is taken once that one is open")
    key = content_key(sub)

    def look(path=None):
        try:
            store = writer.opener.handle()
            if store is None:
                raise Busy("Surasura's library is busy: try again later")
            if path is None:
                return store.paired_item(key)
            from app.library_store import library_rel
            return store.paired_item(key) or store.item_id(library_rel(writer.opener.data_dir, path))
        except Busy:
            raise
        except Exception:
            raise Busy("Surasura's library is busy: try again later") from None
        finally:
            writer.opener.close()               # this thread's handle: never kept between requests
    item = look()
    if item is not None:
        cover(writer, sub, item)                # (sent again: a title still without one takes it now)
        return False, item
    folder = os.path.join(writer.opener.data_dir, "Processed")
    path = os.path.join(folder, file_name(sub))
    if not os.path.exists(path):            # one already there (by hand, or a try whose answer was lost): kept as is
        try:
            write(folder, sub)
        except OSError as e:
            raise Busy(f"Surasura couldn't write it now: {e.strerror or e}") from None
    landed = threading.Event()
    seq = writer.register([path], record(sub, writer.language), rules=rules,
                          done=lambda *_counts: landed.set())
    if seq is None:
        raise Busy("Surasura's library can't be written now (read-only)")
    if not landed.wait(timeout):
        raise Busy("Surasura is busy: try again later")
    item = look(path)
    if item is None:
        raise Busy("Surasura couldn't add it: try again later")
    cover(writer, sub, item)
    return True, item
