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
    monkeypatch.setattr(sentences, "_library", lambda language, store=None, ai=False: info)
    return info


def _place(info, path, item_id, ctx=0.0, hear=sentences.REAL, text=False):
    info[os.path.normcase(os.path.abspath(path))] = (item_id, ctx, hear, text)


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
    _place(no_store, seen, 2)
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


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_episode_says_a_word_moved_by_best_has_its_card_from_a_better_sentence_elsewhere(tmp_path, monkeypatch,
                                                                                           lang):
    # why: Kantan-MA's *Not made from this episode* list named every word an episode made no card for, but a word Best
    # cut from another episode's line vanished from it silently — the learner saw a word of the episode with no card
    # and no reason
    from app.connect import ledger as L
    from app.connect import runner
    from tests.connect.test_kantan_ma_left_out import WORDS, _run, _steps
    away = WORDS[lang][1]

    def best(steps, ledger, lang_, job, words, here):
        kept = [w for w in words if (w["word"], w["reading"]) != away]
        return kept, [{"word": away[0], "reading": away[1], "item_id": 2, "text": EASY}]
    monkeypatch.setattr(runner, "_best", best)
    path = str(tmp_path / "ledger.sqlite")
    _run(_steps(tmp_path, lang), path, lang)
    assert L.left_of(lang, [1], path) == {1: [{"word": away[0], "why": L.LEFT_ELSEWHERE}]}



def test_left_out_names_a_best_word_after_the_pick_and_anki_miners_reasons():
    from app.connect import ledger as L
    from app.connect import runner
    got = {"words": [{"word": "大衆", "reading": "タイシュウ"}], "not_offered": []}
    moved = [{"word": "冒険", "reading": "ボウケン", "item_id": 2, "text": EASY}]
    out = runner._left_out(got, {("大衆", "タイシュウ")}, {}, set(), moved)
    assert out == [{"word": "大衆", "reading": "タイシュウ", "why": L.LEFT_WHY["no_definition"]},
                   {"word": "冒険", "reading": "ボウケン", "why": L.LEFT_ELSEWHERE}]
    assert runner._left_out(got, set(), {}, set()) == [], "no Best move: nothing new said"


# --- a book's line, heard by the AI voice (Sonic 2026-11-22: books count for Best when the AI voice can voice them) --
@pytest.fixture
def irodori(monkeypatch):
    """A stand-in for the beta `modules.irodori` (its public `on` only): `state["on"]` says what it answers; None as
    the module = the folder absent."""
    import sys
    import types
    state = {"on": True, "asked": []}
    fake = types.ModuleType("modules.irodori")

    def on(settings, language="ja"):
        state["asked"].append(language)
        if isinstance(state["on"], Exception):
            raise state["on"]
        return state["on"] and language == "ja"
    fake.on = on
    monkeypatch.setitem(sys.modules, "modules.irodori", fake)
    import modules
    monkeypatch.setattr(modules, "irodori", fake, raising=False)
    return state


def test_the_ai_voice_is_asked_through_its_one_function_and_any_failure_is_a_no(irodori, monkeypatch):
    import sys
    import modules
    assert sentences.ai_voice({}, "ja") is True
    assert sentences.ai_voice({}, "zh") is False, "Chinese: the voice speaks Japanese only"
    irodori["on"] = False
    assert sentences.ai_voice({}, "ja") is False
    irodori["on"] = OSError("its install folder is half removed")
    assert sentences.ai_voice({}, "ja") is False
    monkeypatch.setitem(sys.modules, "modules.irodori", None)       # the folder absent: the import fails
    monkeypatch.delattr(modules, "irodori", raising=False)
    assert sentences.ai_voice({}, "ja") is False


