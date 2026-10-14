"""hato's pairings back-filled (P3.2 rows 3.2.4–3.2.5; 09-hato-layer v2 §4): `hato.backfill` asks the stand-in hato-cli
(`connect_helpers.fake_hato`, started as a real program through `subprocess`) for its pairings and registers every line
through `register`'s own code (`connect_verbs.register_record`).

What a wrong answer would cost:
  * a back-fill that logged a placement event would mine every old episode in hato's folder the moment the preview is
    switched on — the very thing Connect's watermark is there to stop;
  * one that wrote anything when run again (hato now marking each line registered) would rewrite the library at every
    switch-on and every *Ask hato again*;
  * one that went on past a busy library, or registered any of an answer it can't trust (cut short, torn, too big,
    from a failed run), would leave pairings half-made or made from a broken answer;
  * a *Needs you* entry per file, or one that counts again each time nothing changed, buries the real ones; one never
    fixed stays for good;
  * the preview off must be 2.5 byte for byte: hato isn't even asked.

Real Japanese and Chinese subtitles from tests/Test Resources (each copy its own bytes), synthetic titles and videos,
the test's own root and its own shared tools folder (HOUSEKI_TOOLS_DIR)."""
import json
import os
import subprocess
import sys
import time

import pytest

from app import library_store, settings_manager
from app.connect import hato, inbox, library
from app.connect import ledger as book
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

DAY = 86400.0
HATO = library_store.HATO_FOLDER
VERDICTS = ("timed", "timed", "forced", "extracted", "untimed")     # what hato 1.1.0 sends (09-hato-layer v2 §1.2)
FOUR = "4 files in hato's folder have no pairing from hato, so Connect can't tell which video they belong to."


@pytest.fixture(autouse=True)
def tools(tmp_path, monkeypatch):
    """Every test's own shared tools folder: the real one is never read or written."""
    folder = tmp_path / "houseki-tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    return folder


def _settings():
    return settings_manager.load_settings(strict=True)


def _switched_on(lang="ja"):
    """Connect's watermark set as the switch sets it: from here on, a logged event is work for Connect."""
    with c.store(lang) as s:
        library.switch_on(s)


def _lines(paths, start=1, title="Example Show", lang="ja", registered=None):
    """hato's lines for these library copies: episodes from `start`, every verdict and timing reference hato sends."""
    return [c.pairing_line(c.hato_record(path, n, lang=lang, verdict=VERDICTS[n % len(VERDICTS)],
                                         reference=c.REFERENCES[n % 3], title=title), registered)
            for n, path in enumerate(paths, start)]


def _pairings(lang="ja"):
    """{library_path: item id} of the store's pairings."""
    with c.store(lang) as s:
        return {json.loads(p)["library_path"]: i for i, p in s.conn.execute("SELECT item_id, pairing FROM pairings")}


def _log():
    path = os.path.join(h.root(), "local", "logs", hato.LOG_FILE)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _old(path, days=10):
    """A file hato copied long ago: last changed `days` before now."""
    at = time.time() - days * DAY
    os.utime(path, (at, at))
    return path


def _since(days=1):
    return c.iso(time.time() - days * DAY)


# --- the 60 old files ---------------------------------------------------------------------------------------------

