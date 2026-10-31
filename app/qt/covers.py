"""Covers in the window (W3.2 Q6; RUNBOOK §1 *Covers* and *The opened row*, §3, §5a IK-7; the window's spec 01 §1.3):
a title's own picture — art beside its files, an EPUB's cover, the user's chosen image (`app/services/covers.py` finds
and records them) — painted wherever the window shows a cover, the generated cover meanwhile and whenever there is none.

- **`pixmap_for(ref, title, w, h, dpr, shape, on_ready)`** — the one door (Current's rows and Up Next, Finished, Needs
  you, Goal's dock and wells, the opened row's standing cover; the tray and Goal's sheet call it too): the decoded
  picture when it is held, else the generated cover at once — and the decode asked for, `on_ready()` (and
  `notifier().ready(work_id)`) on the GUI thread once it lands, so only what shows that title is painted again (S19).
  `ref`: the view's `CoverRef` (work id, source, ref, path, locked) or None. `decoded(...)`: the same, None meanwhile.
- **Decoded off the GUI thread** (`bridge.run_in_worker`): the file read (≤ `services.covers.MAX_IMAGE`, a cloud
  placeholder never read), checked for a whole image (`services.covers.image_ext`), decoded by `QImageReader` straight
  to its size × the screen's ratio and shaped there (`QImage` + `QPainter`: never a `QPixmap` off the GUI thread); the
  GUI thread only wraps it (`QPixmap.fromImage`). **Never before the first frame** (`hold` / `release`, as the stones'
  sheet: a window holds until its first frame is flushed). **One decode per (work, its record, shape, size, ratio)**:
  asked again while it runs, it waits for the same answer; a broken or vanished image is remembered (the generated
  cover, quietly) until the record changes or `recheck()` runs.
- **Held by bytes** (`DISK_MB`, beside rows.py's generated covers and art: `COVERS_MB` + `ART_MB` + `DISK_MB` well inside
  the 64 MB budget), the oldest let go first; a disk cover read in place is held with its file's size and time, and
  `recheck()` (after each scan, on a worker) lets go of a picture whose file changed or went.
- **The disk scan** (`start_scan(opener, language, writer)`): `services.covers.scan` on a thread of its own after the
  first frame (and when another library opens), over the store's feed read on that thread — once per open; a new start
  cancels the one running. It records through the writer.
- **A title that arrives or changes while the window is open** (Hon a7, `follow(reader, language, writer)`): the
  reader names the works whose files arrived or changed (`LibraryReader.subscribe_arrived`: a folder read, + Add,
  Extract, a drop — books as shows, whatever the download switch says) and `look(opener, work_ids)` scans those
  titles only (`services.covers.works_for`), on a worker of its own, after the first frame — the same scan, one path.
- **Change cover…** (`cover_menu_entries(row)` → [(name, label, tip, callable)], for the ⋯ menu): *Choose an image…*
  (a file picker → `services.covers.keep_user_image` on a worker: copied into `User Files/<lang>/covers/`, the image it
  replaces kept dated — then recorded, locked, with its toast's Undo) and *Use a generated cover* (locked, Undo).
"""
import os
import sys
import threading
from collections import OrderedDict

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPixmap

from app import theme

DISK_MB = 16                    # the decoded pictures kept, by bytes (a row's cover ~50 KB at 250 %, a standing one ~0.4 MB)
SHAPES = ("row", "tile", "stack", "stand", "art")
#   row: a Finished row's or a Needs-you card's cover · tile: Up Next's · stack: Goal's hand and the wells' · stand: the
#   opened row's standing cover (each the picture filling its box, centred, its corners rounded) · art: a Current row's
#   wide strip (from `art-focus` down, its fade to nothing baked in, as `rows.art`)
_RADIUS = {"row": "cover-row", "tile": "cover-tile", "stack": "cover-stack", "stand": "cover-tile"}
SHOWN = ("file", "user", "anilist", "tmdb", "youtube")      # the record's sources that name a picture

_held = OrderedDict()           # key -> (QPixmap, path, stat)
_bytes = [0]
_running = {}                   # key -> [one-shot callbacks]
_broken = set()                 # keys whose picture couldn't be read (the generated cover, until it changes)
_HELD = set()                   # windows whose first frame hasn't come yet: no decode starts
_DEFERRED = []                  # keys asked for meanwhile, (key, job) — started at the release
_where = {"language": "ja", "data_dir": None}
_library = {"writer": None, "window": None, "moves": None}
_scan = {"cancel": None, "thread": None}
_look = {"opener": None, "language": None, "writer": None, "pending": {}, "every": False, "missed": None,
         "thread": None, "cancel": threading.Event()}   # Hon a7: the titles that arrived mid-session, in the order told
