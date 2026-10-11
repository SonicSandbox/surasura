"""The exactness gates (E2.2 D7, row 2.2.6) one rule at a time, on gates built by hand: `arrivals.Gates.check` over a
small synthetic plan and library (real words), so each gate's edge — a word reaching or falling under the cut-off, a
compound's rarity, a name, an idiom row, a spelling — is pinned without a Generate. `test_arrivals_parity.py` proves
the gates on real libraries (RP-2); these pin the branches its one line per gate can't reach.

`_gates(...)` builds a `Gates` the way `Gates.build` would leave it, from plain arguments; `_rec(...)` an arrival's
record as `arrivals.record` returns it (only the fields `check` reads)."""
from collections import Counter
from types import SimpleNamespace

from app import arrivals, phrases, word_selection

# Plan keys: [Word, Reading, is_phrase, half, Occurrences] (plan_engine.Plan).
GAKKOU = ("学校", "ガッコウ")
SENSEI = ("先生", "センセイ")
TOMODACHI = ("友達", "トモダチ")
KYOUSHITSU = ("教室", "キョウシツ")        # off the list: met under the cut-off
JOUSOUBU = ("上層部", "ジョウソウブ")       # a compound of 上層 + 部
JOUSOU = ("上層", "ジョウソウ")


class _Phrase:
    def __init__(self, word, reading, display):
        self.word, self.reading, self.display = word, reading, display


class _PhraseSet:
    def __init__(self, phrases):
        self.phrases = phrases

    def entry(self, index):
        return self.phrases[int(index)]


def _row(orth, forms=""):
    """A plan row: [Tier, phrase Tier, Modality, Sources, Orth, Forms, contexts]."""
    return ["NOW", None, "text", 1, orth, forms, []]


def _gates(keys, *, rows=None, ties=(), spell=None, view_ties=None, counts=None, total=1000, floor0=2,
           min_freq=2, coverage=0, ppm=None, min_count=2, auto=False, band="occasional", parts=None, known=(),
           rare=(), room=None, pieces=None, phrase_set=None, row_of_phrase=None, phrase_uses=None,
           phrase_spellings=None, language="zh", stale=None, tables=None, table_sums=None, term_sums=None,
           names_words=(), known_tuples=(), known_lemmas=(), ignore=(), records=None, unsure=(), phrase_rows=None):
    """A `Gates` as `Gates.build` leaves it, for a plan whose keys are `keys` ([Word, Reading, is_phrase, half,
    Occurrences] each; a listed key has a row — `rows` default: every key listed, Orth = its Word). `counts`: the
    store's counted aggregate {(lemma, reading): n} (default: each key's Occurrences). Manual band by default
    (`min_freq` 2 fixes the cut-off at 2; `min_freq=0` makes it `word_selection.band_floor_count` of `band`)."""
    keys = [list(k) for k in keys]
    rows = [_row(k[0]) for k in keys] if rows is None else rows
    counts = dict(counts if counts is not None else {(k[0], k[1]): k[4] for k in keys if not k[2]})
    parts = parts or {}
    known = set(known)
    plan = SimpleNamespace(keys=keys, rows=rows, ties=[list(t) for t in ties], spell=spell or {},
                           header={"floor": floor0, "total_tokens": total})
    view = SimpleNamespace(
        language=language, plan=plan, keys=[tuple(k) for k in keys],
        index={(k[0], k[1]): i for i, k in enumerate(keys) if not k[2]},
        learning=SimpleNamespace(parts=parts, credits=lambda compound: [p[:2] for p in parts.get(compound, ())]),
        known=lambda key: key in known, rare=frozenset(rare), phrase_set=phrase_set,
        known_tuples=set(known_tuples), known_lemmas=set(known_lemmas), ignore=set(ignore),
        ties=view_ties or {}, counts=counts, total=total, skip_singles=False, entry_of=row_of_phrase or {},
        unsure=set(unsure), phrase_rows=dict(phrase_rows or {}))
    occ = [k[4] for k in keys]
    gates = arrivals.Gates(
        view=view, min_freq=min_freq, coverage=coverage, auto=auto, band=band, band0=band,
        ppm=ppm or word_selection.DEFAULT_BANDS_PPM, min_count=min_count,
        max_words=word_selection.DEFAULT_AUTO_MAX_WORDS, remembered=None, counts=counts, total=total, bound={},
        pieces=pieces or {}, floor0=floor0, lemmas={key[0] for key in counts}, stale=stale,
        room=Counter(room or {}), compound_counts=sorted(n for key, n in counts.items() if key in parts
                                                         and key not in known),
        occ=occ, occ_min=min(occ, default=0), row_of_phrase=dict(row_of_phrase or {}),
        phrase_uses=phrase_uses, phrase_spellings=phrase_spellings, tables=tables, table_sums=table_sums,
        term_sums=term_sums, names_words=set(names_words), records=records,
        known_whole=phrases.known_whole if phrase_set is not None else None)
    return gates


