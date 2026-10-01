"""The set phrases' build (scripts/build_phrase_data.py) — its rules on real headwords and tiny made-up lists.

The build reads every JMdict headword with the app's own tokenizer and keeps a set phrase: two to five words, built
like a phrase (two real words, or one with a light verb or adjective), never one word + grammar, never a card the app
reads as one word + an ending, never a title; a unit in general text (the lists rank it no more than 8 times rarer
than its count there); and a real word that lives only inside its phrase is marked so. The pieces are tested here on
real Japanese through the project's fugashi + unidic-lite, the lists and the text made up — never the reference
corpora, which the build alone reads.
"""

import importlib.util
import json
import os

import pytest

from app import analyzer, settings_manager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def bpd():
    """scripts/build_phrase_data.py — a build step that never ships, so no package."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    spec = importlib.util.spec_from_file_location("build_phrase_data", os.path.join(ROOT, "scripts",
                                                                                    "build_phrase_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def read(bpd):
    """A headword read as the build reads it: every parsing switch at its default, shared data's tokenizer."""
    analyzer.SANITIZE_JA = True
    defaults = settings_manager.DEFAULT_SETTINGS["logic"]
    for name in ("names_katakana", "names_recurring", "names_kanji", "names_work_terms", "phrases_and_titles",
                 "pronoun_bases"):
        analyzer.LOGIC[name] = defaults.get(name, True)
    tagger, joins, compounds = analyzer.Tagger(), analyzer.affix_joins(), analyzer.compound_joins()

    def verdict(spelling):
        tokens = bpd.read_alone(tagger, joins, spelling)
        if len(tokens) < 2:
            return "one word"
        why = bpd.shape(tokens, spelling, compounds)
        if why:
            return why
        return bpd.structure(tokens, bpd.roles(tokens)) or "phrase:" + bpd.roles(tokens)
    return verdict


@pytest.mark.parametrize("spelling, expected", [
    ("気がする", "phrase:cgl"), ("気持ち悪い", "phrase:cc"), ("腑に落ちる", "phrase:cgc"), ("もしかしたら", "phrase:cglg"),
    ("それは", "one word + grammar"), ("言って", "one word + grammar"), ("帰ってくる", "one word + grammar"),
    ("どうしよう", "a card the app reads as one word + an ending"), ("うんうん", "one word said twice"),
    ("予想通り", "one word"), ("あの子", "starts with a filler"),
])
def test_what_is_built_like_a_phrase(read, spelling, expected):
    """Two real words, or one with a light verb or adjective, is built like a phrase; one word + grammar, a card the
    app reads as its one word (どうしよう is どう + する, as 努力する is 努力), a word said twice, a spelling the tokenizer
    reads as one word (予想通り, a compound) and a start the tagger reads as a filler (あの) are not."""
    assert read(spelling) == expected


def test_a_title_is_never_a_phrase(bpd):
    """An entry every sense of which names a work, a product or an organization gives no spelling to read."""
    title = {"seq": 1, "kanji": [("進撃の巨人", (), ())], "kana": [("しんげきのきょじん", (), (), False, ())],
             "senses": [{"pos": ("n",), "misc": ("work",)}]}
    phrase = dict(title, kanji=[("気がする", (), ())], kana=[("きがする", (), (), False, ())],
                  senses=[{"pos": ("exp",), "misc": ()}])
    assert bpd.entry_spellings(title) == []
    assert bpd.entry_spellings(phrase) == [("気がする", ["きがする"])]