def test_sixty_old_flat_files_and_a_series_folder_are_paired_with_no_event_and_again_nothing_is_written(tmp_path):
    """The ~60 files already in hato's flat folder, plus a per-series folder's, get their pairings the day the preview
    goes on — matched by path — and nothing is mined because of it. Asked again (hato now marking each line
    registered), every line answers `same`: the store, its copy and every other file stay as they are."""
    flat = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 61)]
    series = [c.drop(f"Other Show - {n:02d}.ja.srt", folder=HATO + "/Other Show") for n in range(1, 4)]
    c.library()                                     # the window's sync found them long ago: items already
    _switched_on()
    lines = _lines(flat) + _lines(series, title="Other Show")
    fake = c.fake_hato(tmp_path, lines, c.result_line(63, _since()))
    out = hato.backfill("ja", _settings())
    assert (out["hato"], out["new"], out["same"], out["replaced"], out["refused"], out["unpaired"],
            out["stopped"]) == (hato.ASKED, 63, 0, 0, [], [], None), out
    assert fake.calls() == [{"argv": ["pairings", "--json", "--lang", "ja"], "stdin_closed": True}]
    paired = _pairings()
    assert sorted(paired) == sorted(flat + series)
    with c.store() as s:
        rows, gap = s.read_events(library.READER)
        assert not gap and rows == [], "no placement event: nothing mined because of the back-fill"
        assert not inbox.pending(s)
    again = [dict(line, registered={"file_id": paired[line["library_path"]], "at": "2026-10-12T09:00:00Z"})
             for line in lines]
    fake.plan(again, c.result_line(63, _since()))
    before, stored = c.snapshot(), c.store_state()
    out = hato.backfill("ja", _settings())
    assert (out["new"], out["same"], out["replaced"], out["refused"]) == (0, 63, 0, []), out
    assert c.snapshot() == before and c.store_state() == stored, "nothing written: the store, its copy, every file"
    with c.store() as s, Ledger() as ledger:
        assert inbox.consume(s, "ja", ledger)["queued"] == [] and ledger.jobs("ja") == [], "no job queued"
    assert "hato's pairings (Japanese): 0 new, 63 already there." == hato.say(out)


def test_drops_the_window_hasnt_synced_are_added_with_no_event_of_their_own_and_no_job(tmp_path):
    """hato's newer drops (a per-series folder) that the window hasn't synced yet: the back-fill adds them as items at
    the top of NOW, and none of them logs an event (an added item is where `entered_mine_line` would be — what Connect
    mines). The items they push out of the top 20 are logged as having left it (they did: a waiting job of theirs
    isn't due any more); nothing enters it, so no job is queued."""
    flat = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 21)]
    c.library()
    _switched_on()
    series = [c.drop(f"Other Show - {n:02d}.ja.srt", folder=HATO + "/Other Show") for n in range(1, 4)]
    c.fake_hato(tmp_path, _lines(series, title="Other Show"), c.result_line(3, None))
    out = hato.backfill("ja", _settings())
    assert (out["new"], out["refused"], out["stopped"]) == (3, [], None), out
    added = {_pairings()[p] for p in series}
    with c.store() as s:
        assert len(added) == 3 and {s.place_of(i)[0] for i in added} == {"now"}, "the new drops added, in NOW"
        rows, gap = s.read_events(library.READER)
    assert not gap and [r for r in rows if r[1] in added] == [], "no event of their own: never mined because of it"
    assert {r[2] for r in rows} <= {"left_mine_line"}, "the items pushed down only leave the top 20"
    with c.store() as s, Ledger() as ledger:
        assert inbox.consume(s, "ja", ledger)["queued"] == [] and ledger.jobs("ja") == [], "no job queued"


def test_a_line_hato_marks_registered_that_this_store_lacks_is_registered(tmp_path):
    """09-hato-layer v2, the back-fill: every line is registered, so a `registered` mark this store doesn't hold (a
    store rebuilt since hato registered it) is mended, never trusted."""
    paths = [c.drop("Example Show - 01.ja.srt")]
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, _lines(paths, registered={"file_id": 4182, "at": "2026-10-05T11:42:08Z"}),
                c.result_line(1, None))
    out = hato.backfill("ja", _settings())
    assert out["new"] == 1 and list(_pairings()) == paths
    with c.store() as s:
        stored = json.loads(s.conn.execute("SELECT pairing FROM pairings").fetchone()[0])
    assert "registered" not in stored and "type" not in stored, "the record kept as hato's record v1, nothing more"


def test_a_line_surasura_refuses_is_counted_and_logged_and_the_others_are_paired(tmp_path):
    """A copy changed since hato paired it, a path outside the library (`bad-data`), a newer record (`version-skew`)
    and another language's line (`usage`) are each refused and logged; the rest go on."""
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 6)]
    c.library()
    _switched_on()
    lines = _lines(paths)
    with open(paths[1], "ab") as f:
        f.write("\n終わり\n".encode("utf-8"))                   # the copy isn't the file hato paired any more
    outside = tmp_path / "Example Show - 09.ja.srt"
    with open(paths[0], "rb") as f:
        outside.write_bytes(f.read() + b"\n09\n")
    lines.append(c.pairing_line(c.hato_record(str(outside), 9)))
    lines[2] = dict(lines[2], schema=2)
    lines[3] = c.pairing_line(c.hato_record(paths[3], 4, lang="zh"))
    c.fake_hato(tmp_path, lines, c.result_line(6, None))
    out = hato.backfill("ja", _settings())
    assert [(p, code) for p, code, _m in out["refused"]] == [
        (paths[1], "bad-data"), (paths[2], "version-skew"), (paths[3], "usage"), (str(outside), "bad-data")]
    assert out["new"] == 2 and sorted(_pairings()) == sorted([paths[0], paths[4]])
    log = _log()
    assert "refused (bad-data)" in log and paths[1] in log and str(outside) in log
    assert "4 refused: the logs say why." in hato.say(out)


