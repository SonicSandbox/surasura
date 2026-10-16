"""The Finished importer's job (W3.2 S5): `app/services/finished_import.py`.

What a wrong answer would cost a learner:
  * a show they finished years ago counted toward their list again, or its sentences lost for 例文 (N15: kept, never
    counted);
  * the same folder imported twice showing every episode twice (`name_1.srt` beside `name.srt`);
  * a cancelled import leaving half its episodes in Finished, or `.part` debris in their library;
  * an Undo that sends their own files to the trash (only the job's copies may go), or files copied for a store that
    can't take them, left behind with no row;
  * their originals moved or changed (the importer only copies).

The job runs in a real registry, its store half through the window's writer on a real migrated store (Japanese and
Chinese names from tests/Test Resources); the folders it imports from sit in the test's own folder, as Explorer's do.
"""
import json
import os
import shutil
import threading
import time

import pytest

from app import indexer
from app import library_store as ls
from app.qt.strings import MOVE_WORDS as WORDS
from app.services import finished_import as F
from app.services import jobs
from app.services import moves as M
from tests import services_helpers as h
from tests.test_library_store_support import migrated, roots
from tests.test_services_moves import LockHolder, short_lock_wait  # noqa: F401  (the fixture, by name)

SHOW = {"ja": ("進撃の巨人", "phrases_sample.srt", "ja"), "zh": ("进击的巨人", "night_market.srt", "zh")}


class Heard:
    def __init__(self):
        self.saved, self.notes, self.undone = [], [], []
        self.rereads = 0

    def kw(self):
        def reread():
            self.rereads += 1
        return dict(on_saved=lambda c, label: self.saved.append((c, label)), on_note=self.notes.append,
                    on_reread=reread, on_undone=lambda c, label: self.undone.append(c))


class Library:
    def __init__(self, language):
        self.language = language
        self.store = migrated(language)
        self.data_dir, self.user_files_dir = roots(language)
        self.heard = Heard()
        self.writer = M.Writer(ls.StoreOpener(language, self.data_dir, self.user_files_dir, role="window"), language,
                               journal_file=M.journal_path(language), retry=0.05, words=WORDS, **self.heard.kw())
        self.writer.start()
        self.registry = jobs.JobRegistry()

    def show_folder(self, where, episodes=(1, 2, 3)):
        """A finished show as it sits in Downloads: real subtitles named as fansubs name them, plus its poster."""
        title, resource, tag = SHOW[self.language]
        with open(os.path.join(h.RESOURCES, self.language, resource), encoding="utf-8") as f:
            text = f.read()
        folder = os.path.join(where, title)
        os.makedirs(folder, exist_ok=True)
        for n in episodes:
            with open(os.path.join(folder, f"[Group] {title} - {n:02d}.{tag}.srt"), "w", encoding="utf-8") as f:
                f.write(text + f"\n{n}\n")
        with open(os.path.join(folder, "poster.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff\xe0 not content")
        return folder

    def run(self, sources, **kw):
        job = F.ImportJob(self.language, sources, self.writer, self.registry, data_dir=self.data_dir, **kw)
        started = job.start()
        if started is not None:
            assert job.wait(30)
        assert h.until(lambda: not self.writer.pending())
        return job

    def finished(self):
        return {self.store.item(i)["rel_path"]: self.store.item(i) for i in self.store.ids("graduated")}

    def graduated_files(self):
        root = os.path.join(self.data_dir, ls.GRADUATED_FOLDER)
        return sorted(os.path.relpath(os.path.join(d, n), self.data_dir).replace("\\", "/")
                      for d, _s, files in os.walk(root) for n in files)

    def close(self):
        self.writer.finish(time.monotonic() + 5)
        self.store.close()


@pytest.fixture(params=["ja", "zh"])
def lib(request):
    library = Library(request.param)
    yield library
    library.close()


def _snapshot(folder):
    out = {}
    for d, _s, files in os.walk(folder):
        for n in files:
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, folder)] = f.read()
    return out


def _parts(root):
    return [os.path.join(d, n) for d, _s, files in os.walk(root) for n in files if n.endswith(".part")]


