# SPDX-License-Identifier: GPL-3.0-or-later
"""With the Connect preview off, Junban and Backfill do exactly what 2.5 did (P1.4 row 1.4.1).

Every behaviour P1.4 adds — your own cards first, a returning word's card unsuspended, the word found in a sentence
with no bold mark, per-run undo snapshots, the source field — applies only while `connect_enabled` is on
(`modules/junban/connect.py`, read once per run). This file holds the proof for "off": one scene that carries every
one of those triggers (notes Connect made, a card mined by hand after Connect's first, a parked card whose word is back
on the list, a conjugated word in a sentence with no bold mark), run through the 順 window's preview and its Reorder,
the automatic reorder, and Backfill's preview, fill and automatic fill. What each one returns, every request the fake
AnkiConnect saw, the collection afterwards and the snapshot on disk are compared, as text, with the record taken from
2.5.0's own code (public v2.5.0 + private 409bbbe), `golden/preview_gate_2.5.json`.

Recording again (only from 2.5's code, in a scratch tree holding both repos at those commits):
`SURASURA_RECORD_PREVIEW_GATE=1 python -m pytest modules/junban/tests/test_preview_gate.py`.

Against the same FakeCollection as the engine's own tests: real Japanese words on real Lapis fields, never a live Anki.
"""
import json
import os

import pytest

from modules.junban import auto, backfill, reposition, undo
from modules.junban.tests.test_backfill import _Session, _fake, _lapis
from modules.junban.tests.test_backfill import _settings as _fill_settings
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, FIRST_CARD, FIRST_NOTE, FakeCollection, _card,
                                                  _known, _patched, _results, _settings)

_GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden", "preview_gate_2.5.json")
_RECORD = os.environ.get("SURASURA_RECORD_PREVIEW_GATE") == "1"
_ACTIONS = ("setSpecificValueOfCard", "multi", "suspend", "unsuspend")
CONNECT_TAG = "surasura::connect::job-20261006-1"

# (word, its sentence, FreqSort, tags, queue): the triggers of every P1.4 behaviour, in one deck.
SCENE = [
    ("須藤", "須藤さんが来た。", 9000, [], 0),                       # your backlog, not on the list
    ("散歩", "毎朝<b>散歩</b>に出かける。", 3000, [], 0),              # your backlog, on the list
    ("図書館", "図書館で本を読んだ。", 6000, [], 0),                   # your backlog, not on the list
    ("冒険", "冒険が始まった。", 2000, [CONNECT_TAG], 0),             # Connect's first card
    ("走る", "毎朝公園まで走った。", 4000, [], 0),                     # mined by hand after it; no bold, conjugated
    ("眼鏡", "新しい眼鏡を買った。", 5000, [CONNECT_TAG], 0),          # Connect's, a word the list cut off
    ("老婆", "老婆が笑った。", 7000, ["Surasura::later"], -1),         # parked by Junban; back on the list
]
KNOWN = ["毎朝", "公園", "出かける", "来る", "本", "読む", "始まる", "新しい", "買う", "笑う", "さん"]


def _scene(tmp_path):
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    _known(tmp_path, KNOWN)
    cards, notes = [], []
    for i, (word, sentence, freqsort, tags, queue) in enumerate(SCENE):
        note_id = FIRST_NOTE + 300 + i
        notes.append({"noteId": note_id, "modelName": "Lapis", "tags": list(tags), "fields": {
            "Expression": {"value": word, "order": 0},
            "Sentence": {"value": sentence, "order": 1},
            "FreqSort": {"value": str(freqsort), "order": 2},
            "MiscInfo": {"value": "", "order": 3}}})
        card = _card(FIRST_CARD + 300 + i, note_id, 2800 + i)
        card["queue"] = queue
        cards.append(card)
    return FakeCollection(cards, notes, actions=_ACTIONS)


