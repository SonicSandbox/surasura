"""*Link…* (P4.1 row 4.1.9L; ✅ P4.1-1, Sonic 2026-10-15: "Yes build link in 3.0"): the user points an episode whose
video Connect can't find (*No video*) at its video, and Surasura writes the pairing hato would have — through the
store's own `register` on the existing item, so it is one undoable command of the store's, never a new item and never
a move.

- `record(video_path, subtitle_path, language)` -> the pairing record Surasura writes for the episode (09-hato-layer
  §1's fields Connect reads: `schema` 1, `producer` `surasura`, `video_path`, `video_size`, `content_key` =
  `videos.content_key(video)`, the library copy's `subtitle_sha256`). **No `verdict`:** Connect's fit check asks
  tsubasa, as for any episode you placed yourself; no tsubasa, or not timed → *Needs you*'s *Mine anyway*.
- `link(store, item_id, video_path)` -> the store's change (the window's undo keeps it). Refused (`Refused`, its
  reason in plain words, nothing written): a file that isn't there, a cloud placeholder (never read: RD-S1), a file
  that isn't a video (`runner.VIDEO_EXTENSIONS`), one whose bytes can't be read whole now, an item that isn't in the
  library, and a video hato has already paired — **hato's record is never written over** (the intent keeper's S6):
  the user's link lives beside hato's, never on its content key.

A second link replaces the first for Connect (`library.pairing_of`: the newest pairing wins). `runner.Steps.video`
finds the video by the record's `video_path` as it finds hato's; one renamed or moved since is *No video* again unless
the video index finds the same bytes. The caller (the window's writer, on its worker) kicks Connect after
(`kick.kick`): the item's job waiting on *No video* is looked at again at the next run.

Light (02 §5): the standard library, `videos` and the runner's names; the store is the caller's.
"""
import hashlib
import json
import os

PRODUCER = "surasura"


class Refused(ValueError):
    """The link wasn't written: `str(e)` says why, in plain words."""


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(video_path, subtitle_path, language):
    """The pairing record for `subtitle_path` (the library's copy, absolute) and `video_path` -> a dict. Raises
    `Refused` for a video that can't be linked (see `link`)."""
    from app.connect import runner, videos
    video_path = os.path.abspath(video_path)
    if os.path.splitext(video_path)[1].lower() not in runner.VIDEO_EXTENSIONS:
        raise Refused("That file isn't a video Connect can make cards from.")
    if not os.path.isfile(video_path):
        raise Refused("That video isn't there any more.")
    if not runner._on_disk(video_path):
        raise Refused("That video is still in the cloud: download it first, then link it.")
    key = videos.content_key(video_path)
    if key is None:
        raise Refused("That video can't be read just now (still being copied?). Try again in a moment.")
    try:
        sha = _sha256(subtitle_path)
    except OSError:
        raise Refused("The episode's subtitle in your library can't be read just now.") from None
    return {"schema": 1, "content_key": key, "producer": PRODUCER, "language": language, "video_path": video_path,
            "video_size": os.path.getsize(video_path), "library_path": os.path.abspath(subtitle_path),
            "subtitle_sha256": sha}


def link(store, item_id, video_path):
    """The item's video, linked: its pairing written by the store's `register` on the existing item (lands
    `already`; one undoable command) -> the store's change (None when the same link is there already). Raises
    `Refused` (nothing written)."""
    item = store.item(item_id)
    if item is None or not item.get("rel_path"):
        raise Refused("That episode isn't in your library any more.")
    subtitle = os.path.join(store.data_dir, *str(item["rel_path"]).replace("\\", "/").split("/"))
    rec = record(video_path, subtitle, store.language)
    row = store.conn.execute("SELECT item_id, pairing FROM pairings WHERE content_key = ?",
                             (rec["content_key"],)).fetchone()
    if row is not None:
        try:
            producer = (json.loads(row[1]) or {}).get("producer")
        except (ValueError, AttributeError):
            producer = None
        if producer != PRODUCER:
            # hato's own record for this video: kept as hato wrote it (S6), whichever episode it names
            raise Refused("hato has already paired that video with an episode, so Surasura leaves its pairing as it "
                          "is. If hato picked the wrong one, fix it in hato.")
    return store.register(subtitle, rec)
