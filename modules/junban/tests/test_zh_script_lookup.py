# SPDX-License-Identifier: GPL-3.0-or-later
"""Junban under a Chinese `zh_script`: convert the card's lookup KEY, never the card (WP-Z5).

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md §4 (junban row).

With a Chinese library read as one script, `priority_learning_list.csv` spells every word in that
script, but a learner's Anki cards keep whatever script they were mined in. A Traditional 學習 card
has to find 学习 on a list read as Simplified, or the whole backlog reads as "unmatched" and nothing
moves. Only the lookup key converts. Anki is never sent converted text: a run writes `due` values,
never a note field.

Against FakeCollection only, never a real collection (see test_reposition.py).
"""
import csv

from modules.junban import reposition
from modules.junban.tests.test_reposition import FakeCollection, _collection, _patched, _settings

# On the cards: Traditional, as mined from a Taiwanese drama, in a deliberately wrong queue order.
CARDS = ["學習", "經濟", "關係", "發展", "頭髮"]
# The list, read as Simplified. Row index is the rank.
LIST_S = ["发展", "学习", "关系", "经济", "头发"]


def _write_list(tmp_path, words):
    """A BOM-carrying priority list in the sandboxed results/ (conftest points the root here)."""
    path = tmp_path / "results" / "priority_learning_list.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Word", "Orth", "Reading", "Tier"])
        for word in words:
            writer.writerow([word, word, "", "NOW"])


def _backlog():
    cards, notes, _ = _collection(CARDS, dues=[2804, 2803, 2802, 2801, 2800])
    return FakeCollection(cards, notes)


def test_traditional_cards_match_a_list_read_as_simplified(tmp_path):
    _write_list(tmp_path, LIST_S)
    fake = _backlog()
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(target_language="zh", zh_script="s"))
    assert stats["matched"] == len(CARDS)
    ranks = {row.word: row.rank for row in stats["order"]}
    assert ranks == {word: rank for rank, word in enumerate(LIST_S)}
    assert fake.writes == []


def test_as_is_the_same_cards_do_not_match(tmp_path):
    """The problem the conversion solves, pinned so the test above means something."""
    _write_list(tmp_path, LIST_S)
    with _patched(_backlog()):
        _writes, stats = reposition.dry_run(_settings(target_language="zh"))
    assert stats["matched"] == 0


def test_a_run_moves_cards_but_never_rewrites_a_note(tmp_path):
    _write_list(tmp_path, LIST_S)
    fake = _backlog()
    before = {nid: dict(note["fields"]) for nid, note in fake.notes.items()}
    with _patched(fake):
        report = reposition.run(_settings(target_language="zh", zh_script="s"))
    assert report["ok"], report
    assert fake.writes, "the backlog was in the wrong order, so cards must have moved"
    assert fake.note_writes == []
    assert {nid: dict(note["fields"]) for nid, note in fake.notes.items()} == before
