"""The rest of Current's ⋯, the ✂ seam and drop-to-join (W3.2 Q8; RUNBOOK §5a IK-4; the window's spec 05 §5.4, A2 G3,
A3 `split`, 06 E4, E22).

⋯ on a Current row (and on Up Next) lists W3.1a's moves first (`drag.DragController.menu_entries`: *Up next* · *Soon* ·
*Goal* · *Finished* · *See it in your journey*), then:
- *Study its cards first* ↔ *Done with its cards* (`Writer.pin`, the row's `studying` the state shown);
- *What is it?* › the store's media types (`library_store.MEDIA_TYPES`), the row's own checked, and *Let Surasura tell*
  (`Writer.set_media_type` for its title; None goes back to the guess);
- *Split here…* (a part with 2+ files): on an opened row the hand was last on an episode of, after that episode; else a
  small list asks after which (`Writer.split`); the same split from the ✂ seam between two episodes of an opened row
  (`rows.RowsView.split_requested`);
- *Join with…* › the other parts of the same title the view holds (Current, Finished, New arrivals; next to it or not),
  each with its episodes and where it is (E22: the other part comes to this one — its section and place);
- *Change cover…* once Q6's `app/qt/covers.py` offers `cover_menu_entries(row)` (hook: `cover_entries`);
- *Never read this folder* › the row's folder and each one above it inside its source folder, deepest first (K6:
  asked on the looks' worker, added once it answers; none for a row from no folder being read): `Writer.skip_folder`
  with Undo;
- *Open its folder* (`windows.open_url`, N3; looked for on a worker);
- a separator, then *Remove…*: the one modal kind (`confirm.ask`, Esc / Back / a click outside are No) naming its
  files; `Writer.remove` (the trash, 30 days) with Undo.
**Drop-to-join (G3):** a part dragged over the middle of another part of the same title (its top and bottom 30 % stay
a move beside it, so a part can still be placed next to its other part): the rows hold still (no gap opens), that part
shows a green dashed outline and *Drop to join*; the drop joins them in episode order, opens the result and toasts
*Joined Ep x–y* with Undo.

**Episode order where the target is** (E22): the target part keeps its place; one `Writer.join` with the target first —
the other's files go after the target's last, or just before its first when they hold the earlier episodes (`ahead`).
A part from Finished comes back with its cards in the order, one from New arrivals is placed, in that same command
(W3.2 fix round, IK-L2-1): one toast, one Undo.

Every write goes through the window's writer (queued, journalled; W3.1a's `DragController._give` for the toast and
Undo) and is greyed with the store's reason while it can't be written (E4); nothing here reads or writes the store on the
window's thread.
"""
import os
from collections import namedtuple

from PyQt6.QtCore import QObject, QPoint
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from app import library_store
from app.qt import bridge, confirm, drag, finished, rows, strings, windows
from app.services import view_rows

JOIN_EDGE = 0.3                                     # a part's top and bottom 30 %: a move beside it, not a join

Entry = namedtuple("Entry", "name label tip ok children checked payload", defaults=(None, None, None))
Part = namedtuple("Part", "key piece_id ids numbers tier place title")
#   a part of a title as ⋯ and the drop see it: `ids` its files' item ids in order, `numbers` their episode numbers
#   (None where it has none), `tier` the store's, `place` its 1-based place in Current (None elsewhere)


def part_of(row, place=None):
    return Part(key=row.key, piece_id=row.piece_id, ids=tuple(e.id for e in row.episodes),
                numbers=tuple(e.number for e in row.episodes), tier=row.tier, place=place, title=row.title)


def range_text(*parts):
    """*Ep x–y* over the parts' files (every file numbered), else *N files*."""
    nums = [n for p in parts for n in p.numbers]
    if nums and all(n is not None for n in nums):
        lo, hi = min(nums), max(nums)
        return strings.ITEM_RANGE.format(a=lo, b=hi) if lo != hi else strings.ITEM_RANGE_ONE.format(a=lo)
    return strings.ITEM_RANGE_FILES.format(n=sum(len(p.ids) for p in parts))


def comes_first(part, target):
    """Whether `part`'s episodes come before `target`'s (by their first numbers; unnumbered: never)."""
    a = next((n for n in part.numbers if n is not None), None)
    b = next((n for n in target.numbers if n is not None), None)
    return a is not None and b is not None and a < b


