"""The Anki Miner caller (app/connect/anki_miner.py, P1.3 row 1.3.5) against the fake Anki Miner (07-tests §1): every
status, BUSY, a timeout, a crash, an unknown schema, features on and off, the whitelist file, the sentence keys by
version, and each returned line checked against the one sent.

The words are a real pick: the library episode's (`ja/library_episode.ass`), read by the cue reader.
"""
import json
import os
import subprocess

import pytest

from app import analyzer, cues
from app.connect import anki_miner, fields, pick, runfile
from tests.connect.fake_anki_miner import LAPIS_EXPORT

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
EPISODE = os.path.join(RESOURCES, "ja", "library_episode.ass")
GRAMMAR = {"だ", "です", "為る", "の", "は", "を", "に", "が", "て", "た", "も", "と", "この", "ます", "ない", "か", "よ",
           "で", "から", "まで", "ん", "たい", "ので", "其れ", "此方", "御", "じゃあ", "又", "いえ", "済む", "下さる"}


@pytest.fixture(scope="module")
def words(tmp_path_factory):
    # A module fixture runs before each test's own root (conftest): without one of its own, reading the episode read
    # the user's real token store for the library's name tables, and every copy's run read the same one.
    patch = pytest.MonkeyPatch()
    patch.setenv("SURASURA_TEST_ROOT", str(tmp_path_factory.mktemp("words_root")))
    analyzer.SANITIZE_JA = True
    try:
        read = cues.read(EPISODE, "ja")
        chosen = pick.pick(read, cues.tokens(read, "ja"), "ja", lambda key: key[0] in GRAMMAR, mode="unknown")
    finally:
        analyzer.SANITIZE_JA = False
        patch.undo()
    return chosen["words"][:6]


@pytest.fixture
def batch(tmp_path, fake_miner, words):
    """mine_batch with the fake, a stand-in video, the Lapis mapping, into a run folder of the test's own."""
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")                 # the fake never opens it; a real one checks it with ffprobe
    mapping = fields.from_export(LAPIS_EXPORT)

    def run(attempt=1, **kw):
        return anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), EPISODE, words, mapping, "Surasura",
                                     str(tmp_path / "runs" / "job-1"), "http://127.0.0.1:9", attempt=attempt, **kw)
    return run


# --------------------------------------------------------------------------- #
# Finding it
# --------------------------------------------------------------------------- #
def test_find_takes_the_setting_first_and_never_a_path_that_isnt_there(tmp_path, fake_miner):
    assert anki_miner.find({"connect_anki_miner_path": fake_miner.path}) == fake_miner.path
    assert anki_miner.find({"connect_anki_miner_path": str(tmp_path / "AnkiMiner.exe")}) is None
    # nothing set and (here) no install found: absent, the step is skipped (E7)
    assert anki_miner.find({}) is None


def test_find_reads_the_installers_folder_then_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SURASURA_TEST_ROOT")        # outside a test root (the guard below is the test's own)
    installed = tmp_path / "Programs" / "AnkiMiner"
    installed.mkdir(parents=True)
    (installed / "AnkiMiner.exe").write_bytes(b"MZ")
    monkeypatch.setattr(anki_miner, "_registry_location", lambda: str(installed))
    assert anki_miner.find({}) == str(installed / "AnkiMiner.exe")
    monkeypatch.setattr(anki_miner, "_registry_location", lambda: None)
    monkeypatch.setattr(anki_miner, "_default_location", lambda: str(installed))
    assert anki_miner.find({"connect_anki_miner_path": ""}) == str(installed / "AnkiMiner.exe")


# --------------------------------------------------------------------------- #
# One batch
# --------------------------------------------------------------------------- #
def test_under_a_test_root_no_install_is_ever_looked_for(tmp_path, monkeypatch):
    installed = tmp_path / "Programs" / "AnkiMiner"
    installed.mkdir(parents=True)
    (installed / "AnkiMiner.exe").write_bytes(b"MZ")
    monkeypatch.setattr(anki_miner, "_registry_location", lambda: str(installed))
    assert anki_miner.find({}) is None              # SURASURA_TEST_ROOT is set: only the setting's path counts


