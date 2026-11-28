"""TOP-UP (3.0.21, Sonic § 114 B; PROVISIONAL words): *Mine the new words* on a mined episode's ⋯ and on its show's ⋯
— the words that joined the list since the episode was mined, the same ones Connect tops up by itself
(`connect.actions.top_up`), first and past the cap.

Why: from 3.0.18 a mined episode was never mined again, so a tester who widened his rarity saw his mined episodes at
15–42 *new* each with nothing to press. What a wrong answer would cost: a press that makes a second card for a word,
remakes a card he deleted (that is *Mine again*'s), turns for ever, or asks for nothing and says nothing.

The whole flow as a learner walks it, on the real window over a real migrated store (`test_removed`'s `real`): an
episode mined (its receipt and one made word), a Generate's list that grew, the ⋯ opened, the entry picked, the worker,
Connect's ledger, the kick and the bar. Real Japanese and Chinese words; no Anki, no Connect run (the kick recorded).
"""
import json
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint

from app import settings_manager
from app.connect import kick, level, library
from app.connect.ledger import LEVEL, Ledger
from app.qt import mine_actions, strings
from tests.qt.conftest import wait_until
from tests.qt.test_drag import settle
from tests.qt.test_removed import real  # noqa: F401  (real: a fixture)

# (the word its first mining carded, two words the list gained since): real words of each language
WORDS = {"ja": (("残念", "ザンネン"), ("眼鏡", "メガネ"), ("駐車場", "チュウシャジョウ")),
         "zh": (("遗憾", "yí hàn"), ("眼镜", "yǎn jìng"), ("停车场", "tíng chē chǎng"))}


def _mined(language, n=1):
    """`before(store)`: the first `n` NOW items mined, each with a card for the first word -> the hook (`.ids`)."""
    def before(store):
        ids = store.ids("now")[:n]
        for k, item_id in enumerate(ids):
            library.record_batch(store, item_id, {WORDS[language][0][0]: [101 + k]}, "2026-11-20T10:00:00Z",
                                 batch=f"t-{k}")
        before.files = [os.path.basename(store.item(i)["rel_path"]) for i in ids]
        before.ids = ids
    return before


def _generate(language, files, words):
    """A last Generate's files, as Connect reads them (`connect_verbs._read_list`): the list (every word of `WORDS`),
    its run stamp, its language and `file_words.json` ({file: `words`' lemmas})."""
    from app.cli import verbs
    results = verbs._results_dir()
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, verbs.PRIORITY_CSV), "w", encoding="utf-8-sig", newline="") as f:
        f.write("Word,Reading,Orth\n" + "".join(f"{w},{r},{w}\n" for w, r in WORDS[language]))
    with open(os.path.join(results, "run_signature.txt"), "w", encoding="utf-8") as f:
        f.write("run-2")
    with open(os.path.join(results, "library_frequency.json"), "w", encoding="utf-8") as f:
        json.dump({"settings": {"language": language}}, f)
    with open(os.path.join(results, "file_words.json"), "w", encoding="utf-8") as f:
        json.dump({name: [w for w, _r in words] for name in files}, f, ensure_ascii=False)


def _open(real, language, before, monkeypatch):
    """Connect on, the window open on the mined library -> (win, kicks): Connect's kick recorded, never started."""
    settings_manager.save_keys({"connect_enabled": True})
    kicks = []
    monkeypatch.setattr(kick, "kick", lambda settings, videos=False: kicks.append(settings))
    _store, win, _writer = real(language, before=before)
    with Ledger():
        pass                                        # (Connect's ledger, as once Connect ran)
    assert wait_until(lambda: win.mine.off is None, 10), "Connect on: the press may ask"
    return win, kicks


def _row_of(win, item_id):
    """Current's row holding `item_id` once its episode reads mined -> (row, episode)."""
    lst = win.page_widgets["current"].list
    found = []

    def look():
        for _kind, row, _lines in lst.model().entries:      # (Up next's hero row too)
            ep = next((e for e in getattr(row, "episodes", None) or () if e.id == item_id), None)
            if ep is not None and ep.status is not None and ep.status.kind in mine_actions.MINED:
                found[:] = [row, ep]
                return True
        return False
    assert wait_until(look, 15), "the mined episode on Current"
    return found


def _pick(menu, label):
    act = next(a for a in menu.actions() if a.text() == label)
    assert act.isEnabled() and act.toolTip()
    act.trigger()
    menu.hide()


