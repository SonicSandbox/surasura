"""Hover-W: a title's word card (app/plan_engine.py `words_of` / `first_sentences`, app/services/title_words.py).

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py: the samples and Test Resources split into a
dozen files across the tiers), each through one full Generate. What these prove:
  - a title's new words are exactly the ones its *N new* counts (every file, every title, after moves too), in the
    list's own order and spelling; the rest of its words are the ones an earlier title teaches, grouped where taught;
  - the plan's first sentences (F7's `fs` / `firsts`) give each listed word's Context 1 back from the token store, and
    a text whose hash isn't the plan's is never shown; an older plan or another plan on disk shows none;
  - the card's Anki part: struggling first, then young, mature left out; Anki closed and no decks say so; Anki is read
    at most once a minute unless asked.
"""
import gzip
import os
import types

import pytest

from app import analyzer, plan_engine, token_index
from app.services import title_words as TW
from app.services.moves import TitleAnswer
from tests import plan_file_cases as cases
from tests.test_plan_file import read_run

# RP-2's titles (tests/plan_file_cases._rp2): a show's episodes and a book's parts are one title each.
TITLES = {"ja": {"喫茶店の朝": ["gotoubun_ep01.srt", "gotoubun_ep02.srt", "gotoubun_ep03.srt"],
                 "蜘蛛の糸": ["novel_school_part1.txt", "novel_school_part2.txt"],
                 "注文の多い料理店": ["eighty_six_part1.txt", "eighty_six_part2.txt", "eighty_six_part3.txt"],
                 "phrases_sample": ["phrases_sample.srt"], "ごん狐": ["eighty_six_ch2.txt"],
                 "context_test": ["context_test.txt"], "runaway": ["runaway_transcript.txt"]},
          "zh": {"孔乙己": ["zh_high_1.txt"], "从百草园到三味书屋": ["zh_high_2.txt"], "新闻 1": ["news_part1.txt"],
                 "故乡": ["zh_low_1.txt"], "风筝": ["zh_low_2.txt"], "新闻 2": ["news_part2.txt"],
                 "繁體新聞": ["traditional_news.txt"], "mixed": ["mixed_script_transcript.txt"],
                 "patterns": ["patterns_zh_sample.txt"], "context_test": ["context_test.txt"]}}


@pytest.fixture(scope="module", params=["ja", "zh"])
def run(request, tmp_path_factory):
    """One case's library and its Generate (a child process, as the dashboard runs it)."""
    language = request.param
    case = f"rp2-{language}"
    root = str(tmp_path_factory.mktemp(case))
    cases.build(root, case)
    cases.generate(root, case)
    return types.SimpleNamespace(language=language, root=root, out=read_run(root),
                                 plan_path=os.path.join(root, "results", analyzer.PLAN_FILE),
                                 data_dir=os.path.join(root, "data", language),
                                 store_path=os.path.join(root, "index", f"token_store_{language}.db"))


def _engine(run, lean=True):
    plan = plan_engine.load(run.plan_path, pools=not lean)
    eng = plan_engine.Engine(plan, numbers_only=True)
    eng._numbers([(entry[0], entry[1]) for entry in plan.files])     # the Generate's own order
    return plan, eng


def _ids(plan, names):
    by_name = {entry[0].rsplit("/", 1)[-1]: entry[0] for entry in plan.files}
    return [by_name[n] for n in names]


def test_hover_w_a_titles_new_words_are_exactly_what_its_n_new_counts_in_every_file_and_title(run):
    """The card's count is the row's figure, always: one file at a time and a title's files together; its new words
    and its words learned on the way are its words, no word in both."""
    plan, eng = _engine(run)
    for f, entry in enumerate(plan.files):
        new, before = eng.words_of([entry[0]])
        assert len(new) == eng._n_new[f], entry[0]
        assert {w.k for w in new} | {w.k for w in before} == set(eng._uses[f][0])
        assert all(eng._pos[eng._first[w.k]] < eng._pos[f] for w in before)
    for title, names in TITLES[run.language].items():
        ids = _ids(plan, names)
        new, before = eng.words_of(ids)
        assert len(new) == sum(eng._n_new[eng._f_of[i]] for i in ids), title
        assert not {w.k for w in new} & {w.k for w in before}
        assert all(w.taught in ids and w.at in ids for w in new)
        assert all(w.taught not in ids and w.at in ids for w in before)


