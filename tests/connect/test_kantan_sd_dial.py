"""The sentence dial (Kantan-SD, 3.0.18; the mining model's *Nearest · Best* and round 4's young words) — one picker,
`app/connect/sentences.py`, every reader calls; the line inside the episode it chooses is `pick.pick`'s. What each
test holds:

  * Best: understandable first (the fewest other unknown words), then media that can be cut, then the weight — the
    young words the sentence also holds (the younger, the more) and the context you remember — then the episode being
    mined on a tie; a young word or a remembered show never lifts a harder sentence over an easier one;
  * Nearest: the episode's own sentences first, then the rest as Best ranks them;
  * `never` (Swap's old card's sentence) is never chosen again, in the library nor inside the episode;
  * no Anki: the young record absent, empty or unreadable is no weight (the recently-known seam stands in);
  * the runner's Best moves a word to the episode with the better sentence through a kept level job, and only then.

Real Japanese and Chinese lines (natural sentences written for these tests, no show's lines), a real token store as the
indexer leaves it (`sentence_corpus.build` indexes the sandbox library).
"""
import json
import os

import pytest

from app import analyzer, cues
from app import sentence_corpus as sc
from app.connect import level, pick, sentences
from app.connect.ledger import LEVEL, Ledger

EASY = "明日から冒険に出かけよう。"          # every word known but 冒険
TODAY = "今日から冒険に出かけよう。"         # the same, 今日 for 明日
HARD = "未知の迷宮で壮絶な冒険が始まった。"    # 未知 迷宮 壮絶 unknown too
NEAR = "明日から未知の冒険に出かけよう。"      # 未知 unknown too: i+2


@pytest.fixture(autouse=True)
def _a_japanese_run():
    analyzer.SANITIZE_JA = True


def _lemmas(line, language="ja"):
    analyzer.SANITIZE_JA = (language == "ja")
    tok = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    return {t[0] for _text, tokens in tok.tokenize_sentences(line) for t in tokens}


def _key(line, lemma, language="ja"):
    analyzer.SANITIZE_JA = (language == "ja")
    tok = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    return next((t[0], t[1]) for _t, tokens in tok.tokenize_sentences(line) for t in tokens if t[0] == lemma)


def _library(language, files, known=()):
    """A real library in the sandbox, indexed: {name: [lines]} in NOW, KnownWord.json of `known` -> the files' paths in
    library order."""
    root = os.environ["SURASURA_TEST_ROOT"]
    now = os.path.join(root, "data", language, "HighPriority")
    os.makedirs(now, exist_ok=True)
    for name, lines in files.items():
        with open(os.path.join(now, name), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    user_files = os.path.join(root, "User Files", language)
    os.makedirs(user_files, exist_ok=True)
    with open(os.path.join(user_files, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]}, f, ensure_ascii=False)
    sc.build(language, os.path.join(root, f"corpus-{language}.zip"), progress=lambda message: None)
    paths = {os.path.basename(p): p for p in sc.library_files(language)}
    return [paths[name] for name in files]


def _texts(choices):
    return [c.text for c in choices]


@pytest.fixture
def no_store(monkeypatch):
    """No library store's dates: every sentence's context is 0 unless a test hands one in."""
    info = {}
    monkeypatch.setattr(sentences, "_library", lambda language, store=None: info)
    return info


def _place(info, path, item_id, ctx=0.0, audio=True):
    info[os.path.normcase(os.path.abspath(path))] = (item_id, ctx, audio)


def test_best_takes_the_libraries_understandable_sentence_and_nearest_the_episodes_own(no_store):
    # why: Sonic's round 3 — Best is the most automated (the best sentence anywhere: understandable first); Nearest is
    # the episode's own line, an i+2 made i+1 by the other word's card coming first (Junban's order)
    here, other = _library("ja", {"第01話.txt": [HARD], "第02話.txt": [EASY]}, known=_lemmas(EASY) - {"冒険"})
    key = _key(EASY, "冒険")
    best = sentences.choose("ja", [key], here=here, dial=sentences.BEST, files=[here, other], young={})[key]
    nearest = sentences.choose("ja", [key], here=here, dial=sentences.NEAREST, files=[here, other], young={})[key]
    assert _texts(best) == [EASY, HARD] and best[0].others == 0 and best[1].others > 0
    assert best[1].here and not best[0].here
    assert _texts(nearest)[0] == HARD, "Nearest: the episode's own line"
    assert sentences.better(best[0], best[1]) and not sentences.better(best[1], best[0])


