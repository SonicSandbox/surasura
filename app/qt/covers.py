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
- **Change cover…** (`cover_menu_entries(row)` → [(name, label, tip, callable)], for the ⋯ menu): *Choose an image…*
  (a file picker → `services.covers.keep_user_image` on a worker: copied into `User Files/<lang>/covers/`, the image it
  replaces kept dated — then recorded, locked, with its toast's Undo) and *Use a generated cover* (locked, Undo).
"""
import os
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
def start_scan(opener, language, writer):
    """(GUI thread.) The library's covers from disk (`services.covers.scan`) on a thread of its own, over the store's
    feed read there; the one running is cancelled. -> the thread (tests join it), or None (nothing to write with)."""
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
            found = _scan_library(opener, language, writer, cancel, data_dir)
        except Exception as e:                  # never in the window's way: the generated covers stay
            print(f"Covers: the scan stopped: {e!r}")
        finally:
            try:
                n.scanned.emit((cancel, found))
            except RuntimeError:
                pass
    t = threading.Thread(target=run, name=f"window-covers-scan-{language}", daemon=True)
    _scan.update(cancel=cancel, thread=t)
    t.start()
    return t


def _scan_library(opener, language, writer, cancel, data_dir):
    from app.services import covers as disk
    h = opener.handle()
    if h is None:
        return 0
    try:
        feed = h.read_feed()
        works = disk.works_from(feed["items"], feed["works"])
        return disk.scan(language, works, writer, cancel=cancel.is_set, data_dir=data_dir)
    finally:
        close = getattr(opener, "close", None)       # this thread's handle (a store handle belongs to its thread)
        if close is not None:
            close()
        elif hasattr(h, "close"):
            h.close()


def stop_scan():
    if _scan["cancel"] is not None:
        _scan["cancel"].set()


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
    from app.qt import bridge
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
    bridge.run_in_worker(disk.keep_user_image, _where["language"], row.work_id, path, deferred, current, then=done,
                         failed=lambda _info: _say(strings.COVER_NOT_IMAGE))
    return True


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