def _reorder_settings(**over):
    return _settings(junban_order="content", junban_later_tag=True, junban_later_flag=True,
                     junban_later_suspend=True, **over)


def _state(fake):
    """The collection afterwards: each card's position, queue and flag, each note's tags and fields."""
    return {"cards": {str(c): [card["due"], card["queue"], card.get("flags")] for c, card in sorted(fake.cards.items())},
            "notes": {str(n): [note.get("tags") or [], {k: v["value"] for k, v in note["fields"].items()}]
                      for n, note in sorted(fake.notes.items())}}


def _snapshot(language="ja", kind="reorder"):
    saved = undo.load(language, kind=kind)
    if saved:
        saved.pop("written_at", None)
    return saved


def _dry(stats, writes):
    keep = ("later", "touchups", "tiers", "banner", "ready_first", "to_write", "total", "matched", "unmatched",
            "skipped", "skipped_suspended", "decks")
    return {"writes": writes, "order": [_row_as_25(row) for row in stats.get("order") or []],
            **{key: stats.get(key) for key in keep}}


def _row_as_25(row):
    """A preview row as 2.5 had it: P2.2's trailing `pinned` (the *Study its cards first* group) is None whenever
    nothing is pinned — the only case 2.x knows (E1.3-3) — and is then dropped; a pinned row keeps it, so it can never
    pass for a 2.5 row."""
    # P4.1 L2 (package T): the trailing `out` (*Take its new cards out*) is dropped with it the same way
    return list(row)[:-2] if row.pinned is None and row.out is None else list(row)


def _fill_scene():
    """Backfill's scene: a note Connect made, one mined by hand, one already filled."""
    made = _lapis(0, "探検", "たんけん")
    made[0]["tags"] = [CONNECT_TAG]
    return _fake(made, _lapis(1, "大切", "たいせつ", patterns="<div>mine</div>"), _lapis(2, "囲む", "かこむ"))


def _record(tmp_path, preview=None):
    """Everything the scene produces, run by run. `preview` is the value `connect_enabled` is set to (None: absent)."""
    over = {} if preview is None else {"connect_enabled": preview}
    out = {}

    fake = _scene(tmp_path)
    with _patched(fake):
        writes, stats = reposition.dry_run(_reorder_settings(**over))
    out["dry_run"] = {"plan": _dry(stats, writes), "requests": fake.requests}

    fake = _scene(tmp_path)
    with _patched(fake):
        report = reposition.run(_reorder_settings(**over))
    out["reorder"] = {"message": report["message"], "written": report["written"], "requests": fake.requests,
                      "state": _state(fake), "snapshot": _snapshot()}
    os.remove(undo.snapshot_path("ja"))

    fake = _scene(tmp_path)
    with _patched(fake):
        # 2.x-dev: 2.5's dense run; 3.0: spaced always (W3.5 row 7), compared on its own (the test below)
        message = auto.run_quietly(_reorder_settings(junban_auto_reorder=True, enable_junban=True, **over))
    out["auto_reorder"] = {"message": message, "requests": fake.requests, "state": _state(fake),
                           "snapshot": _snapshot()}

    settings = _fill_settings(**over)
    fake = _fill_scene()
    with _patched(fake):
        planned = backfill.preview(settings, _Session())
    out["fill_preview"] = {"edits": planned["edits"], "rows": [list(r) for r in planned["rows"]],
                           "counts": planned["counts"], "requests": fake.requests}
    fake.requests = []
    with _patched(fake):
        report = backfill.run(settings, _Session(), planned=planned)
    out["fill"] = {"message": report["message"], "written": report["written"], "requests": fake.requests,
                   "state": _state(fake), "snapshot": _snapshot(kind="backfill")}
    os.remove(undo.snapshot_path("ja", "backfill"))

    fake = _fill_scene()
    with _patched(fake):        # the automatic fill's own run (`run_auto` minus its background library build)
        report = backfill.run(dict(settings, junban_backfill_cards="new", junban_backfill_replace=False),
                              _Session(), auto=True)
    out["auto_fill"] = {"message": report["message"], "requests": fake.requests, "state": _state(fake)}
    # FT (K1, on purpose): the manual reorder's and Backfill's runs read the open profile once, which 2.5 never did.
    # The automatic step hands its read to S1 instead (C7) — pinned below, request for request.
    for name in ("reorder", "fill", "auto_fill"):
        out[name]["requests"] = [r for r in out[name]["requests"] if r.get("action") != "getActiveProfile"]
    return json.loads(json.dumps(out, ensure_ascii=False))