def test_a_busy_library_stops_the_back_fill_there_and_keeps_what_was_registered(tmp_path, monkeypatch):
    """The library's write lock held past the wait on the third line: the back-fill stops there ("try again later")
    and the two before it stay registered; the lines after it aren't tried, so nothing is paired around a gap."""
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 6)]
    c.library()
    _switched_on()
    real = library_store.register_headless

    def held_at_the_third(language, path, pairing, **kw):
        if path == paths[2]:
            raise library_store.StoreBusy("another Surasura program holds the library")
        return real(language, path, pairing, **kw)
    monkeypatch.setattr(library_store, "register_headless", held_at_the_third)
    c.fake_hato(tmp_path, _lines(paths), c.result_line(5, None))
    out = hato.backfill("ja", _settings(), wait=0.3)
    assert out["new"] == 2 and out["refused"] == [] and "Try again" in out["stopped"], out
    assert sorted(_pairings()) == sorted(paths[:2]), "the earlier lines kept, the later ones not tried"
    assert "try again later" in hato.say(out)


def test_connect_switched_off_part_way_stops_the_back_fill_at_the_next_line(tmp_path, monkeypatch):
    """settings.json is read again for each line (as hato's own `register` reads it): the preview switched off while a
    back-fill runs, the next line writes nothing — and no *Needs you* entry is raised after it."""
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 4)]
    _old(c.drop("Example Show - 09.ja.srt"))                    # an old file no line names
    c.library()
    _switched_on()
    real = library_store.register_headless

    def then_off(*a, **kw):
        done = real(*a, **kw)
        settings_manager.save_keys({"connect_enabled": False})
        return done
    monkeypatch.setattr(library_store, "register_headless", then_off)
    c.fake_hato(tmp_path, _lines(paths), c.result_line(3, _since()))
    out = hato.backfill("ja", _settings())
    assert out["new"] == 1 and out["stopped"] == "Connect's preview was switched off."
    assert list(_pairings()) == paths[:1]
    assert out["need"] is None and not os.path.exists(book.path()), "nothing more of Connect's written"


# --- an answer it can't use -----------------------------------------------------------------------------------------