LOOK_TRIES = 3                  # a scan or a look the store couldn't take (busy, not open) is tried this often ...
LOOK_RETRY_S = 0.5              # ... after this long, then twice that
_look_lock = threading.Lock()
_notifier = []
decodes = [0]                   # pictures decoded (tests: one per key)


class _Notifier(QObject):
    ready = pyqtSignal(object)                  # a work id: its picture landed (or was let go) — repaint what shows it
    scanned = pyqtSignal(object)                # (the scan's cancel token, covers handed on): a scan ended


def notifier():
    """The object whose `ready(work_id)` says a title's picture changed (made on the GUI thread at its first use)."""
    if not _notifier:
        n = _Notifier()
        n.scanned.connect(_scanned)
        _notifier.append(n)
    return _notifier[0]


def held_bytes():
    return _bytes[0]


def use_library(language, data_dir=None, writer=None, window=None, moves=None):
    """The library the window shows (its language, its data folder — the opener's — and its writer; `moves`: the drag
    controller, whose toasts carry Undo). GUI thread."""
    if (language, data_dir) != (_where["language"], _where["data_dir"]):
        clear(keep_holds=True)
    _where.update(language=language or "ja", data_dir=data_dir)
    _library.update(writer=writer, window=window, moves=moves)


def hold(token):
    """A window not yet past its first frame holds every decode back — `release(token)` once its first frame is flushed
    (the shell's `first_frame`), or when it goes. GUI thread."""
    _HELD.add(token)


def release(token):
    _HELD.discard(token)
    if _HELD:
        return
    while _DEFERRED:
        key, job = _DEFERRED.pop(0)
        if key in _running:
            _start(key, job)
    if _look["pending"] or _look["every"]:      # Hon a7: the titles that arrived meanwhile
        look(_look["opener"], ())
    if _online["pending"]:                      # --- W3.2 L3: the online asks held back meanwhile
        _flush_soon()


def clear(keep_holds=False):
    """Everything held let go (tests; another library). A decode still running lands into nothing."""
    _held.clear()
    _bytes[0] = 0
    _running.clear()
    _broken.clear()
    _DEFERRED.clear()
    if not keep_holds:
        _HELD.clear()


# --- the door --------------------------------------------------------------------------------------------------- #
def showable(ref):
    """Whether a cover record names a picture (the user's, a cache file, art beside the files) — else the generated
    cover, with nothing to decode."""
    if not ref:
        return False
    _work, source, rel, path, *_rest = tuple(ref)
    return source in SHOWN and bool(path or (source == "file" and rel))


def _key(ref, shape, w, h, dpr):
    work, source, rel, path, *_rest = tuple(ref)
    return (work, source, rel, path, shape, int(w), int(h), round(float(dpr), 3))


def decoded(ref, w, h, dpr, shape="row", on_ready=None):
    """The title's own picture at (w × h, dpr) in `shape`, or None — the generated cover is the caller's meanwhile
    (the decode is asked for; `on_ready()` runs once on the GUI thread when it lands). GUI thread."""
    if ref is not None and _online["fetcher"] is not None:      # --- W3.2 L3: a title first painted is asked online
        ask((ref,))
    if not showable(ref) or w <= 0 or h <= 0:
        return None
    key = _key(ref, shape, w, h, dpr)
    hit = _held.get(key)
    if hit is not None:
        _held.move_to_end(key)
        return hit[0]
    if key in _broken:
        return None
    notifier()
    if key in _running:
        if on_ready is not None:
            _running[key].append(on_ready)
        return None
    _running[key] = [on_ready] if on_ready is not None else []
    from app.qt import rows                     # (the art's fade in rows.art's colours: the theme's, made here)
    job = (tuple(ref), shape, int(w), int(h), float(dpr), _where["language"], _where["data_dir"],
           theme.RADII[_RADIUS[shape]] if shape in _RADIUS else 0, theme.ROW_LINE["art-focus"],
           theme.ROW_LINE["art-fade"], (rows.faded("shadow", 1.0), rows.faded("shadow", 0.0)))
    if _HELD:
        _DEFERRED.append((key, job))            # never inside the first frame: started at its release
    else:
        _start(key, job)
    return None


