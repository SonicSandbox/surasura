"""Kotoba-K: a word marked Known or Ignore leaves the window's numbers at once (`plan_engine.Engine.leave_out`,
`moves.Numbers.leave_out`) — before the Generate that follows — as that Generate leaves it out.

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py), each through two full Generates: one before
the marks, one after. What a wrong answer would cost: *N new*, Up next or the word card still counting a word the
learner just marked (or dropping one they didn't), an Ignore counted as known, a clear that never brings the word
back, the rows' figures moving at a mark the next Generate would undo.
"""
import os
import types

import pytest

from app import analyzer, anki_sync, plan_engine
from tests import plan_file_cases as cases


@pytest.fixture(scope="module", params=["ja", "zh"])
def marked(request, tmp_path_factory):
    """One case's library, its Generate, two words marked (a common one Known, a rarer one Ignore), and the
    Generate after the marks."""
    language = request.param
    case = f"rp2-{language}"
    root = str(tmp_path_factory.mktemp(f"marks-{case}"))
    cases.build(root, case)
    cases.generate(root, case)
    plan_path = os.path.join(root, "results", analyzer.PLAN_FILE)
    before = plan_engine.load(plan_path)
    eng = plan_engine.Engine(before, numbers_only=True)
    eng._numbers([(entry[0], entry[1]) for entry in before.files])
    # A listed word met in many files (Known) and one met in two (Ignore): never a set phrase; each its own lemma's
    # only key (a word whose lemma has two readings is two rows: either is out once the lemma is marked).
    lemmas = {}
    for k, key in enumerate(before.keys):
        lemmas.setdefault(key[0], []).append(k)
    single = [ks[0] for ks in lemmas.values() if len(ks) == 1 and not before.keys[ks[0]][2]
              and before.rows[ks[0]] is not None and eng._first[ks[0]] is not None]
    by_files = sorted(single, key=lambda k: (-len(eng._files_of[k]), k))
    known_k = by_files[0]
    ignore_k = next(k for k in reversed(by_files) if len(eng._files_of[k]) >= 2)
    known, ignored = before.keys[known_k][0], before.keys[ignore_k][0]
    from app.services import word_lists, word_marks
    with pytest.MonkeyPatch.context() as mp:            # (this case's root while its marks are written)
        mp.setenv("SURASURA_TEST_ROOT", root)
        word_lists._BACKED_UP.clear()
        count = anki_sync.count_known(language)
        result = word_marks.apply(language, [(known, "known"), (ignored, "ignore")])
        assert result.error is None and len(result.done) == 2
        left = word_marks.left_out(language)
        counted = anki_sync.count_known(language)
        word_marks._UNDO.clear()
        word_lists._BACKED_UP.clear()
    cases.generate(root, case)
    after = plan_engine.load(plan_path)
    return types.SimpleNamespace(language=language, before=before, after=after, known=known, ignored=ignored,
                                 left=left, count=count, counted=counted, known_k=known_k, ignore_k=ignore_k)


def _n_new_by_file(plan):
    eng = plan_engine.Engine(plan, numbers_only=True)
    eng._numbers([(entry[0], entry[1]) for entry in plan.files])
    return {entry[0]: eng._n_new[f] for f, entry in enumerate(plan.files)}, eng


def test_known_counts_as_known_and_ignore_never_does(marked):
    assert marked.counted == marked.count + 1                       # only the Known word joined the known words
    words = {key[0] for key in marked.after.keys}
    assert marked.known not in words and marked.ignored not in words    # both left the list at the Generate