def test_hover_w_the_first_title_has_nothing_learned_on_the_way_and_a_later_one_names_where_each_word_is_taught(run):
    plan, eng = _engine(run)
    first_title = next(iter(TITLES[run.language].values()))
    _new, before = eng.words_of(_ids(plan, first_title))
    assert before == []
    names = list(TITLES[run.language].values())[3]           # a Soon title: earlier titles teach some of its words
    new, before = eng.words_of(_ids(plan, names))
    assert before, "a later title meets words an earlier one taught"
    places = [eng._pos[eng._f_of[w.taught]] for w in before]
    assert places == sorted(places)                          # in journey order: where they are taught


def test_hover_w_new_words_come_in_the_lists_own_order_and_spelling(run):
    """Most useful first is the priority list's order; each word spelled as its row shows it (Orth: ありがとうございます,
    never the lemma 有り難う御座るます)."""
    plan, eng = _engine(run)
    rows = run.out["priority"]
    order = {(r["Word"], r["Reading"]): i for i, r in enumerate(rows)}
    orth = {(r["Word"], r["Reading"]): r["Orth"] or r["Word"] for r in rows}
    for names in TITLES[run.language].values():
        new, _before = eng.words_of(_ids(plan, names))
        listed = [w for w in new if (w.word, w.reading) in order]
        assert [order[(w.word, w.reading)] for w in listed] == sorted(order[(w.word, w.reading)] for w in listed)
        assert all(w.label == orth[(w.word, w.reading)] for w in listed)
    if run.language == "ja":
        new, _before = eng.words_of(_ids(plan, TITLES["ja"]["喫茶店の朝"]))
        labels = [w.label for w in new]
        assert "ありがとうございます" in labels and "有り難う御座るます" not in labels


def test_hover_w_after_a_move_the_words_follow_the_new_order(run):
    """Move the Soon title to the top of NOW: words it shared with the titles before it are new there now, and the
    count is still each file's *N new*."""
    plan, eng = _engine(run)
    names = list(TITLES[run.language].values())[3]
    ids = _ids(plan, names)
    _new0, before0 = eng.words_of(ids)
    first_item = plan.files[eng._order[0]][0]
    eng.move(ids, "now", before_id=first_item)
    new, before = eng.words_of(ids)
    assert before == [] and len(new) == sum(eng._n_new[eng._f_of[i]] for i in ids)
    assert {w.k for w in before0} <= {w.k for w in new}
    # the spellings kept for the last order are never this one's: the same words and labels as an engine made afresh
    fresh = plan_engine.Engine(plan_engine.load(run.plan_path, pools=False), numbers_only=True)
    fresh._numbers([(eng._ids[f], ("now", "soon", "goal")[eng._tier[f]]) for f in eng._order])
    for names in TITLES[run.language].values():
        ids_ = _ids(plan, names)
        assert [[(w.k, w.label) for w in part] for part in eng.words_of(ids_)] ==             [[(w.k, w.label) for w in part] for part in fresh.words_of(ids_)]


def test_hover_w_the_plans_first_sentences_give_each_words_context_1_back_from_the_token_store(run):
    """F7's per-file first sentences: a word's first sentence in its first file is its Context 1 (the Generate's), and
    the token store's text has the plan's hash. A lean load never decodes them: `first_sentences` reads them."""
    plan, eng = _engine(run)
    firsts = plan_engine.first_sentences(run.plan_path)
    assert firsts is not None and firsts.files == [entry[0] for entry in plan.files]
    store = token_index.open_reader(run.language, run.store_path)
    context = {(r["Word"], r["Reading"]): r["Context 1"] for r in run.out["priority"]}
    checked = 0
    for f, entry in enumerate(plan.files):
        sentences = store.file_tokens(os.path.join(run.data_dir, *entry[0].split("/")))
        for k, (number, text_hash) in firsts.of(f).items():
            word, reading = plan.keys[k][0], plan.keys[k][1]
            s = TW.sentence_of(sentences, number, text_hash, word, reading, bool(plan.keys[k][2]))
            assert s is not None, (entry[0], word)
            if eng._first[k] == f and context.get((word, reading)):
                assert context[(word, reading)].strip() in s.text or s.text in context[(word, reading)], word
                checked += 1
    store.close()
    assert checked > 20


def test_hover_w_a_sentence_whose_text_isnt_the_plans_is_never_shown():
    """The token store re-read a file since the plan (its text changed): the plan's hash doesn't match, so nothing —
    never another sentence in the first one's place. A number past the file's end: nothing."""
    sentences = [("駅前の喫茶店で友達と待ち合わせた。", [["駅前", "エキマエ", "駅前"], ["喫茶店", "キッサテン", "喫茶店"]])]
    from app import plan_rules
    good = plan_rules.text_hash_of(sentences[0][0])
    s = TW.sentence_of(sentences, 0, good, "喫茶店", "キッサテン", False)
    assert s is not None and s.text[s.start:s.end] == "喫茶店"
    assert TW.sentence_of(sentences, 0, good ^ 1, "喫茶店", "キッサテン", False) is None
    assert TW.sentence_of(sentences, 3, good, "喫茶店", "キッサテン", False) is None


