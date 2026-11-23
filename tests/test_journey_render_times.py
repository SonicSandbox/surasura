"""The journey v3 render's ▶ times and its rail's stones (J-TIMES; SPEC §5.4, §2.4).

The first-ever render of a big library found every playable line's times by reading its subtitle again
(`cues.timeline`), and kept every file's lines to the render's end: 78 MB at 20,000 files. `Sources.prepare` asks the
same questions a file at a time and lets each file's lines go; the timeline reads no name clues (it never tokenizes).
The rail drew a file Connect mined with nothing new to make as *rock* while the window drew it *raw*: the rail had no
status; now it reads Connect's (`status.nothing`) and draws by the same rule (`stone_plan.state_of`).

What a wrong answer would cost a learner: a ▶ that plays the wrong moment, or a stale one after the subtitle changed;
a page that differs from the one before for the same library; a stone on the rail that says the opposite of the
window's. Real Japanese and Chinese subtitles from tests/Test Resources; a real Connect ledger (FakeSteps). No sleeps.
"""
import gzip
import json
import os
import shutil
from types import SimpleNamespace

import pytest

from app import cues
from app import journey_render as jr
from app import static_html_generator as gen
from app.connect import feed, runner, status
from app.connect.ledger import Ledger
from app.services import stone_plan
from tests.connect.fake_steps import FakeSteps

RESOURCES = os.path.join(os.path.dirname(__file__), "Test Resources")
SUBTITLE = {"ja": os.path.join(RESOURCES, "ja", "airing", "夜明けの旅団 第01話.srt"),
            "zh": os.path.join(RESOURCES, "zh", "night_market.srt")}
# Each a sentence as the list keeps it (the tokenizer drops the spaces), one said over its own line in the file
LINES = {"ja": ["おい、起きろ。", "まだ眠いよ……あと五分だけ寝かせて。", "だめだ。今日中に峠を越えないと、次の町に着けない。"],
         "zh": ["大家好，歡迎回到我的頻道。", "今天我们要去台北的夜市吃东西。"]}
WORDS = {"ja": [("起きる", "おきる"), ("眠い", "ねむい"), ("峠", "とうげ")],
         "zh": [("欢迎", "huānyíng"), ("夜市", "yèshì")]}


class _NoPitch:
    def of(self, word, reading="", pinyin=""):
        return None


def _library(tmp_path, language, episodes=2):
    """`episodes` copies of the real subtitle in one show's folder, a video stand-in beside each (so ▶ plays)."""
    show = tmp_path / "data" / "Show"
    show.mkdir(parents=True)
    source_map, media = {}, {}
    for e in range(1, episodes + 1):
        name = f"ep{e:02d}.srt"
        shutil.copyfile(SUBTITLE[language], show / name)
        (show / f"ep{e:02d}.mp4").write_bytes(b"")
        rel = f"Show/{name}"
        source_map[rel] = {"name": name, "type": "subtitle", "abs": str(show / name)}
        media[rel] = (str(show / f"ep{e:02d}.mp4"), "")
    return source_map, media


def _rows(language, episodes=2):
    """Each word at its first episode, its sentences from every episode in turn — so the page asks one file's lines
    between the other's, as a real list does."""
    rows, lines = [], LINES[language]
    for k, (word, reading) in enumerate(WORDS[language]):
        e = k % episodes + 1
        row = {"Sequence": e, "Source File": f"ep{e:02d}.srt", "Word": word, "Orth": word, "Forms": word,
               "Reading": reading, "Occurrences (File)": 2.0, "Count (High)": 1.0, "Count (Low)": 0.0}
        for n in range(1, 4):
            row[f"Context {n}"] = lines[(k + n) % len(lines)]
            row[f"Src {n}"] = f"Show/ep{(k + n) % episodes + 1:02d}.srt"
        rows.append(row)
    return rows


def _stats(episodes=2):
    return [{"File": f"ep{e:02d}.srt"} for e in range(1, episodes + 1)]


def _sources(tmp_path, language, source_map, media):
    timer = gen.AnchorFinder(cache_path=str(tmp_path / "line_times.json"), language=language)
    return jr.Sources(language, source_map, None, media, timer), timer