def test_a_young_word_lifts_an_equally_easy_sentence_the_younger_the_more(no_store):
    # why: round 4 — a sentence that also uses a word you are still learning doubles and cements it; the younger the
    # card, the more it weighs
    a, b = _library("ja", {"第01話.txt": [EASY], "第02話.txt": [TODAY]},
                    known=(_lemmas(EASY) | _lemmas(TODAY)) - {"冒険"})
    key = _key(EASY, "冒険")

    def order(young):
        return _texts(sentences.choose("ja", [key], dial=sentences.BEST, files=[a, b], young=young)[key])
    assert order({}) == [EASY, TODAY], "no young words: the library's order"
    assert order({"今日": 0.9}) == [TODAY, EASY]
    assert order({"今日": 0.3, "明日": 0.9}) == [EASY, TODAY], "the younger word weighs more"
    assert order({"冒険": 1.0}) == [EASY, TODAY], "the card's own word never counts toward its young words"


def test_a_young_word_or_a_remembered_show_never_lifts_a_harder_sentence(no_store):
    # why: round 4 — the young weight never outranks understandable (i+1) or reachable media
    a, b = _library("ja", {"第01話.txt": [NEAR], "第02話.txt": [TODAY]},
                    known=(_lemmas(NEAR) | _lemmas(TODAY)) - {"冒険", "未知"})
    _place(no_store, a, 1, ctx=1.0)
    _place(no_store, b, 2, ctx=0.0)
    key = _key(TODAY, "冒険")
    got = sentences.choose("ja", [key], dial=sentences.BEST, files=[a, b], young={"明日": 1.0})[key]
    assert _texts(got) == [TODAY, NEAR] and got[1].weight > got[0].weight


def test_the_show_you_saw_last_week_beats_goal_content_and_a_tie_stays_in_the_episode(no_store):
    # why: MODEL.md § 2 — the context the learner remembers is the lever (weight and tie-breaker); a word moves to
    # another episode only for a better sentence, never an equal one
    goal, seen = _library("ja", {"第01話.txt": [EASY], "第02話.txt": [TODAY]},
                          known=(_lemmas(EASY) | _lemmas(TODAY)) - {"冒険"})
    _place(no_store, goal, 1, ctx=0.0)
    _place(no_store, seen, 2, ctx=sentences.context("2026-11-14T09:00:00Z",
                                                    now=sentences.datetime(2026, 11, 21, tzinfo=sentences.timezone.utc)))
    key = _key(EASY, "冒険")
    got = sentences.choose("ja", [key], here=goal, dial=sentences.BEST, files=[goal, seen], young={})[key]
    assert _texts(got) == [TODAY, EASY] and got[0].item_id == 2
    no_store[os.path.normcase(os.path.abspath(seen))] = (2, 0.0, True)
    tie = sentences.choose("ja", [key], here=seen, dial=sentences.BEST, files=[goal, seen], young={})[key]
    assert tie[0].here and tie[0].text == TODAY, "equal sentences: the episode being mined keeps it"
    assert not sentences.better(tie[1], tie[0])


def test_context_weighs_a_week_ago_over_the_episodes_ahead_over_eight_months_ago():
    # why: MODEL.md § 2 — finished 8 months ago is worth less than 1 week ago, and probably less than one they'll
    # watch in 2 weeks; Goal and New arrivals nothing (PROVISIONAL numbers, the order is the rule)
    now = sentences.datetime(2026, 11, 21, tzinfo=sentences.timezone.utc)
    week = sentences.context("2026-11-14T00:00:00Z", now=now)
    months = sentences.context("2026-03-21T00:00:00Z", now=now)
    soon = sentences.context(None, place=6, now=now)
    assert 1.0 > week > soon > months > 0
    assert sentences.context("earlier", now=now) == sentences.EARLIER_WEIGHT
    assert sentences.context(None, tier="soon", now=now) == sentences.SOON_WEIGHT
    assert sentences.context(None, tier="goal", now=now) == 0.0 == sentences.context(None, tier="arrivals", now=now)
    assert sentences.context("not a date", tier="goal", now=now) == 0.0