def _filler(size):
    """`size` bytes and more of lines hato might add (a type the back-fill doesn't read)."""
    line = b'{"type":"note","pad":"' + b"x" * (1 << 20) + b'"}\n'
    return line * (size // len(line) + 1)


@pytest.mark.parametrize("trouble", [
    "absent", "schema-2", "contract-2", "cli-missing", "no-pairings-verb", "exit-1", "timeout", "torn-line",
    "no-result", "result-not-ok", "over-16-mib", "over-the-cap-read", "not-utf-8", "since-not-a-time"])
def test_an_answer_it_cant_use_registers_nothing_and_logs_why(trouble, tmp_path, monkeypatch):
    """hato absent, too new, its program gone, too old to offer its pairings; a failed run, no answer in time, a torn
    line, no result line, more than 16 MiB, not UTF-8: nothing is registered (no line of a broken answer is
    trusted), and the reason is in the log and the summary's words."""
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in (1, 2)]
    c.library()
    _switched_on()
    lines = _lines(paths)
    result = c.result_line(2, None)
    fake = c.fake_hato(tmp_path, lines, result)
    run = None
    good = b"".join(json.dumps(x, ensure_ascii=False).encode("utf-8") + b"\n" for x in lines + [result])
    if trouble == "absent":
        os.remove(os.path.join(os.environ["HOUSEKI_TOOLS_DIR"], "hato.json"))
    elif trouble == "schema-2":
        fake.entry(schema=2)
    elif trouble == "contract-2":
        fake.entry(contract=2)
    elif trouble == "cli-missing":
        fake.entry(cli=str(tmp_path / "uninstalled" / "hato-cli.exe"))
    elif trouble == "no-pairings-verb":
        fake.entry(verbs=[])
    elif trouble == "exit-1":
        fake.plan(lines, result, exit=1)
    elif trouble == "timeout":
        monkeypatch.setattr(hato, "TIMEOUT", 1.0)
        fake.plan(lines, result, delay=10)
    elif trouble == "torn-line":
        fake.plan(lines[:1] + [json.dumps(lines[1], ensure_ascii=False)[:60]], result)
    elif trouble == "no-result":
        fake.plan(lines, None)
    elif trouble == "result-not-ok":
        fake.plan(lines, dict(result, ok=False))
    elif trouble == "over-16-mib":
        run = lambda argv, timeout: (0, _filler(hato.MAX_OUT) + good)        # noqa: E731
    elif trouble == "over-the-cap-read":                    # the real reader stops a bigger answer itself
        monkeypatch.setattr(hato, "MAX_OUT", 64 * 1024)
        fake.plan(lines, result, pad=1 << 20)
    elif trouble == "not-utf-8":
        torn = json.dumps(dict(lines[0], show={"title": "例の番組"}), ensure_ascii=False).encode("cp932")
        run = lambda argv, timeout: (0, torn + b"\n" + good)                 # noqa: E731
    elif trouble == "since-not-a-time":
        fake.plan(lines, dict(result, complete_since="yesterday"))
    before, stored = c.snapshot(), c.store_state()
    out = hato.backfill("ja", _settings(), run=run)
    assert out["hato"] != hato.ASKED and (out["new"], out["same"], out["refused"]) == (0, 0, []), out
    assert _pairings() == {} and c.snapshot() == before and c.store_state() == stored, "nothing registered"
    assert out["hato"] in _log(), "the reason logged"
    assert hato.say(out).startswith("hato couldn't be asked for its pairings (Japanese): ")
    assert not os.path.exists(book.path()), "no Needs you entry from an answer it can't use"


def test_hato_is_started_with_no_window_and_its_stdin_closed(monkeypatch):
    """A console window flashing up at every switch-on, or a hato waiting on a stdin nobody writes: neither."""
    seen = {}

    def popen(argv, **kw):
        seen.update(kw, argv=argv)
        raise OSError("not installed here")
    monkeypatch.setattr(hato.subprocess, "Popen", popen)
    with pytest.raises(hato.Unavailable) as e:
        hato.pairings(r"C:\Tools\hato\hato-cli.exe", "ja")
    assert "couldn't be started" in e.value.reason
    assert seen["argv"] == [r"C:\Tools\hato\hato-cli.exe", "pairings", "--json", "--lang", "ja"]
    assert seen["stdin"] is subprocess.DEVNULL and seen["stderr"] is subprocess.DEVNULL
    assert seen["creationflags"] == (hato.CREATE_NO_WINDOW if sys.platform == "win32" else 0)


# --- no pairing from hato -------------------------------------------------------------------------------------------

def test_old_files_no_line_names_are_one_need_naming_how_many_and_a_newer_one_isnt_counted(tmp_path):
    """09-hato-layer v2 §4: files in hato's folder (sub-folders too) last changed before `complete_since` that no line
    names are one *Needs you* entry for the language, saying how many, the files themselves in the log. A newer one
    (hato still copying it, or registering it itself) isn't counted."""
    paired = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in (1, 2)]
    lonely = [_old(c.drop(f"Example Show - {n:02d}.ja.srt")) for n in (3, 4, 5)]
    lonely.append(_old(c.drop("Other Show - 01.ja.srt", folder=HATO + "/Other Show")))
    newer = c.drop("Example Show - 06.ja.srt")
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, _lines(paired), c.result_line(2, _since()))
    out = hato.backfill("ja", _settings())
    assert sorted(out["unpaired"]) == sorted(lonely) and newer not in out["unpaired"]
    assert out["need"] == "raised"
    with Ledger() as ledger:
        needs = ledger.needs("ja")
    assert [(n["kind"], n["say"], n["item_id"]) for n in needs] == [("no-pairing", FOUR, None)], "one, not one a file"
    log = _log()
    assert all(path in log for path in lonely) and newer not in log, "the files themselves in the log"
    assert hato.say(out).endswith(FOUR)
    from app.connect import status
    record = status.read(["ja"])["languages"]["ja"]
    assert [n["kind"] for n in record["needs"]] == ["no-pairing"] and record["unseen"] == 1, "Needs you lists it"