def test_a_batch_makes_every_word_and_returns_its_note_id(batch, fake_miner, words):
    done = batch()
    assert [o["outcome"] for o in done["outcomes"]] == ["made"] * len(words)
    assert all(isinstance(o["note_id"], int) for o in done["outcomes"])
    assert [o["word"] for o in done["outcomes"]] == [w["word"] for w in words]
    assert not any(o["other_line"] for o in done["outcomes"])
    # version, profiles and check are read before the batch (E9, E10), then mine
    assert fake_miner.commands() == ["version", "profiles", "check", "mine"]


def test_the_run_file_is_strict_utf8_without_a_bom_and_names_the_job(batch, fake_miner, words):
    done = batch()
    raw = open(done["run_file"], "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8"))
    episode = data["episodes"][0]
    assert data["profile"] == "p-surasura" and data["language"] == "ja"
    assert episode["tags"] == "surasura::connect::job-1" and episode["subtitle_offset"] == 0.0
    sent = [name for w in words for name in w["sent"]]
    assert [w["word"] for w in episode["words"]] == sent
    assert all("line_expansion" in w and isinstance(w["line_start"], float) for w in episode["words"])
    # every filter of Anki Miner's off; deck, note type and fields from its own export
    config = data["config"]
    assert config["anki_deck_name"] == "DevTest" and config["anki_note_type"] == "Lapis"
    assert config["anki_fields"]["word"] == "Expression" and config["min_frequency_rank"] == 0
    assert "use_whitelist" not in config            # the profile's own: its whitelist is how names pass (N10)


def test_the_whitelist_is_rewritten_with_the_batchs_names_until_anki_miner_whitelists_named_words(
        batch, fake_miner, words):
    batch()
    path = anki_miner.whitelist_path("ja")
    with open(path, "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8").splitlines() == list(dict.fromkeys(n for w in words for n in w["sent"]))
    os.remove(path)
    fake_miner.plan(features=["named-words-whitelisted"])         # Z-1 shipped: no whitelist file any more
    batch(attempt=2)
    assert not os.path.exists(path)


@pytest.fixture
def anki_tags(monkeypatch):
    """A fake AnkiConnect for the one write a batch makes itself: the names' tag. Records each addTags."""
    from app import anki_connect
    calls = []

    def invoke(action, url, timeout=30, **params):
        assert action == "addTags"
        from app import locks
        assert locks.held_here(anki_connect.WRITER_LOCK)        # inside the batch's own hold
        calls.append(params)
        return None
    monkeypatch.setattr(anki_connect, "invoke", invoke)
    return calls


def test_cards_made_for_names_are_tagged_after_mining_inside_the_writer_hold(tmp_path, fake_miner, words, anki_tags):
    named = [dict(w, name=(n % 2 == 1)) for n, w in enumerate(words)]      # every other word a name
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    fake_miner.plan(statuses={name: "duplicate" for name in named[1]["sent"]})     # a name with a card already
    done = anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), EPISODE, named,
                                 fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs" / "job-1"),
                                 "http://127.0.0.1:8765")
    episodes = fake_miner.run_files()[-1]["episodes"]
    assert len(episodes) == 1 and episodes[0]["tags"] == "surasura::connect::job-1"     # one episode, the job's tag
    made_names = [o["note_id"] for w, o in zip(named, done["outcomes"]) if w["name"] and o["outcome"] == "made"]
    assert made_names and done["tagged"] == made_names and done["tag_pending"] == []
    assert anki_tags == [{"notes": made_names, "tags": "surasura::name"}]


def test_a_tag_anki_refuses_is_left_pending_for_the_ledger(tmp_path, fake_miner, words, monkeypatch):
    from app import anki_connect

    def refused(action, url, timeout=30, **params):
        raise anki_connect.AnkiError("Anki closed mid-batch", "offline")
    monkeypatch.setattr(anki_connect, "invoke", refused)
    named = [dict(w, name=True) for w in words]
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    done = anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), EPISODE, named,
                                 fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs" / "job-1"),
                                 "http://127.0.0.1:8765")
    assert done["tagged"] == [] and done["tag_pending"] == [o["note_id"] for o in done["outcomes"]]


