"""`surasura-cli pick` as a caller runs it (P1.3 row 1.3.3): a real Generate's list, a real subtitle from the library,
and — with the video — the run file for Anki Miner, written from the fake Anki Miner's own settings export. Anki is
closed (a closed loopback port), so the card check reads the backlog and says so.
"""
import json
import os

import pytest

from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


@pytest.fixture
def library():
    """A Japanese library generated once by `surasura-cli generate`; its subtitle, and a stand-in video beside it."""
    folder = h.seed_library("ja")
    h.write_settings()
    code, lines = h.run_cli("generate")
    assert code == 0 and h.answer(lines)["ran"] is True, lines
    subtitle = os.path.join(folder, "phrases_sample.srt")
    video = os.path.join(folder, "phrases_sample.mkv")
    with open(video, "wb") as f:
        f.write(b"\x1aE\xdf\xa3")
    return subtitle, video


def _list_words():
    import csv
    with open(os.path.join(h.root(), "results", "priority_learning_list.csv"), encoding="utf-8-sig") as f:
        return {(row["Word"], row["Reading"]) for row in csv.DictReader(f)}


def test_pick_sends_the_files_list_words_each_with_its_line(library):
    subtitle, _video = library
    code, lines = h.run_cli("pick", "--file", subtitle)
    result = h.answer(lines)
    assert code == 0 and result["ok"] and result["mode"] == "list", result
    assert result["words"] and {(w["word"], w["reading"]) for w in result["words"]} <= _list_words()
    assert all(isinstance(w["line_start"], float) and w["line_end"] > w["line_start"] for w in result["words"])
    assert result["cards_from"] == "backlog"            # Anki is closed: the last sync's backlog
    assert result["run_file"] is None                   # no video: nothing for Anki Miner


def test_with_the_video_the_run_file_is_written_from_anki_miners_own_settings(library, fake_miner):
    subtitle, video = library
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    code, lines = h.run_cli("pick", "--file", subtitle, "--video", video, "--job", "job-42")
    result = h.answer(lines)
    assert code == 0 and result["run_file"], result
    assert os.path.commonpath([result["run_file"], h.root()]) == h.root()      # under the test's own local data
    raw = open(result["run_file"], "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8"))
    episode = data["episodes"][0]
    assert data["profile"] == "p-surasura" and data["config"]["anki_deck_name"] == "DevTest"
    assert episode["run_id"] == "job-42-1" and episode["tags"] == "surasura::connect::job-42"
    assert os.path.normcase(episode["video_file"]) == os.path.normcase(os.path.abspath(video))
    assert [w["word"] for w in episode["words"]] == [n for w in result["words"] for n in w["sent"]]
    assert result["anki_miner"]["app"] == "3.5.0"
    assert "mine" not in fake_miner.commands()          # pick writes the run file; it never mines


def test_on_anki_miner_37_the_run_file_has_one_entry_a_word_and_needs_no_surasura_profile(library, fake_miner):
    # P1.3-AM37: every named word whitelisted (Z-1) -> your active profile; a word made from its line (Z-2) -> one
    # entry a word, with the word as written and its reading; the bold in the run's config (Z-5)
    from tests.connect.fake_anki_miner import FEATURES_37
    subtitle, video = library
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    fake_miner.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "default", "name": "Default", "active": True}])
    code, lines = h.run_cli("pick", "--file", subtitle, "--video", video, "--words", "unknown", "--job", "job-37")
    result = h.answer(lines)
    assert code == 0 and result["run_file"], result
    assert result["anki_miner"]["app"] == "3.7.0" and result["anki_miner"]["profile"] is None
    data = json.load(open(result["run_file"], encoding="utf-8"))
    assert "profile" not in data and data["config"]["bold_target_in_sentence"] is True
    entries = data["episodes"][0]["words"]
    assert all(len(w["sent"]) == 1 for w in result["words"])
    assert [e["word"] for e in entries] == [w["sent"][0] for w in result["words"]]
    assert all(e.get("reading") == w["front_reading"] for e, w in zip(entries, result["words"]))
    assert "mine" not in fake_miner.commands()


def test_pick_with_no_anki_miner_installed_still_picks_and_says_it_skipped(library, tmp_path):
    subtitle, video = library
    h.write_settings(connect_anki_miner_path=str(tmp_path / "nowhere" / "AnkiMiner.exe"))
    code, lines = h.run_cli("pick", "--file", subtitle, "--video", video)
    result = h.answer(lines)
    assert code == 0 and result["skipped"] == "anki miner absent" and result["words"] and result["run_file"] is None


def test_a_missing_surasura_profile_needs_you(library, fake_miner):
    subtitle, video = library
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    fake_miner.plan(profiles=[{"id": "default", "name": "Default"}])
    code, lines = h.run_cli("pick", "--file", subtitle, "--video", video)
    assert code == 4 and h.answer(lines)["code"] == "needs-you" and "Surasura" in h.answer(lines)["message"]


def test_without_a_list_pick_says_generate_first_and_unknown_still_works():
    folder = h.seed_library("ja")
    h.write_settings()
    subtitle = os.path.join(folder, "phrases_sample.srt")
    code, lines = h.run_cli("pick", "--file", subtitle)
    assert code == 2 and h.answer(lines)["code"] == "not-set-up"
    code, lines = h.run_cli("pick", "--file", subtitle, "--words", "unknown")
    assert code == 0 and h.answer(lines)["words"]


def test_a_subtitle_or_video_that_isnt_there_is_bad_data(library, tmp_path):
    subtitle, _video = library
    code, lines = h.run_cli("pick", "--file", str(tmp_path / "第02話.srt"))
    assert code == 1 and h.answer(lines)["code"] == "bad-data"
    code, lines = h.run_cli("pick", "--file", subtitle, "--video", str(tmp_path / "第02話.mkv"))
    assert code == 1 and h.answer(lines)["code"] == "bad-data"


def test_a_tv_caption_file_is_picked_and_mined_from_its_cleaned_copy(library, fake_miner):
    # Row 1.3.2: the pick reads, and the run file names, the copy without reading rows (the lines Anki Miner reads)
    import shutil
    _subtitle, video = library
    tv = os.path.join(os.path.dirname(video), "tv_captions.ass")
    shutil.copy2(os.path.join(h.RESOURCES, "ja", "tv_captions.ass"), tv)
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    code, lines = h.run_cli("pick", "--file", tv, "--video", video, "--words", "unknown", "--job", "tv-1")
    result = h.answer(lines)
    assert code == 0 and result["subtitle"] != os.path.abspath(tv), result
    assert "もんばん" not in open(result["subtitle"], encoding="utf-8").read()
    data = json.load(open(result["run_file"], encoding="utf-8"))
    assert data["episodes"][0]["subtitle_file"] == result["subtitle"]
    assert "門番" in {w["word"] for w in result["words"]}