def test_one_file_with_no_pairing_is_said_in_the_singular(tmp_path):
    lonely = _old(c.drop("Example Show - 03.ja.srt"))
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, [], c.result_line(0, _since()))
    out = hato.backfill("ja", _settings())
    assert out["unpaired"] == [lonely]
    with Ledger() as ledger:
        assert [n["say"] for n in ledger.needs("ja")] == [
            "1 file in hato's folder has no pairing from hato, so Connect can't tell which video it belongs to."]


def test_complete_since_null_lists_nothing_and_makes_no_ledger(tmp_path):
    """hato can't say since when its pairings are complete: nothing is guessed, nothing listed."""
    _old(c.drop("Example Show - 03.ja.srt"))
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, [], c.result_line(0, None))
    out = hato.backfill("ja", _settings())
    assert out["hato"] == hato.ASKED and out["unpaired"] == [] and out["need"] is None
    assert not os.path.exists(book.path())


def test_the_same_count_again_is_no_new_badge_a_new_count_is_and_pairing_them_all_fixes_it(tmp_path):
    """The entry counts in the badge only when its words change: asked again with the same four files, nothing is
    written (it stays seen); a fifth makes it count again; hato pairing them all fixes it (a line in the log)."""
    paired = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in (1, 2)]
    lonely = [_old(c.drop(f"Example Show - {n:02d}.ja.srt")) for n in (3, 4, 5, 6)]
    c.library()
    _switched_on()
    fake = c.fake_hato(tmp_path, _lines(paired), c.result_line(2, _since()))
    assert hato.backfill("ja", _settings())["need"] == "raised"
    with Ledger() as ledger:
        (need,) = ledger.needs("ja")
        ledger.mark_seen([need["id"]])                          # *Needs you* shown: the badge stops counting it
    assert hato.backfill("ja", _settings())["need"] == "kept"
    with Ledger() as ledger:
        assert [(n["id"], n["say"], bool(n["seen_at"])) for n in ledger.needs("ja")] == [(need["id"], FOUR, True)]
        assert ledger.needs("ja", unseen=True) == [], "the same count again: no new badge"
    lonely.append(_old(c.drop("Example Show - 07.ja.srt")))
    assert hato.backfill("ja", _settings())["need"] == "raised"
    with Ledger() as ledger:
        assert [n["say"][:7] for n in ledger.needs("ja", unseen=True)] == ["5 files"], "new words: it counts again"
        assert len(ledger.needs("ja", listed=False)) == 1, "still one entry"
    fake.plan(_lines(paired) + _lines(lonely, start=3), c.result_line(7, _since()))
    out = hato.backfill("ja", _settings())
    assert (out["need"], out["unpaired"], out["new"], out["same"]) == ("fixed", [], 5, 2)
    with Ledger() as ledger:
        assert ledger.needs("ja", listed=False) == [], "fixed by a back-fill that finds none left"
    assert "fixed by itself (ja, no-pairing)" in _log()


def test_a_dismissed_entry_stays_dismissed_while_its_count_changes(tmp_path):
    """*Dismiss* takes it off the list until its cause goes (03-actors §4): a changed count doesn't bring it back."""
    lonely = [_old(c.drop(f"Example Show - {n:02d}.ja.srt")) for n in (3, 4, 5, 6)]
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, [], c.result_line(0, _since()))
    hato.backfill("ja", _settings())
    with Ledger() as ledger:
        (need,) = ledger.needs("ja")
        ledger.dismiss(need["id"])
    lonely.append(_old(c.drop("Example Show - 07.ja.srt")))
    assert hato.backfill("ja", _settings())["need"] == "kept"
    with Ledger() as ledger:
        assert ledger.needs("ja") == [] and len(ledger.needs("ja", listed=False)) == 1


# --- the preview off, Chinese ---------------------------------------------------------------------------------------

