"""A problem report keeps the words Anki refused (field report on 3.0.0, Mattias #5; Michi-RM2): a part whose cards
failed because Anki wouldn't take one note left, in 3.0.0's zip, only counts ("3 left out") — so which word, and why,
could only be asked of the tester's PC. Now, for a part that failed, the zip keeps the words Connect sent alone and
Anki Miner still couldn't make, with Anki Miner's reason: in `connect/ledger.json`'s `refused` (one row a failed job:
its id, those words, the reason) and in each failed one-word run's result (that row's `word` and `status`). Never the
sentence, the reading, the other words, nor anything else of a card; every entry is still put through the identity
scrub (the tester's names), as before (SPEC send-report §2).

What a wrong answer would cost: a report that says a part failed and never which word (a second round trip to the
tester); or one that carries the learner's sentences, the other words of the episode, or their name.

The real ledger and report code under the test root; real Japanese words. Never the tester's data.
"""
import json
import os
import zipfile

import pytest

from app import report as core
from app.connect import ledger as book
from app.connect import runner

SAID = "AnkiConnect error in 'addNotes': ['cannot create note for unknown reason']"
SENTENCE = "改札を抜けると、約束の場所に彼女が立っていた。"


@pytest.fixture
def root(tmp_path):
    folder = core.folder()
    assert folder.startswith(os.environ["SURASURA_TEST_ROOT"])
    return folder


def _zip(tmp_path, root):
    core.save("Connectが三つの章のカードを作れなかった。")
    path = core.make_zip(str(tmp_path / "Downloads"), "ja", True, None, root=root)
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _job(led, item, state, outcomes, alone=None):
    """A job of `item` in `state`, its outcomes [(word, reading, outcome)] each with a sentence, and its `alone:`."""
    led.conn.execute("INSERT INTO jobs (language, item_id, state, created_at, updated_at, kind, picked) VALUES "
                     "('ja', ?, ?, '2026-11-09T20:00:00Z', '2026-11-09T20:06:00Z', 'mine', ?)",
                     (item, state, json.dumps({"words": [{"word": w, "reading": r} for w, r, _o in outcomes]},
                                              ensure_ascii=False)))
    job = led.conn.execute("SELECT MAX(id) FROM jobs").fetchone()[0]
    for word, reading, outcome in outcomes:
        led.conn.execute("INSERT INTO outcomes (job_id, word, reading, orth, sentence, outcome, attempt) VALUES "
                         "(?, ?, ?, ?, ?, ?, 2)", (job, word, reading, word, SENTENCE, outcome))
    if alone is not None:
        led.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)",
                         (f"{runner.ALONE}{job}", json.dumps(alone, ensure_ascii=False)))
    return job


def test_a_failed_parts_refused_words_and_the_reason_go_in_the_ledger_never_its_sentences(root, tmp_path):
    with book.Ledger() as led:
        failed = _job(led, 33, "failed", [("約束", "やくそく", "uncertain"), ("改札", "かいさつ", "made"),
                                          ("彼女", "かのじょ", "uncertain")],
                      {"said": SAID, "words": ["約束"]})
        # refused once, then made on a later word-at-a-time try: no longer refused
        later = _job(led, 34, "failed", [("場所", "ばしょ", "made"), ("立つ", "たつ", "uncertain")],
                     {"said": SAID, "words": ["場所"]})
        done = _job(led, 35, "done", [("抜ける", "ぬける", "made")], {"said": SAID, "words": []})
        skipped = _job(led, 36, "skipped", [("待つ", "まつ", "uncertain")], {"said": SAID, "words": ["待つ"]})
    ledger = json.loads(_zip(tmp_path, root)["connect/ledger.json"])
    assert ledger["refused"] == [{"job_id": failed, "words": ["約束"], "said": SAID}]
    assert later not in {r["job_id"] for r in ledger["refused"]}, "its one refused word was made after all"
    assert not any(k.startswith(runner.ALONE) for k in ledger["meta"]), "no second, unchosen copy in meta"
    assert {done, skipped}.isdisjoint(r["job_id"] for r in ledger["refused"]), "a failed part's only"
    text = json.dumps(ledger, ensure_ascii=False)
    assert SENTENCE not in text and "やくそく" not in text and "彼女" not in text and "改札" not in text