def pixmap_for(ref, title, w, h, dpr, shape="row", on_ready=None):
    """The shared door: the title's own picture when decoded, else its generated cover at once (`rows.cover` / `rows.art`;
    the decode asked for, `on_ready()` when it lands). GUI thread."""
    pix = decoded(ref, w, h, dpr, shape, on_ready)
    if pix is not None:
        return pix
    from app.qt import rows
    if shape == "art":
        return rows.art(title, w, h, dpr)
    return rows.cover(title, w, h, dpr, large=shape in ("tile", "stand"))


def _start(key, job):
    from app.qt import bridge
    bridge.run_in_worker(decode, *job, then=lambda out, key=key: _landed(key, out),
                         failed=lambda info, key=key: _landed(key, None))


def _landed(key, out):
    waiting = _running.pop(key, None)
    if waiting is None:
        return                                  # let go meanwhile (`clear`: another library)
    if out is None:
        _broken.add(key)
        if key[1] in ("anilist", "youtube") and str(key[3] or "").startswith("cache:") and _online["fetcher"]:
            ask((key[:4] + (False,),), gone=True)   # --- W3.2 L3 S3 / S4: its downloaded file went: asked again
    else:
        image, path, stat = out
        pix = QPixmap.fromImage(image)
        pix.setDevicePixelRatio(image.devicePixelRatio())
        _held[key] = (pix, path, stat)
        _bytes[0] += _size(pix)
        while len(_held) > 1 and _bytes[0] > DISK_MB * 1024 * 1024:
            _bytes[0] -= _size(_held.popitem(last=False)[1][0])
        for cb in waiting:
            if cb is not None:
                cb()
        notifier().ready.emit(key[0])


def _size(pix):
    return pix.width() * pix.height() * 4


# --- the worker's half ------------------------------------------------------------------------------------------ #
def _file_of(ref, language, data_dir):
    from app.services import covers as disk
    work, source, rel, path, *rest = ref
    return disk.image_path(language, disk.Work(work, (), source, rel, path, bool(rest and rest[0])), data_dir)


def decode(ref, shape, w, h, dpr, language, data_dir, radius, focus, fade, ink):
    """(A worker.) -> (QImage at w × h × dpr in `shape`, its file, (size, mtime_ns)), or None: no file, a placeholder,
    too big, broken, not an image."""
    from app.services import covers as disk
    decodes[0] += 1
    path = _file_of(ref, language, data_dir)
    if path is None or not disk.on_disk(path):
        return None
    try:
        st = os.stat(path)
        if st.st_size > disk.MAX_IMAGE:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if disk.image_ext(data) is None:
        return None
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    reader.setAutoTransform(True)
    src = reader.size()
    W, H = max(1, round(w * dpr)), max(1, round(h * dpr))
    if not src.isValid() or src.width() <= 0 or src.height() <= 0:
        img = reader.read()
        if img.isNull():
            return None
        src = img.size()
    else:
        img = None
    scale = max(W / src.width(), H / src.height())          # the picture fills its box (cropped, never stretched)
    sw, sh = max(1, round(src.width() * scale)), max(1, round(src.height() * scale))
    if img is None:
        reader.setScaledSize(QSize(sw, sh))
        img = reader.read()
        if img.isNull():
            return None
    elif img.size() != QSize(sw, sh):
        img = img.scaled(sw, sh, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    x = (W - sw) / 2
    if shape == "art":                                      # a strip from `art-focus` down, faded out at its right
        p.drawImage(QRectF(x, -round((sh - H) * focus), sw, sh), img)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        g = QLinearGradient(0, 0, W, 0)
        g.setColorAt(0, ink[0])
        g.setColorAt(fade, ink[0])
        g.setColorAt(1, ink[1])
        p.fillRect(QRectF(0, 0, W, H), g)
    else:
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, W, H), radius * dpr, radius * dpr)
        p.setClipPath(clip)
        p.drawImage(QRectF(x, (H - sh) / 2, sw, sh), img)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out, path, (st.st_size, st.st_mtime_ns)


def recheck():
    """(GUI thread.) The pictures held whose files changed or went (a poster replaced in place, a file deleted) are
    let go, found on a worker; a broken one is tried again at its next paint."""
    _broken.clear()
    files = [(key, path, stat) for key, (_pix, path, stat) in _held.items()]
    if not files:
        return
    from app.qt import bridge
    bridge.run_in_worker(_stale, files, then=_let_go)


