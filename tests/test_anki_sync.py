"""The live Anki -> known words engine (`app/anki_sync.py`), against a fake AnkiConnect — never live Anki.

**Why this file is so long:** the engine writes the user's `KnownWord.json`, which CLAUDE.md §4 calls
sacred, and it is meant to run silently in the background. Every rule it lives by is a way the file
could otherwise be damaged without anyone noticing:

  * append-only — an existing entry is never modified, removed or reordered (spec D2/I3);
  * only studied notes count — the new-card backlog is what Junban ranks (D3);
  * a file that cannot be parsed is never written (I4); every write is atomic (I5);
  * delta syncs, with a full resync when anything that would change the answer changed — including
    another importer overwriting the file (D4);
  * Replace is the only path that removes entries, and it verifies a byte-identical backup first (D12).

`FakeCollection` behaves like a small Anki collection behind AnkiConnect: it answers `findNotes`
by actually evaluating the deck / `-is:new` / `-is:suspended` / `note:` terms of the query, so a
test fails if the engine sends the wrong search, not merely if it sends a different string. It is
reached by patching the global `urllib.request.urlopen` — the same seam as `test_anki_connect.py`
and every Junban test.

Real Japanese (from `tests/Test Resources/ja/`) in every note field; one Chinese deck from
`tests/Test Resources/zh/`. The autouse `_isolate_user_data_root` fixture points `User Files/` at a
temp dir, and `test_nothing_is_written_outside_the_sandbox` asserts it.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
from types import SimpleNamespace
from unittest import mock

import pytest

from app import anki_sync
from app.path_utils import get_user_files_path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:8765"
NOTE_BASE = 1789712080047          # real-magnitude Anki note ids


# --------------------------------------------------------------------------- #
# The fake collection
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok(result):
    return {"result": result, "error": None}


class FakeCollection:
    """A handful of notes behind a fake AnkiConnect. Records every request (action + params)."""

    def __init__(self, notes=(), offline=False):
        self.notes = []
        self.requests = []
        self.offline = offline
        for note in notes:
            self.add(**note)

    def add(self, word, deck="TheBank", model="Lapis", fields=None, new=False, suspended=False,
            note_id=None):
        """`fields` is [(name, value), ...] in field order; default: Lapis-like Expression first."""
        if fields is None:
            fields = [("Expression", word), ("Sentence", f"{word}の例文です。"),
                      ("Meaning", "an English gloss")]
        note_id = note_id or NOTE_BASE + len(self.notes)
        self.notes.append({"noteId": note_id, "deck": deck, "model": model, "fields": fields,
                           "new": new, "suspended": suspended})
        return note_id

    def note(self, note_id):
        return next(n for n in self.notes if n["noteId"] == note_id)

    # --- the wire ---
    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append(payload)
        if self.offline:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "No connection could be made"))
        body = json.dumps(self._answer(payload), ensure_ascii=False).encode("utf-8")
        return _FakeResponse(body)

    def _answer(self, payload):
        action, params = payload["action"], payload.get("params") or {}
        if action == "multi":
            return _ok([self._answer(sub) for sub in params["actions"]])
        if action == "findNotes":
            return _ok(self._find(params["query"]))
        if action == "notesInfo":
            by_id = {n["noteId"]: n for n in self.notes}
            return _ok([self._info(by_id[i]) if i in by_id else {} for i in params["notes"]])
        if action == "modelNames":
            return _ok(sorted({n["model"] for n in self.notes}))
        if action == "modelFieldNames":
            for n in self.notes:
                if n["model"] == params["modelName"]:
                    return _ok([name for name, _ in n["fields"]])
            return {"result": None, "error": "model was not found"}
        return _ok(None)

    @staticmethod
    def _unescape(value):
        return re.sub(r"\\(.)", r"\1", value)

    def _find(self, query):
        decks = [self._unescape(d) for d in re.findall(r'deck:"((?:[^"\\]|\\.)*)"', query)]
        models = [self._unescape(m) for m in re.findall(r'note:"((?:[^"\\]|\\.)*)"', query)]
        out = []
        for n in self.notes:
            if not any(n["deck"] == d or n["deck"].startswith(d + "::") for d in decks):
                continue
            if "-is:new" in query and n["new"]:
                continue
            if "-is:suspended" in query and n["suspended"]:
                continue
            if models and n["model"] not in models:
                continue
            out.append(n["noteId"])
        return out

    @staticmethod
    def _info(n):
        # Deliberately NOT in field order: a dict built from a reversed list. The engine must use
        # each field's `order`, never dict order (spec gotcha 9).
        fields = {name: {"value": value, "order": i}
                  for i, (name, value) in reversed(list(enumerate(n["fields"])))}
        return {"noteId": n["noteId"], "modelName": n["model"], "tags": [], "fields": fields}

    # --- what was asked ---
    @property
    def actions(self):
        return [r["action"] for r in self.requests]

    def notes_info_ids(self):
        return [i for r in self.requests if r["action"] == "notesInfo" for i in r["params"]["notes"]]


@pytest.fixture
def ja_words(ja_resources_dir):
    """Real vocabulary from the shared ja test sentences (context_test.txt)."""
    with open(os.path.join(ja_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    words = ["冒険", "準備", "危険", "価値", "冒険家", "有名", "素晴らしい", "求める", "出かける", "今夜"]
    assert all(w[:2] in text for w in words), "the fixture words come from the real resource file"
    return words


@pytest.fixture
def migaku_file(ja_resources_dir):
    """A real Migaku export (a slice of tests/Test Resources/ja/KnownWord.json): databaseFile header,
    KNOWN / LEARNING / UNKNOWN / IGNORED entries. Written into the sandboxed User Files/ja/."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        data = json.load(f)
    words = data["words"]
    picked = [w for w in words if w["knownStatus"] == "KNOWN"][:30]
    for status in ("LEARNING", "UNKNOWN", "IGNORED"):
        picked += [w for w in words if w["knownStatus"] == status][:3]
    data["words"] = picked
    path = _known_path("ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write_json(path, data)
    return path


def _known_path(language="ja"):
    return os.path.join(get_user_files_path(language), "KnownWord.json")


def _state_path(language="ja"):
    return os.path.join(get_user_files_path(language), "anki_sync_state.json")


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _words(language="ja"):
    with open(_known_path(language), encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data["words"]


def _anki_forms(language="ja"):
    return [w["dictForm"] for w in _words(language) if w.get("source") == "AnkiConnect"]


def _sync(fake, decks=("TheBank",), fields=(), **kw):
    with mock.patch("urllib.request.urlopen", fake):
        return anki_sync.sync(kw.pop("language", "ja"), URL, list(decks), list(fields), **kw)


def _replace(fake, decks=("TheBank",), fields=(), **kw):
    with mock.patch("urllib.request.urlopen", fake):
        return anki_sync.replace(kw.pop("language", "ja"), URL, list(decks), list(fields), **kw)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_scope_query_groups_decks_and_excludes_new_and_suspended():
    assert anki_sync.scope_query(["TheBank", "The Accelerator"]) == \
        '(deck:"TheBank" OR deck:"The Accelerator") -is:new -is:suspended'
    assert anki_sync.scope_query(["日本語::語彙"], include_suspended=True) == \
        '(deck:"日本語::語彙") -is:new'


def test_deck_names_with_quotes_are_escaped_in_the_query(ja_words):
    """A real deck name can contain quotes; unescaped, the search silently means something else."""
    deck = '語彙 "N3" \\ 厳選'
    assert anki_sync.scope_query([deck]) == '(deck:"語彙 \\"N3\\" \\\\ 厳選") -is:new -is:suspended'
    fake = FakeCollection([{"word": ja_words[0], "deck": deck}])
    result = _sync(fake, decks=[deck])
    assert result.error is None and result.added == 1, "the escaped query really finds the deck"


def test_resolve_fields_auto_named_two_fields_case_insensitive_and_unresolved():
    fields = ["Expression", "ExpressionFurigana", "Sentence", "Meaning"]
    assert anki_sync.resolve_fields(fields, []) == ["Expression"], "Auto = the first field"
    assert anki_sync.resolve_fields(fields, ["Sentence"]) == ["Sentence"]
    assert anki_sync.resolve_fields(fields, ["sentence", "EXPRESSION"]) == ["Sentence", "Expression"]
    assert anki_sync.resolve_fields(fields, ["Word"]) == [], "a note type lacking it resolves to nothing"
    assert anki_sync.resolve_fields(fields, ["Word", "Expression"]) == ["Expression"]
    assert anki_sync.resolve_fields([], []) == []


def test_deck_study_counts_is_one_multi_and_counts_only_studied_notes(ja_words):
    fake = FakeCollection()
    for w in ja_words[:3]:
        fake.add(w, deck="TheBank")
    fake.add(ja_words[3], deck="TheBank", new=True)
    fake.add(ja_words[4], deck="TheBank::サブ")                 # subdecks count toward the parent
    fake.add(ja_words[5], deck="The Accelerator", suspended=True)
    with mock.patch("urllib.request.urlopen", fake):
        counts = anki_sync.deck_study_counts(URL, ["TheBank", "The Accelerator"])
        with_suspended = anki_sync.deck_study_counts(URL, ["The Accelerator"], include_suspended=True)
        assert anki_sync.deck_study_counts(URL, []) == {}
    assert counts == {"TheBank": 4, "The Accelerator": 0}
    assert with_suspended == {"The Accelerator": 1}
    assert fake.actions == ["multi", "multi"], "one request per call; nothing sent for no decks"


def test_models_in_scope_lists_only_note_types_with_studied_notes_in_field_order(ja_words):
    fake = FakeCollection()
    fake.add(ja_words[0], model="Lapis")
    fake.add(ja_words[1], model="Kiku", fields=[("Word", ja_words[1]), ("Reading", "じゅんび")])
    fake.add(ja_words[2], model="Migaku Japanese", new=True,
             fields=[("Target Word", ja_words[2]), ("Sentence", "危険だ。")])
    fake.add(ja_words[3], model="Lapis", deck="Default")
    with mock.patch("urllib.request.urlopen", fake):
        models = anki_sync.models_in_scope(URL, ["TheBank"])
    assert models == {"Kiku": ["Word", "Reading"], "Lapis": ["Expression", "Sentence", "Meaning"]}
    assert fake.actions == ["modelNames", "multi", "multi"]


def test_importing_anki_sync_is_cheap():
    """The dashboard imports this on its UI thread (spec I6): no tkinter, pandas or tokenizers. A
    CLEAN subprocess, because pytest has already imported all of them in this one."""
    watch = ("tkinter", "pandas", "fugashi", "jieba")
    code = ("import app.anki_sync; import sys; "
            "print(','.join(m for m in %r if m in sys.modules))" % (watch,))
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"importing app.anki_sync failed:\n{result.stderr}"
    loaded = [m for m in result.stdout.strip().split(",") if m]
    assert loaded == [], f"`import app.anki_sync` eagerly loaded: {loaded}"


# --------------------------------------------------------------------------- #
# The first sync
# --------------------------------------------------------------------------- #
def test_first_sync_appends_studied_words_and_new_cards_never_count(ja_words):
    """D3: 73% of the reference collection is unstudied. Marking that backlog known would empty
    Junban's queue and lie to the analyzer."""
    fake = FakeCollection()
    studied = [fake.add(w) for w in ja_words[:4]]
    fake.add(ja_words[4], new=True)
    fake.add(ja_words[5], new=True)

    result = _sync(fake)

    assert result.error is None
    assert result.mode == "full", "no state yet -> full"
    assert (result.added, result.scanned) == (4, 4)
    assert _anki_forms() == ja_words[:4]
    entry = _words()[0]
    assert entry["knownStatus"] == "KNOWN" and entry["hasCard"] == 1 and entry["language"] == "ja"
    assert entry["ankiNoteId"] == studied[0], "source + note id make Anki words identifiable later"
    assert result.fields_by_model == {"Lapis": ["Expression"]}
    assert result.total_known == 4
    assert sorted(set(fake.notes_info_ids())) == sorted(studied), "new notes are never even fetched"


def test_missing_known_file_is_created_in_the_dict_format(ja_words):
    fake = FakeCollection([{"word": ja_words[0]}])
    assert not os.path.exists(_known_path())
    _sync(fake)
    with open(_known_path(), encoding="utf-8") as f:
        data = json.load(f)
    assert set(data) == {"exportDate", "source", "statistics", "words"}
    assert data["source"] == "AnkiConnect"
    assert [w["dictForm"] for w in data["words"]] == [ja_words[0]]


def test_suspended_cards_excluded_by_default_included_when_toggled_and_toggle_forces_full(ja_words):
    """D7: suspended cards are often the ones the user struggled with — off by default."""
    fake = FakeCollection()
    fake.add(ja_words[0])
    fake.add(ja_words[1], suspended=True)

    first = _sync(fake)
    assert _anki_forms() == [ja_words[0]]
    assert "-is:suspended" in fake.requests[0]["params"]["query"]

    fake.requests.clear()
    second = _sync(fake, include_suspended=True)
    assert second.mode == "full", "changing the toggle re-evaluates everything"
    assert "-is:suspended" not in fake.requests[0]["params"]["query"]
    assert _anki_forms() == [ja_words[0], ja_words[1]]
    assert (first.added, second.added) == (1, 1)


def test_nothing_is_written_outside_the_sandbox(ja_words):
    """The autouse sandbox must hold: the file and the state land under SURASURA_TEST_ROOT."""
    root = os.environ["SURASURA_TEST_ROOT"]
    _sync(FakeCollection([{"word": ja_words[0]}]))
    for path in (_known_path(), _state_path()):
        assert os.path.exists(path)
        assert os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    assert not os.path.abspath(root).startswith(os.path.abspath(PROJECT_ROOT))


# --------------------------------------------------------------------------- #
# Delta and full
# --------------------------------------------------------------------------- #
def test_a_second_sync_with_no_changes_sends_one_findnotes_and_writes_nothing(ja_words):
    """The everyday case (~60 ms). Also proves known_sig is recorded AFTER our own write — otherwise
    this run would look like an external change and degrade to a full resync (gotcha 7)."""
    fake = FakeCollection([{"word": w} for w in ja_words[:5]])
    _sync(fake)
    before = _read_bytes(_known_path())
    mtime = os.stat(_known_path()).st_mtime_ns

    fake.requests.clear()
    result = _sync(fake)

    assert result.mode == "delta"
    assert fake.actions == ["findNotes"], "no notesInfo when nothing is new"
    assert (result.added, result.scanned, result.total_known) == (0, 0, 5)
    assert _read_bytes(_known_path()) == before
    assert os.stat(_known_path()).st_mtime_ns == mtime


def test_delta_fetches_exactly_the_newly_studied_notes(ja_words):
    fake = FakeCollection([{"word": w} for w in ja_words[:4]])
    _sync(fake)
    newly = [fake.add(w) for w in ja_words[4:7]]
    fake.add(ja_words[7], new=True)

    fake.requests.clear()
    result = _sync(fake)

    assert result.mode == "delta"
    assert fake.notes_info_ids() == newly
    assert result.added == 3 and result.scanned == 3
    assert _anki_forms() == ja_words[:7]


def test_state_records_the_current_note_set_not_a_union(ja_words):
    """Gotcha 8: a note deleted in Anki must drop out of the state (its word stays — append-only)."""
    fake = FakeCollection([{"word": w} for w in ja_words[:3]])
    _sync(fake)
    gone = fake.notes.pop(0)
    _sync(fake)
    state = anki_sync.load_state("ja")
    assert gone["noteId"] not in state["note_ids"]
    assert sorted(state["note_ids"]) == sorted(n["noteId"] for n in fake.notes)
    assert ja_words[0] in _anki_forms(), "the word of a deleted note is never removed"
    assert state["last_added"] == 0 and state["last_sync"]


def test_a_migaku_overwrite_between_syncs_forces_a_full_resync_that_reappends(ja_words, migaku_file):
    """D4: Migaku/Jiten imports overwrite KnownWord.json wholesale. The next sync notices (stat
    signature) and re-appends every Anki word instead of trusting its saved note ids."""
    migaku_bytes = _read_bytes(migaku_file)
    fake = FakeCollection([{"word": w} for w in ja_words[:4]])
    _sync(fake)
    assert _anki_forms() == ja_words[:4]

    with open(migaku_file, "wb") as f:                     # the Migaku importer runs again
        f.write(migaku_bytes + b"\n")
    fake.requests.clear()
    result = _sync(fake)

    assert result.mode == "full"
    assert sorted(set(fake.notes_info_ids())) == sorted(n["noteId"] for n in fake.notes)
    assert _anki_forms() == ja_words[:4]
    assert result.added == 4


@pytest.mark.parametrize("change", ["decks", "fields"])
def test_changing_decks_or_fields_forces_a_full_resync(ja_words, change):
    fake = FakeCollection()
    fake.add(ja_words[0], deck="TheBank")
    fake.add(ja_words[1], deck="The Accelerator")
    _sync(fake)
    fake.requests.clear()
    if change == "decks":
        result = _sync(fake, decks=["TheBank", "The Accelerator"])
        assert _anki_forms() == [ja_words[0], ja_words[1]]
    else:
        result = _sync(fake, fields=["Sentence"])
        assert f"{ja_words[0]}の例文です。" in _anki_forms()
    assert result.mode == "full"


def test_full_true_forces_a_full_resync(ja_words):
    """Shift-click in the window: re-reads notes whose word field was edited after syncing."""
    fake = FakeCollection([{"word": w} for w in ja_words[:2]])
    _sync(fake)
    fake.requests.clear()
    result = _sync(fake, full=True)
    assert result.mode == "full" and result.scanned == 2 and result.added == 0


def test_a_corrupt_state_file_is_quarantined_and_a_full_sync_adds_no_duplicates(ja_words):
    fake = FakeCollection([{"word": w} for w in ja_words[:3]])
    _sync(fake)
    with open(_state_path(), "w", encoding="utf-8") as f:
        f.write('{"note_ids": [1789712080047, 冒険')        # truncated mid-write
    result = _sync(fake)

    assert result.error is None and result.mode == "full"
    assert result.added == 0
    assert _anki_forms() == ja_words[:3], "appends are deduped, so the full sync is harmless"
    quarantined = [f for f in os.listdir(get_user_files_path("ja"))
                   if f.startswith("anki_sync_state.json.corrupt-")]
    assert len(quarantined) == 1
    assert anki_sync.load_state("ja")["decks"] == ["TheBank"], "a fresh, valid state replaced it"


# --------------------------------------------------------------------------- #
# Append-only against existing data
# --------------------------------------------------------------------------- #
def test_existing_entries_are_never_modified_or_reordered(ja_words, migaku_file):
    """I3. Every pre-existing entry must come back identical and in the same position."""
    before = json.loads(_read_bytes(migaku_file).decode("utf-8"))
    fake = FakeCollection([{"word": w} for w in ja_words])
    result = _sync(fake)
    after = json.loads(_read_bytes(migaku_file).decode("utf-8"))

    n = len(before["words"])
    assert after["words"][:n] == before["words"]
    assert len(after["words"]) == n + result.added
    assert after["databaseFile"] == before["databaseFile"], "unknown top-level keys preserved"
    assert after["statistics"] == before["statistics"] and after["exportDate"] == before["exportDate"]


def test_dedupe_against_known_and_hascard_entries_within_batch_and_nfkc(ja_words):
    """An existing KNOWN or hasCard=1 entry blocks the append; so does an earlier note in the same
    batch; halfwidth katakana (ｶﾞｯｺｳ) matches its fullwidth form (ガッコウ) after NFKC."""
    _write_json(_known_path(), {"exportDate": "2026-02-07T16:24:22", "statistics": {}, "words": [
        {"dictForm": ja_words[0], "secondary": "ぼうけん", "knownStatus": "KNOWN", "hasCard": 0},
        {"dictForm": ja_words[1], "secondary": "じゅんび", "knownStatus": "UNKNOWN", "hasCard": 1},
        {"dictForm": "ガッコウ", "secondary": "", "knownStatus": "KNOWN", "hasCard": 0},
    ]})
    fake = FakeCollection()
    for w in (ja_words[0], ja_words[1], "ｶﾞｯｺｳ", ja_words[2], ja_words[2], f" {ja_words[3]} "):
        fake.add(w)

    result = _sync(fake)

    assert _anki_forms() == [ja_words[2], ja_words[3]]
    assert result.added == 2
    assert result.total_known == 5


def test_an_existing_learning_entry_does_not_block_and_stays_byte_identical(ja_words, migaku_file):
    """The user studied it in Anki, so it is known now — but their Migaku entry is never touched."""
    learning = next(w for w in _words() if w["knownStatus"] == "LEARNING")
    ignored = next(w for w in _words() if w["knownStatus"] == "IGNORED")
    fake = FakeCollection([{"word": learning["dictForm"]}, {"word": ignored["dictForm"]}])

    _sync(fake)

    words = _words()
    assert learning in words and ignored in words, "originals unchanged"
    assert _anki_forms() == [learning["dictForm"], ignored["dictForm"]]


def test_a_legacy_list_format_file_is_appended_to_as_a_list(ja_words):
    legacy = [{"dictForm": "番", "secondary": "ばん", "knownStatus": "KNOWN", "hasCard": 0}]
    _write_json(_known_path(), legacy)
    _sync(FakeCollection([{"word": ja_words[0]}]))
    with open(_known_path(), encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert data[0] == legacy[0] and data[1]["dictForm"] == ja_words[0]


@pytest.mark.parametrize("content", [b'{"words": [{"dictForm": "\xe5\x86\x92\xe9\x99\xba"',
                                     b'"\xe5\x86\x92\xe9\x99\xba"',
                                     b'{"words": {"dictForm": "x"}}'])
def test_a_corrupt_known_file_is_never_written(ja_words, content):
    """I4 — the .apkg importer used to swallow this and overwrite the file with Anki-only words."""
    path = _known_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    result = _sync(FakeCollection([{"word": ja_words[0]}]))
    assert result.error and "nothing was changed" in result.error
    assert _read_bytes(path) == content
    assert not os.path.exists(_state_path()), "no state recorded for a run that wrote nothing"


def test_anki_offline_returns_an_error_and_touches_nothing(ja_words, migaku_file):
    fake = FakeCollection([{"word": w} for w in ja_words[:2]])
    _sync(fake)
    known, state = _read_bytes(migaku_file), _read_bytes(_state_path())

    fake.offline = True
    result = _sync(fake)

    assert result.error and "Is Anki running?" in result.error
    assert result.added == 0 and result.total_known == anki_sync.count_known("ja")
    assert _read_bytes(migaku_file) == known and _read_bytes(_state_path()) == state


def test_no_decks_is_an_error_without_contacting_anki(ja_words):
    fake = FakeCollection([{"word": ja_words[0]}])
    result = _sync(fake, decks=[])
    assert result.error and fake.requests == []


# --------------------------------------------------------------------------- #
# Fields and cleaning
# --------------------------------------------------------------------------- #
def test_field_resolution_auto_named_two_fields_case_insensitive_and_skipped_models(ja_words):
    fake = FakeCollection()
    fake.add(ja_words[0], model="Lapis")
    fake.add(ja_words[1], model="Kiku", fields=[("Word", ja_words[1]), ("Reading", "じゅんび")])

    auto = _sync(fake)
    assert _anki_forms() == [ja_words[0], ja_words[1]], "Auto = first field BY ORDER, per note type"
    assert auto.fields_by_model == {"Lapis": ["Expression"], "Kiku": ["Word"]}

    named = _sync(fake, fields=["expression"])               # case-insensitive
    assert named.fields_by_model == {"Lapis": ["Expression"], "Kiku": []}
    assert named.skipped_by_model == {"Kiku": 1}, "a wrong choice is visible, never silent"

    two = _sync(fake, fields=["Expression", "Reading"])
    assert two.fields_by_model == {"Lapis": ["Expression"], "Kiku": ["Reading"]}
    assert two.skipped_by_model == {}
    assert "じゅんび" in _anki_forms()


def test_field_cleaning_end_to_end(ja_words):
    """Ruby, bracket furigana, <br>-separated alternatives, &quot; and [sound:] as real cards hold them."""
    fake = FakeCollection()
    fake.add("", fields=[("Expression", "<ruby>冒険<rt>ぼうけん</rt></ruby>[sound:bouken.mp3]")])
    fake.add("", fields=[("Expression", " 準備[じゅんび]")])
    fake.add("", fields=[("Expression", "<div>危険</div><div>価値</div>")])
    fake.add("", fields=[("Expression", "&quot;有名&quot;")])
    fake.add("", fields=[("Expression", "素晴らしい・すばらしい")])
    _sync(fake)
    assert _anki_forms() == ["冒険", "準備", "危険", "価値", '"有名"',
                             "素晴らしい・すばらしい"]


def test_a_field_with_no_japanese_is_skipped(ja_words):
    fake = FakeCollection()
    fake.add(ja_words[0], fields=[("Meaning", "adventure; venture"), ("Expression", ja_words[0])])
    fake.add("", fields=[("Expression", "")])
    result = _sync(fake)
    assert result.added == 0 and not os.path.exists(_known_path()), "nothing appended, nothing written"
    assert result.skipped_by_model == {}, "resolved, just nothing usable in it"


def test_a_chinese_deck_appends_chinese_terms(zh_resources_dir):
    """The Anki button stays visible for zh (gotcha 12). Same path, zh's own User Files and regex."""
    with open(os.path.join(zh_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        assert "挑战" in f.read()
    fake = FakeCollection()
    for w in ("冒险", "挑战", "勇敢", "坚强"):
        fake.add(w, deck="中文::词汇", model="Chinese (basic)",
                 fields=[("Hanzi", w), ("Pinyin", "màoxiǎn"), ("English", "adventure")])
    fake.add("", deck="中文::词汇", model="Chinese (basic)", fields=[("Hanzi", "ok")])

    result = _sync(fake, decks=["中文"], language="zh")

    assert result.error is None
    assert _anki_forms("zh") == ["冒险", "挑战", "勇敢", "坚强"]
    assert all(w["language"] == "zh" for w in _words("zh"))
    assert not os.path.exists(_known_path("ja"))


# --------------------------------------------------------------------------- #
# count_known (D10)
# --------------------------------------------------------------------------- #
def test_count_known_counts_distinct_known_forms_across_sources(ja_words, migaku_file):
    migaku = _words()
    expected_migaku = len({w["dictForm"] for w in migaku
                           if w["knownStatus"] == "KNOWN" or w.get("hasCard") == 1})
    assert anki_sync.count_known("ja") == expected_migaku
    assert any(w["knownStatus"] in ("LEARNING", "UNKNOWN", "IGNORED") and w.get("hasCard") != 1
               for w in migaku), "the fixture really holds non-known entries to ignore"

    fresh = [w for w in ja_words if w not in {m["dictForm"] for m in migaku}]
    result = _sync(FakeCollection([{"word": w} for w in fresh]))
    assert result.total_known == anki_sync.count_known("ja") == expected_migaku + len(fresh)


def test_count_known_is_zero_for_a_missing_or_corrupt_file():
    assert anki_sync.count_known("ja") == 0
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    with open(_known_path(), "w", encoding="utf-8") as f:
        f.write("{冒険")
    assert anki_sync.count_known("ja") == 0


# --------------------------------------------------------------------------- #
# Replace / restore (D12)
# --------------------------------------------------------------------------- #
def _trash_files(language="ja"):
    trash = os.path.join(get_user_files_path(language), ".trash")
    return sorted(os.listdir(trash)) if os.path.isdir(trash) else []


def test_replace_dry_run_reports_the_numbers_and_writes_nothing(ja_words, migaku_file):
    before = _read_bytes(migaku_file)
    result = _replace(FakeCollection([{"word": w} for w in ja_words[:3]]), dry_run=True)
    assert result.mode == "dry-run" and result.error is None
    assert result.added == 3
    assert result.total_known == anki_sync.count_known("ja") > 3, "the CURRENT file's total"
    assert _read_bytes(migaku_file) == before and _trash_files() == []
    assert not os.path.exists(_state_path())


def test_replace_builds_an_anki_only_file_and_backs_up_the_old_one_byte_identical(ja_words, migaku_file):
    before = _read_bytes(migaku_file)
    fake = FakeCollection([{"word": w} for w in ja_words[:3]])
    fake.add(ja_words[3], new=True)

    result = _replace(fake)

    assert result.error is None and result.mode == "replace"
    assert _anki_forms() == ja_words[:3] and len(_words()) == 3, "Migaku entries are gone"
    assert result.added == 3 and result.total_known == 3
    assert re.fullmatch(r"KnownWord\.\d{8}-\d{6}\.json", result.backup)
    assert _trash_files() == [result.backup]
    assert _read_bytes(os.path.join(get_user_files_path("ja"), ".trash", result.backup)) == before
    state = anki_sync.load_state("ja")
    assert state["last_backup"] == result.backup

    fake.requests.clear()
    assert _sync(fake).mode == "delta", "known_sig recorded after the replace's own write"


@pytest.mark.parametrize("scenario", ["offline", "empty"])
def test_replace_offline_or_with_zero_words_aborts_without_writing_or_backing_up(ja_words, migaku_file,
                                                                                   scenario):
    """An empty replace would wipe the user's list — never allowed."""
    before = _read_bytes(migaku_file)
    if scenario == "offline":
        fake = FakeCollection([{"word": ja_words[0]}], offline=True)
    else:
        fake = FakeCollection([{"word": ja_words[0], "new": True},
                               {"word": "", "fields": [("Expression", "adventure")]}])
    result = _replace(fake)
    assert result.error
    assert _read_bytes(migaku_file) == before
    assert _trash_files() == []
    assert not os.path.exists(_state_path())


def test_replace_aborts_before_writing_when_the_backup_copy_does_not_match(ja_words, migaku_file):
    before = _read_bytes(migaku_file)

    def bad_copy(src, dst):
        with open(src, "rb") as a, open(dst, "wb") as b:
            b.write(a.read()[:100])                          # a truncated copy (disk full, AV lock...)

    with mock.patch("app.anki_sync.shutil.copyfile", bad_copy):
        result = _replace(FakeCollection([{"word": w} for w in ja_words[:3]]))

    assert result.error and "Nothing was replaced" in result.error
    assert _read_bytes(migaku_file) == before
    assert not os.path.exists(_state_path())


def test_restore_backs_up_the_current_file_restores_byte_identical_and_clears_note_ids(ja_words,
                                                                                         migaku_file):
    original = _read_bytes(migaku_file)
    fake = FakeCollection([{"word": w} for w in ja_words[:3]])
    replaced = _replace(fake)
    anki_only = _read_bytes(migaku_file)

    result = anki_sync.restore_previous("ja")

    assert result.error is None and result.mode == "restore"
    assert _read_bytes(migaku_file) == original
    assert result.backup and result.backup != replaced.backup
    assert _read_bytes(os.path.join(get_user_files_path("ja"), ".trash", result.backup)) == anki_only, \
        "the restore is itself undoable"
    state = anki_sync.load_state("ja")
    assert state["note_ids"] == [] and state["last_backup"] == result.backup
    assert result.total_known == anki_sync.count_known("ja")

    fake.requests.clear()
    resync = _sync(fake)
    assert resync.mode == "full" and resync.scanned == 3, "the next sync re-evaluates cleanly"


def test_restore_without_a_previous_replace_is_an_error():
    result = anki_sync.restore_previous("ja")
    assert result.error and result.mode == "restore" and result.backup is None


# --------------------------------------------------------------------------- #
# Settings (I9)
# --------------------------------------------------------------------------- #
def test_sync_settings_have_defaults_and_never_change_the_run_signature(tmp_path):
    from app import analyzer, settings_manager
    from app.path_utils import get_user_file

    defaults = settings_manager.DEFAULT_SETTINGS
    assert defaults["anki_connect_url"] == "http://127.0.0.1:8765"
    assert defaults["anki_sync_auto"] is False and defaults["anki_sync_include_suspended"] is False
    assert defaults["anki_sync_decks"] == {} and defaults["anki_sync_fields"] == {}
    loaded = settings_manager.load_settings()
    loaded["anki_sync_decks"]["ja"] = ["TheBank"]
    assert settings_manager.DEFAULT_SETTINGS["anki_sync_decks"] == {}, "defaults are not aliased"

    args = SimpleNamespace(language="ja", min_freq=2, target_coverage=90, only_i_plus_one=False,
                           ensure_audio_example=False, include_single_chars=False,
                           exclude_freq_one=False, reinforce=False, context_min=10, context_max=50,
                           max_contexts=3)
    settings_path = get_user_file("settings.json")
    _write_json(settings_path, {"target_language": "ja"})
    base = analyzer.compute_run_signature("ja", [], args)
    _write_json(settings_path, {"target_language": "ja", "anki_connect_url": "http://localhost:8765",
                                "anki_sync_auto": True, "anki_sync_decks": {"ja": ["TheBank"]},
                                "anki_sync_fields": {"ja": ["Expression"]},
                                "anki_sync_include_suspended": True})
    assert base is not None
    assert analyzer.compute_run_signature("ja", [], args) == base