def test_a_mark_leaves_the_numbers_at_once_as_the_next_generate_does(marked):
    """The engine of the plan before the marks, the marked words left out, gives every file the *N new* the Generate
    after the marks gives it (the list's cut-off unmoved: two words don't move it)."""
    assert marked.before.header.get("floor") == marked.after.header.get("floor")
    _n, eng = _n_new_by_file(marked.before)
    assert eng.leave_out(marked.left) is True
    following, _eng = _n_new_by_file(marked.after)
    at_once = {entry[0]: eng._n_new[f] for f, entry in enumerate(marked.before.files)}
    assert at_once == following
    assert eng._first[marked.known_k] is None and eng._first[marked.ignore_k] is None
    gone = {marked.known_k, marked.ignore_k}
    for entry in marked.before.files:                                 # never in a title's words (the word card)
        new, before = eng.words_of([entry[0]])
        assert not gone & {w.k for w in new + before}


def test_the_rank_of_every_other_word_is_the_generates(marked):
    """Up next and the priority list: every other listed word keeps its place, in the Generate's own order."""
    _n, eng = _n_new_by_file(marked.before)
    eng.leave_out(marked.left)
    order = [k for k in sorted((k for k in range(eng._n) if eng._rank_of[k] is not None), key=eng._rank_of.__getitem__)]
    _n2, eng2 = _n_new_by_file(marked.after)
    order2 = sorted((k for k in range(eng2._n) if eng2._rank_of[k] is not None), key=eng2._rank_of.__getitem__)
    assert [marked.before.keys[k][:2] for k in order] == [marked.after.keys[k][:2] for k in order2]


def test_a_mark_taken_out_in_place_equals_the_numbers_worked_out_from_scratch(marked):
    """`leave_out` takes a new mark out in place (no pass over every file: a review's finding); the same numbers as
    `_numbers` from scratch — first places, *N new*, every rank and its tie-break — one word at a time, then both."""
    _n, eng = _n_new_by_file(marked.before)
    for words in ({marked.ignored}, set(marked.left)):
        assert eng.leave_out(words) is True
        in_place = (list(eng._n_new), list(eng._first), list(eng._ranked), list(eng._rank_of))
        eng._numbers([(eng._ids[f], plan_engine.TIERS[eng._tier[f]]) for f in eng._order])
        assert in_place == (eng._n_new, eng._first, eng._ranked, eng._rank_of)


def test_a_clear_brings_the_word_back_with_its_plan_numbers(marked):
    n_new, eng = _n_new_by_file(marked.before)
    first, ranked = list(eng._first), list(eng._ranked)
    eng.leave_out(marked.left)
    assert eng.leave_out(set(marked.left) - {marked.known}) is True       # the Known word cleared
    assert eng._first[marked.known_k] == first[marked.known_k]
    assert eng.leave_out(()) is True                                      # both
    assert eng._first == first and eng._ranked == ranked
    assert {entry[0]: eng._n_new[f] for f, entry in enumerate(marked.before.files)} == n_new
    assert eng.leave_out(()) is False                                     # nothing changed: nothing worked out


def test_a_move_after_a_mark_still_follows_the_order(marked):
    """The engine's moves keep the marked words out: a move after the marks equals the marks after the move."""
    _n, moved_then_marked = _n_new_by_file(marked.before)
    _n, marked_then_moved = _n_new_by_file(marked.before)
    marked_then_moved.leave_out(marked.left)
    last, first = marked.before.files[-1][0], marked.before.files[0][0]
    for eng in (moved_then_marked, marked_then_moved):
        eng.move([last], "now", before_id=first)
    moved_then_marked.leave_out(marked.left)
    assert moved_then_marked._n_new == marked_then_moved._n_new
    assert moved_then_marked._first == marked_then_moved._first


def test_known_raises_the_files_percent_known_and_ignore_leaves_the_known_words_alone(marked):
    """% known comes with the Generate after (the rows' figure is the plan's): each file holding the Known word counts
    more of its tokens known than before."""
    def prog(plan):
        return {entry[0]: plan.per_file[f]["prog"][:2] for f, entry in enumerate(plan.files)}
    before, after = prog(marked.before), prog(marked.after)
    _n, eng = _n_new_by_file(marked.before)
    holders = {marked.before.files[f][0] for f in eng._files_of[marked.known_k]}
    for path in holders:
        assert after[path][1] > before[path][1] and after[path][0] == before[path][0]