def test_a_batch_waits_for_no_other_writer_and_says_who_holds_anki(batch, fake_miner):
    from app import anki_connect, locks
    with locks.take(anki_connect.WRITER_LOCK, "順 reorder"):
        import threading
        failed = {}

        def other():
            try:
                batch()
            except anki_miner.AnkiMinerError as e:
                failed["e"] = e
        t = threading.Thread(target=other)
        t.start()
        t.join(60)
    assert failed["e"].kind == "writer-busy" and "順 reorder" in failed["e"].message
    assert "mine" not in fake_miner.commands()


def test_version_profiles_and_check_are_read_again_before_every_batch(batch, fake_miner):
    batch()
    fake_miner.plan(app="3.6.0")                    # updated between batches (E10)
    done = batch(attempt=2)
    assert fake_miner.commands().count("version") == 2 and done["app"] == "3.6.0"


@pytest.mark.parametrize("app, features, sent", [
    ("3.5.0", [], True),
    ("3.6.0", [], True),
    ("3.7.0", [], False),
    ("3.6.0", ["sentence-rules-off"], False),        # Z-4 shipped: the rules are off whatever the version says
])
def test_the_two_sentence_keys_go_only_to_a_version_that_takes_them(batch, fake_miner, app, features, sent):
    fake_miner.plan(app=app, features=features)
    batch()
    config = fake_miner.run_files()[-1]["config"]
    assert all((k in config) is sent for k in runfile.SENTENCE_KEYS)
    if sent:
        assert config["deduplicate_sentences"] is False and config["use_i_plus_one_filter"] is False


def test_a_build_that_refuses_the_sentence_keys_while_it_says_36_is_asked_once_more_without_them(
        batch, fake_miner, words):
    # Anki Miner's main branch: still 3.6.0, refuses both keys with BAD_RUN_FILE (am-upstream D1)
    fake_miner.plan(app="3.6.0", mine="refuse-sentence-keys")
    done = batch()
    assert fake_miner.commands().count("mine") == 2
    assert [o["outcome"] for o in done["outcomes"]] == ["made"] * len(words)
    assert not any(k in json.load(open(done["run_file"], encoding="utf-8"))["config"] for k in runfile.SENTENCE_KEYS)


# --------------------------------------------------------------------------- #
# What comes back
# --------------------------------------------------------------------------- #
def test_each_status_is_its_outcome_and_a_word_sent_twice_takes_the_better(batch, fake_miner, words):
    statuses = ["duplicate", "not_found", "no_definition", "media_failed", "refused", "not_attempted"]
    plan = {w["sent"][0]: s for w, s in zip(words, statuses)}
    two = next((w for w in words if len(w["sent"]) > 1), None)
    if two is not None:
        plan[two["sent"][0]], plan[two["sent"][1]] = "not_found", "duplicate"
    fake_miner.plan(statuses=plan)
    done = batch()
    for word, outcome in zip(words, done["outcomes"]):
        expected = plan[word["sent"][0]]
        if word is two:
            expected = "duplicate"                  # its Word found the card his card front missed
        assert outcome["outcome"] == expected, word
        assert outcome["note_id"] is None


def test_an_unknown_status_is_uncertain():
    out = anki_miner.outcomes([{"word": "図書館", "reading": "トショカン", "sent": ["図書館"], "line_start": 90.0}],
                              [{"word": "図書館", "status": "half-made", "line_start": 90.0}])
    assert out[0]["outcome"] == "uncertain"


@pytest.mark.parametrize("shift, other", [(0.04, False), (0.06, True), (12.5, True)])
def test_a_card_on_another_line_is_seen_by_its_start(batch, fake_miner, words, shift, other):
    fake_miner.plan(shift={words[0]["sent"][0]: shift})
    done = batch()
    assert done["outcomes"][0]["other_line"] is other
    assert done["outcomes"][0]["returned_start"] == pytest.approx(words[0]["line_start"] + shift)