# --- the import ------------------------------------------------------------------------------------------------- #
def test_N15_a_show_finished_before_lands_in_finished_dated_earlier_kept_for_its_sentences_never_counted(lib, tmp_path):
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    before = _snapshot(folder)
    job = lib.run([folder])
    assert job.outcome == "imported" and job.job.view().state == jobs.DONE
    assert job.job.view().label == "Adding what you finished before"
    assert h.until(lambda: lib.heard.saved)
    title = SHOW[lib.language][0]
    rows = lib.finished()
    assert sorted(rows) == [f"Graduated/{title}/[Group] {title} - {n:02d}.{SHOW[lib.language][2]}.srt" for n in (1, 2, 3)]
    assert all(r["graduated_at"] is None for r in rows.values()), "dated Earlier"
    assert len({r["work_id"] for r in rows.values()}) == 1, "one title, by its folder"
    assert all(not p.endswith("poster.jpg") for p in lib.graduated_files()), "content files only"
    assert _snapshot(folder) == before, "the user's own files untouched, still where they were"
    counted, kept = lib.store.text_lists()
    assert set(rows) <= set(kept) and not set(rows) & set(counted)
    counted_paths, more = indexer.token_store_lists(lib.language, lib.data_dir, [])
    full = {os.path.normcase(os.path.join(lib.data_dir, *r.split("/"))) for r in rows}
    assert full <= {os.path.normcase(p) for p in more["kept"]}, "the token store keeps their text"
    assert not full & {os.path.normcase(p) for p in counted_paths}, "never counted"


def test_importing_the_same_folder_again_adds_nothing_twice(lib, tmp_path):
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    lib.run([folder])
    assert h.until(lambda: lib.heard.saved)
    files, rows = lib.graduated_files(), sorted(lib.finished())
    again = lib.run([folder])
    assert again.copied == [] and len(again.paths) == 3, "the copies are the files Finished holds already"
    assert h.until(lambda: lib.heard.rereads >= 1)
    assert lib.graduated_files() == files and sorted(lib.finished()) == rows, "no name_1 copies, no second rows"
    assert len(lib.heard.saved) == 1
    lib.show_folder(str(tmp_path / "Downloads"), episodes=(4,))              # a new episode since: only it is added
    newer = lib.run([folder])
    title, _resource, tag = SHOW[lib.language]
    assert [os.path.basename(p) for p in newer.copied] == [f"[Group] {title} - 04.{tag}.srt"]
    assert h.until(lambda: len(lib.heard.saved) == 2)
    assert len(lib.finished()) == 4 and len(lib.graduated_files()) == 4


def test_a_file_already_in_the_library_is_imported_where_it_is_never_copied_and_undo_leaves_it(lib, tmp_path):
    episode = lib.store.ids("now")[0]
    rel = lib.store.item(episode)["rel_path"]
    path = os.path.join(lib.data_dir, *rel.split("/"))
    outside = lib.show_folder(str(tmp_path / "Downloads"), episodes=(1,))
    job = lib.run([path, outside])
    assert h.until(lambda: lib.heard.saved)
    assert lib.store.item(episode)["tier"] == "graduated" and lib.store.item(episode)["rel_path"] == rel
    assert len(job.copied) == 1 and all(os.path.normcase(path) != os.path.normcase(c) for c in job.copied)
    lib.writer.undo()
    assert h.until(lambda: lib.heard.undone)
    assert os.path.isfile(path) and lib.store.item(episode)["tier"] == "now", "its own file and place back"
    assert not os.path.exists(job.copied[0]), "the job's copy went to the trash"
    assert any(os.listdir(os.path.join(lib.data_dir, ".trash")))
    assert _snapshot(outside), "the user's originals are still there"


# --- cancel, refusals, failures ---------------------------------------------------------------------------------- #
def test_cancel_mid_copy_leaves_no_part_no_row_and_its_copies_in_the_trash(lib, tmp_path):
    folder = lib.show_folder(str(tmp_path / "Downloads"), episodes=(1, 2, 3, 4))
    before = _snapshot(folder)
    holder = {}

    def heard(snapshot):                                # the first file's progress: the user presses Stop
        for view in snapshot:
            if view.kind == F.KIND and view.progress is not None and view.progress.done == 1 and "job" in holder:
                holder.pop("job").cancel()
    lib.registry.subscribe(heard)
    job = F.ImportJob(lib.language, [folder], lib.writer, lib.registry, data_dir=lib.data_dir)
    holder["job"] = job
    job.start()
    assert job.wait(30)
    view = job.job.view()
    assert job.outcome == "cancelled" and view.cancelled and view.state == jobs.DONE
    assert lib.finished() == {} and not lib.writer.pending() and lib.heard.saved == []
    assert lib.graduated_files() == [] and _parts(lib.data_dir) == []
    assert len(os.listdir(os.path.join(lib.data_dir, ".trash"))) == 1, "the one file it had copied"
    assert _snapshot(folder) == before