def _stale(files):
    out = []
    for key, path, stat in files:
        try:
            st = os.stat(path)
            if (st.st_size, st.st_mtime_ns) == stat:
                continue
        except OSError:
            pass
        out.append(key)
    return out


def _let_go(keys):
    works = set()
    for key in keys:
        hit = _held.pop(key, None)
        if hit is not None:
            _bytes[0] -= _size(hit[0])
            works.add(key[0])
    for work in works:
        notifier().ready.emit(work)


# --- the disk scan ---------------------------------------------------------------------------------------------- #
def start_scan(opener, language, writer, progress=None, then=None):
    """(GUI thread.) The library's covers from disk (`services.covers.scan`) on a thread of its own, over the store's
    feed read there; the one running is cancelled. A store it can't open (busy) is tried `LOOK_TRIES` times; one not
    there yet (a migration, setup's first library) leaves the scan to the reader's first read (Hon a7: `look(opener,
    None)`). `progress(done, total)` / `then(found)`: on that thread (setup's load screen). -> the thread (tests join
    it), or None (nothing to write with)."""
    if opener is None or writer is None:
        return None
    old = _scan["cancel"]
    if old is not None:
        old.set()
    cancel = threading.Event()
    n = notifier()
    data_dir = getattr(opener, "data_dir", None)

    def run():
        found = 0
        try:
            for tries in range(1, LOOK_TRIES + 1):
                found = _scan_library(opener, language, writer, cancel, data_dir, progress=progress)
                if found is not None or tries == LOOK_TRIES or cancel.wait(LOOK_RETRY_S * tries):
                    break
            if found is None and not cancel.is_set():
                with _look_lock:
                    _look["missed"] = opener        # the reader's first read of it scans it (`look`)
        except Exception as e:                  # never in the window's way: the generated covers stay
            print(f"Covers: the scan stopped: {e!r}")
        finally:
            if then is not None:
                try:
                    then(found or 0)
                except Exception as e:
                    print(f"Covers: the scan's listener failed: {e!r}")
            try:
                n.scanned.emit((cancel, found or 0))
            except RuntimeError:
                pass
    t = threading.Thread(target=run, name=f"window-covers-scan-{language}", daemon=True)
    _scan.update(cancel=cancel, thread=t)
    t.start()
    return t


def _scan_library(opener, language, writer, cancel, data_dir, work_ids=None, progress=None):
    """The library's works (`work_ids` None: the open's scan), else those works only, on this thread's handle -> the
    covers handed on, or None when the store couldn't be opened."""
    h = opener.handle()
    if h is None:
        return None
    try:
        return _scan_works(h, language, writer, cancel, data_dir, work_ids, progress)
    finally:
        _close(opener, h)


def _scan_works(h, language, writer, cancel, data_dir, work_ids=None, progress=None):
    from app.services import covers as disk
    if work_ids is None:
        feed = h.read_feed()
        works = disk.works_from(feed["items"], feed["works"], disk.originals(h))     # Hon a6: beside the originals too
    else:
        works = disk.works_for(h, work_ids)                                         # Hon a7: those titles only
    return disk.scan(language, works, writer, cancel=cancel.is_set, data_dir=data_dir, progress=progress)


def _close(opener, h):
    close = getattr(opener, "close", None)       # this thread's handle (a store handle belongs to its thread)
    if close is not None:
        close()
    elif hasattr(h, "close"):
        h.close()


def stop_scan():
    if _scan["cancel"] is not None:
        _scan["cancel"].set()
    _look["cancel"].set()                       # Hon a7: and the arrivals' look, between titles


# --- Hon a7: a title that arrives or changes while the window is open ---------------------------------------------- #
def follow(reader, language, writer):
    """(GUI thread.) The covers of the titles whose files arrive or change from now on in `reader`'s library
    (`subscribe_arrived`), recorded through `writer`; the library left's looks are let go (a `stop_scan` ended its
    worker). A reader without the call (a test's) follows nothing."""
    opener = getattr(reader, "opener", None)
    with _look_lock:
        _look.update(opener=opener, language=language, writer=writer, pending={}, every=False, missed=None,
                     thread=None, cancel=threading.Event())     # (the library left's worker ends by its own cancel)
    subscribe = getattr(reader, "subscribe_arrived", None)
    if subscribe is not None and opener is not None and writer is not None:
        subscribe(lambda work_ids: look(opener, work_ids))