def test_hover_w_an_older_plan_or_garbage_has_no_first_sentences(run, tmp_path):
    """Format 3's tables only: a plan written without its first sentences (cut here), a missing file or one that isn't
    a plan gives None — the card then shows no sentence."""
    with gzip.open(run.plan_path, "rb") as fh:
        lines = fh.read().split(b"\n")
    cut = tmp_path / "plan.json.gz"
    with gzip.open(cut, "wb") as fh:
        fh.write(b"\n".join(line for line in lines if not line.startswith(b'{"firsts":')))
    assert plan_engine.first_sentences(str(cut)) is None
    assert plan_engine.first_sentences(str(tmp_path / "none.json.gz")) is None
    junk = tmp_path / "junk.json.gz"
    junk.write_bytes(b"not a plan")
    assert plan_engine.first_sentences(str(junk)) is None


# --- the service ------------------------------------------------------------------------------------------------- #
class _Numbers:
    """`moves.Numbers.words` over a real engine (its own lock and table are moves' to prove)."""

    def __init__(self, run, eng, kept=False):
        self.run, self.eng, self.kept = run, eng, kept
        st = os.stat(run.plan_path)
        self.key = (st.st_mtime_ns, st.st_size)

    def words(self, ids):
        new, before = self.eng.words_of(ids)
        files, f_of = self.eng.plan.files, self.eng._f_of
        rel = {f_of[i]: files[f_of[i]][0] for i in ids if i in f_of}
        return TitleAnswer(new, before, self.kept, self.run.plan_path, self.key, self.run.data_dir, rel)


Ep = types.SimpleNamespace


def _row(plan, title, names, tier="soon"):
    eps = tuple(Ep(id=i, label=f"Part {n}", watched=False) for n, i in enumerate(_ids(plan, names), 1))
    return types.SimpleNamespace(key=("row", title), title=title, tier=tier, episodes=eps, next_index=0)


def _view(plan, language):
    return types.SimpleNamespace(rows=[_row(plan, t, names) for t, names in TITLES[language].items()])


Standing = types.SimpleNamespace


def _provider(run, eng, standing=None, kept=False):
    read = (lambda language, settings: standing) if not callable(standing) else standing
    tw = TW.TitleWords(_Numbers(run, eng, kept), run.language,
                       open_store=lambda: token_index.open_reader(run.language, run.store_path), read_standing=read)
    return tw


def _ask(tw, row, view):
    got = []
    tw.ask(row, view, got.append)
    assert tw.idle(30)
    return got[0]


def test_hover_w_the_card_counts_the_rows_new_and_groups_the_rest_under_the_title_that_teaches_them(run):
    plan, eng = _engine(run)
    view = _view(plan, run.language)
    title = list(TITLES[run.language])[3]
    row = next(r for r in view.rows if r.title == title)
    tw = _provider(run, eng)
    card = _ask(tw, row, view)
    ids = [e.id for e in row.episodes]
    assert card.n_new == sum(eng._n_new[eng._f_of[i]] for i in ids) == len(card.new)
    assert card.today == card.n_new + sum(len(g.words) for g in card.before)
    assert [g.title for g in card.before] == [t for t in TITLES[run.language] if t in {g.title for g in card.before}]
    assert card.anki is None and card.tier == "Soon" and not card.kept      # no Anki read yet: the part isn't shown
    tw.close()


def test_hover_w_the_anki_part_lists_struggling_then_young_and_leaves_mature_words_out(run):
    """Real words of the title that the test library knows, given standings: a leech first, then the most forgotten,
    then young; a mature card's word is not there."""
    plan, eng = _engine(run)
    view = _view(plan, run.language)
    row = view.rows[0]
    store = token_index.open_reader(run.language, run.store_path)
    counts = TW.counts_of(store, [os.path.join(run.data_dir, *e.id.split("/")) for e in row.episodes])
    store.close()
    words = sorted(counts, key=lambda w: -counts[w])[:6]
    assert len(words) >= 4, words
    standing = {words[0]: Standing(leech=False, lapses=0, young=False, mature=True),
                words[1]: Standing(leech=False, lapses=0, young=True, mature=False),
                words[2]: Standing(leech=False, lapses=3, young=False, mature=False),
                words[3]: Standing(leech=True, lapses=1, young=False, mature=False)}
    tw = _provider(run, eng, standing)
    tw.refresh_anki()
    card = _ask(tw, row, view)
    assert [a.word for a in card.anki] == [words[3], words[2], words[1]]
    assert card.anki[0].leech and card.anki[1].lapses == 3 and card.anki[2].young
    tw.close()