def _top_ups(language):
    with Ledger() as ledger:
        return [ledger.job_by_id(j["id"]) for j in ledger.jobs(language)
                if j["kind"] == LEVEL and j["source"] == level.TOP_UP]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_episodes_menu_mines_its_new_words_only_first_and_says_so(real, monkeypatch, language):
    # why: the learner's flow — an episode mined, the list grown, its ⋯ → *Mine the new words*: Connect's ledger gets
    # a top-up naming only the words no card holds (never the one its first mining carded), carrying the press's
    # time (first, past the cap); Connect is kicked; the pill turns from the press; the bar says what comes next
    before = _mined(language)
    win, kicks = _open(real, language, before, monkeypatch)
    made, *added = WORDS[language]
    _generate(language, before.files, [made] + added)
    row, ep = _row_of(win, before.ids[0])
    entries = win.mine.episode_entries(row, ep)
    assert [e.name for e in entries][:2] == ["ep-top-up", "ep-mine-again"], "beside *Mine again*"
    assert entries[0].tip == strings.TOP_UP_TIP and entries[0].writes
    _pick(win.items.episode_menu(row, ep, QPoint(0, 0)), strings.TOP_UP)
    press = win.presses.find(f"top-up:{win.language}:{ep.id}")
    assert press is not None, "the press is live from the pick"
    assert wait_until(lambda: len(_top_ups(language)) == 1, 10)
    (job,) = _top_ups(language)
    assert job["item_id"] == ep.id and job["asked_at"] and job["state"] == "queued"
    assert job["words"] == sorted(added), "the new words only: never the word its card holds"
    assert wait_until(lambda: kicks, 5), "Connect kicked"
    assert wait_until(lambda: win.bar_line.full() == strings.TOP_UP_ASKED[True].format(label=ep.label), 5)


def test_the_shows_menu_mines_every_mined_episodes_new_words(real, monkeypatch):
    # why: the show's ⋯ is one press for all its mined episodes (the tester's 15–42 *new* each)
    before = _mined("ja", n=2)
    win, kicks = _open(real, "ja", before, monkeypatch)
    made, *added = WORDS["ja"]
    _generate("ja", before.files, [made] + added)
    row, _ep = _row_of(win, before.ids[0])
    mined = {e.id for e in row.episodes if e.status is not None and e.status.kind in mine_actions.MINED}
    assert before.ids[0] in mined
    m = win.items.menu(row, QPoint(0, 0))
    assert strings.TOP_UP in [a.text() for a in m.actions()]
    _pick(m, strings.TOP_UP)
    assert wait_until(lambda: {j["item_id"] for j in _top_ups("ja")} == mined, 10)
    assert all(j["words"] == sorted(added) and j["asked_at"] for j in _top_ups("ja"))
    assert wait_until(lambda: kicks, 5)


def test_nothing_new_queues_nothing_and_the_bar_says_so(real, monkeypatch):
    # why: a press must never turn for ever nor ask Connect for an empty job
    before = _mined("ja")
    win, kicks = _open(real, "ja", before, monkeypatch)
    _generate("ja", before.files, [WORDS["ja"][0]])         # its only listed word has its card
    row, ep = _row_of(win, before.ids[0])
    _pick(win.items.episode_menu(row, ep, QPoint(0, 0)), strings.TOP_UP)
    assert wait_until(lambda: win.bar_line.full() == strings.TOP_UP_NOTHING, 10)
    settle(50)
    assert _top_ups("ja") == [] and kicks == []
    lst = win.page_widgets["current"].list
    assert ep.id not in lst.pressed_ids, "its pill is its own again"


def test_an_unmined_row_offers_no_top_up_and_connect_off_asks_nothing(real, monkeypatch):
    before = _mined("ja")
    win, kicks = _open(real, "ja", before, monkeypatch)
    row, ep = _row_of(win, before.ids[0])
    unmined = row._replace(episodes=type(row.episodes)(e._replace(status=None) for e in row.episodes))
    assert win.mine.row_entries(unmined) == []
    win.mine._off_read("Connect is off")
    (entry,) = [e for e in win.mine.row_entries(row) if e.name.endswith("top-up")]
    assert entry.tip == strings.ROWS_ACTION_OFF.format(tip=strings.TOP_UP_SHOW_TIP, why="Connect is off")
    entry.payload()
    settle(50)
    assert win.bar_line.full() == "Connect is off" and _top_ups("ja") == [] and kicks == []