def test_a_job_cancelled_while_it_waits_for_another_import_copies_nothing(lib, tmp_path):
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    gate, entered = threading.Event(), threading.Event()
    real = ls.copy_into_finished

    def slow(*a, **k):
        entered.set()
        gate.wait(10)
        return real(*a, **k)
    first = F.ImportJob(lib.language, [folder], lib.writer, lib.registry, data_dir=lib.data_dir)
    second = F.ImportJob(lib.language, [folder], lib.writer, lib.registry, data_dir=lib.data_dir)
    try:
        ls.copy_into_finished = slow
        first.start()
        assert entered.wait(10)
        second.start()
        assert second.job.view().state == jobs.WAITING, "never two imports at once"
        second.cancel()
        assert second.outcome == "cancelled"
    finally:
        gate.set()
        ls.copy_into_finished = real
    assert first.wait(30) and first.outcome == "imported"
    assert h.until(lambda: lib.heard.saved) and len(lib.finished()) == 3


class Writer:
    """The writer's face for a store that turns read-only between the copy and the write."""
    def __init__(self, writable=True, takes=False):
        self.writable, self.takes = writable, takes
        self.calls = []

    def can_write(self):
        return self.writable

    def reason(self):
        return "read-only"

    def import_finished(self, paths, copied=(), label=None, answer=None):
        self.calls.append((paths, copied))
        return 1 if self.takes else None


def test_E4_a_store_that_cant_be_written_is_refused_before_anything_is_copied(lib, tmp_path):
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    w = Writer(writable=False)
    job = F.ImportJob(lib.language, [folder], w, lib.registry, data_dir=lib.data_dir)
    assert job.start() is None and job.outcome == "refused" and lib.registry.snapshot() == ()
    assert lib.graduated_files() == []


def test_a_store_that_turns_read_only_after_the_copy_gets_the_copies_sent_to_the_trash(lib, tmp_path):
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    w = Writer()
    job = F.ImportJob(lib.language, [folder], w, lib.registry, data_dir=lib.data_dir)
    job.start()
    assert job.wait(30)
    view = job.job.view()
    assert job.outcome == "refused" and view.state == jobs.FAILED and view.message == "read-only"
    assert len(w.calls) == 1 and len(w.calls[0][1]) == 3, "it handed its three copies"
    assert lib.graduated_files() == [] and len(os.listdir(os.path.join(lib.data_dir, ".trash"))) == 3


def _graduated_rows(db):
    """Finished's rows, read from the file itself (the store is marked damaged: no handle opens it)."""
    import sqlite3
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM items WHERE tier = 'graduated'").fetchone()[0]
    finally:
        conn.close()


def test_S2_a_store_that_turns_read_only_after_the_import_was_queued_keeps_no_copy_and_the_job_says_refused(
        lib, tmp_path):
    """S2: the writer let a queued import go on a store gone read-only, but only a drop's copies went to the trash —
    the import's stayed in `Graduated/` (never walked: invisible, for ever) and the job had already said *imported*."""
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    lib.writer.hold()                                   # a drag: the import queues behind it
    job = F.ImportJob(lib.language, [folder], lib.writer, lib.registry, data_dir=lib.data_dir)
    job.start()
    assert h.until(lambda: lib.writer.pending() == 1)
    assert len(lib.graduated_files()) == 3, "copied, waiting for the store"
    lib.store.close()
    ls.mark_damaged(lib.store.db_path, "test: a damaged store")
    assert h.until(lambda: not lib.writer.can_write(), seconds=M.MODE_RECHECK_S * 3)
    lib.writer.release()
    assert job.wait(30)
    view = job.job.view()
    assert job.outcome == "refused" and view.state == jobs.FAILED and view.message
    assert job.paths == [] and job.copied == []
    assert lib.graduated_files() == [] and len(os.listdir(os.path.join(lib.data_dir, ".trash"))) == 3
    assert _graduated_rows(lib.store.db_path) == 0 and lib.heard.saved == []