def _text(record):
    return json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


@pytest.mark.parametrize("preview", [None, False])
def test_with_the_preview_off_every_junban_and_backfill_run_is_2_5s(tmp_path, preview):
    """Off — the key absent, as on every 2.5 install, or set to false — the window's preview and Reorder, the
    automatic reorder, and Backfill's preview, fill and automatic fill return, ask Anki, leave the collection and
    save their undo exactly as 2.5.0 did, byte for byte.

    2.x-dev keeps the automatic reorder in that compare too; 3.0 (E1.1 04 §5, Haya's G2b): it numbers spaced always,
    so its positions are new and it keeps today's baseline, not the window's snapshot — and, as in 2.5, nothing else:
    every card's queue and flag and every note as 2.5.0 left them."""
    record = _record(tmp_path, preview)
    if _RECORD:
        os.makedirs(os.path.dirname(_GOLDEN), exist_ok=True)
        with open(_GOLDEN, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_text(record))
        return
    with open(_GOLDEN, "r", encoding="utf-8") as handle:
        was = json.loads(handle.read())
    spaced_run, dense_run = record.pop("auto_reorder"), was.pop("auto_reorder")
    if _text(record) != _text(was):
        differ = [key for key in sorted(set(record) | set(was)) if record.get(key) != was.get(key)]
        pytest.fail(f"with the preview off, these differ from 2.5.0: {differ}")
    assert "Reordered" in spaced_run["message"] and spaced_run["snapshot"] is None, spaced_run["message"]
    assert spaced_run["state"]["notes"] == dense_run["state"]["notes"]
    cards, cards_25 = spaced_run["state"]["cards"], dense_run["state"]["cards"]
    assert {c: card[1:] for c, card in cards.items()} == {c: card[1:] for c, card in cards_25.items()}
    assert cards != cards_25, "spaced numbers, not 2.5's block"


def test_the_automatic_reorder_asks_anki_what_it_asked_before_the_first_touch_record(tmp_path, monkeypatch):
    """FT C7 (IK5 / H11): the automatic step's first-touch record costs no request — its profile read is the one S1
    made before the record. The scene's automatic reorder, run once with the record and once as it ran before it (each
    in a folder of its own), sends the same requests in the same order."""
    from app import anki_sync_rule
    from modules.junban import first_touch
    seen = {}
    for name in ("with_the_record", "before_it"):
        root = tmp_path / name
        (root / "persistent").mkdir(parents=True)
        monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))
        monkeypatch.setattr("app.path_utils.get_persistent_user_data_path", lambda root=root: str(root / "persistent"))
        monkeypatch.setattr(anki_sync_rule, "_path", lambda root=root: str(root / "anki_sync.json"))
        if name == "before_it":
            monkeypatch.setattr(reposition, "_keep_order", lambda *args, **kwargs: None)
        first_touch._COVERED.clear()
        fake = _scene(root)
        with _patched(fake):
            message = auto.run_quietly(_reorder_settings(junban_auto_reorder=True, enable_junban=True))
        assert "Reordered" in message, message
        seen[name] = fake.requests
    assert first_touch.has_anything("ja") is False          # the second folder's: the first kept its record
    assert seen["with_the_record"] == seen["before_it"]