def test_a_run_that_failed_mid_way_keeps_its_cards_and_marks_the_rest(batch, fake_miner, words):
    fake_miner.plan(mine="mining-failed", fail_after=2)       # two entries made, the third in flight, then none
    done = batch()
    status = ["made", "made", "uncertain"]
    at, expected = 0, []
    for w in words:                                 # each word: the best of its entries' outcomes
        mine = [status[i] if i < 3 else "not_attempted" for i in range(at, at + len(w["sent"]))]
        at += len(w["sent"])
        expected.append(min(mine, key=["made", "uncertain", "not_attempted"].index))
    assert [o["outcome"] for o in done["outcomes"]] == expected and done["run"]["ok"] is False
    assert expected[0] == "made" and expected[-1] == "not_attempted"


def test_mining_the_same_run_again_reads_the_newest_result(batch, fake_miner, words):
    batch()
    fake_miner.plan(statuses={name: "duplicate" for w in words for name in w["sent"]})
    done = batch()                                  # attempt 1 again: result-2.json beside result-1.json
    assert [o["outcome"] for o in done["outcomes"]] == ["duplicate"] * len(words)


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("how, kind", [
    ("busy", "busy"),                    # its window is open (E8)
    ("anki-closed", "anki-closed"),      # AnkiConnect didn't answer (E1)
    ("crash", "crashed"),                # exit 3: the batch is uncertain (E11)
    ("garbage", "crashed"),              # a traceback where the verdict should be
    ("no-stdout", "crashed"),            # exit 0 and nothing said
])
def test_a_batch_that_gets_no_cards_says_why(batch, fake_miner, how, kind):
    fake_miner.plan(mine=how)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch()
    assert e.value.kind == kind


def test_a_call_that_hangs_is_stopped_at_its_timeout(batch, fake_miner):
    fake_miner.plan(mine="hang")
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch(timeout=3)
    assert e.value.kind == "timeout"


def test_an_unknown_api_schema_is_refused_before_anything_is_mined(batch, fake_miner):
    fake_miner.plan(schema=2)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch()
    assert e.value.kind == "unknown-version" and "mine" not in fake_miner.commands()


def test_a_missing_surasura_profile_or_an_unfinished_setup_needs_you(batch, fake_miner):
    fake_miner.plan(profiles=[{"id": "default", "name": "Default"}])
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch()
    assert e.value.kind == "needs-you" and "Surasura" in e.value.message
    fake_miner.plan(check={"ready": False, "items": [{"name": "anki", "ok": True, "message": None},
                                                     {"name": "dictionary", "ok": False, "message": "No dictionary."}]})
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch()
    assert e.value.kind == "setup" and "dictionary" in e.value.message
    fake_miner.plan(check={"ready": False, "items": [{"name": "anki", "ok": False, "message": "refused"}]})
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch()
    assert e.value.kind == "anki-closed"
    assert "mine" not in fake_miner.commands()


def test_a_program_windows_security_blocked_is_named_never_retried(monkeypatch, fake_miner):
    def blocked(*_a, **_k):
        e = OSError(22, "Operation did not complete successfully because the file contains a virus")
        e.winerror = 225
        raise e
    monkeypatch.setattr(subprocess, "Popen", blocked)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.version(fake_miner.path)
    assert e.value.kind == "quarantined" and "Windows Security" in e.value.message


def test_a_program_that_isnt_there_is_absent(tmp_path):
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.api(str(tmp_path / "AnkiMiner.exe"), ["version"])
    assert e.value.kind == "absent"


@pytest.mark.parametrize("how", ["crash-after-result", "internal-after-result"])
def test_a_crash_after_the_run_reads_the_result_it_left(batch, fake_miner, words, how):
    # Review #4: the result is written before the verdict; a crash at teardown leaves it complete
    fake_miner.plan(mine=how, statuses={n: "duplicate" for n in words[0]["sent"]})
    done = batch()
    assert done["error"] == "crashed"
    assert done["outcomes"][0]["outcome"] == "duplicate" and done["outcomes"][1]["outcome"] == "made"


