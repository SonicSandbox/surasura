"""E-HOVER: the word card's first sentence comes from the sentence table at level 2 (SPEC § 10.3; § 5.2's last-but-two
row: "a word's block, the lines of one file, the lowest place: a read of the table, not a ranking").

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py), each through one full Generate at level 2
with *Never longer than* at 30 characters, so that many a word's first sentence in a file is over it. What these prove:
  - at level 2 the word card's reader (`title_words.first_sentences` → `sentence_table.TableFirsts`) answers from
    the table beside the plan: the same sentence, for every word and file, as the plan's own per-file first sentences — with those cut from the plan, so only the table can answer;
    the kept-open card shows the same words' sentences as before;
  - a first sentence over *Never longer than* is still the card's (the walk keeps it in the table, marked OVER);
  - a title with no table (none written, another run's, a damaged one) reads the plan as today; neither: nothing shown;
  - a file changed since the Generate shows none of its words' sentences, never another one;
  - below level 2 the table is never opened (inert: the tree's level is 0).
"""
import gzip
import json
import os
import shutil
import types

import pytest

from app import analyzer, plan_engine, plan_rules, sentence_table, token_index
from app.services import title_words as TW
from tests import plan_file_cases as cases
from tests.test_title_words import TITLES, _Numbers, _engine, _view

NEVER_LONGER = 30


@pytest.fixture(scope="module", params=["ja", "zh"])
def run(request, tmp_path_factory):
    """One case's library and its Generate at level 2 (a child process, as the dashboard runs it)."""
    language = request.param
    case = f"rp2-{language}"
    root = str(tmp_path_factory.mktemp(f"e-hover-{language}"))
    cases.build(root, case)
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"logic": {"context": {"max_chars": NEVER_LONGER}}}, f)
    cases.generate(root, case, extra_env={"SURASURA_SENTENCE_TABLE": "2"})
    results = os.path.join(root, "results")
    # A level-2 Generate stamps its plan format 5 (E-REDRAW), whose pools and first sentences are the table's; these
    # tests read the plan's own first sentences as today's answer, which part 1's plan still carries: read as format 4
    path = os.path.join(results, analyzer.PLAN_FILE)
    with gzip.open(path, "rb") as fh:
        lines = fh.read().split(b"\n")
    lines[0] = json.dumps(dict(json.loads(lines[0]), format=4)).encode("utf-8")
    with gzip.open(path, "wb") as fh:
        fh.write(b"\n".join(lines))
    return types.SimpleNamespace(language=language, root=root, results=results,
                                 plan_path=os.path.join(results, analyzer.PLAN_FILE),
                                 table_path=os.path.join(results, sentence_table.TABLE_FILE),
                                 data_dir=os.path.join(root, "data", language),
                                 store_path=os.path.join(root, "index", f"token_store_{language}.db"))


def _level(monkeypatch, n):
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", n)


def _plan_copy(run, folder, cut=True, table=True, header=None):
    """The run's plan in `folder` — `cut`: without its per-file first sentences (the `firsts` table), so the plan alone
    can't answer; `table`: the run's sentence table beside it; `header`: header keys changed."""
    os.makedirs(folder, exist_ok=True)
    with gzip.open(run.plan_path, "rb") as fh:
        lines = fh.read().split(b"\n")
    if header:
        lines[0] = json.dumps(dict(json.loads(lines[0]), **header)).encode("utf-8")
    path = os.path.join(folder, analyzer.PLAN_FILE)
    with gzip.open(path, "wb") as fh:
        fh.write(b"\n".join(line for line in lines if not (cut and line.startswith(b'{"firsts":'))))
    if table:
        shutil.copy(run.table_path, os.path.join(folder, sentence_table.TABLE_FILE))
    return path


def _answers(firsts, n_files, n_rows):
    """{(file, row): sentence number} of every file, every row the plan lists."""
    out = {}
    for f in range(n_files):
        for k, (number, *_check) in firsts.of_files({f: range(n_rows)})[f].items():
            out[(f, k)] = number
    return out


def _today(run, monkeypatch):
    _level(monkeypatch, 0)
    found = plan_engine.first_sentences(run.plan_path)
    assert found is not None
    return found


