"""The run file for Anki Miner's `--api mine` (app/connect/runfile.py, P1.3 row 1.3.4): written strict UTF-8 with no BOM
(K61), refused before a byte is written when Anki Miner would refuse it (a surrogate, an unknown key, an empty word
list), the two sentence keys only to a version that takes them (am-upstream D1), and round-tripped intact."""
import json
import os

import pytest

from app.connect import fields, runfile
from tests.connect.fake_anki_miner import LAPIS_EXPORT

MAPPING = fields.from_export(LAPIS_EXPORT)
WORDS = [
    {"word": "図書館", "sent": ["図書館"], "line_start": 90.0, "line_expansion": [0, 1]},
    {"word": "下さる", "sent": ["ください", "下さる"], "line_start": 103.0, "line_expansion": [2, 0]},
    {"word": "延長", "sent": ["延長"], "line_start": 116.4, "line_expansion": [0, 0]},
]


def _data(tmp_path, words=WORDS, **config):
    episode = runfile.episode("job-7-1", str(tmp_path / "第01話.mkv"), str(tmp_path / "第01話.ja.ass"),
                              runfile.word_requests(words), tags=runfile.job_tag("job-7"))
    return runfile.build(str(tmp_path / "runs" / "job-7"), "ja", [episode], profile="p-surasura",
                         run_config=runfile.config(MAPPING, config.pop("app", "3.5.0"), config.pop("features", [])))