def test_a_failed_one_word_runs_result_keeps_its_word_and_status_and_nothing_else(root, tmp_path):
    runs = os.path.join(os.path.dirname(book.path()), "runs", "3b-67")
    os.makedirs(os.path.join(runs, "3b-67-1"))
    os.makedirs(os.path.join(runs, "3b-67-2"))
    os.makedirs(os.path.join(runs, "3b-67-3"))
    row = {"word": "約束", "mined_form": "約束", "status": "uncertain", "note_id": None, "sentence": SENTENCE,
           "unit_index": 12, "location": "第三章"}
    failed = {"schema": 1, "run_id": "3b-67-1", "outcome": "failed", "anki_write_state": "note_write_uncertain",
              "failure_is_transient": False, "error": "MINING_FAILED", "message": SAID, "words": [row]}
    together = dict(failed, run_id="3b-67-2", words=[row, dict(row, word="改札", mined_form="改札")])
    made = dict(failed, run_id="3b-67-3", outcome="success", error=None, message=None,
                words=[dict(row, status="created", note_id=5)])
    for name, data in (("3b-67-1", failed), ("3b-67-2", together), ("3b-67-3", made)):
        with open(os.path.join(runs, name, "result-1.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    files = _zip(tmp_path, root)
    one = json.loads(files["anki-miner/3b-67/3b-67-1/result-1.json"])
    assert one["words"] == [{"word": "約束", "status": "uncertain"}] and one["message"] == SAID
    assert json.loads(files["anki-miner/3b-67/3b-67-2/result-1.json"])["words"] == "2 left out", \
        "a batch's words, together: counted as before (which one Anki refused isn't known from it)"
    assert json.loads(files["anki-miner/3b-67/3b-67-3/result-1.json"])["words"] == "1 left out", \
        "a run that went through: counted as before"
    everything = b"".join(files.values()).decode("utf-8", "replace")
    assert SENTENCE not in everything and "第三章" not in everything


def test_an_unreadable_alone_record_is_said_never_a_reason_the_ledger_is_missing(root, tmp_path):
    with book.Ledger() as led:
        job = _job(led, 33, "failed", [("約束", "やくそく", "uncertain")])
        led.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (f"{runner.ALONE}{job}", "{broken"))
    ledger = json.loads(_zip(tmp_path, root)["connect/ledger.json"])
    assert ledger["refused"] == [] and [j["id"] for j in ledger["jobs"]] == [job]


@pytest.mark.parametrize("row", [
    {"word": SENTENCE * 2, "status": "uncertain", "sentence": SENTENCE},      # no word: a whole line
    {"word": "約束", "status": {"why": SENTENCE}, "sentence": SENTENCE},       # a status that isn't a string
    {"word": "", "status": "uncertain"},
])
def test_an_odd_one_word_row_is_counted_never_copied(root, tmp_path, row):
    """Review N1: only a short word and a plain status are kept; anything else is counted as before."""
    runs = os.path.join(os.path.dirname(book.path()), "runs", "3b-77", "3b-77-1")
    os.makedirs(runs)
    with open(os.path.join(runs, "result-1.json"), "w", encoding="utf-8") as f:
        json.dump({"outcome": "failed", "error": "MINING_FAILED", "message": SAID, "words": [row]}, f,
                  ensure_ascii=False)
    files = _zip(tmp_path, root)
    assert json.loads(files["anki-miner/3b-77/3b-77-1/result-1.json"])["words"] == "1 left out"
    assert SENTENCE not in b"".join(files.values()).decode("utf-8", "replace")