def test_with_the_preview_off_hato_isnt_asked_and_nothing_is_written(tmp_path):
    """2.5 byte for byte: `skipped`, the stand-in never started, no store write, no ledger, no log."""
    paths = [c.drop("Example Show - 01.ja.srt")]
    _old(c.drop("Example Show - 02.ja.srt"))
    c.library(connect=False)
    fake = c.fake_hato(tmp_path, _lines(paths), c.result_line(1, _since()))
    before, stored = c.snapshot(), c.store_state()
    out = hato.backfill("ja", _settings())
    assert out["skipped"] == "connect preview off" and out["hato"] is None and out["new"] == 0
    assert fake.calls() == [], "hato never asked"
    assert c.snapshot() == before and c.store_state() == stored
    assert not os.path.exists(book.path()) and _log() == ""
    assert hato.say(out) == "hato's pairings (Japanese) weren't asked for: Connect's preview is off."


def test_a_chinese_line_lands_in_chinese_store(tmp_path):
    """Each language is asked for its own (`--lang zh`): a Chinese pairing lands in the Chinese library — an old item
    and a new drop the back-fill adds — with no event."""
    paths = [c.drop("示例节目 - 01.zh.srt", "zh")]
    c.library("zh")
    _switched_on("zh")
    paths.append(c.drop("示例节目 - 02.zh.srt", "zh"))         # copied while Surasura was closed: not an item yet
    fake = c.fake_hato(tmp_path, _lines(paths, lang="zh", title="示例节目"), c.result_line(2, None))
    out = hato.backfill("zh", _settings())
    assert (out["hato"], out["new"], out["refused"]) == (hato.ASKED, 2, []), out
    assert fake.calls()[0]["argv"] == ["pairings", "--json", "--lang", "zh"]
    assert sorted(_pairings("zh")) == sorted(paths)
    with c.store("zh") as s:
        rows, _gap = s.read_events(library.READER)
        assert rows == [] and not inbox.pending(s)
    assert hato.say(out) == "hato's pairings (Chinese): 2 new, 0 already there."


# --- the review's rows (P3.2 fixer) -----------------------------------------------------------------------------------

def _answer(lines, result):
    """hato's answer as bytes, each line ASCII-escaped JSON (so a lone surrogate travels as hato would send it)."""
    return b"".join(json.dumps(x).encode("ascii") + b"\n" for x in list(lines) + [result])


def test_a_second_back_fill_while_one_runs_answers_at_once_that_hato_is_being_asked(tmp_path):
    """*Ask hato again* pressed while the switch's back-fill still waits for hato (up to a minute): the second one
    answers at once, "hato is being asked already", and hato isn't started a second time."""
    # why: one back-fill at a time in a process; a second that queued behind the first left the window's note on
    # "Asking hato…" for up to a minute with nothing said, then asked hato all over again
    import threading
    c.fake_hato(tmp_path, [], c.result_line(0, None))
    started, release, asked = threading.Event(), threading.Event(), []

    def slow(argv, timeout):
        asked.append(argv)
        started.set()
        release.wait(10)
        return 0, _answer([], c.result_line(0, None))
    first, second = {}, {}
    one = threading.Thread(target=lambda: first.update(hato.backfill("ja", {"connect_enabled": True}, run=slow)))
    two = threading.Thread(target=lambda: second.update(hato.backfill("ja", {"connect_enabled": True}, run=slow)))
    one.start()
    try:
        assert started.wait(10)
        two.start()
        two.join(2)
        assert not two.is_alive(), "the second back-fill answered at once, never waiting behind the first"
    finally:
        release.set()
        one.join(10)
        if two.ident is not None:
            two.join(10)
    assert first["hato"] == hato.ASKED and len(asked) == 1, "hato asked once"
    assert (second["hato"], second["new"], second["need"]) == (hato.ASKING, 0, None)
    assert hato.say(second) == "hato is being asked already (Japanese); try again once it has answered."