def test_the_word_cards_first_sentence_comes_from_the_table(run, tmp_path, monkeypatch):
    # why: release 2 retires the plan's first-sentence tables (E-REDRAW), so the card's sentence must come from the
    # table — the same sentence as before for every word and file (the walk keeps a word's first line of each file)
    plan, _eng = _engine(run)
    n_files, n_rows = len(plan.files), len(plan.keys)
    today = _answers(_today(run, monkeypatch), n_files, n_rows)
    assert len(today) > 50
    cut = _plan_copy(run, str(tmp_path / "results"))
    assert plan_engine.first_sentences(cut) is None              # the cut plan alone has none
    _level(monkeypatch, 2)
    firsts = TW.first_sentences(cut, run.data_dir)
    assert firsts is not None and firsts.files[:n_files] == [entry[0] for entry in plan.files]
    st = os.stat(cut)
    assert firsts.key == (st.st_mtime_ns, st.st_size)            # the plan's stamp: the service's "same plan" check
    assert _answers(firsts, n_files, n_rows) == today


def test_the_kept_open_card_shows_the_same_sentences_from_the_table(run, tmp_path, monkeypatch):
    # why: what a learner sees must not move at the switch: each word's sentence, its mark and its part, as before
    plan, eng = _engine(run)
    view = _view(plan, run.language)

    def shown(numbers):
        tw = TW.TitleWords(numbers, run.language,
                           open_store=lambda: token_index.open_reader(run.language, run.store_path))
        out = []
        for row in view.rows:
            got = []
            tw.sentences(row, got.append)
            assert tw.idle(30)
            out.append(got[0])
        tw.close()
        return out

    _level(monkeypatch, 0)
    before = shown(_Numbers(run, eng))
    assert sum(len(s) for s in before) > 30
    numbers = _Numbers(run, eng)
    numbers.run = types.SimpleNamespace(**dict(vars(run), plan_path=_plan_copy(run, str(tmp_path / "results"))))
    st = os.stat(numbers.run.plan_path)
    numbers.key = (st.st_mtime_ns, st.st_size)
    _level(monkeypatch, 2)
    assert shown(numbers) == before


def test_a_first_sentence_over_never_longer_than_is_still_the_cards(run, tmp_path, monkeypatch):
    # why: a word's first sentence in a file is the card's even when it is over *Never longer than* (today's plan keeps
    # it regardless); the table keeps it too, marked OVER, and the card must not skip it for a later, shorter line
    plan, _eng = _engine(run)
    n_files, n_rows = len(plan.files), len(plan.keys)
    today = _answers(_today(run, monkeypatch), n_files, n_rows)
    table = sentence_table.open_table(run.table_path)
    over = 0
    for (f, k), number in today.items():
        cols = table.block(k)[0]
        at = [i for i in range(len(cols["src"])) if cols["src"][i] == f and cols["number"][i] == number]
        assert at, (f, plan.keys[k][0])
        over += bool(cols["marks"][at[0]] & sentence_table.OVER)
    assert over >= 5, "the run's cap leaves some first sentences over it"
    _level(monkeypatch, 2)
    firsts = TW.first_sentences(_plan_copy(run, str(tmp_path / "results")), run.data_dir)
    assert _answers(firsts, n_files, n_rows) == today


def test_a_title_with_no_table_reads_the_plan_as_today_and_without_either_shows_nothing(run, tmp_path, monkeypatch):
    # why: a library generated before the switch has no table, and a damaged or another run's table is no table
    # (SPEC § 5.1: the caller takes today's path, never an exception); with neither, the card shows no sentence
    plan, eng = _engine(run)
    n_files, n_rows = len(plan.files), len(plan.keys)
    today = _today(run, monkeypatch)
    _level(monkeypatch, 2)
    whole = TW.first_sentences(_plan_copy(run, str(tmp_path / "plain"), cut=False, table=False),
                                        run.data_dir)
    assert isinstance(whole, plan_engine.FirstSentences)
    assert [whole.of(f) for f in range(n_files)] == [today.of(f) for f in range(n_files)]
    assert TW.first_sentences(_plan_copy(run, str(tmp_path / "none"), table=False), run.data_dir) is None
    other = _plan_copy(run, str(tmp_path / "other"), header={"run_signature": "another run"})
    assert TW.first_sentences(other, run.data_dir) is None
    unnamed = _plan_copy(run, str(tmp_path / "unnamed"), header={"run_signature": None})
    assert TW.first_sentences(unnamed, run.data_dir) is None     # no run named: no table is this plan's
    engineless = _plan_copy(run, str(tmp_path / "engineless"), header={"engine": None})
    assert TW.first_sentences(engineless, run.data_dir) is None  # no engine named: never another engine's
    damaged = _plan_copy(run, str(tmp_path / "damaged"))
    table = os.path.join(str(tmp_path / "damaged"), sentence_table.TABLE_FILE)
    with open(table, "r+b") as fh:
        fh.truncate(os.path.getsize(table) - 7)
    assert TW.first_sentences(damaged, run.data_dir) is None
    numbers = _Numbers(run, eng)
    numbers.run = types.SimpleNamespace(**dict(vars(run), plan_path=_plan_copy(run, str(tmp_path / "none2"),
                                                                                  table=False)))
    st = os.stat(numbers.run.plan_path)
    numbers.key = (st.st_mtime_ns, st.st_size)
    tw = TW.TitleWords(numbers, run.language, open_store=lambda: token_index.open_reader(run.language, run.store_path))
    got = []
    tw.sentences(_view(plan, run.language).rows[0], got.append)
    assert tw.idle(30) and got == [{}]
    tw.close()