def test_hover_w_anki_closed_says_so_and_no_decks_hides_the_part(run):
    from app import anki_connect, anki_words
    plan, eng = _engine(run)
    view = _view(plan, run.language)

    def closed(language, settings):
        raise anki_connect.AnkiError("Anki isn't answering")

    def no_decks(language, settings):
        raise anki_words.NoDecks("no Anki deck chosen")
    for read, want in ((closed, TW.ANKI_CLOSED), (no_decks, None)):
        tw = _provider(run, eng, read)
        tw.refresh_anki()
        assert _ask(tw, view.rows[0], view).anki == want
        tw.close()


def test_hover_w_anki_is_read_at_most_once_a_minute_unless_a_sync_asks(run):
    plan, eng = _engine(run)
    now = [1000.0]
    tw = TW.TitleWords(_Numbers(run, eng), run.language, read_standing=lambda language, settings: {},
                       clock=lambda: now[0])
    for _ in range(3):
        tw.refresh_anki()
    assert tw.idle(30) and tw.reads["standing"] == 1
    now[0] += TW.ANKI_EVERY_S + 1
    tw.refresh_anki()
    tw.refresh_anki(force=True)
    assert tw.idle(30) and tw.reads["standing"] == 3
    tw.close()


def test_hover_w_with_anki_switched_off_for_the_suites_anki_is_never_reached(run, monkeypatch):
    plan, eng = _engine(run)
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    import app.anki_words as anki_words
    monkeypatch.setattr(anki_words, "word_states", lambda *a, **k: pytest.fail("Anki reached"))
    tw = TW.TitleWords(_Numbers(run, eng), run.language)
    tw.refresh_anki(force=True)
    assert tw.idle(30) and tw.standing() is None
    tw.close()


def test_hover_w_a_kept_open_card_gets_each_words_sentence_from_this_title_with_its_place(run):
    """Every word with a first sentence in the plan gets it, from the title's own file where it is first met there (a
    word taught earlier: its first sentence here, not where it is taught), the word marked in it, and the part it is
    from when the title has several files. The plan is read once for every card while it is the same."""
    plan, eng = _engine(run)
    view = _view(plan, run.language)
    title, names = next((t, n) for t, n in TITLES[run.language].items() if len(n) > 1 and t != list(TITLES[
        run.language])[0]) if run.language == "ja" else ("故乡", TITLES["zh"]["故乡"])
    row = next(r for r in view.rows if r.title == title)
    tw = _provider(run, eng)
    got = []
    tw.sentences(row, got.append)
    assert tw.idle(30)
    sentences = got[0]
    new, before = eng.words_of([e.id for e in row.episodes])
    listed = [w for w in new + before if plan.rows[w.k] is not None]
    assert listed and all((w.word, w.reading) in sentences for w in listed)
    labels = {e.id: e.label for e in row.episodes}
    for w in listed:
        s = sentences[(w.word, w.reading)]
        assert s.place == (labels[w.at] if len(names) > 1 else None)
        assert 0 <= s.start <= s.end <= len(s.text)
    marked = [s for s in sentences.values() if s.end > s.start]
    assert len(marked) >= len(sentences) * 0.8               # the word found in its sentence (a few: spelled apart)
    tw.sentences(view.rows[0], got.append)
    assert tw.idle(30) and tw.reads["firsts"] == 1
    tw.close()


def test_hover_w_another_plan_on_disk_shows_no_sentence_rather_than_a_guess(run, tmp_path):
    """A Generate replaced the plan since the words were read: its first sentences aren't these words' — none shown."""
    import shutil
    plan, eng = _engine(run)
    view = _view(plan, run.language)
    copy = tmp_path / "plan.json.gz"
    shutil.copy(run.plan_path, copy)
    numbers = _Numbers(run, eng)
    numbers.run = types.SimpleNamespace(**dict(vars(run), plan_path=str(copy)))
    st = os.stat(copy)
    numbers.key = (st.st_mtime_ns, st.st_size + 1)           # the plan the words were read from isn't this one
    tw = TW.TitleWords(numbers, run.language, open_store=lambda: token_index.open_reader(run.language, run.store_path))
    got = []
    tw.sentences(view.rows[0], got.append)
    assert tw.idle(30) and got == [{}]
    tw.close()