def test_the_same_count_again_takes_no_write_lock_on_the_ledger_of_its_own(tmp_path, monkeypatch):
    """Asked again with the same files left: the entry is kept as it is, and only read — no write transaction beyond
    the one the ledger's opening always takes."""
    # why: a back-fill with nothing new to say that takes the ledger's write lock waits behind a Connect run writing
    # it (up to 5 s), for a write it never makes
    import sqlite3
    for n in (3, 4, 5, 6):
        _old(c.drop(f"Example Show - {n:02d}.ja.srt"))
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, [], c.result_line(0, _since()))
    assert hato.backfill("ja", _settings())["need"] == "raised"
    statements, real = [], sqlite3.connect

    def traced(target, *a, **k):
        conn = real(target, *a, **k)
        if str(target).endswith("ledger.sqlite"):
            conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(book.sqlite3, "connect", traced)
    assert hato.backfill("ja", _settings())["need"] == "kept"
    opened = statements.index("COMMIT")             # the ledger's opening (its tables made if absent)
    assert [s for s in statements[opened + 1:] if s.startswith("BEGIN")] == [], statements[opened + 1:]
    with Ledger() as ledger:
        assert [n["say"] for n in ledger.needs("ja")] == [FOUR]


@pytest.mark.parametrize("error, refused", [
    (PermissionError(13, "The process cannot access the file because it is being used by another process"), True),
    (RuntimeError("a fault of Surasura's own"), False)], ids=["locked", "other-fault"])
def test_a_line_whose_subtitle_cant_be_read_is_refused_and_the_rest_go_on(error, refused, tmp_path, monkeypatch):
    """One copy hato paired that can't be read just now (another program holding it, an unreadable copy): that line
    is refused, counted and logged, and the lines after it are paired. Any other fault still stops the back-fill."""
    # why: hato's order is stable, so a read error that stopped the back-fill stopped it at the same line every time:
    # every line after it would never be paired
    from app.cli import connect_verbs
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 5)]
    c.library()
    _switched_on()
    real = connect_verbs._sha256

    def reads(path):
        if path == paths[1]:
            raise error
        return real(path)
    monkeypatch.setattr(connect_verbs, "_sha256", reads)
    c.fake_hato(tmp_path, _lines(paths), c.result_line(4, None))
    out = hato.backfill("ja", _settings())
    if refused:
        assert out["stopped"] is None and out["new"] == 3, out
        assert [(p, code) for p, code, _m in out["refused"]] == [(paths[1], "unreadable")]
        assert sorted(_pairings()) == sorted(paths[:1] + paths[2:])
        assert "refused (unreadable)" in _log() and "1 refused: the logs say why." in hato.say(out)
    else:
        assert out["new"] == 1 and out["refused"] == [] and "RuntimeError" in out["stopped"], out
        assert list(_pairings()) == paths[:1]


def test_a_line_with_a_lone_surrogate_in_its_path_is_refused_and_the_rest_go_on(tmp_path):
    """A line whose `library_path` holds a lone surrogate (valid JSON, never a file name Surasura can write down):
    refused and logged, the others paired."""
    # why: the record's UTF-8 size check raised UnicodeEncodeError, which stopped the back-fill there every time
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 4)]
    c.library()
    _switched_on()
    lines = _lines(paths)
    lines[1] = dict(lines[1], library_path=paths[1][:-len(".ja.srt")] + "\ud800.ja.srt")
    c.fake_hato(tmp_path, [], c.result_line(0, None))
    out = hato.backfill("ja", _settings(), run=lambda argv, timeout: (0, _answer(lines, c.result_line(3, None))))
    assert out["stopped"] is None and out["new"] == 2, out
    assert [code for _p, code, _m in out["refused"]] == ["bad-data"]
    assert sorted(_pairings()) == sorted([paths[0], paths[2]])
    assert "refused (bad-data)" in _log() and "\\ud800" in _log(), "logged, the surrogate written as an escape"


def _count_opens(monkeypatch):
    """Every store handle opened from here on (each `Store` made)."""
    opened, real = [], library_store.Store.__init__

    def counting(self, *a, **k):
        opened.append(1)
        return real(self, *a, **k)
    monkeypatch.setattr(library_store.Store, "__init__", counting)
    return opened