def test_a_file_changed_since_the_generate_shows_none_of_its_words_sentences(run, tmp_path, monkeypatch):
    # why: the table keeps no text, so a line is shown only while its file is the one the Generate read (SPEC § 5.4,
    # the file's digest) — a changed file gives nothing, never another sentence in the first one's place
    plan, _eng = _engine(run)
    n_rows = len(plan.keys)
    _level(monkeypatch, 2)
    firsts = TW.first_sentences(_plan_copy(run, str(tmp_path / "results")), run.data_dir)
    every = range(n_rows)
    f = max(range(len(plan.files)), key=lambda i: len(firsts.of(i, every)))
    other = next(i for i in range(len(plan.files)) if i != f and firsts.of(i, every))
    held = firsts.of(other, every)
    assert firsts.of(f, every)
    path = os.path.join(run.data_dir, *plan.files[f][0].split("/"))
    st = os.stat(path)
    try:
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        both = firsts.of_files({f: every, other: every})          # in one title: only the changed file's go
        assert both == {f: {}, other: held}
    finally:
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert firsts.of(f, every)                                     # the file as read again: its words' sentences back
    assert firsts.of(len(firsts.files) + 3, every) == {} and firsts.of_files({-1: every}) == {-1: {}}
    table = sentence_table.open_table(run.table_path)
    assert table.as_read(len(table.sources()) - 1, run.data_dir) or table.as_read(0, run.data_dir)
    assert not table.as_read(-1, run.data_dir)                     # never the last source read from the end
    assert not table.as_read(len(table.sources()), run.data_dir)


def test_a_file_the_table_names_otherwise_shows_none_of_its_words_sentences(run, tmp_path, monkeypatch):
    # why: a word's file is told by the plan's number; the card shows a line only when the table names that file by
    # the same path as the words' engine (a table whose numbering differs gives nothing, never another file's line)
    plan, eng = _engine(run)
    view = _view(plan, run.language)
    row = max(view.rows, key=lambda r: len(r.episodes))      # (zh: every title one file)
    numbers = _Numbers(run, eng)
    numbers.run = types.SimpleNamespace(**dict(vars(run), plan_path=_plan_copy(run, str(tmp_path / "results"))))
    st = os.stat(numbers.run.plan_path)
    numbers.key = (st.st_mtime_ns, st.st_size)
    renamed = row.episodes[0].id
    swap = {renamed: row.episodes[1].id, row.episodes[1].id: renamed} if len(row.episodes) > 1 else         {renamed: renamed + ".moved"}               # two files' paths swapped (a real file, the wrong one); else gone
    words = numbers.words

    def elsewhere(ids):
        answer = words(ids)
        return answer._replace(rel={f: swap.get(rel, rel) for f, rel in answer.rel.items()})
    numbers.words = elsewhere
    _level(monkeypatch, 2)
    tw = TW.TitleWords(numbers, run.language, open_store=lambda: token_index.open_reader(run.language, run.store_path))
    got = []
    tw.sentences(row, got.append)
    assert tw.idle(30)
    tw.close()
    new, before = eng.words_of([e.id for e in row.episodes])
    at = {(w.word, w.reading): w.at for w in new + before}
    assert all(at[key] not in swap for key in got[0]) and (bool(got[0]) == (len(row.episodes) > 2))
    assert any(w.at == renamed for w in new + before)


def test_a_table_line_is_shown_only_when_its_text_is_the_lines_length():
    # why: the table keeps no text, only its file's digest and the line's length: the token store's sentence at that
    # place, read again differently (another split), must not be shown in the first one's place
    sentences = [("駅前の喫茶店で友達と待ち合わせた。", [["駅前", "エキマエ", "駅前"], ["喫茶店", "キッサテン", "喫茶店"]])]
    n = len(sentences[0][0])
    s = TW.sentence_of(sentences, 0, None, "喫茶店", "キッサテン", False, n)
    assert s is not None and s.text[s.start:s.end] == "喫茶店"
    assert TW.sentence_of(sentences, 0, None, "喫茶店", "キッサテン", False, n - 3) is None
    assert TW.sentence_of(sentences, 1, None, "喫茶店", "キッサテン", False, n) is None