def look(opener, work_ids):
    """(Any thread: the reader's.) These titles' covers from disk (`_scan_works(..., work_ids)`) on the looks' worker —
    started now unless one runs (it takes them next) or no first frame is out yet (`release` starts it). `work_ids`
    None: the reader's first read — the whole library, only when the open's scan found no store to read (`missed`).
    Nothing for another library than the one followed, nor after `stop_scan`. -> the worker started, or None."""
    with _look_lock:
        if opener is None or opener is not _look["opener"] or _look["writer"] is None or _look["cancel"].is_set():
            return None
        if work_ids is None:
            if _look["missed"] is opener:
                _look["missed"], _look["every"] = None, True
        else:
            for w in work_ids:
                _look["pending"][w] = None
        if not (_look["pending"] or _look["every"]) or _look["thread"] is not None or _HELD:
            return None
        t = _look["thread"] = threading.Thread(target=_looking, args=(opener, _look["language"], _look["writer"],
                                                                      _look["cancel"]),
                                               name=f"window-covers-look-{_look['language']}", daemon=True)
    t.start()
    return t


def _looking(opener, language, writer, cancel):
    """(The looks' worker.) What was told, a batch at a time on one handle, until nothing is left (or `cancel`): each
    title once however often it was told meanwhile. A batch the store couldn't take (busy, not open) is put back and
    tried again, `LOOK_TRIES` times in all, then left for the title's next change or the next open."""
    me = threading.current_thread()
    data_dir = getattr(opener, "data_dir", None)
    h, tries = None, 0
    try:
        while not cancel.is_set():
            with _look_lock:
                mine = _look["opener"] is opener
                every = mine and _look["every"]
                ids = list(_look["pending"]) if mine else []
                if not ids and not every:       # let go under the lock: a title told from now on starts a worker
                    if _look["thread"] is me:
                        _look["thread"] = None
                    return
                _look["pending"].clear()
                _look["every"] = False
            try:
                if h is None:
                    h = opener.handle()
                if h is None:
                    raise LookupError("the store couldn't be opened")
                _scan_works(h, language, writer, cancel, data_dir, None if every else ids)
                tries = 0
            except Exception as e:              # never in the window's way: the generated covers stay meanwhile
                if h is not None:
                    _close(opener, h)
                    h = None
                tries += 1
                if tries >= LOOK_TRIES:
                    what = "the library" if every else f"{len(ids)} titles"
                    print(f"Covers: the look at {what} stopped: {e!r}")
                    tries = 0
                    continue
                with _look_lock:
                    if _look["opener"] is opener:
                        for w in ids:
                            _look["pending"].setdefault(w, None)
                        _look["every"] = _look["every"] or every
                cancel.wait(LOOK_RETRY_S * tries)
    finally:
        if h is not None:
            _close(opener, h)
        with _look_lock:
            if _look["thread"] is me:
                _look["thread"] = None


def _scanned(result):
    cancel, _found = result
    if cancel is _scan["cancel"]:
        _scan["thread"] = None
    recheck()                                   # a poster replaced in place shows (its record didn't change)


# --- Change cover… (the ⋯ menu's entries; Q8 draws the menu) -------------------------------------------------------- #
def cover_menu_entries(row):
    """[(name, label, tip, callable)] for a row's *Change cover…* (`row`: a view row with `work_id`, `cover_title` and
    its `cover`): *Choose an image…* and *Use a generated cover* — none without a work or a writer that can write."""
    from app.qt import strings
    writer = _library["writer"]
    work = getattr(row, "work_id", None)
    if work is None or writer is None:
        return []
    out = [("cover-choose", *strings.COVER_MENU["choose"], lambda: choose_image(row))]
    ref = getattr(row, "cover", None)
    if not (ref and tuple(ref)[1] == "generated" and tuple(ref)[4]):         # not already the generated one, kept
        out.append(("cover-generated", *strings.COVER_MENU["generated"], lambda: use_generated(row)))
    return out