def test_a_run_file_round_trips_strict_utf8_without_a_bom(tmp_path):
    path = runfile.write(str(tmp_path / "runs" / "job-7" / "run-1.json"), _data(tmp_path))
    raw = open(path, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8", errors="strict"))
    assert data == json.loads(json.dumps(_data(tmp_path)))
    assert os.path.isdir(data["run_dir"])                          # Anki Miner refuses a run_dir that isn't there
    # each word's entries in order, Surasura's Word after its card front, the line's expansion always sent
    assert [w["word"] for w in data["episodes"][0]["words"]] == ["図書館", "ください", "下さる", "延長"]
    assert data["episodes"][0]["words"][2] == {"word": "下さる", "line_start": 103.0, "line_expansion": [2, 0]}
    assert "図書館" in raw.decode("utf-8")                          # written as itself, not \\u escapes


@pytest.mark.parametrize("app, features, sent", [
    ("3.5.0", [], True), ("3.6.0", [], True), ("3.6.2", [], True),
    ("3.7.0", [], False), ("4.0.0", [], False),
    ("3.6.0", ["sentence-rules-off"], False),
    ("not a version", [], False),
])
def test_the_sentence_keys_by_version_and_features(app, features, sent):
    assert runfile.sends_sentence_keys(app, features) is sent
    config = runfile.config(MAPPING, app, features)
    assert all((k in config) is sent for k in runfile.SENTENCE_KEYS)
    assert set(config) <= runfile.CONFIG_KEYS


def test_without_sentence_keys_takes_only_those_two_out(tmp_path):
    data = _data(tmp_path)
    out = runfile.without_sentence_keys(data)
    assert set(data["config"]) - set(out["config"]) == set(runfile.SENTENCE_KEYS)
    assert out["episodes"] == data["episodes"]


def test_a_lone_surrogate_is_refused_before_anything_is_written(tmp_path):
    # A file name or a subtitle line that Windows handed over with an unpaired surrogate: 3.6.0's BAD_RUN_FILE
    words = [dict(WORDS[0], sent=["図書\ud800館"])]
    path = tmp_path / "runs" / "job-7" / "run-1.json"
    with pytest.raises(runfile.RunFileError, match="surrogate"):
        runfile.write(str(path), _data(tmp_path, words))
    assert not path.exists()


@pytest.mark.parametrize("change, says", [
    (lambda d: d.update(extra=1), "unknown keys"),
    (lambda d: d.update(config=None), "config must be an object"),
    (lambda d: d["config"].update(whitelist_path="x"), "doesn't take"),
    (lambda d: d["episodes"][0].update(words=[]), "names no word"),
    (lambda d: d["episodes"][0].update(run_id="第1話"), "run_id"),
    (lambda d: d["episodes"].append(dict(d["episodes"][0])), "share a run_id"),
    (lambda d: d["episodes"][0]["words"][0].update(line_start=float("nan")), "finite"),
    (lambda d: d["episodes"][0]["words"][0].update(line_start=-1.0), "finite"),
    (lambda d: d["episodes"][0]["words"][0].update(word="  "), "empty"),
    (lambda d: d.update(episodes=[]), "at least one episode"),
])
def test_what_anki_miner_would_refuse_is_never_written(tmp_path, change, says):
    data = _data(tmp_path)
    change(data)
    with pytest.raises(runfile.RunFileError, match=says):
        runfile.write(str(tmp_path / "run.json"), data)
    assert not (tmp_path / "run.json").exists()


def test_a_run_file_over_8_mb_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(runfile, "MAX_BYTES", 200)
    with pytest.raises(runfile.RunFileError, match="bytes"):
        runfile.write(str(tmp_path / "run.json"), _data(tmp_path))


def test_rewriting_a_run_file_replaces_it_whole(tmp_path):
    path = str(tmp_path / "runs" / "job-7" / "run-1.json")
    runfile.write(path, _data(tmp_path))
    runfile.write(path, runfile.without_sentence_keys(_data(tmp_path)))
    data = json.load(open(path, encoding="utf-8"))
    assert not any(k in data["config"] for k in runfile.SENTENCE_KEYS)
    assert [p for p in os.listdir(os.path.dirname(path)) if p.endswith(".tmp")] == []


# --------------------------------------------------------------------------- #
# Anki Miner 3.7.0 (P1.3-AM37): what its `features` name, and only then
# --------------------------------------------------------------------------- #
FEATURES_37 = ["sentence-rules-off", "bold-target", "named-words-whitelisted", "script-fold", "filter-names",
               "word-from-line", "dry-run", "render", "media", "settings-import", "setup", "fetch", "beside-window"]
# pick's words as 3.7 is sent them: the word as its line writes it, and its card front's reading in hiragana
WORDS_37 = [
    {"word": "図書館", "sent": ["図書館"], "surface": "図書館", "front_reading": "としょかん", "line_start": 90.0,
     "line_expansion": [0, 1]},
    {"word": "下さる", "sent": ["くださる", "下さる"], "surface": "ください", "front_reading": "くださる",
     "line_start": 103.0, "line_expansion": [2, 0]},
    {"word": "借りる", "sent": ["借りる"], "surface": "借り", "front_reading": "かりる", "line_start": 116.4,
     "line_expansion": [0, 0]},
]


def test_on_37_each_word_goes_once_with_the_word_as_written_and_its_reading():
    # Z-2: a second name (Surasura's Word) could be made from the same line as a second card; one entry a word
    requests = runfile.word_requests(WORDS_37, FEATURES_37)
    assert [r["word"] for r in requests] == ["図書館", "くださる", "借りる"]
    assert "surface" not in requests[0]                             # written as its front: nothing to add
    assert requests[1] == {"word": "くださる", "line_start": 103.0, "line_expansion": [2, 0], "surface": "ください",
                           "reading": "くださる"}
    assert requests[2]["surface"] == "借り" and requests[2]["reading"] == "かりる"


def test_before_37_the_words_go_as_before_with_no_new_keys():
    requests = runfile.word_requests(WORDS_37, ["named-words-whitelisted", "sentence-rules-off"])
    assert [r["word"] for r in requests] == ["図書館", "くださる", "下さる", "借りる"]
    assert all(set(r) == {"word", "line_start", "line_expansion"} for r in requests)


def test_a_word_with_no_reading_or_an_empty_surface_goes_without_them():
    # Chinese keeps no reading; a blank surface would be Anki Miner's BAD_RUN_FILE
    words = [{"word": "夜市", "sent": ["夜市"], "surface": " ", "front_reading": None, "line_start": 3.0,
              "line_expansion": [0, 0]}]
    (request,) = runfile.word_requests(words, FEATURES_37)
    assert set(request) == {"word", "line_start", "line_expansion"}


@pytest.mark.parametrize("features, bold", [([], False), (["named-words-whitelisted"], False), (FEATURES_37, True)])
def test_the_target_is_bolded_only_where_anki_miner_takes_it(features, bold):
    config = runfile.config(MAPPING, "3.7.0", features)
    assert config.get("bold_target_in_sentence") is (True if bold else None)
    assert set(config) <= runfile.CONFIG_KEYS


def test_a_37_run_file_with_bold_a_dry_run_and_surface_round_trips(tmp_path):
    episode = runfile.episode("job-7-1", str(tmp_path / "第01話.mkv"), str(tmp_path / "第01話.ja.ass"),
                              runfile.word_requests(WORDS_37, FEATURES_37), tags=runfile.job_tag("job-7"))
    data = runfile.build(str(tmp_path / "runs" / "job-7"), "ja", [episode],
                         run_config=runfile.config(MAPPING, "3.7.0", FEATURES_37), dry_run=True)
    assert "profile" not in data                                    # Anki Miner's active profile
    path = runfile.write(str(tmp_path / "runs" / "job-7" / "run-1.json"), data)
    written = json.load(open(path, encoding="utf-8"))
    assert written["dry_run"] is True and written["config"]["bold_target_in_sentence"] is True
    assert not any(k in written["config"] for k in runfile.SENTENCE_KEYS)
    assert "dry_run" not in runfile.build(str(tmp_path), "ja", [episode])     # a real run says nothing of it


@pytest.mark.parametrize("change, says", [
    (lambda d: d.update(dry_run="yes"), "dry_run"),
    (lambda d: d["episodes"][0]["words"][1].update(surface="  "), "surface"),
    (lambda d: d["episodes"][0]["words"][1].update(reading=""), "reading"),
    (lambda d: d["episodes"][0]["words"][0].update(line_text=" "), "line_text"),
])
def test_what_37_would_refuse_is_never_written(tmp_path, change, says):
    episode = runfile.episode("job-7-1", str(tmp_path / "a.mkv"), str(tmp_path / "a.ass"),
                              runfile.word_requests(WORDS_37, FEATURES_37))
    data = runfile.build(str(tmp_path / "runs"), "ja", [episode], run_config=runfile.config(MAPPING, "3.7.0",
                                                                                             FEATURES_37))
    change(data)
    with pytest.raises(runfile.RunFileError, match=says):
        runfile.write(str(tmp_path / "run.json"), data)
    assert not (tmp_path / "run.json").exists()