def test_a_sentence_whose_media_cant_be_cut_is_no_choice(no_store):
    # why: media reach before Torii — another show's sentence needs its video to cut the clip; a look that fails is a no
    here, other = _library("ja", {"第01話.txt": [HARD], "第02話.txt": [EASY]}, known=_lemmas(EASY) - {"冒険"})
    _place(no_store, here, 1)
    _place(no_store, other, 2)
    key = _key(EASY, "冒険")

    def best(reach):
        return _texts(sentences.choose("ja", [key], here=here, dial=sentences.BEST, files=[here, other], young={},
                                       reach=reach)[key])
    assert best(lambda item_id: True) == [EASY, HARD]
    assert best(lambda item_id: item_id != 2) == [HARD], "its video isn't there"

    def broken(item_id):
        raise OSError("the NAS is asleep")
    assert best(broken) == [HARD], "the episode being mined is never asked"


def test_never_the_same_line_in_the_library_or_inside_the_episode(no_store, tmp_path):
    # why: Swap's rule on top of the picker — a new card is never cut from the old card's line again; a word said in
    # that line only has no other choice
    here, other = _library("ja", {"第01話.txt": [HARD], "第02話.txt": [EASY]}, known=_lemmas(EASY) - {"冒険"})
    key = _key(EASY, "冒険")
    got = sentences.choose("ja", [key], dial=sentences.BEST, files=[here, other], young={},
                           never={key: {"明日から 冒険に出かけよう。\n"}})[key]
    assert _texts(got) == [HARD], "the same characters, spaces and line breaks aside"
    assert sentences.same_line("冒険に出かけよう", {EASY}), "a line inside the old card's sentence is the same line"
    assert not sentences.same_line(HARD, {EASY}) and not sentences.same_line(EASY, set())

    srt = _srt(tmp_path, [(10.0, 12.0, EASY), (40.0, 42.0, TODAY)])
    read = cues.read(srt, "ja")
    tokens = cues.tokens(read, "ja")
    new = {"冒険"}

    def picked(**kw):
        return pick.pick(read, tokens, "ja", lambda k: k[0] not in new, mode="unknown", **kw)
    assert [w["line_start"] for w in picked(never={key: {EASY}})["words"]] == [40.0]
    out = picked(never={key: {EASY, TODAY}})
    assert out["words"] == [] and [n["reason"] for n in out["not_offered"]] == ["only-line"]


def test_inside_an_episode_a_young_word_breaks_the_last_tie_only(tmp_path):
    # why: round 4, as Nearest's tie-break — after every rule the line already has (no other new word, its audio, the
    # 8 s cap, written out), never before them
    srt = _srt(tmp_path, [(10.0, 12.0, EASY), (40.0, 42.0, TODAY), (70.0, 72.0, NEAR)])
    read = cues.read(srt, "ja")
    tokens = cues.tokens(read, "ja")

    def start(young, new=("冒険",)):
        chosen = pick.pick(read, tokens, "ja", lambda k: k[0] not in set(new), mode="unknown", young=young)
        return {w["word"]: w["line_start"] for w in chosen["words"]}["冒険"]
    assert start(None) == 10.0, "the earliest, as before"
    assert start({"今日": 0.9}) == 40.0
    assert start({"未知": 1.0, "明日": 1.0}, new=("冒険", "未知")) == 10.0, "never over a line with no other new word"


