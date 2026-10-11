"""The exactness gates (E2.2 D7, row 2.2.6) one rule at a time, on gates built by hand: `arrivals.Gates.check` over a
small synthetic plan and library (real words), so each gate's edge — a word reaching or falling under the cut-off, a
compound's rarity, a name, an idiom row, a spelling — is pinned without a Generate. `test_arrivals_parity.py` proves
the gates on real libraries (RP-2); these pin the branches its one line per gate can't reach (the E2.2 mutant pass).

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
           names_words=(), known_tuples=(), known_lemmas=(), ignore=(), records=None):
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
        ties=view_ties or {}, counts=counts, total=total, skip_singles=False, entry_of=row_of_phrase or {})
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
    """E2.2 review A2 / mutant names_no_tables_never_moves: a store holding no name tables yet (none computed) still
    has its files' name records. A katakana run the library met twice (under the 3 uses a run needs) joins with an
    arrival's third use — the gate must see it, never judge the arrival's record alone."""
    library = [_name_record("ミカサ", ("ミ", "カサ")), _name_record("ミカサ", ("ミ", "カサ"))]
    gates = _gates(LIST, language="ja", tables=None, records=library)
    exact, moved = gates.check([_rec(uses={GAKKOU: 1}, names=_name_record("ミカサ", ("ミ", "カサ")))])
    assert (exact, moved) == (False, ["names"])
    other = gates.check([_rec(uses={GAKKOU: 1}, names=_name_record("エレン", ("エ", "レン")))])
    assert other == (True, []), "a run met once in all moves nothing"