def test_the_lines_go_through_one_store_handle_back_to_back(tmp_path, monkeypatch):
    """Every line of one answer is registered through the one store handle the first opened (measured on already
    paired lines: 60 took 0.88 s with a handle a line and 0.11 s with one; 2,000 took 139 s and 3.9 s)."""
    # why: opening the store costs 14 ms on a 60-item library and 68 ms on a 2,000-item one, so a handle a line made
    # a back-fill of a large Hato folder take minutes, at every switch-on and every *Ask hato again*
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 7)]
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, _lines(paths), c.result_line(6, None))
    opened = _count_opens(monkeypatch)
    out = hato.backfill("ja", _settings())
    assert out["new"] == 6 and out["stopped"] is None, out
    assert len(opened) == 1, f"one handle for the six lines, not {len(opened)}"
    assert library_store._span() is None, "the span ends with the lines"


def test_a_busy_library_is_waited_for_with_no_store_handle_held_then_the_rest_go_on(tmp_path, monkeypatch):
    """Another Surasura program writing the library at the third line: the handle the lines shared is let go before
    the back-fill waits for the library, the line is tried again after the wait, and the rest go on in a new span."""
    # why: a span held across a lock's wait keeps a store handle open through another program's write (a store marked
    # damaged meanwhile couldn't be set aside by Repair): spans are for store work back to back only
    import types
    from app.cli import connect_verbs
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 7)]
    c.library()
    _switched_on()
    real, busy, waits = library_store.register_headless, [2], []

    def busy_twice_at_the_third(language, path, pairing, **kw):
        if path == paths[2] and busy[0]:
            busy[0] -= 1
            raise library_store.StoreBusy("another Surasura program holds the library")
        return real(language, path, pairing, **kw)
    monkeypatch.setattr(library_store, "register_headless", busy_twice_at_the_third)
    monkeypatch.setattr(connect_verbs, "time", types.SimpleNamespace(
        monotonic=time.monotonic, sleep=lambda s: waits.append(library_store._span() is None)))
    c.fake_hato(tmp_path, _lines(paths), c.result_line(6, None))
    opened = _count_opens(monkeypatch)
    out = hato.backfill("ja", _settings())
    assert out["new"] == 6 and out["stopped"] is None and out["refused"] == [], out
    assert waits and all(waits), "every wait for the library with no span (no handle) held"
    assert len(opened) == 3, "the lines before it, the busy line after its wait, the rest: one handle each"


def test_a_back_fill_the_switch_stopped_says_connect_was_switched_off_never_try_again_later():
    """The learner turned Connect off: the words say so, and never send them to try again."""
    # why: "it stopped part-way, so try again later" reads as a fault to retry, after the learner's own switch-off
    out = {"language": "ja", "hato": hato.ASKED, "new": 1, "same": 0, "replaced": 0, "refused": [], "unpaired": [],
           "stopped": hato.SWITCHED_OFF, "skipped": None, "need": None}
    assert hato.say(out) == "hato's pairings (Japanese): 1 new, 0 already there. Connect was switched off, so it " \
                            "stopped."


@pytest.mark.parametrize("when", ["no-lines", "after-the-last-line"])
def test_connect_switched_off_with_no_line_left_to_see_it_raises_no_need(when, tmp_path, monkeypatch):
    """The preview switched off while hato is asked (it has no lines), or after the last line was registered: no
    line comes after to see it, so settings.json is read again before the *Needs you* entry — off, none is raised and
    the back-fill says it stopped."""
    # why: the per-line read sees a switch-off only at the next line; without one, an entry was raised with the
    # preview off (with the preview off nothing of Connect's is written)
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in (1, 2)]
    _old(c.drop("Example Show - 09.ja.srt"))                    # an old file no line names
    c.library()
    _switched_on()
    lines = [] if when == "no-lines" else _lines(paths)
    answer = _answer(lines, c.result_line(len(lines), _since()))
    real = library_store.register_headless

    def then_off(language, path, pairing, **kw):
        done = real(language, path, pairing, **kw)
        if path == paths[-1]:
            settings_manager.save_keys({"connect_enabled": False})
        return done
    monkeypatch.setattr(library_store, "register_headless", then_off)

    def run(argv, timeout):
        if when == "no-lines":
            settings_manager.save_keys({"connect_enabled": False})
        return 0, answer
    c.fake_hato(tmp_path, [], c.result_line(0, None))
    out = hato.backfill("ja", _settings(), run=run)
    assert out["new"] == len(lines) and out["stopped"] == hato.SWITCHED_OFF, out
    assert out["need"] is None and out["unpaired"] == [] and not os.path.exists(book.path()), "nothing of Connect's"