def test_a_word_with_one_sentence_gets_it_either_way_and_none_gets_an_empty_list(no_store):
    here = _library("ja", {"第01話.txt": [EASY]}, known=_lemmas(EASY) - {"冒険"})[0]
    key = _key(EASY, "冒険")
    for dial in sentences.DIALS:
        assert _texts(sentences.choose("ja", [key], here=here, dial=dial, files=[here], young={})[key]) == [EASY]
    missing = ("竜巻", "タツマキ")
    assert sentences.choose("ja", [missing], files=[here], young={}) == {missing: []}
    assert sentences.choose("ja", [], files=[here]) == {}


def test_chinese_sentences_are_chosen_by_the_same_rules(no_store):
    known = {"在", "桌子", "上", "他", "接到", "了", "我", "明天", "给", "你", "打"}
    easy, hard = "他接到电话了。", "那个陌生人打来的电话很奇怪。"
    here, other = _library("zh", {"第01集.txt": [hard], "第02集.txt": [easy]}, known=known)
    key = _key(easy, "电话", "zh")
    got = sentences.choose("zh", [key], here=here, dial=sentences.BEST, files=[here, other], young={})[key]
    assert _texts(got) == [easy, hard] and got[0].others == 0
    near = sentences.choose("zh", [key], here=here, dial=sentences.NEAREST, files=[here, other], young={})[key]
    assert _texts(near)[0] == hard


def test_young_words_come_from_anki_and_without_it_from_the_recently_known_seam(monkeypatch):
    # why: no Anki — the young record absent, empty or unreadable is no weight; the review loop's known dates stand in
    assert sentences.young_weights("ja", read=lambda lang: [("今日", 1), ("明日", 20), ("今日", 5)]) == {
        "今日": pytest.approx(20 / 21), "明日": pytest.approx(1 / 21)}
    assert sentences.young_weights("ja", read=lambda lang: []) == {}

    def unreadable(lang):
        raise ValueError("anki_young.json is not JSON")
    assert sentences.young_weights("ja", read=unreadable) == {}
    assert sentences.young_weights("ja", read=lambda lang: [("", 1), (3, 2), ("猫", True), ("犬", 30)]) == {}
    monkeypatch.setattr(sentences, "recently_known", lambda lang: {"冒険": 0, "迷宮": 40})
    assert sentences.young_weights("ja", read=lambda lang: []) == {"冒険": 1.0}
    assert sentences.young_weights("ja", read=lambda lang: [("今日", 7)]) == {"今日": pytest.approx(14 / 21)}


def test_the_dial_reads_best_by_default_and_any_other_value_as_best():
    assert sentences.dial_of({}) == sentences.BEST == sentences.DEFAULT
    assert sentences.dial_of({"connect_sentence_dial": "nearest"}) == sentences.NEAREST
    assert sentences.dial_of({"connect_sentence_dial": "balanced"}) == sentences.BEST
    assert sentences.dial_of(None) == sentences.BEST
    from app import settings_manager
    assert settings_manager.DEFAULT_SETTINGS["connect_sentence_dial"] == sentences.DEFAULT


# --- the runner's Best: a word moves to the episode with the better sentence ---------------------------------------
class _Steps:
    def __init__(self, dial="best", videos=(2, 3)):
        self.dial, self.videos = dial, set(videos)

    def _settings(self, lang):
        return {"connect_sentence_dial": self.dial}

    def video(self, lang, job):
        return f"episode-{job['item_id']}.mkv" if job["item_id"] in self.videos else None


def _words(*keys):
    return [{"word": w, "reading": r, "line_text": HARD, "other_new": 2} for w, r in keys]


def _choices(here, by_key):
    def choose(lang, keys, **kw):
        assert kw["dial"] == sentences.BEST and kw["here"] == here
        return {key: by_key.get(key, []) for key in keys}
    return choose