def test_how_a_line_is_heard_its_own_clip_then_the_ai_voice_then_none():
    assert sentences.heard(False, False, False) == sentences.REAL, "a video's or an audio file's line"
    assert sentences.heard(True, True, False) == sentences.REAL, "a book with its audiobook: the narrator, AI never"
    assert sentences.heard(True, True, True) == sentences.REAL
    assert sentences.heard(True, False, True) == sentences.AI_VOICE
    assert sentences.heard(True, False, False) is sentences.SILENT, "the voice off: exactly as before"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_books_line_is_a_choice_while_the_ai_voice_can_voice_it_and_real_audio_wins_a_tie(no_store, lang):
    # why: a book with no audiobook was never a Best choice for Connect (nothing to cut a clip from); with the AI
    # voice on its line is heard, ranked after an equally clear line with its own clip and before a harder one
    easy, today, hard = (EASY, TODAY, HARD) if lang == "ja" else ("他接到电话了。", "我接到电话了。",
                                                                  "那个陌生人打来的电话很奇怪。")
    lemma = "冒険" if lang == "ja" else "电话"
    here, book, other = _library(lang, {"第01話.txt": [hard], "本.txt": [easy], "第02話.txt": [today]},
                                 known=(_lemmas(easy, lang) | _lemmas(today, lang)) - {lemma})
    key = _key(easy, lemma, lang)
    _place(no_store, here, 1)
    _place(no_store, other, 3, ctx=0.0)

    def best(hear, books=True, reach=lambda item_id: item_id != 1):
        _place(no_store, book, 2, ctx=0.9, hear=hear, text=True)
        return sentences.choose(lang, [key], here=here, dial=sentences.BEST, files=[here, book, other], young={},
                                reach=reach, books=books)[key]
    got = best(sentences.AI_VOICE)
    assert [(c.item_id, c.audio, c.ai) for c in got][:2] == [(3, True, False), (2, True, True)], \
        "a real clip first on a tie, though the book's context weighs more"
    assert got[-1].here and sentences.better(got[1], got[-1]), "the AI-voiced clear line beats the harder own line"
    assert 2 not in [c.item_id for c in best(sentences.SILENT)], "the voice off: no choice, as before"
    assert 2 not in [c.item_id for c in best(sentences.AI_VOICE, books=False)], "Anki Miner doesn't read books"
    paired = best(sentences.REAL)
    assert paired[0].item_id == 2 and not any(c.ai for c in paired), "a paired audiobook: its own clip, AI never"
    assert 2 in [c.item_id for c in best(sentences.SILENT, reach=None)], "a caller that cuts no media: as before"


class _BookSteps:
    def __init__(self, got, ai=True):
        self.got, self.ai = got, ai

    def _settings(self, lang):
        return {"enable_irodori": self.ai}

    def line_up(self, lang, job, epub):
        return self.got


def _ai_marked(ledger, job):
    from app.connect import runner
    return runner._meta(ledger, f"{runner.AI_JOB}{job['id']}") is not None


def test_a_best_job_at_a_book_with_no_audiobook_is_never_asked_and_its_cards_get_the_ai_voice(tmp_path, irodori):
    from app.connect import runner
    epub = str(tmp_path / "本.epub")
    ask = {"book_ask": "Do you have the audiobook?", "item_id": 7, "key": "k-7", "epub": epub}
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        best = {"id": 41, "item_id": 7, "kind": LEVEL, "source": level.BEST, "words": [("冒険", "ボウケン")]}
        assert runner._line_up(_BookSteps(ask), ledger, "ja", best, ("本.txt", epub)) is None
        assert _ai_marked(ledger, best), "mined without audio, the voice fills it"
        ordinary = {"id": 42, "item_id": 7, "kind": "new"}
        with pytest.raises(runner.Wait):
            runner._line_up(_BookSteps(ask), ledger, "ja", ordinary, ("本.txt", epub))
        assert not _ai_marked(ledger, ordinary), "the book's own mining still asks its question"
        irodori["on"] = False
        late = dict(best, id=43)
        assert runner._line_up(_BookSteps(ask), ledger, "ja", late, ("本.txt", epub)) is None
        assert not _ai_marked(ledger, late), "the voice switched off since: a card without audio, nothing queued"


def test_a_best_job_at_a_book_with_its_audiobook_lined_up_takes_the_narrator_never_the_ai_voice(tmp_path, irodori):
    from app.connect import runner
    lined = {"status": "done", "key": "k-7", "grade": "good", "files": []}
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        best = {"id": 44, "item_id": 7, "kind": LEVEL, "source": level.BEST}
        steps = _BookSteps({"lineup": lined, "line": None, "item_id": None})
        assert runner._line_up(steps, ledger, "ja", best, ("本.txt", str(tmp_path / "本.epub"))) == lined
        assert not _ai_marked(ledger, best)