def _rec(counts=None, uses=None, phrases=None, bound=None, tally=None, spc=None, names=None):
    """An arrival's record as `arrivals.record` gives it — the fields `Gates.check` reads. `counts` default: `uses`."""
    uses = Counter(uses or {})
    return {"counts": Counter(counts if counts is not None else uses), "uses": uses, "phrases": Counter(phrases or {}),
            "bound": Counter(bound or {}), "tally": tally or ({}, {}), "spc": spc or {}, "names": names}


LIST = [[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3], [*TOMODACHI, 0, 0, 2]]


def test_an_arrival_of_list_words_only_moves_no_gate():
    """The baseline every test below departs from: list words met again, nothing else — exact."""
    gates = _gates(LIST)
    assert gates.check([_rec(uses={GAKKOU: 2, SENSEI: 1})]) == (True, [])


def test_a_word_off_the_list_reaching_the_cut_off_moves_the_floor_gate():
    """教室 was met once (under the cut-off of 2); an arrival using it once more brings it to 2: a new list word."""
    gates = _gates(LIST, counts={GAKKOU: 5, SENSEI: 3, TOMODACHI: 2, KYOUSHITSU: 1})
    assert gates.check([_rec(uses={KYOUSHITSU: 1})]) == (False, ["floor"])


def test_a_store_that_no_longer_holds_the_plans_library_is_never_exact():
    """`stale` (Gates.build found the store's total or cut-off isn't the plan's): every check says so, whatever the
    arrival holds — the engine's numbers can't be trusted to be the next Generate's."""
    gates = _gates(LIST, stale="the token store isn't the plan's library")
    assert gates.check([_rec(uses={GAKKOU: 1})]) == (False, ["stale"])


def _name_record(spelling, pieces, n=1):
    """A file's name record (`names.Record` data) holding the katakana run `spelling` `n` times, cut into `pieces`."""
    return {"ks": {spelling: {"|".join(pieces): n}}, "p": {piece: n for piece in pieces}}


def test_with_no_tables_kept_the_names_gate_counts_the_librarys_records_too():
    """a store holding no name tables yet (none computed) still
    has its files' name records. A katakana run the library met twice (under the 3 uses a run needs) joins with an
    arrival's third use — the gate must see it, never judge the arrival's record alone."""
    library = [_name_record("ミカサ", ("ミ", "カサ")), _name_record("ミカサ", ("ミ", "カサ"))]
    gates = _gates(LIST, language="ja", tables=None, records=library)
    exact, moved = gates.check([_rec(uses={GAKKOU: 1}, names=_name_record("ミカサ", ("ミ", "カサ")))])
    assert (exact, moved) == (False, ["names"])
    other = gates.check([_rec(uses={GAKKOU: 1}, names=_name_record("エレン", ("エ", "レン")))])
    assert other == (True, []), "a run met once in all moves nothing"