def test_best_moves_a_word_to_the_episode_with_the_better_sentence_through_a_kept_level_job(tmp_path, monkeypatch):
    from app.connect import runner
    adventure, maze = ("冒険", "ボウケン"), ("迷宮", "メイキュウ")
    here = str(tmp_path / "第01話.srt")
    better = sentences.Choice("第02話.srt", 2, EASY, 0, 0.5, False, True)
    own = sentences.Choice(here, 1, HARD, 2, 0.5, True, True)
    monkeypatch.setattr(sentences, "choose", _choices(here, {adventure: [better, own], maze: [own]}))
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        job = {"id": 9, "item_id": 1, "kind": "new", "store_id": "s-1"}
        kept, moved = runner._best(_Steps(), ledger, "ja", job, _words(adventure, maze), here)
        assert [w["word"] for w in kept] == ["迷宮"]
        assert moved == [{"word": "冒険", "reading": "ボウケン", "item_id": 2, "text": EASY}]
        (made,) = [ledger.job_by_id(j["id"]) for j in ledger.jobs("ja") if j["kind"] == LEVEL]
        assert made["item_id"] == 2 and made["source"] == level.BEST and made["words"] == [adventure]
        assert made["store_id"] == "s-1"


def test_best_keeps_the_word_on_a_tie_an_ask_nearest_or_when_the_other_episode_is_busy(tmp_path, monkeypatch):
    from app.connect import runner
    adventure = ("冒険", "ボウケン")
    here = str(tmp_path / "第01話.srt")
    equal = sentences.Choice("第02話.srt", 2, EASY, 2, 0.5, False, True)
    own = sentences.Choice(here, 1, HARD, 2, 0.5, True, True)
    better = equal._replace(others=0)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        job = {"id": 9, "item_id": 1, "kind": "new", "store_id": "s-1"}
        monkeypatch.setattr(sentences, "choose", _choices(here, {adventure: [equal, own]}))
        assert runner._best(_Steps(), ledger, "ja", job, _words(adventure), here)[1] == [], "a tie stays"
        monkeypatch.setattr(sentences, "choose", _choices(here, {adventure: [better, own]}))
        for steps, asked in ((_Steps(dial="nearest"), {}), (_Steps(), {"asked_at": "2026-11-21T10:00:00Z"}),
                             (_Steps(), {"kind": runner.LEVEL})):
            assert runner._best(steps, ledger, "ja", dict(job, **asked), _words(adventure), here)[1] == []
        ledger.queue("ja", 2, "user", None)              # the other episode's first mining, not started
        kept, moved = runner._best(_Steps(), ledger, "ja", job, _words(adventure), here)
        assert moved == [] and len(kept) == 1, "its own pick takes the list's words as they are"
        assert [j for j in ledger.jobs("ja") if j["kind"] == LEVEL] == []

        def broken(lang, keys, **kw):
            raise OSError("the token store is busy")
        monkeypatch.setattr(sentences, "choose", broken)
        assert runner._best(_Steps(), ledger, "ja", dict(job, item_id=5), _words(adventure), here)[1] == []


def test_a_best_job_is_kept_for_a_watched_or_finished_episode_and_reads_its_unlisted_word():
    # why: a Best word's episode was chosen for the context you remember — watched or finished is why, not a reason to
    # drop it (the 3.0 rule against new cards from watched episodes is about first minings and raises); removed drops
    from app.connect import inbox
    best = {"kind": LEVEL, "source": level.BEST, "words": [("冒険", "ボウケン"), ("迷宮", "メイキュウ")]}
    assert inbox.keeps(best) and inbox.keeps(best, "finished") and inbox.keeps(best, "left_mine_line")
    assert not inbox.keeps(best, "removed")
    assert level.BEST in level.KEPT and level.NEW_FILES in level.KEPT
    listed = {("冒険", "ボウケン"): 4, ("散歩", "サンポ"): 1}
    assert level.restrict(listed, best) == {("冒険", "ボウケン"): 4, ("迷宮", "メイキュウ"): 2}, \
        "Cards for every new word: an unlisted word still goes, after the listed"
    raise_job = dict(best, source=level.NEW_FILES)
    assert level.restrict(listed, raise_job) == {("冒険", "ボウケン"): 4}


def _srt(tmp_path, lines, name="episode.ja.srt"):
    def stamp(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    body = "\n".join(f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n" for n, (a, b, text) in enumerate(lines, 1))
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)
