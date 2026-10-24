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
- *Same show as…* › the other shows the view holds, one entry each (Current's in order, Goal's, Finished's, New
  arrivals'; at most `SAME_SHOW_MAX` from each), each asking first (`confirm.ask`, Cancel the default: "Make <B> part of
  <A>?"): one `Writer.merge_works` — <B>'s title made <A>'s, <A>'s name kept, and nothing moves (every file stays
  in its section and place: he asked for one show, never for files to change section) — the store's refusal (two
  AniList ids, TMDB ids or YouTube channels: `TITLES_APART`) said in the bar as the store words it, its toast only
  once the store saved it;
- *Same show as…* and any list longer than `MENU_PAGE` go on under *More…*, page by page;
- a separator, then *Remove…*: the one modal kind (`confirm.ask`, Esc / Back / a click outside are No) naming its
  files; `Writer.remove` (the trash, 30 days) with Undo.
**⋯ on a group (LM11b G3, IK-5):** the moves, *Study its cards first*, *Split here…*, *Rename…* (a card with the name
shown in a field: `Writer.rename_piece`, empty = named after its shows again, the name it has writes nothing), *Ungroup*
(`Writer.ungroup`: each show back in a row of its own, in place), a separator, *Remove…* — never *What is it?*, *Join
with…*, *Same show as…*, *Change cover…*, *Never read this folder* or *Open its folder* (each is one show's). Its writes
toast at the press, with Undo (*· saving…* until the store saved them; IK-2: no mark on the rows).
**An episode's own ⋯ (row 28):** an opened row's episode line under the hand or the keyboard shows its own ⋯
(`rows.RowsView.episode_menu_requested`): *Mark watched* / *Mark not watched* (the page's one Done path), *Play* (▶'s
path, when it can play), *Split here…* after it (when that split is allowed), then each `episode_hooks` entry —
callables `(row, ep) -> [Entry]`, asked as the menu opens; an entry's `payload`, a callable, runs when it is picked.
**Group… (LM11b G4):** Ctrl+click picks Current's rows and an opened row's episodes (its stones), Shift+click the rows
from the last one Ctrl picked instead (Ctrl+Shift+click adds them), Ctrl+Space the keyboard's row
(`rows.RowsView.pick_row`); with things picked from 2+ shows (IK-4: one show's alone would be no group), ⋯ on a picked
row (a right-click opens it at the hand) starts with *Group…*: one
`Writer.group` — the picked rows' pieces in the list's order (both of a show the Soon line runs through), then the
picked episodes — its toast *Grouped N into one row* with Undo at the press. Esc / Back (the shell's router), a plain
click, a drag and a view without a picked key let the picks go.
**Drop-to-join (G3):** a part dragged over the middle of another part of the same title (its top and bottom 30 % stay
a move beside it, so a part can still be placed next to its other part): the rows hold still (no gap opens), that part
shows a green dashed outline and *Drop to join*; the drop joins them in episode order, opens the result and toasts
*Joined Ep x–y* with Undo.
**Drop to group (LM11b G2; Sonic's answers: a drop on another show makes a group, no question):** over the middle of
another show's part, or of a group (either side a group), the hand rests `JOIN_REST_MS` before that row is outlined with
*Drop to group* (a passing drag still reorders); the drop is one `Writer.join(..., how="group")`, the row dropped on
first (it keeps its place, a group its name), never `ahead` — toasted *Grouped … with …* with Undo once the store
saved it (a refusal toasts nothing: no promise the store didn't keep), the result opened. A row in Finished or New
arrivals is never a group's target (the store's `NO_GROUP_TIERS`).
On an opened group, the hand on one of its episodes before its last lands a show's part after that episode
(`Writer.move`: the store takes it into the group there, LM11-Q1); a group dragged there joins at its end (a group
never moves into another, which would cut it in three). A New arrivals file rested on a group joins it
(`Writer.add_to_group`, IK-3); on a show's part it is placed as before. A row the Soon line runs through names both its
pieces (`pieces_of`, IK-1).

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

from PyQt6.QtCore import QObject, QPoint, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from app import library_store
from app.qt import bridge, confirm, drag, finished, rows, strings
from app.services import view_rows

JOIN_EDGE = 0.3                                     # a part's top and bottom 30 %: a move beside it, not a join
JOIN_REST_MS = 500                                  # LM11b G2: another show groups only once the hand rests this long

Entry = namedtuple("Entry", "name label tip ok children checked payload writes", defaults=(None, None, None, False))
#   writes: a hook's entry that asks the store for a write — greyed by the menu, with the store's reason, while the
#   store is read-only (`_refused_tip`: one rule, the menu's)
Part = namedtuple("Part", "key piece_id ids numbers tier place title")
Show = namedtuple("Show", "key work_id title where")
#   LM11b G3: a show *Same show as…* offers — `work_id` the title it merges into, `where` its section as *Join with…*
#   names it
SAME_SHOW_MAX = 20                                  # (from each section: a full Current never hides the rest)
MENU_PAGE = 12                                      # a submenu's entries before its *More…* (each page fits an
#   800 px window at every text size, and at 150 % on a laptop's screen: Qt split a longer one into columns)
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


def pieces_of(row):
    """The pieces a row stands for: its own, and the second of a show the Soon line runs through (B2-2)."""
    out = [row.piece_id]
    if getattr(row, "soon_from", None) is not None:
        out.append(getattr(row, "soon_piece", None))
    return [p for p in dict.fromkeys(out) if p is not None]


def same_show(a, b):
    """Two runs of one show (a drop joins them at once): never a group on either side (LM11b G2)."""
    return not getattr(a, "group", False) and not getattr(b, "group", False) and a.work_id == b.work_id


def ep_tier(row, ep):
    """`row`'s episode `ep`'s tier: Soon from `soon_from` on (a show the Soon line runs through), else the row's."""
    cut = getattr(row, "soon_from", None)
    k = next((i for i, e in enumerate(row.episodes) if e.id == ep.id), 0)
    return "soon" if cut is not None and k >= cut else row.tier


def joinable(row):
    """A part that can be joined or split: a title's piece (hato's mix never)."""
    return row is not None and row.piece_id is not None and row.work_id is not None and not drag.is_mix(row)


def groups_there(row):
    """Whether a group can live where `row` is: never Finished or New arrivals (the store's `NO_GROUP_TIERS`, which it
    refuses — so the window never offers it, and never toasts what can't happen)."""
    return getattr(row, "tier", None) not in library_store.NO_GROUP_TIERS


def ep_name(row, ep):
    """`ep` as ⋯ names it: in a group "<show> · Ep N", as the group's row labels it (two shows' Ep 1 never read
    alike); else its own label."""
    show = getattr(ep, "show", None)
    return view_rows.STRINGS["group_ep"].format(show=show, label=ep.label) if getattr(row, "group", False) and show \
        else ep.label


def unnamed(row):
    """Whether a group has no name of its own: its title is the one the store makes of its shows ("<first show> + N
    more", `view_rows.STRINGS["group_name"]`) — what the rename compares with (its stored name is None)."""
    eps = getattr(row, "episodes", None) or ()
    if not getattr(row, "group", False) or not eps or not getattr(eps[0], "show", None):
        return False
    shows = {e.work_id if e.work_id is not None else ("s", e.show) for e in eps}
    return row.title == view_rows.STRINGS["group_name"].format(first=eps[0].show, n=len(shows) - 1)


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
        self.lst.episode_menu_requested.connect(self.episode_menu)       # --- row 28
        self.episode_hooks = []                      # row 28: (row, ep) -> [Entry], asked as an episode's ⋯ opens
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
        # --- LM11b G4: Ctrl+click picks a part of a title (never hato's mix); Esc / Back let the picks go (the router)
        self.lst.pickable = lambda row: row.piece_id is not None and not drag.is_mix(row)
        register = getattr(win, "register_overlay", None)
        if register is not None:
            register(self.lst.picks)
        # --- LM11b G2: the row under the hand that a drop would group with, (drag, key), and the one it has rested on;
        # the opened group's episode the hand is on (a drop lands after it), (key, episode)
        self._resting = self._rested = None
        self._group_key = None
        self._ep_at = None
        self._rest = QTimer(self)
        self._rest.setSingleShot(True)
        self._rest.setInterval(JOIN_REST_MS)
        self._rest.timeout.connect(self._rested_on)

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
        New arrivals'. A group (LM11b G1) is no title's part: it has none and is never one."""
        view = self._view()
        if view is None or not joinable(row) or getattr(row, "group", False):
            return []
        out = []
        for n, r in enumerate(view.rows, 1):
            if r.key != row.key and r.work_id == row.work_id and joinable(r) and not getattr(r, "group", False):
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
    def _refused_tip(self):
        """None while the store can be written; else a greyed entry's tip, the store's reason in it (E4)."""
        if self.writer.can_write():
            return None
        raw = self.writer.reason() or ""
        return strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)

    def entries(self, row):
        """These entries for `row`, in order (after the moves): [Entry] — *Remove…* last (the menu puts a separator
        before it)."""
        reason = self._refused_tip()
        writable = reason is None

        def entry(name, label=None, tip=None, writes=True, **kw):
            words, own_tip = strings.ITEM_MENU.get(name, (None, None))
            ok = writable or not writes
            return Entry(name, label or words, (tip or own_tip) if ok else reason, ok, **kw)
        group = getattr(row, "group", False)
        out = [entry("unpin") if row.studying else entry("pin")]
        if row.work_id is not None and not group:
            kinds = [entry("type-to", label=strings.ITEM_TYPES[m], tip=strings.ITEM_TYPE_TIP.format(
                kind=strings.ITEM_TYPES[m]), checked=row.media == m, payload=m) for m in library_store.MEDIA_TYPES]
            kinds.append(entry("type-to", label=strings.ITEM_TYPE_GUESS[0], tip=strings.ITEM_TYPE_GUESS[1],
                               checked=False, payload=None))
            out.append(entry("type", children=kinds))
        if joinable(row) and len(row.episodes) >= 2:
            after = self._hovered_after(row)
            cuts = [k for k in range(1, len(row.episodes)) if view_rows.split_piece(row, k) is not None]   # B2-2
            if after is not None and after in cuts:
                ep = ep_name(row, row.episodes[after - 1])
                out.append(entry("split", label=strings.ITEM_SPLIT_HERE.format(ep=ep),
                                 tip=strings.ITEM_SPLIT_AFTER_TIP.format(ep=ep, rest=rows._rest_of(row, after)),
                                 payload=row.episodes[after]))
            elif cuts:
                out.append(entry("split", children=[
                    entry("split", label=strings.ITEM_SPLIT_AFTER.format(ep=ep_name(row, row.episodes[k - 1])),
                          tip=strings.ITEM_SPLIT_AFTER_TIP.format(ep=ep_name(row, row.episodes[k - 1]),
                                                                  rest=rows._rest_of(row, k)),
                          payload=row.episodes[k]) for k in cuts]))
        if group:                                    # --- LM11b G3 (IK-5): the rest is one show's
            out += [entry("rename"), entry("ungroup"), entry("remove")]
            return out
        others = self.other_parts(row)
        if others:
            out.append(entry("join", children=[
                entry("join", label=strings.ITEM_JOIN_PART.format(range=range_text(p), where=where),
                      tip=strings.ITEM_JOIN_PART_TIP.format(range=range_text(p)), payload=p) for p, where in others]))
        shows = self.same_shows(row)                 # --- LM11b G3 (IK-6)
        if shows:
            out.append(entry("same-show", children=[
                entry("same-show", label=strings.ITEM_SAME_SHOW_PICK.format(title=s.title, where=s.where),
                      tip=strings.ITEM_SAME_SHOW_PICK_TIP.format(title=s.title), payload=s) for s in shows]))
        covers = self.cover_entries(row) if self.cover_entries is not None else None
        if covers:
            out.append(entry("cover", children=[
                Entry("cover-to", label, tip if ok else reason, ok and writable, payload=cb)
                for label, tip, ok, cb in covers]))
        out.append(entry("folder", writes=False))
        out.append(entry("remove"))
        return out

    # --- LM11b G4: *Group…* ------------------------------------------------------------------------------------------- #
    def _picked(self):
        """What Ctrl+click picked, in the list's order: ([whole rows], [(row, episode)]) — an episode of a row picked
        whole is in it already."""
        view = self._view()
        rows_ = view.rows if view is not None else ()
        whole_keys, eps = self.lst.picked_rows, self.lst.picked_eps
        whole = [r for r in rows_ if r.key in whole_keys]
        picked = [(r, e) for r in rows_ if r.key not in whole_keys for e in r.episodes if (r.key, e.id) in eps]
        return whole, picked

    @staticmethod
    def _shows(whole, eps):
        """The shows the picks span (one show's alone would be no group): a whole row's every show (`works`: a group's each), an episode's own
        (`work_id`: a group's second show's is that show) — a row or episode with no title counts as its row's own."""
        out = set()
        for r in whole:
            out.update(getattr(r, "works", None) or (r.work_id if r.work_id is not None else ("row", r.key),))
        for r, e in eps:
            w = getattr(e, "work_id", None)
            out.add(w if w is not None else r.work_id if r.work_id is not None else ("row", r.key))
        return out

    def _to_group(self, row=None):
        """(whole rows, episodes) *Group…* would take: 2+ picks from 2+ shows (one show's, or one group's row alone
        though it spans two: the store would make no group of them) and, asked from `row`'s ⋯, `row` among them (a row
        that isn't picked has its own menu) — else None."""
        whole, eps = self._picked()
        if len(whole) + len(eps) < 2 or len(self._shows(whole, eps)) < 2:
            return None
        if row is not None and row.key not in {r.key for r in whole} | {r.key for r, _e in eps}:
            return None
        return whole, eps

    def group_entry(self, row=None):
        """`row`'s ⋯'s *Group…* (its first entry) when `_to_group` has something, else None; greyed with the store's
        reason while it can't be written (E4)."""
        picks = self._to_group(row)
        if picks is None:
            return None
        n = len(picks[0]) + len(picks[1])
        reason = self._refused_tip()
        words, tip = strings.ITEM_MENU["group"]
        return Entry("group", words, tip.format(n=n) if reason is None else reason, reason is None)

    def group(self, row=None):
        """*Group…* (from `row`'s ⋯): one `Writer.group` — the picked rows' pieces in the list's order, then the picked
        episodes — one row in Current; its toast with Undo (which takes them apart again); the picks let go."""
        picks = self._to_group(row)
        if picks is None or self.moves.refused() is not None:
            return None
        whole, eps = picks
        pieces = [p for r in whole for p in pieces_of(r)]
        items = [e.id for _r, e in eps]
        keys = list(dict.fromkeys([r.key for r in whole] + [r.key for r, _e in eps]))
        ids = [i for r in whole for i in drag.ids_of(r)] + items
        text = strings.ITEM_GROUPED.format(n=len(whole) + len(eps))
        seq = self.moves._give(drag.Ticket(text, keys, ids),
                               lambda t: self.writer.group(piece_ids=pieces, item_ids=items, label=t))
        if seq is not None:
            self.lst.clear_picks()
        return seq
    # --- end LM11b G4

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
        group = self.group_entry(row)                    # --- LM11b G4: *Group…* first, on a picked row
        if group is not None:
            self._action(m, row, group)
            m.addSeparator()
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
                self._submenu(m, row, e.label, e.tip, e.ok and any(c.ok for c in e.children), e.children)
                continue
            self._action(m, row, e)
        self.last_menu = m
        if not getattr(row, "group", False):         # (LM11b G3: a group's folders are several shows')
            self._offer_skip(row, m)                 # K6: *Never read this folder*, once the looks' worker answers
        m.popup(at)
        return m

    def _submenu(self, menu, row, label, tip, ok, children):
        """`children` in a submenu of `menu`: `MENU_PAGE` of them, then *More…* holding the rest, page by page (a long
        *Same show as…* or *Split here…* list never runs past the window). -> the submenu."""
        sub = menu.addMenu(label)
        sub.setObjectName("rowmenu")
        sub.setToolTipsVisible(True)
        sub.menuAction().setToolTip(tip)
        sub.menuAction().setEnabled(ok)
        page, rest = (children, []) if len(children) <= MENU_PAGE + 1 else (children[:MENU_PAGE], children[MENU_PAGE:])
        for c in page:
            self._action(sub, row, c)
        if rest:
            self._submenu(sub, row, strings.MENU_MORE[0], strings.MENU_MORE[1], any(c.ok for c in rest), rest)
        return sub

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
        if name == "group":                              # --- LM11b G4: what is picked, whichever row's ⋯
            self.group(row)
        elif name in ("pin", "unpin"):
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
        elif name == "rename":                           # --- LM11b G3
            self.ask_rename(row)
        elif name == "ungroup":
            self.ungroup(row)
        elif name == "same-show" and payload is not None:
            self.ask_same_show(row, payload)

    # --- row 28: an episode's own ⋯ ---------------------------------------------------------------------------- #
    def episode_entries(self, row, ep):
        """An opened row's episode `ep`'s ⋯: [Entry] — *Mark watched* ↔ *Mark not watched*, *Play* (when it can play),
        *Split here…* after it (when that split is allowed), then each hook's entries (a hook that fails is left out)."""
        reason = self._refused_tip()
        return self._episode_own(row, ep, reason) + self._episode_hooked(row, ep, reason)

    def _episode_own(self, row, ep, reason):
        name = ep_name(row, ep)
        action = strings.ROWS_STONE_ACTION[ep.watched]       # IK-10: the stone's own words for its click
        words, tip = strings.ITEM_EP_MARK
        out = [Entry("ep-unwatched" if ep.watched else "ep-watched", words.format(action=action),
                     tip.format(ep=name, action=action) if reason is None else reason, reason is None)]
        if ep.can_play:                              # IK-2: ▶'s own verb and tip (`view_rows`: the episode's media)
            out.append(Entry("ep-play", view_rows.VERB.get(ep.media_word or row.media_word, view_rows.VERB["video"]),
                             ep.play_tip, True))
        k = next((i for i, e in enumerate(row.episodes) if e.id == ep.id), None)
        if joinable(row) and k is not None and k + 1 < len(row.episodes) and \
                view_rows.split_piece(row, k + 1) is not None:
            words, tip = strings.ITEM_SPLIT_HERE.format(ep=name), \
                strings.ITEM_SPLIT_AFTER_TIP.format(ep=name, rest=rows._rest_of(row, k + 1))
            out.append(Entry("split", words, tip if reason is None else reason, reason is None,
                             payload=row.episodes[k + 1]))
        return out

    def _episode_hooked(self, row, ep, reason):
        """Each hook's entries; one that writes greyed with the store's reason while it is read-only (AD-8)."""
        out = []
        for hook in list(self.episode_hooks):
            try:
                out += [e._replace(ok=False, tip=reason) if e.writes and reason is not None else e
                        for e in hook(row, ep) or ()]
            except Exception as e:                   # an optional module's entry never takes the menu down
                print(f"Episode menu: an entry couldn't be made ({e})")
        return out

    def episode_menu(self, row, ep, at):
        """The episode's ⋯: its entries in the list's one menu (C4), every entry's tip shown."""
        m = drag.list_menu(self.lst, row.title)
        m.setAccessibleName(strings.ITEM_EP_MENU_NAME.format(ep=ep_name(row, ep)))
        reason = self._refused_tip()
        own, hooked = self._episode_own(row, ep, reason), self._episode_hooked(row, ep, reason)
        for e in own + hooked:
            if hooked and e is hooked[0]:
                m.addSeparator()                     # the modules' entries apart from the episode's own (AD-8)
            act = QAction(e.label, m)
            act.setToolTip(e.tip)
            act.setEnabled(e.ok)
            act.triggered.connect(lambda _c=False, n=e.name, pl=e.payload: self.episode_pick(row, ep, n, pl))
            m.addAction(act)
        self.last_menu = m
        m.popup(at)
        return m

    def episode_pick(self, row, ep, name, payload=None):
        if name in ("ep-watched", "ep-unwatched"):
            self.page.done(row, ep)                  # the one path for a Done (S12): watched ↔ not watched
        elif name == "ep-play":
            self.lst.play_requested.emit(ep)         # ▶'s own path
        elif name == "split" and payload is not None:
            self.split(row, payload)
        elif callable(payload):                      # a hook's entry
            payload()
    # --- end row 28

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
        """*Open its folder*: a press (`press.open`, round 8 row 45) — the row's ⋯ turns (IK-2), the folder is looked
        for (a drive may be slow or gone) and opened on a worker."""
        return finished.open_folder_of(self.win, self.language, row, self.lst, self.moves.say)

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
        reason = self._refused_tip()
        writable = reason is None
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

    # --- LM11b G3: a group's *Rename…* / *Ungroup*, a show's *Same show as…* ------------------------------------- #
    def same_shows(self, row):
        """*Same show as…*'s shows for `row` (a show's own row, never a group): [Show] — each other show the view holds
        once, by its title (`work_id`: the merge names no piece), where it first stands: Current's runs in order, Goal's
        tiles, Finished's, New arrivals'; at most `SAME_SHOW_MAX` from each section."""
        view = self._view()
        if view is None or not joinable(row) or getattr(row, "group", False):
            return []
        out, seen, taken = [], {row.work_id}, {}

        def add(section, work_id, key, title, where):
            if work_id is None or work_id in seen:
                return
            seen.add(work_id)                        # (past its section's cap too: listed where it first stands only)
            if taken.get(section, 0) < SAME_SHOW_MAX:
                taken[section] = taken.get(section, 0) + 1
                out.append(Show(key, work_id, title, where))
        for n, r in enumerate(view.rows, 1):
            if joinable(r) and not getattr(r, "group", False):
                add("now", r.work_id, r.key, r.title,
                    strings.ITEM_JOIN_WHERE[r.tier if r.tier in ("now", "soon") else "now"].format(n=n))
        for w in getattr(getattr(view, "goal", None), "works", None) or ():
            if not getattr(w, "group", False):
                add("goal", w.work_id, w.key, w.title, strings.ITEM_JOIN_WHERE["goal"])
        for month in view.finished or ():
            for r in month.rows:
                if joinable(r) and not getattr(r, "group", False):
                    add("graduated", r.work_id, r.key, r.title, strings.ITEM_JOIN_WHERE["graduated"])
        for a in view.arrivals or ():
            add("arrivals", a.work_id, a.key, a.title, strings.ITEM_JOIN_WHERE["arrivals"])
        return out

    def ungroup(self, row):
        """*Ungroup*: `Writer.ungroup` — each show back in a row of its own, in place; its toast with Undo."""
        if not getattr(row, "group", False) or self.moves.refused() is not None:
            return None
        piece = row.piece_id
        return self.moves._give(drag.Ticket(strings.ITEM_UNGROUPED.format(title=row.title), (row.key,),
                                            drag.ids_of(row)), lambda t: self.writer.ungroup(piece, label=t))

    def ask_rename(self, row):
        """*Rename…*: the card with the name shown in a field (Esc / Back / Cancel: nothing written)."""
        if not getattr(row, "group", False) or self.moves.refused() is not None:
            return None

        def answered(said_yes):
            self.question = None
            if said_yes:
                self.rename(row, card.text)
        card = confirm.ask(self.win, strings.ITEM_RENAME_ASK, strings.ITEM_RENAME_BODY, strings.ITEM_RENAME_YES,
                           strings.ITEM_RENAME_YES_TIP, field=row.title, on_answer=answered)
        self.question = card
        return card

    def rename(self, row, text):
        """The group's own name (`Writer.rename_piece`): `text` stripped; empty → None, named after its shows again; the
        name shown → nothing written. Its toast with Undo."""
        if not getattr(row, "group", False) or self.moves.refused() is not None:
            return None
        name = (text or "").strip() or None
        if name in (row.title, None if unnamed(row) else row.title):    # its name as shown, or as stored
            return None
        piece = row.piece_id
        words = strings.ITEM_RENAMED.format(title=row.title, name=name) if name is not None else \
            strings.ITEM_RENAME_CLEARED.format(title=row.title)
        return self.moves._give(drag.Ticket(words, (row.key,), drag.ids_of(row)),
                                lambda t: self.writer.rename_piece(piece, name, label=t))

    def ask_same_show(self, row, show):
        """*Same show as…* › `show`: asked first (Cancel the default; Esc / Back / a click outside: nothing written)."""
        if self.moves.refused() is not None:
            return None

        def answered(said_yes):
            self.question = None
            if said_yes:
                self.same_show(row, show)
        self.question = confirm.ask(
            self.win, strings.ITEM_SAME_SHOW_ASK.format(b=row.title, a=show.title),
            strings.ITEM_SAME_SHOW_BODY.format(b=row.title, a=show.title), strings.ITEM_SAME_SHOW_YES,
            strings.ITEM_SAME_SHOW_YES_TIP.format(b=row.title, a=show.title), default_no=True, on_answer=answered)
        return self.question

    def same_show(self, row, show):
        """`row`'s show made part of `show`: one `Writer.merge_works(show, [row's])` — the titles alone, `show`'s name
        kept; no file moves, from whichever section either stands in — refused by the store when
        the ids say two shows (`TITLES_APART`, said in the bar through the writer's `failed` note); its toast with Undo
        at the press."""
        if not joinable(row) or getattr(row, "group", False) or self.moves.refused() is not None:
            return None
        keep, other = show.work_id, row.work_id
        text = strings.ITEM_SAME_SHOW_DONE.format(b=row.title, a=show.title)
        return self.moves._give(drag.Ticket(text, (row.key, show.key), drag.ids_of(row)),
                                lambda t: self.writer.merge_works(keep, [other], label=t))
    # --- end LM11b G3

    # --- LM11b G2: drop to group ------------------------------------------------------------------------------------ #
    def group_join(self, target, other):
        """`other` (a row) dropped on `target` (another show's part, or a group): one `Writer.join(how="group")`, the
        target's pieces first (it keeps its place, a group its name), never `ahead`; its toast with Undo at the press, the
        result opened. -> the target's key."""
        if not groups_there(target) or self.moves.refused() is not None:
            return None
        pieces = list(dict.fromkeys(pieces_of(target) + pieces_of(other)))
        text = strings.ITEM_GROUPED_WITH.format(other=other.title, title=target.title)
        if self.moves._give(drag.Ticket(text, (target.key, other.key), drag.ids_of(target) + drag.ids_of(other)),
                            lambda t: self.writer.join(pieces, label=t, how="group")) is None:
            return None
        self._open(target.key)
        return target.key

    def into_group_at(self, group, ep, ids, title, keys=()):
        """Files `ids` dropped on the opened `group`'s episode `ep` (not its last): moved after it, in its tier — the
        store takes them into the group there (GI1, LM11-Q1); its toast at the press. -> the group's key."""
        if not groups_there(group) or self.moves.refused() is not None:
            return None
        ids = list(ids)
        tier = ep_tier(group, ep)
        text = strings.ITEM_GROUPED_WITH.format(other=title, title=group.title)
        if self.moves._give(drag.Ticket(text, (group.key,) + tuple(keys), ids),
                            lambda t: self.writer.move(ids, tier, after_id=ep.id, label=t)) is None:
            return None
        self._open(group.key)
        return group.key

    def add_to_group(self, group, ids, title):
        """New arrivals' files `ids` dropped on `group`: one `Writer.add_to_group`, after its last row; its toast
        at the press. -> its key."""
        if not groups_there(group) or self.moves.refused() is not None:
            return None
        ids = list(ids)
        piece = group.piece_id
        text = strings.ITEM_GROUPED_WITH.format(other=title, title=group.title)
        if self.moves._give(drag.Ticket(text, (group.key,), ids),
                            lambda t: self.writer.add_to_group(piece, item_ids=ids, label=t)) is None:
            return None
        self._open(group.key)
        return group.key
    # --- end LM11b G2

    # --- drop-to-join (G3; `drag.DragController` asks) ------------------------------------------------------------- #
    def target(self, d, global_pos):
        """The key of the row under the hand that a drop joins: a part of the same show at once; another show's, or a
        group, once the hand has rested `JOIN_REST_MS` on it (LM11b G2). Else None."""
        hit = self._over(d, global_pos)
        other, ep = hit if hit is not None else (None, None)
        if other is None or (d.row is not None and same_show(d.row, other)):
            self._resting = self._rested = self._group_key = self._ep_at = None
            self._rest.stop()
            return other.key if other is not None else None
        self._ep_at = (other.key, ep) if ep is not None else None
        if self._rested == (d, other.key):
            self._group_key = other.key
            return other.key
        self._group_key = None
        if self._resting != (d, other.key):          # a new row under the hand: its rest starts now
            self._resting, self._rested = (d, other.key), None
            self._rest.start()
        return None

    def _over(self, d, global_pos):
        """(the row under the hand a drop would join, the opened group's episode it is on — not its last — or None),
        else None: over a row's middle (its edges place beside it), or anywhere on an opened group's episodes. A drag
        from the list: a joinable part; New arrivals' (IK-3): a group only."""
        row = d.row
        if d.external:
            if getattr(d, "source", None) != "arrivals":
                return None
        elif not joinable(row):
            return None
        vp = self.lst.viewport()
        pos = vp.mapFromGlobal(global_pos)
        if not vp.rect().contains(pos):
            return None
        idx = self.lst.indexAt(QPoint(pos.x(), pos.y()))
        if not idx.isValid():
            return None
        entry = self.lst.model().entries[idx.row()]
        kind, other, _lines = entry
        if kind not in (rows.HERO, rows.ROW) or other.key == d.key or not joinable(other) or not groups_there(other):
            return None                              # (a stale row: no group lives there, no part joins Finished)
        group = getattr(other, "group", False)
        if d.external and not group:
            return None                              # a tray file on a show's part: placed in the list, as before
        rect = self.lst.visualRect(idx)
        ep = self.lst.delegate.episode_at(entry, rect, pos) if group else None
        if ep is not None:
            return other, (ep if ep.id != other.episodes[-1].id else None)
        slab = self.lst.delegate.slot_rect(kind, rect, _lines)
        edge = round(slab.height() * JOIN_EDGE)
        if not slab.top() + edge <= pos.y() <= slab.bottom() - edge:
            return None                              # its edges place it beside the part, as any row's do
        return other, None

    def _rested_on(self):
        """The hand has rested on another show's row: asked again where it is (no move comes while it rests)."""
        d = self.moves.running
        if d is None or self._resting is None or self._resting[0] is not d:
            return
        self._rested = self._resting
        self.moves._follow(d.at)

    def show(self, key):
        self.lst.set_join(key, strings.JOIN_GROUP_LABEL if key is not None and key == self._group_key else None)

    def drop(self, d, key):
        target = self._row(key)
        if target is None:
            return None
        ep = self._ep_at[1] if self._ep_at is not None and self._ep_at[0] == key else None
        if d.external:
            if ep is not None:
                return self.into_group_at(target, ep, d.ids, d.title)
            return self.add_to_group(target, d.ids, d.title)
        if d.row is None:
            return None
        if same_show(target, d.row):
            return self.join(part_of(target, self._place(target)), part_of(d.row))
        if ep is not None and not getattr(d.row, "group", False):     # a group dragged there joins at its end
            return self.into_group_at(target, ep, drag.ids_of(d.row), d.row.title, (d.row.key,))
        return self.group_join(target, d.row)


def _numbers(arrival):
    """An arrival's episode numbers, from its files' names (`view_rows.episode_number`)."""
    return [view_rows.episode_number(os.path.basename(rel or "")) for rel in arrival.rel_paths or ()]