def test_a_watched_episode_gives_a_best_job_its_sentence_only_never_its_own_new_words(tmp_path):
    # why (Sonic 2026-11-22, Best from places you've seen): the card is for the word the study order asked for now —
    # the watched episode lends its line; its other new words (迷宮, 壮絶, 未知: listed ones too) get nothing from it
    srt = _srt(tmp_path, [(10.0, 12.0, HARD), (40.0, 42.0, EASY)])
    read = cues.read(srt, "ja")
    tokens = cues.tokens(read, "ja")
    new = {"冒険", "迷宮", "壮絶", "未知"}
    adventure, maze = _key(EASY, "冒険"), _key(HARD, "迷宮")
    listed = {maze: 0, adventure: 5}                 # 迷宮 ranks first on the list
    job = {"kind": LEVEL, "source": level.BEST, "words": [adventure]}
    chosen = pick.pick(read, tokens, "ja", lambda k: k[0] not in new, mode="list", listed=level.restrict(listed, job))
    assert [(w["word"], w["line_start"]) for w in chosen["words"]] == [("冒険", 40.0)]
    # the 3.0 rule for the episode's own minings is untouched (pinned by tests/connect/test_lf4_level_watched.py:
    # its first mining and a level raise make no cards from a watched episode)
    assert level.WATCHED_GIVES_NO_NEW_CARDS and level.watched_out({"watched": 1})
    assert not level.wants({"watched": 1, "in_learning_order": 1})


def test_a_best_word_and_a_raise_never_share_one_job(tmp_path):
    # why (review, failures lens): a Best word merged into a raise's waiting job took the raise's rules — dropped when
    # its episode was watched since, or as an unlisted word — after it had left its own episode: a word with no card
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        adventure, maze, walk = ("冒険", "ボウケン"), ("迷宮", "メイキュウ"), ("散歩", "サンポ")
        with ledger.transaction():
            raise_id = ledger.queue_level("ja", 2, [maze], source=level.NEW_FILES)
            assert ledger.queue_level("ja", 2, [adventure], source=level.BEST) is None, "it stays in its episode"
            best_id = ledger.queue_level("ja", 3, [adventure], source=level.BEST)
            assert ledger.queue_level("ja", 3, [maze], source=level.NEW_FILES) is None
            assert ledger.queue_level("ja", 3, [walk], source=level.BEST) == best_id, "two Best words: one job"
            assert ledger.queue_level("ja", 2, [walk], source=level.NEW_FILES) == raise_id
        assert ledger.job_by_id(best_id)["words"] == sorted([adventure, walk])
        assert ledger.job_by_id(raise_id)["words"] == sorted([maze, walk])


def test_files_outside_the_store_each_answer_for_themselves(no_store):
    # why (review): the media look-up's memo keyed every file outside the store as one (item id None): the first
    # file's answer stood for all of them
    here, gone, there = _library("ja", {"第01話.txt": [HARD], "第02話.txt": [EASY], "第03話.txt": [TODAY]},
                                 known=(_lemmas(EASY) | _lemmas(TODAY)) - {"冒険"})
    os.remove(gone)
    key = _key(EASY, "冒険")
    got = sentences.choose("ja", [key], here=here, dial=sentences.BEST, files=[here, gone, there], young={})[key]
    assert _texts(got) == [TODAY, HARD], "the file no longer there is no choice; the one there is"


def test_lines_nobody_can_hear_never_crowd_out_a_line_that_can_be_cut(no_store):
    # why (review, bounds lens): the corpus keeps a word's 8 best sentences before the picker drops the ones it can't
    # use — ten clear lines of books nobody can voice took all 8 places, and the video's i+2 line was lost
    starts = ["明日", "今日", "来週", "週末", "朝", "夜", "春", "夏", "秋", "冬"]
    lines = [f"{s}から冒険に出かけよう。" for s in starts]
    books = {f"本{k}.txt": lines[2 * k:2 * k + 2] for k in range(5)}
    files = _library("ja", dict(books, **{"第02話.txt": [NEAR], "第01話.txt": [HARD]}),
                     known=set().union(*(_lemmas(x) for x in lines)) - {"冒険"})
    *book_paths, video, here = files
    for n, path in enumerate(book_paths, 10):
        _place(no_store, path, n, hear=sentences.SILENT, text=True)
    _place(no_store, video, 2)
    _place(no_store, here, 1)
    key = _key(NEAR, "冒険")
    got = sentences.choose("ja", [key], here=here, dial=sentences.BEST, files=files, young={},
                           reach=lambda item_id: item_id != 1)[key]
    assert _texts(got) == [NEAR, HARD]