def choose_image(row, path=None):
    """*Choose an image…*: a file picker (or `path`, tests), then the copy and its dated backup on a worker
    (`keep_user_image`), then the record — locked — handed to the writer with its toast's Undo. GUI thread."""
    from app.qt import strings
    window, writer = _library["window"], _library["writer"]
    if writer is None or not writer.can_write():
        _say(strings.COVER_CANT)
        return False
    if path is None:
        from PyQt6.QtWidgets import QFileDialog
        path, _filter = QFileDialog.getOpenFileName(window, strings.COVER_PICK_TITLE, "", strings.COVER_PICK_FILTER)
        if not path:
            return False
    from app.qt import press as qpress
    from app.services import covers as disk
    deferred = _Deferred(writer)
    current = tuple(row.cover)[3] if getattr(row, "cover", None) else None
    title = getattr(row, "cover_title", None) or getattr(row, "title", "")

    def done(kept):
        if not kept or deferred.call is None:
            _say(strings.COVER_NOT_IMAGE)
            return
        args, kw = deferred.call
        _give(strings.COVER_CHOSEN.format(title=title), row,
              lambda label: writer.set_cover(*args, label=label, **kw))
    qpress.run(None, ("cover-choose", row.work_id), disk.keep_user_image, _where["language"], row.work_id, path,
               deferred, current, then=done, failed=lambda _info: _say(strings.COVER_NOT_IMAGE), win=window,
               at=_mark(row))                         # round 8 row 45: its cover turns while the image is copied
    return True


def _mark(row):
    """What a cover's press marks (round 8 row 45, IK-2): the row's cover in the list on screen (`press.row_mark`),
    else — not on that list, no list — the bar's arc."""
    from app.qt import press as qpress
    window = _library["window"]
    episodes = getattr(row, "episodes", None) or ()
    pages = getattr(window, "page_widgets", None) or {}
    current = getattr(window, "current_tab", None)
    lst = getattr(pages.get(current()) if callable(current) else None, "list", None)
    if not episodes or not hasattr(lst, "mark_ids"):
        return None
    return qpress.row_mark(lst, [episodes[0].id], "cover")


def use_generated(row):
    """*Use a generated cover*: the generated cover, locked (a picture found later never replaces it), with Undo."""
    from app.qt import strings
    writer = _library["writer"]
    if writer is None or not writer.can_write():
        _say(strings.COVER_CANT)
        return False
    title = getattr(row, "cover_title", None) or getattr(row, "title", "")
    _give(strings.COVER_GENERATED.format(title=title), row,
          lambda label: writer.set_cover(row.work_id, "generated", locked=True, label=label))
    return True


class _Deferred:
    """`keep_user_image`'s writer on the worker: the copy and the backup happen there, the record is handed back to the
    window's thread (its toast and Undo are the window's)."""

    def __init__(self, writer):
        self.writer = writer
        self.call = None

    def can_write(self):
        return self.writer.can_write()

    def set_cover(self, *args, **kw):
        self.call = (args, kw)
        return 0


def _give(text, row, command):
    moves = _library["moves"]
    if moves is not None:
        from app.qt import drag
        moves._give(drag.Ticket(text, (getattr(row, "key", None),)), command)
    else:
        command(None)


def _say(text):
    window = _library["window"]
    say = getattr(window, "say", None)
    if say is not None:
        say(text)


# --- W3.2 L3: online covers asked for what the window shows, and Change cover…'s online entries ---------------------- #
# The shell makes Q7's `covers_online.Fetcher` with the library (`use_fetcher`; again at a library / language switch,
# stopped at close). A title is asked when it first paints here (`decoded`: rows, Up Next, Goal's dock and wells, the
# sheet, the tray) or arrives (the shell's `_show_arrivals`) — once a session, never a sweep; with `covers_download`
# off nothing is kept and nothing read (asked again at its next paint once it is on). Its row read (`resolve`: the
# store's rows of those works only, `covers_online.wants_for`) and the hand-on run on a worker; the fetcher's own
# thread does the rest, and a cover it records repaints through the reader's next view.
_online = {"fetcher": None, "resolve": None, "asked": set(), "pending": set(), "flushing": False, "menu": None}
asked_online = [0]              # tests: the titles handed to the fetcher's `want`


def use_fetcher(fetcher, resolve=None):
    """(GUI thread.) The library's fetcher, or None, and `resolve(work_ids) -> [Want]` (a worker's: the store read)."""
    _online.update(fetcher=fetcher, resolve=resolve, asked=set(), pending=set(), menu=None)


def fetcher():
    return _online["fetcher"]


def ask_again():
    """(GUI thread.) Every title may be asked again (after *Remove downloaded covers*: refetched while the switch is on)."""
    _online["asked"] = set()


def resolver(opener):
    """`resolve` over the library's opener: this worker's handle, read, then closed (a handle belongs to its thread)."""
    def resolve(work_ids):
        from app.services import covers_online
        h = opener.handle() if opener is not None else None
        if h is None:
            return []
        try:
            return covers_online.wants_for(h, work_ids)
        finally:
            opener.close()
    return resolve