def test_S2_an_import_the_store_fails_keeps_no_copy_and_the_job_says_failed(lib, tmp_path, monkeypatch):
    def fails(self, paths):
        raise ls.NotInLibrary("not in the library: a folder moved meanwhile")
    monkeypatch.setattr(ls.Store, "import_finished", fails)
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    job = lib.run([folder])
    view = job.job.view()
    assert job.outcome == "failed" and view.state == jobs.FAILED and "a folder moved meanwhile" in view.message
    assert lib.graduated_files() == [] and len(os.listdir(os.path.join(lib.data_dir, ".trash"))) == 3
    assert lib.finished() == {} and lib.heard.saved == [] and not lib.writer.can_undo()


def test_a_copy_that_fails_half_way_sends_what_it_made_to_the_trash_and_says_why(lib, tmp_path, monkeypatch):
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    real = shutil.copy2
    n = []

    def copy2(src, dst, *a, **k):
        n.append(src)
        if len(n) == 2:
            with open(dst, "wb") as f:              # half a file, then the disk is full
                f.write(b"half")
            raise OSError(28, "No space left on device")
        return real(src, dst, *a, **k)
    monkeypatch.setattr(shutil, "copy2", copy2)
    job = lib.run([folder])
    view = job.job.view()
    assert job.outcome == "failed" and view.state == jobs.FAILED and "No space left" in view.message
    assert lib.graduated_files() == [] and lib.finished() == {} and lib.heard.saved == []
    assert len(os.listdir(os.path.join(lib.data_dir, ".trash"))) == 2, "the whole copy and the half one"


