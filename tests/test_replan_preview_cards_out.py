"""*Take its new cards out*, the whole loop through the window's re-order host (P4.1 L2 package T, with the review's
fixes TF; L2.2 05 §5.7, D14).

On the RP-2 library (tests/plan_file_cases.py: real Japanese and Chinese text across Current, Soon and Goal),
generated as a Generate leaves it, and Junban's fake collection holding one new card per word of its list, plus three
cards whose words aren't on it:

  * *Take its new cards out* on a Current item → once the Generate its Finished drag starts has run (W-1b: Finished is
    set aside, like a watched episode, so the drag writes nothing to Anki before it), the host's job (owed through
    `pins_version`, T-4) places the
    item's new cards whose words left the list after every other card, tags them `Surasura::out` and suspends them —
    with your 順 actions off (T-1) — while its card whose word is on the list stays in, placed by the list (TF fix 3,
    P4.1-7); its reviewed card and a card another Current item shares stay as they are (T-3), the store records
    exactly the cards suspended and the notes tagged (`anki_changes`, T-6, by the host: TF fix 10), and the bar says
    how many were taken out (TF fix 10);
  * *Put back*, *Put them back in the order* or the take-out's undo → the next job (after the Generate for a tier
    move: *Put back* and the undo) unsuspends exactly those, takes
    the tag off exactly those notes, places them in the same job and closes the record (T-5); a card you suspended
    meanwhile stays suspended;
  * a review that begins just before the suspends → nothing taken out, and the job stays owed (TF fix 6);
  * automation off → the host writes nothing to Anki and records nothing.

Never Anki: the fake answers on `urlopen`.
"""
import json
import os

import pytest

pytest.importorskip("modules.junban")

from app import library_store, replan_preview  # noqa: E402
from modules.junban.tests.test_reposition import _collection, _patched  # noqa: E402
from tests import plan_file_cases as cases  # noqa: E402
from tests.test_replan_preview import ACTIONS, DECK, MarkingCollection, _list_words, _settings_file  # noqa: E402

OUT_TAG = "Surasura::out"
REVIEWED = {"ja": "眼鏡", "zh": "眼镜"}
# Three words the RP-2 list doesn't hold (checked below): the out item's two cards whose words left the list, and the
# card it shares with another Current item (P4.1-7, TF fix 3: a list word's card would stay in, placed by the list).
UNLISTED = {"ja": ["蝸牛", "薔薇", "躑躅"], "zh": ["蜗牛", "玫瑰", "杜鹃"]}