def _askable(ref, gone=False):
    """What the cover record alone says: no cover, an unlocked generated one, or an online one whose file went (no
    path; or `gone`: the decoder found its cache file missing — the fetcher checks again on its worker)."""
    _w, source, _rel, path, locked = tuple(ref)[:5]
    return not locked and (source in (None, "generated") or (source in ("anilist", "youtube") and (not path or gone)))


def ask(refs, gone=False):
    """(GUI thread.) These titles' covers asked online — each once a session; nothing while the switch is off.
    -> how many were newly asked."""
    f = _online["fetcher"]
    if f is None or _online["resolve"] is None:
        return 0
    asked = _online["asked"]
    new = []
    for ref in refs:
        if ref is None or tuple(ref)[0] is None or tuple(ref)[0] in asked or not _askable(ref, gone):
            continue
        new.append(tuple(ref)[0])
    if not new or not f.on():
        return 0
    asked.update(new)
    _online["pending"].update(new)
    _flush_soon()
    return len(new)


def _flush_soon():
    if not _online["flushing"]:
        _online["flushing"] = True
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, _flush)


def _flush():
    _online["flushing"] = False
    f, resolve = _online["fetcher"], _online["resolve"]
    if _HELD or f is None or resolve is None or not _online["pending"]:
        return                                  # held: the release flushes
    ids, _online["pending"] = sorted(_online["pending"]), set()
    from app.qt import bridge
    bridge.run_in_worker(_hand_on, f, resolve, ids,
                         failed=lambda info: print(f"Covers online: the titles couldn't be read: {info[1]}"))


def _hand_on(f, resolve, ids):
    """(A worker.) The works' rows read, handed to the fetcher (which asks the switch again)."""
    wants = resolve(ids)
    asked_online[0] += len(wants)
    return f.want(wants)


def _want_of(row):
    """A menu row's Want, from what the view holds (the candidates read its name; a pick its id and cover file)."""
    from app.services import covers_online
    ref = tuple(getattr(row, "cover", None) or (row.work_id, None, None, None, False))
    title = getattr(row, "cover_title", None) or getattr(row, "title", "")
    return covers_online.Want(row.work_id, title, None, None, None, None, ref[1], ref[2], ref[3], bool(ref[4]))


def change_cover_entries(row):
    """Every ⋯'s *Change cover…*: [(name, label, tip, callable)] — Q6's two, then, only with the fetcher and
    `covers_download` on, *Find it online…* (the top five candidates) and *Paste a link*."""
    from app.qt import strings
    out = cover_menu_entries(row)
    f = _online["fetcher"]
    if out and f is not None and f.on():
        out.append(("cover-online", *strings.COVER_ONLINE, lambda: find_online(row)))
        out.append(("cover-paste", *strings.COVER_PASTE, lambda: paste_link(row)))
    return out


def add_cover_menu(menu, row, writable=True, reason=None):
    """*Change cover…* as a submenu of `menu` (a tray's, a Goal tile's, Finished's ⋯), its entries' tips shown; greyed
    with the store's reason while it can't be written. -> the submenu, or None (nothing to offer)."""
    from PyQt6.QtGui import QAction
    from app.qt import strings
    entries = change_cover_entries(row)
    if not entries:
        return None
    sub = menu.addMenu(strings.ITEM_MENU["cover"][0])
    sub.setObjectName("rowmenu")
    sub.setToolTipsVisible(True)
    sub.menuAction().setToolTip(strings.ITEM_MENU["cover"][1] if writable else (reason or ""))
    sub.menuAction().setEnabled(writable)
    for _name, label, tip, call in entries:
        act = QAction(label, sub)
        act.setToolTip(tip if writable else (reason or tip))
        act.setEnabled(writable)
        act.triggered.connect(lambda _c=False, c=call: c())
        sub.addAction(act)
    return sub


