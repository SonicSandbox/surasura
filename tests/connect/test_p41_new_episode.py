"""P4.1 row 4.1.4 (C5; P3.3's C3; the intent keeper's S2): a new episode placed into the top 20 is mined before
its Generate.

A placement of a file no Generate has counted used to Generate first — the whole library analysed again, every card
held back for it. Now `replan.current` answers "after" (`new-files`) when the only thing that moved is files added (the
plan's own files all there, unchanged): the engine re-plans the files it knows, the new episode is mined at once — its
pick reads the episode's own lines as for every job (one recipe: bound one-kanji pieces, set phrases and names as
Generate reads them), ranked by the re-plan's list — then one Generate after mining (F11), the follow-up re-order and
the level look, which gives the episode the words that Generate newly lists. A file added with anything else moved (the
band, a file changed or gone) still Generates first.

On a real library (tests/plan_file_cases.py's RP-2 Japanese library, generated once, as `tests/test_replan_preview.py`'s
`lib` builds it; a Chinese twin on RP-2's Chinese one), a real episode copied in (`Test Resources/ja/placed_episode.srt`
a school-festival scene holding words already on the list, two set phrases — 気が付く on the list, 腑に落ちる listed only
once this episode counts — and 門 only as a counter, 二門, a bound piece the list never offers) and Connect's own steps
— the inbox and the level look, the pick, the store, Junban's re-order with the Junban suite's fake AnkiConnect — real;
only where Anki Miner sits a stand-in that makes one note a word. What a wrong answer would cost: every placed episode
waiting a whole Generate for its cards (or a Generate skipped when a file changed); a pick by a second recipe giving a
card to a piece of 二門 or missing a phrase; the episode's own new words never mined after the Generate.
"""
import os
import shutil

import pytest

pytest.importorskip("modules.junban")

from app import library_store  # noqa: E402
from app.cli import verbs  # noqa: E402
from app.connect import fit_check, replan, runner  # noqa: E402
from app.connect.ledger import Ledger  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402
from tests.connect.test_p33_replan import _loaded, connect  # noqa: E402,F401
from tests.test_replan_preview import _deck, _settings_file, lib  # noqa: E402,F401

RES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
EPISODE = "placed_episode.srt"
BOUND = ("門", "モン")                       # listed (RP-2's novels); in the episode only in 二門 (a counter: a piece)
ON_THE_LIST = ("気が付く", "キガツク")         # a set phrase the list holds already
NEWLY = {("文化祭", "ブンカサイ"), ("腑に落ちる", "フニオチル")}   # listed once the episode is counted


class PlacedEpisodeSteps(runner.Steps):
    """Connect's real steps — the inbox and level look (`consume`), prepare, the pick, the store's record, Junban's
    re-order, the Generate after mining — with a stand-in where Anki Miner and the outside world sit: no video or
    fit check to look at, one made note a word, no Backfill, no shelf. Every pick's job kind, words, the plan's
    ranks it was given and how many Generates had run by then are kept (`picks`)."""

    def __init__(self, loaded, generates):
        super().__init__(loaded)
        self.generates, self.picks, self.note = generates, [], 700000

    def lower_priority(self):
        pass

    def blocked(self, lang):
        return None

    def after_write(self, lang):
        pass

    def miner_found(self):
        return True

    def cap(self, lang=None):
        return 0

    def notes_gone(self, lang):
        return []

    def shelf_session(self, lang, ledger):
        pass

    def video(self, lang, job):
        return f"episode-{job['item_id']}.mkv"

    def pick(self, lang, job, video):
        got = super().pick(lang, job, None)         # no video: no Anki Miner asked at the pick
        plan = self.current(lang)
        self.picks.append({"kind": job.get("kind") or "mine", "item": job["item_id"],
                           "words": [(w["word"], w["reading"]) for w in got["words"]], "listed": plan.listed,
                           "generate": plan.generate, "generates": len(self.generates)})
        return dict(got, profile="p1", anki_miner="3.7.0", absent=False)

    def fit(self, lang, job, pairing, video, subtitle):
        return (fit_check.TIMED, "hato", None, 0.0)

    def mine(self, lang, job, picked, words, attempt):
        out = []
        for w in words:
            self.note += 1
            out.append({"word": w["word"], "reading": w["reading"], "outcome": "made", "note_id": self.note,
                        "line_start": w.get("line_start")})
        return {"outcomes": out, "app": "3.7.0", "doubt": False, "tag_pending": []}

    def name_media(self, lang, job, picked, lines):
        return None

    def fill(self, lang, job, note_ids):
        pass