def test_a_crash_with_no_new_result_never_takes_an_older_attempts(batch, fake_miner):
    batch()                                         # result-1.json of this run id
    fake_miner.plan(mine="crash")
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch()
    assert e.value.kind == "crashed"                # uncertain: checked by the job's tag, never by the old result


def test_a_run_refused_before_anki_is_refused_never_uncertain(batch, fake_miner):
    # Review #5: an unreadable video stops the run before any Anki write
    fake_miner.plan(mine="video-unreadable")
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        batch()
    assert e.value.kind == "unreadable" and e.value.code == "VIDEO_UNREADABLE"


def test_a_row_that_isnt_its_entry_proves_nothing():
    # Review #9: another build's order or count never hands a note id to the wrong word
    words = [{"word": "図書館", "reading": "トショカン", "sent": ["図書館"], "line_start": 90.0},
             {"word": "延長", "reading": "エンチョウ", "sent": ["延長"], "line_start": 116.4}]
    rows = [{"word": "延長", "status": "created", "note_id": 2, "line_start": 116.4},
            {"word": "図書館", "status": "created", "note_id": 1, "line_start": 90.0}]
    assert [o["outcome"] for o in anki_miner.outcomes(words, rows)] == ["uncertain", "uncertain"]


def test_no_mining_while_you_review_and_no_tag_either(tmp_path, fake_miner, words, monkeypatch):
    from app import anki_connect
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: True)
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), EPISODE, words,
                              fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs"), "http://127.0.0.1:9")
    assert e.value.kind == "reviewing" and "mine" not in fake_miner.commands()
    # reviewing starts while the batch runs: the cards stay, the names' tag waits for the ledger
    answers = iter([False, True])
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: next(answers))
    named = [dict(w, name=True) for w in words]
    done = anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), EPISODE, named,
                                 fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs"), "http://127.0.0.1:9")
    assert done["tagged"] == [] and len(done["tag_pending"]) == len(words)


def test_the_tag_search_reads_underscores_as_written():
    assert anki_miner.tag_query("surasura::connect::job_1") == 'tag:"surasura::connect::job\\_1"'


def test_after_a_crash_a_card_made_under_its_dictionary_form_is_found(monkeypatch, words):
    # Review #6: Anki Miner wrote the form it placed the word by (下さる), not the card front sent (くださる)
    from app import anki_connect
    word = next(w for w in words if len(w["sent"]) > 1) if any(len(w["sent"]) > 1 for w in words) else None
    if word is None:
        pytest.skip("no word sent twice in this episode's first words")
    monkeypatch.setattr(anki_connect, "find_notes", lambda url, query: [21])
    monkeypatch.setattr(anki_connect, "notes_info", lambda url, ids: [
        {"noteId": 21, "fields": {"Expression": {"value": word["word"], "order": 0}}}])
    out = anki_miner.uncertain_by_tag("http://127.0.0.1:8765", "job-1", [word], "Expression")
    assert out[0]["outcome"] == "made" and out[0]["note_id"] == 21


def test_after_a_crash_the_jobs_tag_says_which_words_reached_anki(monkeypatch, words):
    from app import anki_connect
    asked = {}

    def find_notes(url, query):
        asked["query"] = query
        return [11, 12]

    def notes_info(url, ids):
        return [{"noteId": 11, "fields": {"Expression": {"value": words[0]["sent"][0], "order": 0}}},
                {"noteId": 12, "fields": {"Expression": {"value": "全然ちがう言葉", "order": 0}}}]
    monkeypatch.setattr(anki_connect, "find_notes", find_notes)
    monkeypatch.setattr(anki_connect, "notes_info", notes_info)
    out = anki_miner.uncertain_by_tag("http://127.0.0.1:8765", "job-1", words, "Expression")
    assert asked["query"] == 'tag:"surasura::connect::job-1"'
    assert out[0]["outcome"] == "made" and out[0]["note_id"] == 11
    assert all(o["outcome"] == "uncertain" for o in out[1:])
