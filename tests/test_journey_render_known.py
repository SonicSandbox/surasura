"""The journey v3 page's *% known* is the window's (J-DATA; the dup audit's row 4): one number everywhere
(`view_rows.pct_of`, known tokens ÷ counted tokens, the plan's count), never file_statistics.json's Coverage (%); and
the kanji hover's known words are the list's own (row 7), never a rule of the page's over KnownWord.json.

A real Generate on the sample library (test_generate_watched's: two shows of three episodes cut from the bundled
samples' real text), then the window's own numbers (`moves.Numbers` over the plan file) against the page's figure,
for every file — with the plan handed in, and without it (the store's 'last' snapshot, the same Generate's count).

What a wrong answer would cost a learner: the rail beside an episode saying one % and its row in the window another.
Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT."""
import json
import os
import time

import pytest

from app import journey_render as jr, plan_engine
from app.path_utils import report_name
from app.services import moves as M, view_rows
from tests.test_generate_watched import _generate, _library
from tests.test_library_store_support import LANGUAGES, roots


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_pages_known_percent_is_the_windows_for_every_file_with_or_without_the_plan(language):
    root = os.environ["SURASURA_TEST_ROOT"]
    store, _paths, ids = _library(language)
    store.close()
    _generate(root, language)
    numbers = M.Numbers(M.store_opener(language), language)
    try:
        numbers._load()
        _v, table = numbers()
    finally:
        numbers.close()
    window = {item: round(view_rows.pct_of(known, counted), 1) for item, (known, counted, _n) in table.items()}
    assert set(window) == set(ids.values()), "every counted file has the window's figure"

    data_dir, user_files_dir = roots(language)
    facts = jr.store_facts(language, data_dir, user_files_dir)
    plan = plan_engine.load(os.path.join(root, "results", "plan.json.gz"), pools=False)
    # The stats file disagreeing must not matter: the page never reads its Coverage (%)
    stats = [{"File": report_name(e[0]), "Coverage (%)": 1.0} for e in plan.files]
    for handed in (plan, None):
        out = jr.build(language, [], stats, facts=facts, plan=handed, pitch=jr.Pitch(language, kanjium={}))
        page = {e[0]: e[6] for e in out.head["eps"] if e[0] is not None}
        assert page == window, ("with the plan" if handed else "from the store's 'last' snapshot", page, window)


def test_known_percent_is_none_with_nothing_counted_never_zero():
    """A file with no words (0 of 0) shows no figure, as the window's em dash: never 0 %."""
    assert jr._known_pct(0, 0) is None and jr._pct({"known": 0, "counted": 0}) is None and jr._pct(None) is None
    assert jr._known_pct(1, 3) == 33.3 and jr._pct({"known": None, "counted": 4}) == 0.0


def _known_file(entries):
    from app.path_utils import get_user_files_path
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": entries}, f, ensure_ascii=False)
    return path


def test_the_kanji_hovers_known_words_are_the_lists_own_never_a_rule_over_the_file():
    """The dup audit's row 7: the hover's known words are the known lemmas the list's own test made
    (`analyzer.read_known_words`, kept in the token store by Generate) — a known sentence read into its words, a word
    still being learned left out — and none at all once the file changed after that Generate, or with no store."""
    from app import analyzer, token_index
    assert jr._known_terms("ja") == []                                          # no store yet: no hover word
    path = _known_file([{"dictForm": "時間がない", "knownStatus": "KNOWN", "hasCard": 0},
                        {"dictForm": "勉強", "knownStatus": "LEARNING", "hasCard": 0},
                        {"dictForm": "電車", "knownStatus": "UNKNOWN", "hasCard": 1}])
    store = token_index.open_store("ja")
    try:
        _tuples, lemmas = analyzer.read_known_words(store, path, token_index.known_signature(path),
                                                    analyzer.JapaneseTokenizer())        # as Generate keeps them
    finally:
        store.close()
    terms = jr._known_terms("ja")
    assert terms == sorted(lemmas) and "時間" in terms and "電車" in terms and "勉強" not in terms
    assert jr.known_with({"時", "電"}, terms)["時"] == "時間", "the sentence's word, not the sentence"
    time.sleep(0.05)
    _known_file([{"dictForm": "時間がない", "knownStatus": "KNOWN", "hasCard": 0}, {"dictForm": "学校", "hasCard": 1}])
    assert jr._known_terms("ja") == [], "the file changed since the Generate: no hover word until the next reads it"
