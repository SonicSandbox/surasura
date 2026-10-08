"""Connect's mine step on Anki Miner 3.7.0 (P1.3-AM37; API.md and `cli/api/contract.py` at tag v3.7.0, fee1c3b),
against the fake Anki Miner taught 3.7's contract and against a real 3.7.0's own answers, recorded
(`am370_recorded.json`: its `version` verdict and the result rows of two dry runs of the proof's episode, the
run file 3.6 was sent and the one 3.7 is sent now).

- any profile works once every named word is whitelisted (Z-1): the "Surasura" profile when Anki Miner has one, else
  the active one (Sonic, 2026-10-07: the separate profile is optional); before 3.7 it is still needed
- one entry a word, with the word as written and its reading (Z-2), so no word can make two cards
- the target bolded (Z-5); `from_line` and `filter` (Z-6) reach the outcome; 3.5 / 3.6 unchanged

The words are a real pick: the library episode's (`ja/library_episode.ass`), read by the cue reader.
"""
import json
import os

import pytest

from app import analyzer, cues
from app.connect import anki_miner, fields, pick, runfile
from tests.connect.fake_anki_miner import FEATURES_37, LAPIS_EXPORT

HERE = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.join(os.path.dirname(HERE), "Test Resources")
EPISODE = os.path.join(RESOURCES, "ja", "library_episode.ass")
RECORDED = os.path.join(HERE, "am370_recorded.json")
GRAMMAR = {"だ", "です", "為る", "の", "は", "を", "に", "が", "て", "た", "も", "と", "この", "ます", "ない", "か", "よ",
           "で", "から", "まで", "ん", "たい", "ので", "其れ", "此方", "御", "じゃあ", "又", "いえ", "済む"}
ONLY_DEFAULT = [{"id": "default", "name": "Default", "active": True}]


@pytest.fixture(scope="module")
def words(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.setenv("SURASURA_TEST_ROOT", str(tmp_path_factory.mktemp("words_root")))
    analyzer.SANITIZE_JA = True
    try:
        read = cues.read(EPISODE, "ja")
        chosen = pick.pick(read, cues.tokens(read, "ja"), "ja", lambda key: key[0] in GRAMMAR, mode="unknown")
    finally:
        analyzer.SANITIZE_JA = False
        patch.undo()
    picked = chosen["words"][:8]
    if not any(len(w["sent"]) > 1 for w in picked):                # keep one word that 3.6 sends twice (下さる)
        picked.append(next(w for w in chosen["words"] if len(w["sent"]) > 1))
    return picked


@pytest.fixture
def batch(tmp_path, fake_miner, words):
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")

    def run(attempt=1, profile="Surasura"):
        return anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), EPISODE, words,
                                     fields.from_export(LAPIS_EXPORT), profile, str(tmp_path / "runs" / "job-1"),
                                     "http://127.0.0.1:9", attempt=attempt)
    return run


def _check_args(fake_miner):
    return [c["argv"] for c in fake_miner.calls() if "argv" in c and c["argv"][1:2] == ["check"]]


# --------------------------------------------------------------------------- #
# The profile
# --------------------------------------------------------------------------- #
def test_on_37_any_profile_works_your_active_one_when_there_is_no_surasura_profile(batch, fake_miner, words):
    fake_miner.plan(app="3.7.0", features=FEATURES_37,
                    profiles=[{"id": "anime", "name": "Anime"}, {"id": "drama", "name": "Drama", "active": True}])
    done = batch()
    assert [o["outcome"] for o in done["outcomes"]] == ["made"] * len(words)
    # the active one, pinned by its id (review #5): checked and mined as one profile, whatever is active later
    assert fake_miner.run_files()[-1]["profile"] == "drama"
    assert _check_args(fake_miner)[-1][-2:] == ["--profile", "drama"]
    assert not os.path.exists(anki_miner.whitelist_path("ja"))      # no whitelist file to keep (Z-1)


def test_on_37_the_surasura_profile_is_still_used_when_anki_miner_has_it(batch, fake_miner):
    fake_miner.plan(app="3.7.0", features=FEATURES_37)
    batch()
    assert fake_miner.run_files()[-1]["profile"] == "p-surasura"
    assert _check_args(fake_miner)[-1][-2:] == ["--profile", "p-surasura"]


def test_on_37_an_empty_profile_setting_is_the_active_profile(batch, fake_miner):
    fake_miner.plan(app="3.7.0", features=FEATURES_37, profiles=ONLY_DEFAULT)
    batch(profile="")
    assert fake_miner.run_files()[-1]["profile"] == "default"
    fake_miner.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "default", "name": "Default"}])
    batch(profile="", attempt=2)
    assert "profile" not in fake_miner.run_files()[-1]              # none marked active: Anki Miner's own choice