@pytest.fixture(params=["ja", "zh"])
def lib(request, tmp_path, monkeypatch):
    """The RP-2 library for the language, generated, with the host's gate open: (language, root, store)."""
    language = request.param
    case = f"rp2-{language}"
    root = str(tmp_path / "lib")
    env = cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, env[name])
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    cases.needs_junban()
    cases.build(root, case)
    _settings_file(root, target_language=language, junban_replan_language=language)
    from app import run_args
    from app.path_utils import ensure_data_setup, get_data_path, get_user_files_path
    ensure_data_setup(language)
    with open(os.path.join(root, "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    cases.generate(root, case, argv=run_args.analyzer_args(settings, language, headless=True)[1:])
    store = library_store.open_store(language, get_data_path(language), get_user_files_path(language))
    assert store is not None, "the Generate left no library store"
    yield language, root, store
    store.close()


def _deck(language, root):
    """40 of the list's words (queued in the reverse of the list's order), three words off the list and a card the
    learner has studied."""
    assert not set(UNLISTED[language]) & set(_list_words(root)), "the words off the list must be off it"
    words = _list_words(root, 40) + UNLISTED[language] + [REVIEWED[language]]
    cards, notes, _ = _collection(words, dues=list(range(3000 + len(words) - 1, 2999, -1)), deck=DECK)
    fake = MarkingCollection(cards, notes, actions=ACTIONS)
    by_word = {fake.notes[c["note"]]["fields"]["Expression"]["value"]: c for c in fake.cards.values()}
    by_word[REVIEWED[language]].update(type=2, queue=2, due=500)
    return fake, words, by_word


def _link(store, item_id, *cards):
    with store._writing():
        store.conn.executemany("INSERT INTO anki_links (item_id, note_id, source, linked_at) VALUES (?, ?, 'connect', "
                               "'2026-10-16T09:00:00Z')", [(item_id, card["note"]) for card in cards])


def _tags(fake, card):
    return fake.notes[card["note"]].get("tags") or []


def _owed(store):
    v = store.versions()
    return v["pins_version"] > v["planned_pins_version"]


def _generate(root, language):
    """A full Generate as the dashboard starts it, so the host's signature is the run's."""
    from app import run_args
    with open(os.path.join(root, "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    cases.generate(root, f"rp2-{language}", argv=run_args.analyzer_args(settings, language, headless=True)[1:])


def _after_its_generate(lib, fake, host, out, queue):
    """A Finished drag (in or out) waits for the Generate it starts: the host's job writes nothing to the cards before
    it (each still in `queue`); then the Generate, and the host's job after it."""
    language, root, _store = lib
    with _patched(fake):
        host._job("move")
    assert [card["queue"] for card in out] == [queue] * len(out), "nothing written before the Generate"
    _generate(root, language)
    with _patched(fake):
        host._job("generate")


def _take_out(lib):
    """Current's first item linked to two cards off the list, one list word's card and the studied card; Current's
    second item shares a third card off the list with it. Then the host lays the ladder (its lines kept in `said`, its
    reports in `reports`), and the first item's cards are taken out by the caller."""
    language, root, store = lib
    fake, words, by_word = _deck(language, root)
    out = [by_word[w] for w in UNLISTED[language][:2]]
    shared, listed, other = by_word[UNLISTED[language][2]], by_word[words[0]], by_word[words[5]]
    reviewed = by_word[REVIEWED[language]]
    a, b = store.ids("now")[:2]
    _link(store, a, *out, listed, shared, reviewed)
    _link(store, b, shared)
    said, reports = [], []
    host = replan_preview.Host(language, say=said.append)
    write = host._write
    host._write = lambda *args, **kwargs: reports.append(write(*args, **kwargs)) or reports[-1]
    with _patched(fake):
        host._job("catch-up")
    return fake, host, a, out, shared, listed, other, dict(reviewed), said, reports


@pytest.mark.parametrize("how", ["put-back", "order-on", "undo"])
def test_taken_out_then_put_back_round_trips_exactly_what_was_changed(lib, monkeypatch, how):
    language, root, store = lib
    fake, host, a, out, shared, listed, other, reviewed, said, reports = _take_out(lib)
    recorded_by = []
    record = library_store.Store.record_anki_changes
    monkeypatch.setattr(library_store.Store, "record_anki_changes",
                        lambda self, rows, by="connect": recorded_by.append(by) or record(self, rows, by=by))
    change = store.finish([a], keep_cards=False)
    assert _owed(store), "T-4: owed to Anki"
    _after_its_generate(lib, fake, host, out, 0)
    out_ids = sorted(card["cardId"] for card in out)
    assert [card["queue"] for card in out] == [-1, -1] and all(OUT_TAG in _tags(fake, card) for card in out)
    new = {c["cardId"]: c["due"] for c in fake.cards.values() if c["type"] == 0 and c["cardId"] not in out_ids}
    assert min(card["due"] for card in out) > max(new.values()), "after every other card"
    # P4.1-7 (TF fix 3; moved from T-2's "the item wins over the list"): its list word's card stays in, by the list
    assert listed["queue"] == 0 and OUT_TAG not in _tags(fake, listed) and listed["due"] < min(c["due"] for c in out)
    assert shared["queue"] == 0 and OUT_TAG not in _tags(fake, shared), "T-3: Current's second item claims it"
    by_id = {c["cardId"]: c for c in fake.cards.values()}
    assert by_id[reviewed["cardId"]] == reviewed, "a studied card is never touched"
    records = store.anki_changes_of([a])
    assert [(r["action"], r["after"]["suspended"], r["after"]["tag"], sorted(r["after"]["tagged"])) for r in records] \
        == [("cards_out", out_ids, OUT_TAG, sorted(card["note"] for card in out))]
    assert recorded_by == ["replan"], "TF fix 10: the host's own record"
    assert not _owed(store), "the clean job recorded the order planned"
    assert any("2 new cards taken out of your order" in line for line in said), said

    other["queue"] = -1                                         # meanwhile you suspend a card yourself
    if how == "put-back":
        store.put_back_finished([a])
    elif how == "order-on":
        store.set_learning_order([a], on=True)
    else:
        store.undo(change)
    assert store.item(a)["in_learning_order"] == 1 and _owed(store)
    if how == "order-on":                                       # no tier move: the re-order at once
        with _patched(fake):
            host._job("move")
    else:
        _after_its_generate(lib, fake, host, out, -1)
    assert [card["queue"] for card in out] == [0, 0] and not any(OUT_TAG in _tags(fake, card) for card in out)
    planned = reports[-1]["stats"]["order"]
    assert set(out_ids) <= {row.card_id for row in planned} and not [row for row in planned if row.out], \
        "placed again in the same job, nothing out"
    assert other["queue"] == -1, "the card you suspended stays suspended"
    assert by_id[reviewed["cardId"]]["queue"] == 2
    assert store.anki_changes_of([a]) == [] and store.cards_out() == {"out": [], "back": []}
    unsuspended = [c for action, ids in fake.suspend_calls if action == "unsuspend" for c in ids]
    assert sorted(unsuspended) == out_ids, "exactly the recorded cards, never more"
    assert any("2 cards put back in your order" in line for line in said), said


def test_a_review_at_the_suspends_leaves_the_take_out_owed(lib):
    """TF fix 6 (adversary S3): a review begins just as the job re-reads the cards it would suspend — nothing is taken
    out, nothing recorded, and the host doesn't record the plan as written: the take-out stays owed for its next look."""
    language, root, store = lib
    fake, host, a, out, _shared, _listed, _other, _reviewed, _said, _reports = _take_out(lib)
    out_ids = sorted(card["cardId"] for card in out)

    def review_begins(ids):
        if sorted(ids) == out_ids:
            fake.reviewing = True
    fake.before_cards_info = review_begins
    store.finish([a], keep_cards=False)
    _after_its_generate(lib, fake, host, out, 0)
    assert [card["queue"] for card in out] == [0, 0] and not any(OUT_TAG in _tags(fake, card) for card in out)
    assert store.anki_changes_of([a]) == []
    assert _owed(store), "still owed: the next look takes them out"


def test_a_name_two_items_carry_is_not_returned_as_one_items_out_name(lib, monkeypatch):
    """The take-out's names: a name two items carry is shared, so it is no out item's own name. The item that
    stays in carries 山田 too, so read_out's `names` for the out item keep only 小鳥遊; 山田 is in no kept name either.
    The names are patched so the shared name is known exactly."""
    from modules.junban import pins
    language, root, store = lib
    fake, host, a, out, _shared, _listed, _other, _reviewed, _said, _reports = _take_out(lib)
    a, b = store.ids("now")[:2]
    store.finish([a], keep_cards=False)
    _after_its_generate(lib, fake, host, out, 0)
    paths = dict(store.conn.execute("SELECT id, rel_path FROM items").fetchall())
    carried = {paths[a]: {"小鳥遊", "山田"}, paths[b]: {"山田"}}
    monkeypatch.setattr(pins, "names_of", lambda path, video=None: carried.get(path, set()))
    got = pins.read_out(language)
    assert [item_id for item_id, _path in got["out"]] == [a]
    assert got["names"] == {a: {"小鳥遊"}}, "山田 is carried by the item that stays in: not the out item's own"
    assert "山田" not in got["kept_names"]


def test_with_automation_off_nothing_reaches_anki_and_nothing_is_recorded(lib):
    """T-6: D29 off — the window's words stay *Leave its new cards out of your order*; Anki is never asked."""
    language, root, store = lib
    fake, host, a, out, _shared, _listed, _other, _reviewed, _said, _reports = _take_out(lib)
    _settings_file(root, target_language=language, junban_replan_language=language, logic={"automation": False})
    store.finish([a], keep_cards=False)
    fake.requests.clear()
    with _patched(fake):
        host._job("move")
    assert fake.requests == [] and [card["queue"] for card in out] == [0, 0]
    assert store.anki_changes_of([a]) == []


def test_a_refused_put_back_tag_removal_is_reported_in_note_failures(lib, monkeypatch):
    """A note whose Put-back tag removal Anki refuses is a failure the job reports in its note_failures. Real
    Anki refusals are answered through the fake's `urlopen`; here the removal is refused on the module the host
    calls it through."""
    from modules.junban import ankiconnect
    language, root, store = lib
    fake, host, a, out, _shared, _listed, _other, _reviewed, _said, reports = _take_out(lib)
    store.finish([a], keep_cards=False)
    _after_its_generate(lib, fake, host, out, 0)
    assert all(OUT_TAG in _tags(fake, card) for card in out), "the take-out tagged the cards first"
    store.put_back_finished([a])
    assert _owed(store), "the Put back is owed to Anki"

    def refuse(url, note_ids, tag, chunk=150):          # touched nothing; every note a (note_id, reason) failure, as _tag_action returns
        return [], [(note_id, "refused") for note_id in note_ids]
    monkeypatch.setattr(ankiconnect, "remove_tags", refuse)
    _after_its_generate(lib, fake, host, out, -1)
    report = reports[-1]                                        # the job's report: _put_back_owed puts the failures here
    assert sorted(note_id for note_id, _reason in report["note_failures"]) == sorted(card["note"] for card in out), \
        "Each refused removal is a note failure of the job's report"
    assert {reason for _note_id, reason in report["note_failures"]} == {"refused"}


def test_only_cards_out_records_are_held_as_cards_out(lib):
    """The cards held out of a learner's order are the ones the take-out itself recorded as cards out; the
    read-back `held` list must hold those records and nothing else, or a card the learner never took out would count."""
    from modules.junban import pins
    language, root, store = lib
    fake, host, a, out, _shared, _listed, _other, _reviewed, _said, _reports = _take_out(lib)
    store.finish([a], keep_cards=False)
    _after_its_generate(lib, fake, host, out, 0)
    assert [card["queue"] for card in out] == [-1, -1], "the take-out ran, so the cards are out"
    # a non-cards-out record on the same out item (a suspend the learner made elsewhere) is open too; it must not be held
    store.record_anki_changes([(a, "suspend", [999000001], {"queue": 0}, {"queue": -1})])
    store.record_anki_changes([(a, "tag", [999000002], {"tag": ""}, {"tag": "Surasura::other"})])
    open_records = store.anki_changes_of([a])
    assert any(record["action"] == "suspend" for record in open_records), "the stray record is open"
    assert any(record["action"] == "tag" for record in open_records), "the second stray record is open"
    cards_out = [record for record in open_records if record["action"] == pins.OUT_ACTION]
    assert cards_out, "the take-out recorded its cards as cards out"
    held = pins.read_out(language).get("held") or []
    assert held, "the taken-out cards are held out"
    assert all(record["action"] == pins.OUT_ACTION for record in held), held
    assert sorted(record["id"] for record in held) == sorted(record["id"] for record in cards_out), held