def _copy_in(store, language, name, folder="GoalContent"):
    """A new episode dropped into the library (the Content Manager's sync takes it in) -> its item id."""
    from app.path_utils import get_data_path
    path = os.path.join(get_data_path(language), folder, name)
    shutil.copy(os.path.join(RES, language, name), path)
    library_store.sync_for_window(store)
    found = [i for tier in ("now", "soon", "goal") for i in store.ids(tier)
             if str((store.item(i) or {}).get("rel_path") or "").replace("\\", "/").endswith("/" + name)]
    assert len(found) == 1, found
    return found[0]


def _place_on_top(store, item):
    """You drag it to the top of NOW: into the top 20 (`entered_mine_line`, by you)."""
    store.move([item], "now", before_id=store.ids("now")[0])
    assert item in store.ids("now")[:20]


def _referee_pick(language, path, listed=None):
    """What a pick of the episode makes after a full Generate first (today's path): the same pick, the last
    Generate's list (`listed` None: the CSV), nothing made yet."""
    from types import SimpleNamespace
    ns = SimpleNamespace(lang=language, file=path, video=None, words=None, job="referee", wait=5.0, made=set(),
                         listed=listed)
    return [(w["word"], w["reading"]) for w in verbs.pick(ns)["words"]]


def test_a_placed_new_episode_is_mined_before_its_generate_then_given_its_new_words(connect):
    root, store, generates, _ledger_path = connect
    fake = _deck(root, n=20)
    steps = PlacedEpisodeSteps(_loaded(), generates)
    with _patched(fake), Ledger() as ledger:
        steps.consume("ja", ledger)                 # Connect on before you place it (the inbox's watermark, G1.1-2)
        item = _copy_in(store, "ja", EPISODE)
        _place_on_top(store, item)
        verdict = replan.current("ja", dict(_loaded(), target_language="ja"), store)
        assert verdict.generate == "after" and verdict.reason == "new-files", verdict.reason
        assert verdict.verdict == ("replan-now", ("files-added",)) and verdict.result is not None
        summary = runner.run(steps.loaded, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        owed = ledger.resort_owed("ja")
        jobs = [j for j in ledger.jobs("ja") if j["item_id"] == item]
    out = summary["languages"]["ja"]
    assert out["done"].count(item) == 2 and not out["needs"], out
    mine, level = steps.picks
    # mined before its Generate, by the re-plan's list, in the list's order
    assert mine["kind"] == "mine" and mine["item"] == item and mine["generates"] == 0, mine
    assert mine["generate"] == "after" and mine["words"], mine
    ranks = [mine["listed"][k] for k in mine["words"]]
    assert ranks == sorted(ranks), "picked in the list's order"
    assert ON_THE_LIST in mine["words"], "a set phrase already on the list is mined from the episode at once"
    assert BOUND in mine["listed"] and BOUND not in mine["words"], "二門's 門 is a piece: never its card"
    assert not NEWLY & set(mine["words"]), "words no list holds yet wait for the Generate"
    # then one Generate after mining, the follow-up order, and the level look's job for the words it newly lists
    assert generates == ["ja"], "one Generate, after mining"
    assert level["kind"] == "level" and level["item"] == item and level["generates"] == 1, level
    assert set(level["words"]) == NEWLY, level["words"]
    assert owed is None, "the follow-up re-order landed"
    assert [j["kind"] for j in jobs] == ["mine", "level"] and all(j["state"] == "done" for j in jobs), jobs
    # parity (one recipe): what Connect made for it is what a Generate first would have picked for it
    from app.path_utils import get_data_path
    path = os.path.join(get_data_path("ja"), "GoalContent", EPISODE)     # a move is data: the file stays put
    with _patched(fake):
        referee = _referee_pick("ja", path)
    assert set(mine["words"]) <= set(referee), "the words picked before the Generate are a full Generate's"
    assert set(mine["words"]) | set(level["words"]) == set(referee), "and with the level job, all of them"
    assert BOUND not in referee


def test_a_new_file_alone_is_re_planned_from_the_plans_own_files(lib):
    # S2: no "indexed" condition — the engine re-plans only the plan's files and the pick reads the episode's own
    # lines, so a file the background indexer hasn't read yet is served the same: the placed episode never waits
    root, store = lib
    item = _copy_in(store, "ja", EPISODE)
    _place_on_top(store, item)
    got = replan.current("ja", dict(_loaded(), target_language="ja"), store)
    assert got.generate == "after" and got.reason == "new-files", got.reason
    assert got.listed and item not in got.result.sequence, "the engine's re-plan holds the plan's files only"
    assert BOUND in got.listed and not NEWLY & set(got.listed), "the list as the plan holds it"


def _band_raised(root):
    _settings_file(root, logic={"selection": {"band": "uncommon"}})          # occasional -> uncommon


@pytest.mark.parametrize("also", ["band", "changed", "removed"])
def test_a_new_file_with_anything_else_moved_generates_first(lib, also):
    # why: only files added alone keep the plan's own words right — a band, a changed or a removed file moves what
    # the old list would mine (the Generate first, as today)
    root, store = lib
    item = _copy_in(store, "ja", EPISODE)
    _place_on_top(store, item)
    if also == "band":
        _band_raised(root)
    else:
        from app.path_utils import get_data_path
        other = os.path.join(get_data_path("ja"), "HighPriority", "gotoubun_ep01.srt")
        if also == "changed":
            with open(other, "a", encoding="utf-8") as f:
                f.write("\n99\n00:09:00,000 --> 00:09:02,000\nまた明日ね。\n")
        else:
            os.remove(other)
        library_store.sync_for_window(store)
    got = replan.current("ja", dict(_loaded(), target_language="ja"), store)
    assert got.generate == "first" and got.verdict[0] == "generate-first", (got.verdict, got.reason)
    assert got.result is None and got.listed is None


def test_with_the_band_raised_too_connect_generates_before_it_mines(connect):
    root, store, generates, _ledger_path = connect
    fake = _deck(root, n=20)
    steps = PlacedEpisodeSteps(_loaded(), generates)
    with _patched(fake), Ledger() as ledger:
        steps.consume("ja", ledger)
        item = _copy_in(store, "ja", EPISODE)
        _place_on_top(store, item)
        _settings_file(root, connect_enabled=True, logic={"selection": {"band": "uncommon"}})
        steps.loaded = _loaded()
        runner.run(steps.loaded, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    first = steps.picks[0]
    assert first["item"] == item and first["generates"] == 1, "today's path: the Generate first"
    assert generates == ["ja"]


# --- the Chinese twin ---------------------------------------------------------------------------------------- #
from tests.connect import test_replan_current as zh_case  # noqa: E402
lib_zh = zh_case.lib_zh


def test_in_chinese_too_a_new_file_alone_is_re_planned_and_its_pick_is_a_full_generates(lib_zh):
    # Connect waits for Chinese cards (E24), but the verdict and the pick are one recipe for both languages: the
    # re-plan ranks the plan's words, and the new episode's pick by it is a subset of a full Generate's
    root, store = lib_zh
    item = _copy_in(store, "zh", "night_market.srt")
    _place_on_top(store, item)
    got = replan.current("zh", zh_case._loaded("zh"), store)
    assert got.generate == "after" and got.reason == "new-files", got.reason
    from app.path_utils import get_data_path
    path = os.path.join(get_data_path("zh"), "GoalContent", "night_market.srt")
    before = _referee_pick("zh", path, listed=got.listed)
    assert before, "the episode holds words already on the Chinese list"
    store.close()
    zh_case._generate(root, "rp2-zh", "zh")              # the full Generate: the referee
    after = _referee_pick("zh", path)
    assert set(before) <= set(after), (sorted(set(before) - set(after)))
    assert set(after) - set(before), "the Generate lists words only this episode holds: the level look's"