def test_a_profile_you_named_that_anki_miner_lacks_is_never_swapped_for_another(batch, fake_miner):
    # Review #4: only the default "Surasura" is optional; a name you chose yourself and Anki Miner no longer has
    # needs you, on 3.7 as before it
    fake_miner.plan(app="3.7.0", features=FEATURES_37, profiles=ONLY_DEFAULT)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch(profile="Anime JP")
    assert e.value.kind == "needs-you" and "Anime JP" in e.value.message and "mine" not in fake_miner.commands()


def test_a_profile_name_matches_whatever_its_case(batch, fake_miner):
    fake_miner.plan(app="3.7.0", features=FEATURES_37)
    batch(profile="surasura")
    assert fake_miner.run_files()[-1]["profile"] == "p-surasura"


@pytest.mark.parametrize("app, features", [("3.5.0", []), ("3.6.0", ["sentence-rules-off"])])
def test_before_37_a_missing_profile_still_needs_you(batch, fake_miner, app, features):
    fake_miner.plan(app=app, features=features, profiles=ONLY_DEFAULT)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch()
    assert e.value.kind == "needs-you" and "Surasura" in e.value.message and "mine" not in fake_miner.commands()


# --------------------------------------------------------------------------- #
# One entry a word: no word makes two cards
# --------------------------------------------------------------------------- #
def test_on_37_each_word_goes_once_with_its_surface_and_reading_and_no_word_makes_two_cards(
        batch, fake_miner, words):
    # Every name made from its line, as 3.7 makes a word its own reading doesn't find there: still one card a word
    fake_miner.plan(app="3.7.0", features=FEATURES_37, from_line=[n for w in words for n in w["sent"]])
    done = batch()
    entries = fake_miner.run_files()[-1]["episodes"][0]["words"]
    assert [e["word"] for e in entries] == [w["sent"][0] for w in words]           # one entry a word, its front
    # a reading only for a word Anki Miner may not find by itself (review #2): its own reading stands otherwise
    assert all(e.get("reading") == (w["front_reading"] if w["predicted_class"] else None)
               for e, w in zip(entries, words))
    assert any("reading" in e for e in entries) and any("reading" not in e for e in entries)
    two = next(w for w in words if len(w["sent"]) > 1)
    entry = entries[words.index(two)]
    assert entry.get("surface") == (two["surface"] if two["surface"] != two["sent"][0] else None)
    assert two["word"] not in [e["word"] for e in entries]                         # its Word goes no more
    assert any("surface" in e for e in entries)                                    # 借り(たい): as written
    rows = done["result"]["words"]
    assert len(rows) == len(words) and sum(r["status"] == "created" for r in rows) == len(words)
    assert len({r["note_id"] for r in rows}) == len(words)
    assert all(o["outcome"] == "made" and o["from_line"] for o in done["outcomes"])


def test_the_two_entry_shape_would_make_two_cards_of_one_word_on_37(tmp_path, fake_miner, words):
    # The risk the change removes, in the fake's terms (every name it is told is made from its line): the card front
    # and Surasura's Word both made, two notes of one word. The real 3.7 did it for 時 / とき (recorded, below); for
    # 下さる it would answer `duplicate`, as both names reach one word on the line.
    two = next(w for w in words if len(w["sent"]) > 1)
    fake_miner.plan(app="3.7.0", features=FEATURES_37, from_line=two["sent"])
    run_dir = tmp_path / "runs"
    episode = runfile.episode("old-1", str(tmp_path / "e.mkv"), EPISODE, runfile.word_requests([two]))
    path = runfile.write(str(run_dir / "run.json"), runfile.build(str(run_dir), "ja", [episode]))
    verdict = anki_miner.api(fake_miner.path, ["mine", path])
    rows = anki_miner.read_result(str(run_dir), "old-1", verdict["runs"][0]["file"])["words"]
    assert [r["status"] for r in rows] == ["created", "created"]                     # two cards of 下さる
    # ... and what Connect sends 3.7 now: one entry, one card
    episode = runfile.episode("new-1", str(tmp_path / "e.mkv"), EPISODE, runfile.word_requests([two], FEATURES_37))
    path = runfile.write(str(run_dir / "run.json"), runfile.build(str(run_dir), "ja", [episode]))
    verdict = anki_miner.api(fake_miner.path, ["mine", path])
    rows = anki_miner.read_result(str(run_dir), "new-1", verdict["runs"][0]["file"])["words"]
    assert [r["status"] for r in rows] == ["created"]