def test_a_table_replaced_since_it_was_opened_answers_nothing(run, tmp_path, monkeypatch):
    # why: the card keeps its reader while the plan is the same; a Generate whose plan write failed can still replace
    # the table beside it — its blocks are then not where the head said, so nothing, never a block of another word
    plan, _eng = _engine(run)
    every = range(len(plan.keys))
    _level(monkeypatch, 2)
    folder = str(tmp_path / "results")
    firsts = TW.first_sentences(_plan_copy(run, folder), run.data_dir)
    f = next(i for i in range(len(plan.files)) if firsts.of(i, every))
    table = os.path.join(folder, sentence_table.TABLE_FILE)
    st = os.stat(table)
    os.utime(table, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert firsts.of(f, every) == {}
    os.remove(table)
    assert firsts.of_files({f: every}) == {f: {}}


def test_a_damaged_block_gives_nothing_and_never_an_error(run, tmp_path, monkeypatch):
    # why: the card's worker must never raise (CLAUDE.md § 6, fail gracefully): a block that cannot be read or is the
    # wrong shape, whatever the error, gives no sentence for the title, never a guess
    plan, _eng = _engine(run)
    every = range(len(plan.keys))
    _level(monkeypatch, 2)
    firsts = TW.first_sentences(_plan_copy(run, str(tmp_path / "results")), run.data_dir)
    f = next(i for i in range(len(plan.files)) if firsts.of(i, every))
    for error in (TypeError("a head with a null size"), KeyError("chars"), ValueError("a block of the wrong size")):
        def broken(self, k, error=error):
            raise error
        monkeypatch.setattr(sentence_table.Table, "block", broken)
        assert firsts.of_files({f: every, f + 1: every}) == {f: {}, f + 1: {}}


def test_a_table_written_after_the_card_first_read_the_plan_is_read_at_the_next_card(run, tmp_path, monkeypatch):
    # why: a Generate writes the plan, then the table; a card kept open in between (after a move) found no table —
    # the next card must read the table once it is there, and while plan and table hold, never read either again
    plan, eng = _engine(run)
    view = _view(plan, run.language)
    row = max(view.rows, key=lambda r: len(r.episodes))
    folder = str(tmp_path / "results")
    numbers = _Numbers(run, eng)
    numbers.run = types.SimpleNamespace(**dict(vars(run), plan_path=_plan_copy(run, folder, table=False)))
    st = os.stat(numbers.run.plan_path)
    numbers.key = (st.st_mtime_ns, st.st_size)
    _level(monkeypatch, 2)
    tw = TW.TitleWords(numbers, run.language, open_store=lambda: token_index.open_reader(run.language, run.store_path))
    got = []
    tw.sentences(row, got.append)
    assert tw.idle(30) and got == [{}]
    shutil.copy(run.table_path, os.path.join(folder, sentence_table.TABLE_FILE))
    for _ in range(2):
        tw.sentences(row, got.append)
        assert tw.idle(30)
    tw.close()
    assert got[1] and got[2] == got[1] and tw.reads["firsts"] == 2


def test_a_titles_words_read_each_words_block_once(run, tmp_path, monkeypatch):
    # why: a title's files share words; one read a word, not one a word and file (the Chinese root's 3,940 asks of
    # 907 words took 0.43 s one by one, 0.08 s once each: the register's booking) — and the answers are each file's own
    plan, _eng = _engine(run)
    every = range(len(plan.keys))
    _level(monkeypatch, 2)
    firsts = TW.first_sentences(_plan_copy(run, str(tmp_path / "results")), run.data_dir)
    files = list(range(len(plan.files)))
    one_by_one = {f: firsts.of(f, every) for f in files}
    asked = {f: sorted(one_by_one[f]) + [k for k in every if k not in one_by_one[f]][:3] for f in files}
    reads = []
    block = sentence_table.Table.block
    monkeypatch.setattr(sentence_table.Table, "block", lambda self, k: reads.append(k) or block(self, k))
    assert firsts.of_files(asked) == one_by_one
    assert sorted(reads) == sorted({k for rows in asked.values() for k in rows})


@pytest.mark.parametrize("level", [0, 1])
def test_below_level_2_the_table_is_never_opened(run, tmp_path, monkeypatch, level):
    # why: inert below level 2 — release 1 (level 1) and the tree (0) keep today's read, the table untouched
    opened = []
    monkeypatch.setattr(sentence_table, "open_table", lambda *a, **k: opened.append(a))
    _level(monkeypatch, level)
    cut = _plan_copy(run, str(tmp_path / "results"))
    assert TW.first_sentences(cut, run.data_dir) is None
    assert isinstance(TW.first_sentences(run.plan_path, run.data_dir), plan_engine.FirstSentences)
    assert opened == []