def find_online(row, at=None):
    """*Find it online…*: a menu's press (`press.run`: the row's cover turns — IK-2, round 8 row 45 —, the hairline,
    and *Looking … up on AniList…* holds the bar from the click: a network wait worth naming), the top five candidates
    read on a worker, then a menu of them at the hand (`at`) — or *No cover found*, or *couldn't be reached* (a lookup
    that didn't answer is never "nothing found"). A pick is fetched and kept as the user's (locked, its toast's Undo).
    A second press while it looks does nothing."""
    from app.qt import press as qpress
    from app.qt import strings
    from app.services import covers_online
    f, writer = _online["fetcher"], _library["writer"]
    if f is None or writer is None or not writer.can_write():
        _say(strings.COVER_CANT)
        return False
    if not f.on():                                  # an instant answer needs no pending
        _say(strings.COVER_PASTE_WHY["off"])
        return False
    want = _want_of(row)
    if at is None:
        from PyQt6.QtGui import QCursor
        at = QCursor.pos()

    def found(answer):
        if _online["fetcher"] is not f:             # a library / language switch meanwhile: another library's covers
            return
        if answer is None:                          # switched off (or stopped) before AniList was asked
            _say(strings.COVER_PASTE_WHY["off"])
            return
        _offer(row, want, answer, at)

    def failed(info):
        if _online["fetcher"] is not f:
            return
        if isinstance(info[0] if info else None, covers_online.LookupFailed):
            _say(strings.COVER_LOOKUP_FAILED.format(title=want.title))
            return
        print(f"Find it online failed: {info[1] if info else ''}", file=sys.stderr)     # a fault: logged, said
        _say(strings.COVER_LOOKUP_BROKE.format(title=want.title, why=info[0] if info else ""))
    return qpress.run(None, ("cover-online", want.id), f.candidates, want,
                      busy=strings.COVER_LOOKING.format(title=want.title), win=_library["window"],
                      then=found, failed=failed, at=_mark(row)) is not None


def _offer(row, want, found, at):
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import QMenu
    from app.qt import strings
    if not found:
        _say(strings.COVER_NONE_FOUND.format(title=want.title))
        return None
    m = QMenu(_library["window"])
    m.setObjectName("rowmenu")
    m.setToolTipsVisible(True)
    m.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    for c in found:
        act = QAction(" · ".join(str(p) for p in (c.title, c.year, c.format) if p), m)
        act.setToolTip(strings.COVER_CANDIDATE_TIP.format(title=want.title))
        act.triggered.connect(lambda _c=False, cand=c: pick(row, want, cand))
        m.addAction(act)
    _online["menu"] = m
    m.popup(at)
    return m


def pick(row, want, candidate):
    """A candidate chosen: fetched on a worker and kept as the user's; its record given with a toast and Undo."""
    f = _online["fetcher"]
    return _kept(row, want, lambda deferred: f.pick(want, candidate, writer=deferred))


def paste_link(row, link=None):
    """*Paste a link*: the link copied (the clipboard's text, or `link`) — AniList, TMDB or YouTube only — fetched on
    a worker and kept as the user's (locked, Undo)."""
    from app.qt import strings
    from app.services import covers_online
    if link is None:
        from PyQt6.QtWidgets import QApplication
        link = QApplication.clipboard().text()
    link = (link or "").strip()
    f, want = _online["fetcher"], _want_of(row)
    why = "not_a_link" if covers_online.parse_link(link) is None else (f.refused(link) if f is not None else None)
    if why == "not_a_link":
        _say(strings.COVER_PASTE_NOT_A_LINK)
        return False
    if why is not None:                             # off / TMDB: answered at once, no pending (Sonic's rule)
        _say(strings.COVER_PASTE_WHY[why])
        return False

    def fetch(deferred):
        path, why = f.paste(want, link, writer=deferred)
        return path if path else why
    return _kept(row, want, fetch)


def _kept(row, want, fetch):
    from app.qt import press as qpress
    from app.qt import strings
    writer = _library["writer"]
    if _online["fetcher"] is None or writer is None or not writer.can_write():
        _say(strings.COVER_CANT)
        return False
    deferred = _Deferred(writer)

    f = _online["fetcher"]

    def done(answer):
        if _online["fetcher"] is not f or _library["writer"] is not writer:
            return                                  # a library / language switch meanwhile: kept nowhere, said nowhere
        if deferred.call is None:
            _say(strings.COVER_PASTE_WHY[answer if answer in strings.COVER_PASTE_WHY else "failed"])
            return
        args, kw = deferred.call
        _give(strings.COVER_CHOSEN.format(title=want.title), row,
              lambda label: writer.set_cover(*args, label=label, **kw))
    return qpress.run(None, ("cover-fetch", want.id), fetch, deferred, win=_library["window"],
                      busy=strings.COVER_FETCHING.format(title=want.title), then=done,
                      failed=lambda _info: done(None), at=_mark(row)) is not None
# --- end W3.2 L3