def test_before_37_a_word_still_goes_as_its_front_and_its_word(batch, fake_miner, words):
    fake_miner.plan(app="3.6.0", features=["sentence-rules-off", "named-words-whitelisted"])
    batch()
    entries = fake_miner.run_files()[-1]["episodes"][0]["words"]
    assert [e["word"] for e in entries] == [n for w in words for n in w["sent"]]
    assert not any("surface" in e or "reading" in e for e in entries)
    assert "bold_target_in_sentence" not in fake_miner.run_files()[-1]["config"]


def test_a_word_sent_twice_before_37_still_takes_the_better_outcome(batch, fake_miner, words):
    two = next(w for w in words if len(w["sent"]) > 1)
    fake_miner.plan(app="3.6.0", statuses={two["sent"][0]: "not_found", two["sent"][1]: "duplicate"})
    done = batch()
    assert done["outcomes"][words.index(two)]["outcome"] == "duplicate"


# --------------------------------------------------------------------------- #
# What else 3.7 says and takes
# --------------------------------------------------------------------------- #
def test_on_37_the_target_is_bolded_and_the_sentence_keys_stay_out(batch, fake_miner):
    fake_miner.plan(app="3.7.0", features=FEATURES_37)
    batch()
    config = fake_miner.run_files()[-1]["config"]
    assert config["bold_target_in_sentence"] is True
    assert not any(k in config for k in runfile.SENTENCE_KEYS)


def test_a_word_the_merge_removed_says_so(batch, fake_miner, words):
    front = words[0]["sent"][0]
    fake_miner.plan(app="3.7.0", features=FEATURES_37, statuses={front: "not_found"},
                    filter={front: "duplicate-expression"})
    done = batch()
    assert done["outcomes"][0]["outcome"] == "not_found" and done["outcomes"][0]["filter"] == "duplicate-expression"
    assert done["outcomes"][1]["filter"] is None and done["outcomes"][1]["from_line"] is False


def test_every_37_feature_is_known_by_its_ask():
    info = {"features": FEATURES_37 + ["something-later"]}
    assert anki_miner.features(info) == {"Z-1", "Z-2", "Z-3", "Z-4", "Z-5", "Z-6", "Z-7", "Z-8", "Z-10", "Z-11",
                                         "Z-12", "Z-13"}


# --------------------------------------------------------------------------- #
# A real 3.7.0's own answers, recorded
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def recorded():
    with open(RECORDED, encoding="utf-8") as f:
        return json.load(f)


def test_a_real_37_version_answer_reads_as_37(fake_miner, recorded):
    fake_miner.plan(replay={"version": recorded["version"]})
    info = anki_miner.version(fake_miner.path)
    assert info["app"] == "3.7.0" and {"Z-1", "Z-2", "Z-5"} <= anki_miner.features(info)
    assert runfile.from_line(info["features"]) and not runfile.sends_sentence_keys(info["app"], info["features"])


def test_on_a_real_37_the_two_entry_shape_makes_two_cards_and_one_entry_one(recorded):
    # The proof episode's line 時間があるときに電話して。: 3.7 makes とき from its line, and 時 (Surasura's Word, the
    # second entry) from the same line, found inside 時間: two fronts, two cards. One entry a word: one card.
    def fronts_by_word(shape, features):
        words, rows, out, at = recorded[shape]["words"], recorded[shape]["rows"], {}, 0
        for w in words:
            n = len(runfile.entries(w, features))
            out[w["word"]] = {r["mined_form"] for r in rows[at:at + n] if r["status"] == "ready"}
            at += n
        assert at == len(rows)
        return out
    features = recorded["version"]["result"]["features"]
    old = fronts_by_word("dry_run_two_entries", ())
    assert old["時"] == {"とき", "時"}
    assert [w for w, fronts in old.items() if len(fronts) > 1] == ["時"]
    new = fronts_by_word("dry_run", features)
    assert all(len(fronts) == 1 for fronts in new.values()) and new["時"] == {"とき"}


def test_a_real_37_dry_run_reads_back_one_row_a_word(recorded):
    # The proof's words as sent (one entry each) and the rows the real build gave back for them, in order
    words, rows = recorded["dry_run"]["words"], recorded["dry_run"]["rows"]
    assert len(rows) == len(words) and [r["word"] for r in rows] == [w["sent"][0] for w in words]
    fronts = [r["mined_form"] for r in rows if r["status"] == "ready"]
    assert len(fronts) == len(set(fronts))                          # no word would be made twice
    out = anki_miner.outcomes(words, rows, features=recorded["version"]["result"]["features"])
    assert [o["word"] for o in out] == [w["word"] for w in words]
    assert {o["outcome"] for o in out} == {"ready"}                 # a dry run's words: ready, nothing made
    assert any(o["from_line"] for o in out) == any(r["from_line"] for r in rows)