def _lines_of(out):
    """Every word's lines as the chunks carry them: [text, source, start, end]."""
    found = []
    for chunk in out.chunks:
        for word in json.loads(gzip.decompress(chunk).decode("utf-8"))["w"]:
            found.extend(word[9] or ())         # a word's record: [word, orth, reading, kana, forms, …, its lines]
    return found


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_first_render_answers_a_file_at_a_time_and_keeps_no_files_lines(tmp_path, language, monkeypatch):
    source_map, media = _library(tmp_path, language)
    rows, stats = _rows(language), _stats()
    (tmp_path / "a").mkdir()
    sources, timer = _sources(tmp_path / "a", language, source_map, media)
    out = jr.build(language, rows, stats, settings={}, pitch=_NoPitch(), sources=sources, stamp="s")
    # why: every file's lines were let go once its sentences were answered (the 78 MB at 20k), and the folder
    # listings once every file was checked (31 MB)
    assert timer._timelines == {} and timer._dirs == {}
    asked = []
    # The page before the change: each line asked as `build` meets it, every file's lines kept
    monkeypatch.setattr(jr.Sources, "prepare", lambda self, asks: None)
    (tmp_path / "b").mkdir()
    before_sources, before_timer = _sources(tmp_path / "b", language, source_map, media)
    real = before_timer.times
    monkeypatch.setattr(before_timer, "times", lambda path, s: asked.append((path, s)) or real(path, s))
    before = jr.build(language, rows, stats, settings={}, pitch=_NoPitch(), sources=before_sources, stamp="s")
    assert len({p for p, _s in asked}) == 2 and len(before_timer._timelines) == 2
    assert out.chunks == before.chunks and jr._json(out.head) == jr._json(before.head)     # the page, byte for byte
    # and the times are the file's own: the sentence's line, in seconds
    times = {line[0]: tuple(line[2:4]) for line in _lines_of(out)}
    assert times[LINES[language][0]] == (1.2, 4.1 if language == "ja" else 3.8)
    timer.save_memo()
    before_timer.save_memo()
    assert (tmp_path / "a" / "line_times.json").read_bytes() == (tmp_path / "b" / "line_times.json").read_bytes()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_subtitle_changed_since_the_memo_is_read_again_never_a_stale_time(tmp_path, language):
    source_map, media = _library(tmp_path, language, episodes=1)
    rows, stats = _rows(language, 1), _stats(1)
    sources, timer = _sources(tmp_path, language, source_map, media)
    jr.build(language, rows, stats, settings={}, pitch=_NoPitch(), sources=sources)
    timer.save_memo()
    path = source_map["Show/ep01.srt"]["abs"]
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    # The first line now said four seconds later (and the file one byte longer: its signature moves)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace("00:00:01,200 -->", "00:00:05,200 --> ", 1))
    again, _timer = _sources(tmp_path, language, source_map, media)
    out = jr.build(language, rows, stats, settings={}, pitch=_NoPitch(), sources=again)
    times = {line[0]: tuple(line[2:4]) for line in _lines_of(out)}
    assert times[LINES[language][0]][0] == 5.2


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_an_empty_library_and_no_playable_file_ask_nothing(tmp_path, language):
    source_map, media = _library(tmp_path, language, episodes=1)
    sources, timer = _sources(tmp_path, language, source_map, {})       # nothing plays: no time asked
    out = jr.build(language, _rows(language, 1), _stats(1), settings={}, pitch=_NoPitch(), sources=sources)
    assert timer._timelines == {} and timer._entries == {}
    assert all(len(line) <= 2 for line in _lines_of(out))
    empty, timer = _sources(tmp_path, language, source_map, media)
    out = jr.build(language, [], [], settings={}, pitch=_NoPitch(), sources=empty)
    assert out.head["eps"] == [] and timer._entries == {}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_timeline_reads_no_name_clues_and_the_same_lines(language):
    path = SUBTITLE[language]
    with_clues, without = cues.read(path, language), cues.read(path, language, clues=False)
    assert list(with_clues) == list(without) and without.clues is None
    line = cues.timeline(path, language).line(LINES[language][1])
    assert line is not None and line[0] > 0


# --- the rail's stones ------------------------------------------------------------------------------------------ #

def _nothing_ledger(tmp_path, language):
    """A real ledger: Ep 1 made its cards, Ep 2 held only words already carded — mined with nothing new to make."""
    words = WORDS[language]
    plan = {"line": {language: [1, 2]}, "queue": {language: [1, 2]}, "words": {"1": words, "2": words}}
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        runner.run({}, [language], steps=FakeSteps(str(tmp_path), plan), ledger=ledger, sleep=lambda s: None,
                   looks=1)
        jobs = [(j["item_id"], j["state"], j.get("reason")) for j in ledger.jobs(language)]
    assert jobs == [(1, "done", None), (2, "done", runner.NO_WORDS)], f"why: Ep 2 must find nothing new: {jobs}"
    return path


def _facts(cards):
    items = {i: {"id": i, "rel_path": f"Show/ep{i:02d}.srt", "tier": "now", "work_id": 3, "parent_folder": "Show",
                 "watched": 0, "availability": "present", "ord": i, "source_type": "subtitle"} for i in (1, 2, 3)}
    works = {3: {"id": 3, "title": "夜明けの旅団", "media_type": "anime"}}
    return jr.StoreFacts(items, works, [1, 2, 3], cards, {}, {}, "e1")


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_file_mined_with_nothing_new_is_raw_on_the_rail_as_in_the_window(tmp_path, language):
    path = _nothing_ledger(tmp_path, language)
    nothing = jr.nothing_new(language, path)
    assert nothing == {2}
    out = jr.build(language, [], [], facts=_facts({1: 3}), pitch=_NoPitch(), nothing=nothing)
    eps = {e[0]: e[9] for e in out.head["eps"]}
    # the window's stone for Ep 2: its row's status is Connect's NOTHING item, read by the same rule
    item = feed.build(status.read(languages=[language], path=path), language).items[2]
    window = stone_plan.state_of(SimpleNamespace(watched=False, cards=0, status=item))
    assert eps == {1: "raw", 2: window, 3: "rock"} and window == "raw"


def test_no_ledger_or_a_newer_one_draws_no_status(tmp_path):
    assert jr.nothing_new("ja", str(tmp_path / "absent.sqlite")) == set()
    path = _nothing_ledger(tmp_path, "ja")
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(99),))
    conn.commit()
    conn.close()
    assert status.nothing("ja", path) == [] and jr.nothing_new("ja", path) == set()
    out = jr.build("ja", [], [], facts=_facts({}), pitch=_NoPitch())        # no status handed in: as before
    assert [e[9] for e in out.head["eps"]] == ["rock", "rock", "rock"]