def joinable(row):
    """A part that can be joined or split: a title's piece (hato's mix never)."""
    return row is not None and row.piece_id is not None and row.work_id is not None and not drag.is_mix(row)


class ItemActions(QObject):
    """Current's ⋯ (the whole menu now: the moves, then these), the ✂ seam's split and drop-to-join, on the window's
    thread. Made by the shell after the moves (`win.moves`)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.page = win.page_widgets["current"]
        self.lst = self.page.list
        self.page.on_menu = self.menu
        self.lst.split_requested.connect(self.split)
        win.moves.joins = self
        self.cover_entries = None                    # Q6: (row) -> [(label, tip, enabled, callback)] (*Change cover…*)
        try:
            from app.qt import covers                # (Q6's; absent until it lands)
            self.cover_entries = getattr(covers, "cover_menu_entries", None)
        except ImportError:
            pass
        # --- W3.2 L3: Q6's entries and, with Download covers on, Q7's online ones — in this hook's shape
        from app.qt import covers as qcovers
        self.cover_entries = lambda row: [(label, tip, True, call)
                                          for _name, label, tip, call in qcovers.change_cover_entries(row)]
        # --- end W3.2 L3
        self.last_menu = None
        self.question = None                         # *Remove…*'s confirmation while it is open

    # N3: the window's moves, writer and language read at call time (a language switch remakes them)
    @property
    def moves(self):
        return self.win.moves

    @property
    def writer(self):
        return self.win.services.writer

    @property
    def language(self):
        return self.win.language

    # --- the view's parts ------------------------------------------------------------------------------------------ #
    def _view(self):
        return self.page.view_model

    def other_parts(self, row):
        """The other parts of `row`'s title the view holds: [(Part, where)] — Current's in order, then Finished's, then
        New arrivals'."""
        view = self._view()
        if view is None or not joinable(row):
            return []
        out = []
        for n, r in enumerate(view.rows, 1):
            if r.key != row.key and r.work_id == row.work_id and joinable(r):
                out.append((part_of(r, n), strings.ITEM_JOIN_WHERE[r.tier if r.tier in ("now", "soon") else "now"]
                            .format(n=n)))
        for month in view.finished or ():
            for r in month.rows:
                if r.key != row.key and r.work_id == row.work_id and r.piece_id is not None:
                    out.append((part_of(r), strings.ITEM_JOIN_WHERE["graduated"]))
        for a in view.arrivals or ():
            if a.key != row.key and a.work_id == row.work_id and a.piece_id is not None:
                out.append((Part(key=a.key, piece_id=a.piece_id, ids=tuple(a.item_ids),
                                 numbers=tuple(_numbers(a)), tier="arrivals", place=None, title=a.title),
                            strings.ITEM_JOIN_WHERE["arrivals"]))
        return out

    def _row(self, key):
        view = self._view()
        return next((r for r in (view.rows if view is not None else ()) if r.key == key), None)

    # --- ⋯ ------------------------------------------------------------------------------------------------------------ #
    def entries(self, row):
        """These entries for `row`, in order (after the moves): [Entry] — *Remove…* last (the menu puts a separator
        before it)."""
        writable = self.writer.can_write()
        reason = None
        if not writable:
            raw = self.writer.reason() or ""
            reason = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)

        def entry(name, label=None, tip=None, writes=True, **kw):
            words, own_tip = strings.ITEM_MENU.get(name, (None, None))
            ok = writable or not writes
            return Entry(name, label or words, (tip or own_tip) if ok else reason, ok, **kw)
        out = [entry("unpin") if row.studying else entry("pin")]
        if row.work_id is not None:
            kinds = [entry("type-to", label=strings.ITEM_TYPES[m], tip=strings.ITEM_TYPE_TIP.format(
                kind=strings.ITEM_TYPES[m]), checked=row.media == m, payload=m) for m in library_store.MEDIA_TYPES]
            kinds.append(entry("type-to", label=strings.ITEM_TYPE_GUESS[0], tip=strings.ITEM_TYPE_GUESS[1],
                               checked=False, payload=None))
            out.append(entry("type", children=kinds))
        if joinable(row) and len(row.episodes) >= 2:
            after = self._hovered_after(row)
            cuts = [k for k in range(1, len(row.episodes)) if view_rows.split_piece(row, k) is not None]   # B2-2
            if after is not None and after in cuts:
                out.append(entry("split", label=strings.ITEM_SPLIT_HERE.format(ep=row.episodes[after - 1].label),
                                 tip=strings.ITEM_SPLIT_AFTER_TIP.format(ep=row.episodes[after - 1].label,
                                                                         rest=rows._rest_of(row, after)),
                                 payload=row.episodes[after]))
            elif cuts:
                out.append(entry("split", children=[
                    entry("split", label=strings.ITEM_SPLIT_AFTER.format(ep=row.episodes[k - 1].label),
                          tip=strings.ITEM_SPLIT_AFTER_TIP.format(ep=row.episodes[k - 1].label,
                                                                  rest=rows._rest_of(row, k)),
                          payload=row.episodes[k]) for k in cuts]))
        others = self.other_parts(row)
        if others:
            out.append(entry("join", children=[
                entry("join", label=strings.ITEM_JOIN_PART.format(range=range_text(p), where=where),
                      tip=strings.ITEM_JOIN_PART_TIP.format(range=range_text(p)), payload=p) for p, where in others]))
        covers = self.cover_entries(row) if self.cover_entries is not None else None
        if covers:
            out.append(entry("cover", children=[
                Entry("cover-to", label, tip if ok else reason, ok and writable, payload=cb)
                for label, tip, ok, cb in covers]))
        out.append(entry("folder", writes=False))
        out.append(entry("remove"))
        return out

    def _hovered_after(self, row):
        """The episode after the one the hand was last on in this opened row (where *Split here* splits), or None."""
        hover = self.lst.ep_hover
        if self.lst.model().open_key != row.key or hover is None or hover[0] != row.key:
            return None
        k = next((i for i, e in enumerate(row.episodes) if e.id == hover[1]), None)
        return k + 1 if k is not None and k + 1 < len(row.episodes) else None

    def menu(self, row, at):
        """⋯: the moves, these, a separator and *Remove…* — a plain menu in the theme's style (Esc closes it), every
        entry's tip shown."""
        m = drag.list_menu(self.lst, row.title)          # C4: the list's one menu, emptied as it hides
        for name, label, tip, ok in self.moves.menu_entries(row):
            act = QAction(label, m)
            act.setToolTip(tip)
            act.setEnabled(ok)
            act.triggered.connect(lambda _c=False, n=name: self.moves.menu_pick(row, n))
            m.addAction(act)
        for e in self.entries(row):
            if e.name == "remove":
                m.addSeparator()
            if e.children is not None:
                sub = m.addMenu(e.label)
                sub.setObjectName("rowmenu")
                sub.setToolTipsVisible(True)
                sub.menuAction().setToolTip(e.tip)
                sub.menuAction().setEnabled(e.ok and any(c.ok for c in e.children))
                for c in e.children:
                    self._action(sub, row, c)
                continue
            self._action(m, row, e)
        self.last_menu = m
        self._offer_skip(row, m)                     # K6: *Never read this folder*, once the looks' worker answers
        m.popup(at)
        return m

    def _action(self, menu, row, e):
        act = QAction(e.label, menu)
        act.setToolTip(e.tip)
        act.setEnabled(e.ok)
        if e.checked is not None:
            act.setCheckable(True)
            act.setChecked(e.checked)
        act.triggered.connect(lambda _c=False, n=e.name, pl=e.payload: self.menu_pick(row, n, pl))
        menu.addAction(act)
        return act

    def menu_pick(self, row, name, payload=None):
        if name in ("pin", "unpin"):
            self.pin(row, name == "pin")
        elif name == "type-to":
            self.set_type(row, payload)
        elif name == "split" and payload is not None:
            self.split(row, payload)
        elif name == "join" and payload is not None:
            self.join(part_of(row, self._place(row)), payload)
        elif name == "cover-to" and payload is not None:
            payload()
        elif name == "folder":
            self.open_folder(row)
        elif name == "remove":
            self.ask_remove(row)

    def _place(self, row):
        view = self._view()
        return next((n for n, r in enumerate(view.rows if view is not None else (), 1) if r.key == row.key), None)

    # --- the writes ------------------------------------------------------------------------------------------------- #
    def pin(self, row, on):
        """*Study its cards first* (on) ↔ *Done with its cards* (off)."""
        if self.moves.refused() is not None:
            return None
        ids = drag.ids_of(row)
        text = (strings.ITEM_PINNED if on else strings.ITEM_UNPINNED).format(title=row.title)
        return self.moves._give(drag.Ticket(text, (row.key,), ids), lambda t: self.writer.pin(ids, on, label=t))

    def set_type(self, row, media):
        """*What is it?*: the title's type (None: Surasura tells again)."""
        if row.work_id is None or self.moves.refused() is not None:
            return None
        text = strings.ITEM_TYPE_GUESSED.format(title=row.title) if media is None else \
            strings.ITEM_TYPE_DONE.format(title=row.title, kind=strings.ITEM_TYPES[media])
        work = row.work_id
        return self.moves._give(drag.Ticket(text, (row.key,), drag.ids_of(row)),
                                lambda t: self.writer.set_media_type([work], media, label=t))

    def split(self, row, ep):
        """✂ *Split here*: a new part from `ep` to the end of `ep`'s own piece (a show the Soon line runs through holds
        two: `view_rows.split_piece`); nothing moves. A split that would change nothing gives no toast and no Undo."""
        if not joinable(row) or self.moves.refused() is not None:
            return None
        k = next((i for i, e in enumerate(row.episodes) if e.id == ep.id), 0)
        at = view_rows.split_piece(row, k)
        if at is None:
            return None
        piece = at[0]
        text = strings.ITEM_SPLIT_DONE.format(title=row.title, rest=rows._rest_of(row, k))
        return self.moves._give(drag.Ticket(text, (row.key,), drag.ids_of(row)),
                                lambda t: self.writer.split(piece, ep.id, label=t))

    def join(self, target, other):
        """`other` joins `target` where the target is, in episode order (E22): one `Writer.join` with the target first —
        `ahead` when `other` holds the earlier episodes (they go just before the target's first file). A part from
        Finished comes back with its cards in the order, one from New arrivals is placed: the store's join does both in
        its one command (IK-L2-1), so one toast, one Undo, one Ctrl+Z. -> the key the result has (opened)."""
        if self.moves.refused() is not None:
            return None
        text = strings.ITEM_JOINED.format(range=range_text(target, other))
        pieces = [target.piece_id, other.piece_id]
        ahead = comes_first(other, target)
        if self.moves._give(drag.Ticket(text, (target.key,), target.ids + other.ids),
                            lambda t: self.writer.join(pieces, label=t, ahead=ahead)) is None:
            return None
        self._open(target.key)
        return target.key

    def _open(self, key):
        """The result opened (G3), as a click on it would."""
        model = self.lst.model()
        if model.open_key != key:
            model.open_key = key
            self.lst.relayout()
            self.lst.opened.emit(key)

    def open_folder(self, row):
        """*Open its folder* (N3: `windows.open_url`), looked for on a worker first (a drive may be slow or gone)."""
        path = finished.folder_of(self.language, row)

        def found(there):
            if there:
                windows.open_url(path)
            else:
                self.moves.say(strings.FIN_NO_FOLDER.format(title=row.title))
        if path is None:
            found(False)
            return
        bridge.run_in_worker(os.path.isdir, path, then=found, failed=lambda _info: found(False))

    # --- K6: *Never read this folder* (the item's folder or one above it, inside its source folder) --------------- #
    def _offer_skip(self, row, m):
        """Asked on the looks' worker (`SourceLooks.skippable`: the store's origin records); the submenu goes in before
        *Open its folder* when the answer comes while this menu is still open. A row from no folder being read (or no
        looks: no library) gets none."""
        looks = getattr(self.win, "looks", None)
        ids = drag.ids_of(row)
        self._skip_ask = getattr(self, "_skip_ask", 0) + 1
        if looks is None or not ids or not hasattr(looks, "skippable"):
            return False
        ask, relay = self._skip_ask, bridge.Relay(self)

        def found(folders):
            relay.deleteLater()
            if folders and ask == self._skip_ask and self.last_menu is m and m.isVisible():
                self.add_skip(row, m, folders)
        relay.said.connect(found)
        if not looks.skippable(ids, relay.call):
            relay.deleteLater()
            return False
        return True

    def add_skip(self, row, m, folders):
        """*Never read this folder* › each of `folders` (deepest first) by its name, its whole path in its tip; greyed
        with the store's reason while it can't be written (E4). -> the submenu."""
        writable = self.writer.can_write()
        reason = None
        if not writable:
            raw = self.writer.reason() or ""
            reason = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)
        before = next((a for a in m.actions() if a.text() == strings.ITEM_MENU["folder"][0]), None)
        sub = QMenu(strings.ITEM_SKIP[0], m)
        sub.setObjectName("rowmenu")
        sub.setToolTipsVisible(True)
        if before is not None:
            m.insertMenu(before, sub)
        else:
            m.addMenu(sub)
        sub.menuAction().setToolTip(strings.ITEM_SKIP[1] if writable else reason)
        sub.menuAction().setEnabled(writable)
        for path in folders:
            act = QAction(os.path.basename(path) or path, sub)
            act.setToolTip(strings.ITEM_SKIP_TIP.format(path=path) if writable else reason)
            act.setEnabled(writable)
            act.triggered.connect(lambda _c=False, p=path: self.skip_folder(row, p))
            sub.addAction(act)
        return sub

    def skip_folder(self, row, path):
        """`Writer.skip_folder` (on the writer's thread): the folder's items to the trash, the folder never read
        again; its toast with Undo (which reads it again)."""
        if self.moves.refused() is not None:
            return None
        ids = drag.ids_of(row)
        text = strings.ITEM_SKIPPED.format(name=os.path.basename(path) or path)
        return self.moves._give(drag.Ticket(text, (row.key,), ids), lambda t: self.writer.skip_folder(path, label=t))

    def ask_remove(self, row):
        """*Remove…*: the confirmation naming its files (Esc, Back, a click outside: No; Cancel the default)."""
        if self.moves.refused() is not None:
            return None
        n = len(row.episodes)
        body = strings.ITEM_REMOVE_BODY_ONE if n == 1 else strings.ITEM_REMOVE_BODY.format(n=f"{n:,}")
        yes = strings.ITEM_REMOVE_YES_ONE if n == 1 else strings.ITEM_REMOVE_YES.format(n=f"{n:,}")

        def answered(said_yes):
            self.question = None
            if said_yes:
                self.remove(row)
        self.question = confirm.ask(self.win, strings.ITEM_REMOVE_ASK.format(title=row.title), body, yes,
                                    strings.ITEM_REMOVE_YES_TIP, default_no=True, danger=True, on_answer=answered)
        return self.question

    def remove(self, row):
        """`Writer.remove`: its files to the trash (30 days), its toast with Undo."""
        if self.moves.refused() is not None:
            return None
        ids = drag.ids_of(row)
        return self.moves._give(drag.Ticket(strings.ITEM_REMOVED.format(title=row.title), (row.key,), ids),
                                lambda t: self.writer.remove(ids, label=t))

    # --- drop-to-join (G3; `drag.DragController` asks) ------------------------------------------------------------- #
    def target(self, d, global_pos):
        """The key of the part of the same title under the hand (a part dragged from the list), else None."""
        row = d.row
        if d.external or not joinable(row):
            return None
        vp = self.lst.viewport()
        pos = vp.mapFromGlobal(global_pos)
        if not vp.rect().contains(pos):
            return None
        idx = self.lst.indexAt(QPoint(pos.x(), pos.y()))
        if not idx.isValid():
            return None
        kind, other, _lines = self.lst.model().entries[idx.row()]
        if kind not in (rows.HERO, rows.ROW) or other.key == d.key or other.work_id != row.work_id or \
                not joinable(other):
            return None
        slab = self.lst.delegate.slot_rect(kind, self.lst.visualRect(idx), _lines)
        edge = round(slab.height() * JOIN_EDGE)
        if not slab.top() + edge <= pos.y() <= slab.bottom() - edge:
            return None                              # its edges place it beside the part, as any row's do
        return other.key

    def show(self, key):
        self.lst.set_join(key)

    def drop(self, d, key):
        target = self._row(key)
        if target is None or d.row is None:
            return None
        return self.join(part_of(target, self._place(target)), part_of(d.row))


def _numbers(arrival):
    """An arrival's episode numbers, from its files' names (`view_rows.episode_number`)."""
    return [view_rows.episode_number(os.path.basename(rel or "")) for rel in arrival.rel_paths or ()]
