"""Connect's actions in the window (P4.1 L2: rows 4.1.11 and 4.1.12's two hidden hooks; the P4.1 RUNBOOK's C2, C3, C6,
IK S3, S7). What the rows, Finished, the arrivals and *Needs you* ask for, routed:

- **One way to ask for mining (C2):** *Mine now* (Waiting's icon) and *Mine this* (a *Mine* status) — the rows'
  `mine_requested` —, Finished's *Mine* / *Mine it too* and the arrivals' *Mine them too* are all `Writer.ask_mining(ids)`,
  given through the drag controller's tickets (its toast's Undo, Ctrl+Z). The writer's after-commit hook
  (`shell.connect_after_commit`) then kicks Connect. A non-video item's *Mine this* makes no ask: it is *Mine text* (K67,
  IK S3: Anki Miner mines video only).
- ***Link…*** (No video's): the system's file picker, videos only (`runner.VIDEO_EXTENSIONS`) → `Writer.link_video`.
- ***Mine text*** (C6), and *Needs you*'s *Mine the text only*: Anki Miner's own window (as Settings' *Open Anki Miner*
  does) with the file's path on the clipboard, and a toast saying so — mining by hand.
- **Connect off** (`settings_manager.connect_on` false): the rows' `connect_off` holds why (`feed.OFF_*`): their buttons
  ask nothing and their tips say why; the other asks say it in the bar. Read on a worker when the window opens and when
  Connect's switch or D29's automation is written.

- ***Make their cards*** (a gap in *Needs you*): an explicit press is an ask (Michi 🧭 2026-10-16, C2; P2.1-3 — "a gap
  reconciles, never mines" — still holds for Connect's automatic mining): the gap's files asked for, then the entry
  answered as *Leave them* answers it.
Nothing here reads the store or the settings on the window's thread: the writes are the writer's, the looks a worker's.
"""
import os

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import path_utils
from app.qt import bridge, drag, strings, windows

OFF_KEYS = frozenset(("connect_enabled", "logic.automation", "automation"))


def connect_off(settings):
    """Why Connect may not run now (the feed's own off line: `feed.OFF_CONNECT` / `feed.OFF_AUTOMATION`), or None."""
    from app import settings_manager
    from app.connect import feed
    if settings_manager.connect_on(settings):
        return None
    return feed._off(settings).line


def _video_patterns():
    """(A worker.) The picker's filter: the videos Connect can make cards from."""
    from app.connect import runner
    return " ".join("*" + ext for ext in runner.VIDEO_EXTENSIONS)


def _miner_and_file(settings, path):
    """(A worker.) -> (Anki Miner's program or None, the file's path)."""
    from app.connect import anki_miner
    return anki_miner.find(settings), path