# --- E2.2 final review (adversary X7 / X12, intent keeper 5d, haiku worker #13) ----------------------------------- #
def test_a_phrase_row_a_format_1_plan_cant_place_moves_the_phrases_gate():
    """X12: a format-1 plan doesn't name each phrase row's phrase, and a row two phrases of the set could hold is
    `unsure` — its uses are counted nowhere, so an arrival meeting that phrase can't be exact, whatever the rest of
    the phrase gate finds (here the store's tallies put it under the cut-off, so the new-row check says nothing)."""
    idiom = _Phrase("気がする", "キガスル", "気がする")
    keys = LIST + [["気がする", "キガスル", 1, 0, 3]]
    gates = _gates(keys, phrase_set=_PhraseSet([idiom]), phrase_uses={0: 0}, phrase_spellings={0: ["気がする"]},
                   unsure={3}, phrase_rows={("気がする", "キガスル"): 3})
    assert gates.check([_rec(uses={GAKKOU: 1}, phrases={0: 1})]) == (False, ["phrases"])
    assert gates.check([_rec(uses={GAKKOU: 1})]) == (True, []), "no use of the phrase: nothing to tell"


def test_with_no_tables_kept_the_librarys_own_tables_are_worked_out_once():
    """Haiku worker #13 (waste): with no name tables kept, the library's tables without the arrivals are the same for
    every check — worked out once per view, never again per arrival."""
    from unittest.mock import patch
    from app import names
    library = [_name_record("ミカサ", ("ミ", "カサ")), _name_record("ミカサ", ("ミ", "カサ"))]
    gates = _gates(LIST, language="ja", tables=None, records=library)
    real = names.compute_tables
    with patch.object(names, "compute_tables", side_effect=real) as made:
        for _ in range(3):
            gates.check([_rec(uses={GAKKOU: 1}, names=_name_record("エレン", ("エ", "レン")))])
    assert made.call_count == 4, "the library's once, then one per check"


def _order(files, keys=2, per_file=None):
    """An `arrivals.Order` over a plan of `files` ([id, tier] each) whose keys are first met as `per_file` says."""
    per_file = per_file or [{"main": [], "ph": []} for _f in files]
    plan = SimpleNamespace(files=[list(f) for f in files], keys=[["語", "ゴ", 0, 0, 1]] * keys, per_file=per_file)
    return arrivals.Order(plan)


def test_after_its_show_anchors_only_in_current():
    """Intent keeper 5d (D28): a new episode joins its show only where the show's episodes are in Current (NOW, Soon);
    a show whose episodes are all in 6+ Months gives no "after its show" (its new episode leads Current: the
    top-of-NOW figure)."""
    show = "HighPriority/作品"
    current = _order([[f"{show}/第01話.srt", "now"], [f"{show}/第02話.srt", "soon"], ["GoalContent/作品/第03話.srt",
                                                                                   "goal"]])
    top, after, anchor = current.n_new([0, 1], f"{show}/第04話.srt")
    assert (top, anchor) == (2, f"{show}/第02話.srt") and after == 2
    later = _order([["GoalContent/作品/第01話.srt", "goal"], ["GoalContent/作品/第02話.srt", "goal"]])
    assert later.n_new([0, 1], f"{show}/第03話.srt") == (2, None, None)
    placed = [("GoalContent/作品/第02話b.srt", [0], None, None, None)]
    assert later.n_new([0, 1], f"{show}/第03話.srt", placed)[1:] == (1, "GoalContent/作品/第02話b.srt"), \
        "a file placed after its show with no episode in Current leads NOW, and the next joins it there"


def test_an_estimate_on_a_plan_the_engine_stands_aside_from_is_never_exact():
    """X7: a coverage-mode plan (or i+1, shared phrases) is one `plan_engine.Engine` refuses to load — the gates don't
    model its list, so the estimate must not say exact."""
    plan = SimpleNamespace(header={"target_coverage": 90, "weights": {"now": 1}}, rows=[_row("学校")])
    view = SimpleNamespace(plan=plan, keys=[GAKKOU])
    order = SimpleNamespace(n_new=lambda keys, rel, placed: (1, None, None))
    gates = SimpleNamespace(check=lambda records: (True, []))
    rec = {"main": [0, 2], "ph": [], "sp": [], "prog": [10, 8], "spc": {}, "plan": "sig", "keys": 1, "name": "a.txt"}
    answer = arrivals.estimate(view, gates, order, rec)
    assert (answer["exact"], answer["moved"]) == (False, ["stand-aside"])
    plan.header = {"weights": {"now": 1}}
    assert arrivals.estimate(view, gates, order, rec)["exact"] is True