def _lists(bpd, tmp_path, monkeypatch, *lists):
    """Tiny frequency lists in their own shape ([word, reading] pairs, best rank first)."""
    import build_reference_data as brd
    monkeypatch.setattr(brd, "LISTS_DIR", str(tmp_path))
    out = []
    for n, entries in enumerate(lists):
        (tmp_path / f"list{n}.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        out.append(brd.ListReadings(f"list{n}"))
    return out


def _cand(key, readings, roles, spellings, readings_jm, orths=None):
    return {"key": tuple(key), "readings": tuple(readings), "roles": roles, "spellings": list(spellings),
            "readings_jm": list(readings_jm), "orths": orths or [{k} for k in key], "flags": {},
            "spelled": {s: r for s, r in zip(spellings, readings_jm)}}


def test_the_unit_test_keeps_a_phrase_the_lists_rank_near_its_count_and_folds_a_failing_form(bpd, tmp_path,
                                                                                           monkeypatch):
    """A phrase's matches in the text, as a rank among the text's words, against the list's rank: 腑に落ちる (ranked
    near its count) is kept; いいと思う (matched far more than the list ranks it) is dropped; 腑に落ちない fails too, and
    being 腑に落ちる + grammar it folds into it — its matches count for 腑に落ちる; a phrase no list has is dropped."""
    filler = [[f"語{i}", "ゴ"] for i in range(3000)]           # list ranks: 腑に落ちる 11, いいと思う 152, 腑に落ちない 3,003
    jpdb, jiten = _lists(bpd, tmp_path, monkeypatch,
                         filler[:10] + [["腑に落ちる", "フニオチル"]] + filler[10:150] + [["いいと思う", "イイトオモウ"]]
                         + filler[150:] + [["腑に落ちない", "フニオチナイ"]], [])
    gut = _cand(["腑", "に", "落ちる"], ["フ", "ニ", "オチル"], "bgc", ["腑に落ちる"], ["フニオチル"])
    gut_not = _cand(["腑", "に", "落ちる", "ない"], ["フ", "ニ", "オチル", "ナイ"], "bgcg", ["腑に落ちない"],
                    ["フニオチナイ"])
    think = _cand(["良い", "と", "思う"], ["ヨイ", "ト", "オモウ"], "lgc", ["いいと思う"], ["イイトオモウ"])
    nowhere = _cand(["雨", "が", "上がる"], ["アメ", "ガ", "アガル"], "cgc", ["雨が上がる"], ["アメガアガル"])
    cands = [gut, gut_not, think, nowhere]
    words = {(f"語{i}", "ゴ"): 3000 - 10 * i for i in range(300)}  # the text's word counts: 3000, 2990, ... 10
    # In the text: 腑に落ちる + its folded form as often as the 11th word (list rank 11: x1), いいと思う as the 1st
    # (list rank 152: x152), 腑に落ちない as the 291st (list rank 3,003: x10.3, over the line).
    found = {0: 2800, 1: 100, 2: 2995, 3: 0}
    kept, dropped, folded = bpd.unit_test(cands, found, words, jpdb, jiten)
    assert [c["key"] for c in kept] == [gut["key"]]
    assert folded == {gut_not["key"]: gut["key"]} and gut["uses"] == 2800 + 100
    assert {c["key"] for c in dropped} == {gut_not["key"], think["key"], nowhere["key"]}
    assert think["ratio"] > bpd.UNIT_RATIO >= gut["ratio"]


def test_a_word_is_bound_when_the_list_ranks_it_alone_rarer_than_its_phrase(bpd, tmp_path, monkeypatch):
    """腑 (rarer alone than 腑に落ちる) lives only inside the phrase; 落ちる (far commoner) is free; 気 in 気がする is
    free. A word the list gives another reading — the one the phrase's own reading holds (read alone the tagger misread
    it: 気の強い's 強い as シイ) — is ranked by that reading, not taken for unlisted."""
    jpdb, = _lists(bpd, tmp_path, monkeypatch,
                   [["気", "キ"], ["強い", "ツヨイ"], ["落ちる", "オチル"], ["気がする", "キガスル"], ["気の強い", "キノツヨイ"],
                    ["腑に落ちる", "フニオチル"], ["腑", "フ"]])
    gut = dict(_cand(["腑", "に", "落ちる"], ["フ", "ニ", "オチル"], "cgc", ["腑に落ちる"], ["フニオチル"]), jpdb=6)
    feel = dict(_cand(["気", "が", "為る"], ["キ", "ガ", "スル"], "cgl", ["気がする"], ["キガスル"]), jpdb=4)
    strong = dict(_cand(["気", "の", "強い"], ["キ", "ノ", "シイ"], "cgc", ["気の強い"], ["キノツヨイ"]), jpdb=5)
    assert bpd.bind(gut, jpdb) == "bgc"
    assert bpd.bind(feel, jpdb) == "cgl"
    assert bpd.bind(strong, jpdb) == "cgc", "強い is the list's ツヨイ, the reading 気の強い holds"
    assert bpd.bind(dict(gut, jpdb=None), jpdb) == "cgc", "no rank for the phrase: nothing bound"


def test_the_spelling_shown_reads_as_the_phrase_does(bpd, tmp_path, monkeypatch):
    """Among a phrase's spellings the one shown reads as its own words do (このみ, not こん身 — 渾身 misread into the same
    words), then the one the lists rank best."""
    jpdb, jiten = _lists(bpd, tmp_path, monkeypatch, [["こん身", "コンシン"], ["この身", "コノミ"]], [])
    body = _cand(["此の", "身"], ["コノ", "ミ"], "cc", ["こん身", "この身"], ["コンシン", "コノミ"])
    assert bpd.display(body, jpdb, jiten) == "この身"
    notice = _cand(["気", "が", "付く"], ["キ", "ガ", "ツク"], "cgc", ["気が付く", "気がつく"], ["キガツク", "キガツク"])
    jpdb, jiten = _lists(bpd, tmp_path, monkeypatch, [["気がつく", "キガツク"], ["気が付く", "キガツク"]], [])
    assert bpd.display(notice, jpdb, jiten) == "気がつく"


def test_the_module_is_written_with_its_attribution(bpd, tmp_path):
    """The generated module decodes to the rows written, with JMdict's date, a revision and the EDRDG's licence."""
    path = tmp_path / "phrase_data.py"
    rows = [["気|が|為る", "キ|ガ|スル", "cgl", "気がする", "キガスル", 0], ["罪|無い", "ツミ|ナイ", "cl", "罪なき", "ツミナキ", 1],
            ["ああ|言う", "アア|イウ", "cc", "ああいう", "アアイウ", 2]]
    revision = bpd.write_module(rows, "2026-09-28", str(path))
    spec = importlib.util.spec_from_file_location("toy_phrase_data", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.phrases() == rows and module.COUNT == 3 and module.REVISION == revision
    assert module.JMDICT_CREATED == "2026-09-28" and "CC BY-SA 4.0" in module.__doc__
    doc = " ".join(module.__doc__.split())
    assert "pre-noun adjectival (2 phrases), 2 when it also says it is usually written in kana (1 of them" in doc
    with pytest.raises(AssertionError):
        bpd.write_module([["気", "キ", "c", "気", "キ", 0]], "", str(path))      # one word is no phrase


def test_a_phrase_is_marked_pre_noun_only_when_jmdict_classes_it_so_and_nothing_else():
    """JMdict's class: adj-pn in every sense, with nothing beside it but exp (ああいう: exp + adj-pn; こういう:
    adj-pn) — or an expression every sense of which JMdict sends to such a one (そういった: exp, 'see そういう') —
    then the phrase stands only before a noun. Not when a sense is a noun too (脳足りん), not an expression sent
    nowhere or to a word of another class, nor an entry with no sense."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    spec = importlib.util.spec_from_file_location("bpd_pre_noun", os.path.join(ROOT, "scripts", "build_phrase_data.py"))
    bpd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bpd)

    def entry(*pos_lists, xref=()):
        return {"senses": [{"pos": tuple(pos), "xref": tuple(xref)} for pos in pos_lists]}
    assert bpd.pre_noun(entry(("exp", "adj-pn"))) and bpd.pre_noun(entry(("adj-pn",), ("adj-pn",)))
    assert not bpd.pre_noun(entry(("adj-no", "adj-pn"), ("n",)))
    assert not bpd.pre_noun(entry(("exp",))) and not bpd.pre_noun(entry())
    sou_iu, iu = entry(("adj-pn",)), entry(("v5u",))
    idx = ({"そう言う": [sou_iu], "言う": [iu]}, {"そういう": [sou_iu], "いう": [iu]})
    assert bpd.pre_noun(entry(("exp",), xref=("そういう",)), idx), "そういった: 'see そういう'"
    assert bpd.pre_noun(entry(("exp",), xref=("そう言う・そういう・1",)), idx)
    assert not bpd.pre_noun(entry(("exp",), xref=("そういう",)))           # no index to look it up in
    assert not bpd.pre_noun(entry(("exp",), xref=("言う",)), idx)          # sent to a verb
    assert not bpd.pre_noun(entry(("exp",), xref=("どこにもない",)), idx)  # sent nowhere it can find


def test_a_pre_noun_adjectival_usually_written_in_kana_is_marked_2(bpd):
    """JMdict's "uk" on every sense of every entry behind a pre-noun phrase (そういった, ああいう, どういう) makes the mark
    2 — found only as written in kana — when the phrase has a spelling in kana to be found in; one sense without it,
    or no kana spelling, leaves it 1; a phrase that is no pre-noun adjectival is 0 whatever its tags."""
    assert bpd.usually_kana({"senses": [{"misc": ("uk",)}, {"misc": ("uk", "form")}]})
    assert not bpd.usually_kana({"senses": [{"misc": ("uk",)}, {"misc": ()}]})
    assert not bpd.usually_kana({"senses": []})

    def cand(prenoun, kana, spellings):
        return {"prenoun": prenoun, "kana": kana, "spellings": spellings}
    assert bpd.pre_noun_mark(cand(True, True, ["そう言った", "そういった"])) == 2
    assert bpd.pre_noun_mark(cand(True, True, ["有り得べき"])) == 1           # no spelling in kana to be found in
    assert bpd.pre_noun_mark(cand(True, False, ["罪なき", "罪無き"])) == 1
    assert bpd.pre_noun_mark(cand(False, True, ["もったいない"])) == 0
