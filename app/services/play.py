"""The file an episode's ▶ opens (laptop fix "play", FEEDBACK row 5; review AD-2 – AD-6, IK-3, R2-2). A worker's; never writes.

Found as Connect finds the episode's video (`app/connect/runner.Runner.video`), through Connect's own rules, so ▶ and
the row's status agree: a paired episode (hato's, or a source folder's scan that found the video beside the original)
opens the video its pairing names, or — moved — the one of that name and size Connect's index holds whose bytes say it
is that video (`runner.paired_video`); any other opens a video beside its content file — or, for a file a source
folder holds, beside the original: the content file is a copy in `Library/`, the video stays where the folder was read
— by name (`runner.beside`); else one Connect's video index holds by name. A book or a text opens its original, else
the file itself.

Connect's index is read as Connect last saved it (`videos.Index.find` with no refresh): never listed or written here
(Connect owns it). Each folder is listed once (one round trip on a share), and an original's folder that can't be
listed (a share offline) is said, never waited on.
"""
import os
import re

AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".opus", ".ogg", ".flac", ".wav")
WHY = {
    "not-on-disk": "it isn't on disk",
    "no-media": "no {word} beside it on disk",
    "unreachable": "its folder can't be reached just now",        # the original's folder: a share offline (AD-2)
    "unreadable": "the library can't be read just now",           # read-only, busy or damaged: its record unread (AD-6)
}
_UNLISTED = object()                # `runner.beside`'s answer for a folder that can't be listed


def pairing(language, item_id):
    """The item's pairing record (`connect.library.pairing_of`: hato's, else a source folder's origin row), {} with
    none (no record, or no store: a 2.x library), or None when the store is there but can't be read just now."""
    from app import library_store, path_utils
    from app.connect import library
    data_dir = path_utils.get_data_path(language)
    try:
        # the mode is probed once (R2-5): a store that turns read-only between two probes never reads as a 2.x library
        mode = library_store.check_mode(language, data_dir, busy_wait=0.0)[0]
        if mode != "store":
            return None if mode == "read-only" else {}
        store = library_store.open_store(language, data_dir, path_utils.get_user_files_path(language), role="reader")
        if store is None:
            return None                     # a store, not ready since the probe: can't be read just now
        with store:
            record = library.pairing_of(store, item_id)
    except Exception as e:
        print(f"Play: the episode's pairing couldn't be read ({e!r})")
        return None
    return record if isinstance(record, dict) else {}


def _index_find(language, names, size=None):
    """Connect's video index, as last saved (`videos.Index.find` with no refresh: nothing listed, nothing written)."""
    from app.connect import videos
    try:
        return videos.Index(language).find(names, size)
    except Exception as e:
        print(f"Play: Connect's video index couldn't be read ({e!r})")
        return None


def _reachable(path):
    """Whether the folder holding `path` is there (one stat): an original's that isn't is a share offline."""
    return os.path.isdir(os.path.dirname(path))


def to_open(language, item_id, rel_path, media):
    """-> (path, None), or (None, why: plain words for the bar's *Couldn't open X: why*)."""
    from app import path_utils
    from app.connect import runner, videos
    from app.services.view_rows import MEDIA_WORD
    rel = rel_path or ""
    path = os.path.join(path_utils.get_data_path(language), *rel.split("/")) if rel else None   # AD-5
    record = pairing(language, item_id)
    unread = record is None
    record = record or {}
    origin = record.get("origin") if record.get("producer") == "source" else None
    origin = origin if isinstance(origin, str) and os.path.isabs(origin) else None
    word = MEDIA_WORD.get(media, "video")
    if word in ("EPUB", "file"):
        book = origin and re.sub(r"#\d+$", "", origin)              # an EPUB's part (`<book>.epub#3`): the book
        if book and os.path.exists(book):
            return book, None
        if book and not _reachable(book):
            return None, WHY["unreachable"]                         # never the copy in its place, unsaid (R2-6)
        if path and os.path.exists(path):
            return path, None
        return None, WHY["unreadable" if unread else "not-on-disk"]
    named = record.get("video_path")
    if isinstance(named, str) and os.path.isabs(named):             # AD-4: a relative one is no pairing here
        found = runner.paired_video(record, lambda names, size: _index_find(language, names, size))
        if found:
            return found, None
        return None, WHY["no-media"].format(word=word) if _reachable(named) else WHY["unreachable"]
    exts = AUDIO_EXTS if word == "audio" else None
    unreachable = False
    for p in (path, origin):
        if not p:
            continue
        found = runner.beside(p, exts, unlisted=_UNLISTED)
        if found is _UNLISTED:
            unreachable = unreachable or p is origin    # the copy's folder not there: nothing beside it
        elif found:
            return found, None
    if word == "video":
        found = _index_find(language, [n for p in (path, origin) if p for n in videos.names_for(p)])
        if found:
            return found, None
    if unreachable:
        return None, WHY["unreachable"]
    return None, WHY["unreadable"] if unread else WHY["no-media"].format(word=word)