class MineActions(QObject):
    """Made by the shell when it has a writer (as Finished's actions). The controller, the writer and the language are
    the window's as they are at each call (a language switch rebuilds `win.moves`: nothing here is rebuilt)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.off = None                              # why Connect may not run (None: it may), read on a worker
        self.pick_file = lambda title, folder, patterns: QFileDialog.getOpenFileName(
            self.win, title, folder, strings.LINK_FILTER.format(patterns=patterns))[0]     # (tests replace it)
        self.lists = [page.list for page in win.page_widgets.values() if hasattr(getattr(page, "list", None),
                                                                                  "mine_requested")]
        for lst in self.lists:
            lst.mine_requested.connect(self.mine_row)
            lst.link_requested.connect(self.link)
            lst.mine_text_requested.connect(lambda row, ep: self.mine_text(ep.label, ep.rel_path))
        fin = getattr(win, "finished", None)
        if fin is not None:
            fin.on_mine = lambda row: self.mine_row(row, [e.id for e in row.episodes])
            fin.on_mine_too = lambda row: self.mine_row(row, [e.id for e in row.episodes if not e.cards])
        tray = getattr(win, "arrivals_tray", None)
        if tray is not None:
            tray.mine_too = self.mine_ids
        needs = getattr(win, "needs_you", None)
        if needs is not None:
            needs.hooks["mine_text_only"] = self._needs_mine_text
            needs.hooks["make_cards"] = self._needs_make_cards
            needs.rewire()
        win.bridge.settings_written.connect(self._settings_written)
        self.read_off()

    # --- Connect off ------------------------------------------------------------------------------------------- #
    def read_off(self):
        get = self.win.services.settings.get
        bridge.run_in_worker(lambda: connect_off(get()), then=self._off_read,
                             failed=lambda info: print(f"Connect's switch wasn't read: {info[1]}"))

    def _off_read(self, why):
        self.off = why
        for lst in self.lists:
            lst.connect_off = why

    def _settings_written(self, keys):
        if OFF_KEYS & set(keys or ()):
            self.read_off()

    # --- asking for mining (C2) ------------------------------------------------------------------------------ #
    def mine_row(self, row, ids):
        """*Mine now* / *Mine this* / Finished's *Mine* and *Mine it too*: the ask, or a non-video item's *Mine text*."""
        ids = list(dict.fromkeys(ids))
        if not ids:
            return None
        if getattr(row, "media_word", "video") != "video":         # K67: Anki Miner mines video only
            ep = next((e for e in row.episodes if e.id == ids[0]), row.episodes[0])
            return self.mine_text(ep.label, ep.rel_path)
        return self._ask(strings.MINE_ASKED.format(title=row.title), (row.key,), ids)

    def mine_ids(self, ids):
        """The arrivals' *Mine them too*."""
        ids = list(dict.fromkeys(ids))
        return self._ask(strings.MINE_ASKED_N.format(n=len(ids)), (), ids) if ids else None

    def _ask(self, text, keys, ids):
        """-> the writer's number, or None (Connect off: said in the bar; the store refused: the controller says)."""
        if self.off:
            self.win.say(self.off)
            return None
        moves = self.win.moves
        if moves is None or moves.refused() is not None:
            return None
        writer = moves.writer
        return moves._give(drag.Ticket(text, keys, ids), lambda t: writer.ask_mining(ids, label=t))

    # --- Link… ------------------------------------------------------------------------------------------------ #
    def link(self, row, ep):
        """No video's *Link…*: a video chosen in the system's picker → the writer's `link_video` (refused there with
        its words, as Needs you's)."""
        if self.win.moves is None:
            return
        folder = os.path.dirname(os.path.join(path_utils.get_data_path(self.win.language),
                                              *(ep.rel_path or "").split("/")))

        def pick(patterns):
            moves = self.win.moves
            path = self.pick_file(strings.LINK_TITLE.format(label=ep.label), folder, patterns)
            if not path or moves is None or moves.refused() is not None:
                return
            writer = moves.writer
            moves._give(drag.Ticket(strings.LINKING_ONE.format(label=ep.label), (row.key,), (ep.id,)),
                        lambda t: writer.link_video(ep.id, path, label=t))
        bridge.run_in_worker(_video_patterns, then=pick, failed=lambda info: self.win.say(str(info[1])))

    # --- Mine text (C6) --------------------------------------------------------------------------------------- #
    def mine_text(self, label, rel_path):
        """Anki Miner's own window, the file's path on the clipboard, a toast saying so (never hidden: K67)."""
        path = os.path.join(path_utils.get_data_path(self.win.language), *(rel_path or "").split("/"))
        get = self.win.services.settings.get
        bridge.run_in_worker(lambda: _miner_and_file(get(), path), then=lambda found: self._open_miner(label, found),
                             failed=lambda info: self.win.say(strings.MINE_TEXT_NO_MINER))

    def _open_miner(self, label, found):
        miner, path = found
        if not miner:
            self.win.say(strings.MINE_TEXT_NO_MINER)
            return
        QApplication.clipboard().setText(path)
        if not windows.open_url(miner):
            self.win.say(strings.MINE_TEXT_NOT_OPENED.format(path=miner))
            return
        self.win.toasts.show(strings.MINE_TEXT_COPIED.format(name=label))

    def _needs_mine_text(self, entry, line):
        line = line if line is not None else (entry.lines[0] if entry.lines else None)
        if line is not None:
            self.mine_text(line.label, line.rel_path)

    def _needs_make_cards(self, entry, _line=None):
        """A gap's *Make their cards*: one ask for its files (toast + Undo); once given, the entry answered as *Leave them*
        answers it (on a worker), and *Needs you* read again."""
        ids = list(dict.fromkeys((entry.data or {}).get("item_ids") or ()))
        if not ids or self._ask(strings.MINE_ASKED.format(title=entry.title), (), ids) is None:
            return
        from app.services import needs as service
        needs, keys = self.win.needs_you, service.answer_keys(entry)
        bridge.run_in_worker(service.answer, needs.language, keys, then=lambda _n: needs.refresh(),
                             failed=needs._failed)