def test_nothing_to_import_is_a_job_done_with_nothing_written(lib, tmp_path):
    empty = tmp_path / "空のフォルダ"
    empty.mkdir()
    (empty / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    job = lib.run([str(empty)])
    assert job.outcome == "nothing" and job.job.view().state == jobs.DONE and lib.heard.saved == []


def test_undo_trashes_only_the_jobs_copies_never_a_file_that_was_already_in_finisheds_folder(lib, tmp_path):
    """A file already in `Graduated/` but no row yet (put there by hand) is imported where it is; its Undo leaves the
    file and its row — only what the job copied goes to the trash, with its row."""
    title, resource, tag = SHOW[lib.language]
    there = os.path.join(lib.data_dir, ls.GRADUATED_FOLDER, f"{title} 総集編.{tag}.srt")
    os.makedirs(os.path.dirname(there), exist_ok=True)
    shutil.copy2(os.path.join(h.RESOURCES, lib.language, resource), there)
    outside = lib.show_folder(str(tmp_path / "Downloads"), episodes=(1,))
    job = lib.run([there, outside])
    assert h.until(lambda: lib.heard.saved)
    assert len(job.paths) == 2 and len(job.copied) == 1
    lib.writer.undo()
    assert h.until(lambda: lib.heard.undone)
    # C2: a file it didn't copy stays where it was, row and all (Finished's folder is never walked)
    assert list(lib.finished()) == [f"{ls.GRADUATED_FOLDER}/{os.path.basename(there)}"] and os.path.isfile(there)
    assert not os.path.exists(job.copied[0])


# --- W3.2 H: the last fix round ------------------------------------------------------------------------------------ #
def test_H_F4_a_job_that_fails_after_the_writer_took_its_import_never_trashes_the_saved_copies(lib, tmp_path,
                                                                                              monkeypatch):
    """Once the import is the writer's, the job's own failure (its bar's end raising) sent the copies to the trash
    — rows saved, pointing at files that were gone. The copies are the writer's from the queue on."""
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    real = jobs.Job.finish
    calls = []

    def finish(self, *a, **k):
        calls.append(k)
        if len(calls) == 1:
            raise RuntimeError("the jobs bar went away")
        return real(self, *a, **k)
    monkeypatch.setattr(jobs.Job, "finish", finish)
    job = lib.run([folder])
    assert job.outcome == "failed"                      # (the job's own end said so)
    assert h.until(lambda: lib.heard.saved) and len(lib.finished()) == 3
    assert sorted(lib.finished()) == lib.graduated_files(), "every saved row's file is where it says"


def _held_import(lib, tmp_path):
    """An import whose store half waits behind a drag (the writer held): -> (job, its folder) once it is queued."""
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    lib.writer.hold()
    job = F.ImportJob(lib.language, [folder], lib.writer, lib.registry, data_dir=lib.data_dir)
    job.start()
    assert h.until(lambda: lib.writer.pending() == 1)
    return job, folder


def test_H_T3_stop_pressed_while_the_store_saves_takes_the_writers_answer_never_imported_for_a_refusal(lib,
                                                                                                     tmp_path):
    """T3: Stop while the job waited for the writer ended it *imported* — then the store refused the command and
    trashed the copies. The job's outcome now follows the writer's answer."""
    job, _folder = _held_import(lib, tmp_path)
    job.cancel()
    assert job.wait(10) and job.outcome == "pending"
    lib.store.close()
    ls.mark_damaged(lib.store.db_path, "test: a damaged store")
    assert h.until(lambda: not lib.writer.can_write(), seconds=M.MODE_RECHECK_S * 3)
    lib.writer.release()
    assert h.until(lambda: job.outcome == "refused")
    assert job.paths == [] and lib.graduated_files() == []


def test_H_T2_an_import_whose_writer_stopped_ends_stopped_and_stays_in_the_journal(lib, tmp_path, short_lock_wait):
    """T2: a language switch (or the quit) stopped the writer with the import queued: the job waited for an answer
    that never comes — RUNNING for ever, every later import of the session waiting behind it."""
    holder = LockHolder(lib.store.db_path)              # another program's save: the import can't land
    try:
        job = F.ImportJob(lib.language, [lib.show_folder(str(tmp_path / "Downloads"))], lib.writer, lib.registry,
                          data_dir=lib.data_dir)
        job.start()
        assert h.until(lambda: lib.writer.pending() == 1)
        lib.writer.finish(time.monotonic() + 0.3)       # the switch's wait ran out: the writer let go
        assert job.wait(5) and job.outcome == "stopped"
    finally:
        holder.release()
    assert job.job.view().state == jobs.DONE
    with open(M.journal_path(lib.language), encoding="utf-8") as f:
        assert [e["op"] for e in json.load(f)["pending"]] == ["import_finished"], "the next start lands it"


def test_H_F5_a_twin_copy_that_cant_go_to_the_trash_is_listed_never_left_hidden(lib, tmp_path, monkeypatch):
    """The same folder imported again makes `name_1.srt` twins, which go to the trash; one that couldn't stayed in
    Finished's folder — never walked, listed nowhere, outside Undo. Now it is listed as it stands."""
    folder = lib.show_folder(str(tmp_path / "Downloads"))
    lib.run([folder])
    assert h.until(lambda: len(lib.heard.saved) == 1)

    def held(data_dir, rel):
        raise PermissionError(13, "the file is open in another program")
    monkeypatch.setattr(ls, "trash_file", held)
    lib.run([folder])
    assert h.until(lambda: len(lib.heard.saved) == 2)
    assert len(lib.graduated_files()) == 6 and sorted(lib.finished()) == lib.graduated_files()


def test_H_F5_copies_a_cancel_couldnt_trash_are_listed_never_left_hidden(lib, tmp_path, monkeypatch):
    folder = lib.show_folder(str(tmp_path / "Downloads"), episodes=(1, 2, 3, 4))
    holder = {}

    def heard(snapshot):                                # the first file's progress: the user presses Stop
        for view in snapshot:
            if view.kind == F.KIND and view.progress is not None and view.progress.done == 1 and "job" in holder:
                holder.pop("job").cancel()
    lib.registry.subscribe(heard)

    def held(data_dir, rel):
        raise PermissionError(13, "the file is open in another program")
    monkeypatch.setattr(ls, "trash_file", held)
    job = F.ImportJob(lib.language, [folder], lib.writer, lib.registry, data_dir=lib.data_dir)
    holder["job"] = job
    job.start()
    assert job.wait(30) and job.outcome == "cancelled"
    assert h.until(lambda: not lib.writer.pending() and lib.graduated_files())
    assert sorted(lib.finished()) == lib.graduated_files()