def test_hover_w_r1_anki_open_with_no_studied_card_is_never_called_closed_and_closed_is_looked_at_again(run):
    """Review r1 #4: Anki answering with no studied card (NoneStudied / NoWords) hides the part — never "Anki is closed";
    only Anki not answering is closed, and a card that said so reads Anki again at once next time, not a minute later."""
    from app import anki_connect, anki_words
    plan, eng = _engine(run)
    now = [0.0]
    answers = [anki_words.NoneStudied("no studied card"), anki_connect.AnkiError("closed"), {}]

    def read(language, settings):
        got = answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    tw = TW.TitleWords(_Numbers(run, eng), run.language, read_standing=read, clock=lambda: now[0])
    tw.refresh_anki()
    assert tw.idle(30) and tw.standing() == {}
    tw.refresh_anki(force=True)
    assert tw.idle(30) and tw.standing() == TW.ANKI_CLOSED
    now[0] += 1                                              # well inside the minute
    tw.refresh_anki()
    assert tw.idle(30) and tw.standing() == {} and tw.reads["standing"] == 3
    tw.close()


def test_hover_w_r1_a_mature_card_once_forgotten_is_not_in_the_not_mature_part_but_a_mature_leech_is(run):
    plan, eng = _engine(run)
    answer = _Numbers(run, eng).words([e[0] for e in plan.files[:1]])
    counts = {"甲": 5, "乙": 3, "丙": 2}
    standing = {"甲": Standing(leech=False, lapses=2, young=False, mature=True),
                "乙": Standing(leech=True, lapses=1, young=False, mature=True),
                "丙": Standing(leech=False, lapses=0, young=True, mature=False)}
    assert [a.word for a in TW.anki_part(standing, counts, answer)] == ["乙", "丙"]


def test_hover_w_r1_close_shuts_the_store_reader_on_its_own_worker_and_opens_none_after(run):
    """Review r1 #3: SQLite's handle is closed on the thread that opened it (a close from the window's thread was
    refused and swallowed: the file stayed open); a job queued before the close opens no new one."""
    import threading
    plan, eng = _engine(run)
    opened, closed = [], []

    class Store:
        def __init__(self):
            opened.append(threading.get_ident())
            self.conn = token_index.open_reader(run.language, run.store_path).conn

        def close(self):
            closed.append(threading.get_ident())
            self.conn.close()
    known = {"扉": Standing(leech=False, lapses=0, young=True, mature=False)}   # (a standing to match: the counts read)
    tw = TW.TitleWords(_Numbers(run, eng), run.language, open_store=Store, read_standing=lambda *a: known)
    view = _view(plan, run.language)
    tw.refresh_anki(force=True)
    assert _ask(tw, view.rows[0], view) is not None and len(opened) == 1
    tw.close()
    tw.worker._thread.join(10) if getattr(tw.worker, "_thread", None) else None
    assert closed == opened                                  # the same thread, once
    assert tw._token_store() is None and len(opened) == 1


def test_hover_w_r2_anki_busy_or_slow_is_never_closed_and_keeps_what_it_last_said(run):
    """Review r2: Anki open but busy (its own sync, Check Database) or answering late keeps the last standing — never
    "Anki is closed · open it to see these" — and is asked again at the next moment, inside the minute too."""
    from app import anki_connect
    plan, eng = _engine(run)
    busy = anki_connect.AnkiError("busy", kind="action")
    busy.busy = True
    late = anki_connect.AnkiError("timed out", kind="offline")
    late.timed_out = True
    first = {"扉": Standing(leech=False, lapses=0, young=True, mature=False)}
    answers = [first, busy, late, anki_connect.AnkiError("no answer", kind="offline")]

    def read(language, settings):
        got = answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    now = [0.0]
    tw = TW.TitleWords(_Numbers(run, eng), run.language, read_standing=read, clock=lambda: now[0])
    tw.refresh_anki()
    assert tw.idle(30) and tw.standing() == first
    tw.refresh_anki(force=True)                              # a known-words sync ended while Anki is busy
    assert tw.idle(30) and tw.standing() == first
    now[0] += 1
    tw.refresh_anki()                                        # inside the minute: a busy answer left no throttle
    assert tw.idle(30) and tw.standing() == first            # (late: still what it last said)
    now[0] += 1
    tw.refresh_anki()
    assert tw.idle(30) and tw.standing() == TW.ANKI_CLOSED and tw.reads["standing"] == 4
    tw.close()

