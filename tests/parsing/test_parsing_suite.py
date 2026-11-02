"""The parsing-robustness suite's guard — every case of the registry, inside `python run_tests.py`.

LOCK cases must pass: a failure is a regression, or an intended change whose expectation is updated on purpose.
TARGET cases run as strict expected failures: the change that fixes one fails the run until the case is promoted
to LOCK, so no fix goes unnoticed (and a TARGET case that crashes fails too — only a wrong answer is expected).
LIMIT and DISPUTED cases are skipped here, with their decision; the scorecard (scorecard.py) reports them. A case
its evaluator can't judge on this machine as it stands (harness.Skip — installed パターン databases older than the
code's builder) is skipped with the reason, whatever its status.

The integrity tests below keep the registry honest for the agents porting cases into it: well-formed unique ids,
known layers and expectation keys, and decisions that exist and fit the status that cites them.
"""
import json
import re

import pytest

from tests.parsing import harness
from tests.parsing.case import CATEGORIES, LANGUAGES, SOURCES, STATUSES, Case
from tests.parsing.cases import CASES
from tests.parsing.decisions import ALL as ALL_DECISIONS, DECISIONS

harness.load_evaluators()       # at collection: the marks and the integrity tests read the registry

_ID = re.compile(r"^(JA|ZH)-[A-Z][A-Z0-9]{1,5}-\d{3,4}[a-z]?$")


def _why(case):
    decision = DECISIONS.get(case.decision)
    if decision is None:
        return case.status
    return f"{case.status} — {decision.id} ({decision.status}): {harness.short(decision.choice or decision.question, 110)}"


def _param(case):
    marks = ()
    if case.status == "TARGET":
        marks = (pytest.mark.xfail(strict=True, raises=AssertionError, reason=_why(case)),)
    elif case.status in ("LIMIT", "DISPUTED"):
        marks = (pytest.mark.skip(reason=_why(case)),)
    return pytest.param(case, id=case.id, marks=marks)


@pytest.mark.parametrize("case", [_param(case) for case in CASES])
def test_case(case, parsing_ctx):
    result = harness.evaluate(case, parsing_ctx)
    if result.verdict == "skip":            # can't be judged on this machine as it stands (harness.Skip): say why
        pytest.skip(f"{case.status}: {result.problems[0]}")
    judge = harness.EVALUATORS[case.layer]
    assert result.verdict == "pass", (f"{case.id} [{case.status}] {case.span!r}: " + "; ".join(result.problems)
                                      + f"\n  observed: {judge.show(result.observed)}")


# --- the registry's integrity ------------------------------------------------------------------------------------ #
def test_case_ids_are_unique_and_well_formed():
    areas = {}
    for case in CASES:
        assert _ID.match(case.id), f"{case.id!r}: an id is <LANG>-<GROUP>-<NNN>, e.g. JA-CMP-012"
        assert case.id.split("-")[0].lower() == case.lang, f"{case.id}: the prefix is the case's language"
        assert case.id not in areas, f"{case.id} is defined twice (cases_{areas[case.id]}.py, cases_{case.area}.py)"
        areas[case.id] = case.area


def test_each_id_group_belongs_to_one_area():
    """Areas are ported in parallel: a group (JA-KNW) two files both use would let their numbers collide."""
    owners = {}
    for case in CASES:
        owners.setdefault(case.id.rsplit("-", 1)[0], set()).add(case.area)
    shared = {group: sorted(areas) for group, areas in owners.items() if len(areas) > 1}
    assert not shared, f"id groups used by more than one cases file: {shared}"


def test_every_case_names_a_known_language_layer_category_status_and_source():
    for case in CASES:
        assert case.lang in LANGUAGES, case.id
        assert case.layer in harness.EVALUATORS, f"{case.id}: no evaluator for layer {case.layer!r}"
        assert case.category in CATEGORIES, f"{case.id}: category {case.category!r} is not one of A–O"
        assert case.status in STATUSES, f"{case.id}: status {case.status!r}"
        assert case.source.split(":")[0].strip() in SOURCES, f"{case.id}: source starts with one of {SOURCES}"
        assert case.basis.strip(), f"{case.id}: a basis — why the expectation is right"
        assert isinstance(case.nth, int) and case.nth >= 1, case.id
        assert isinstance(case.refs, tuple) and isinstance(case.ctx, dict), case.id
        assert case.span == "" or case.span in case.text, f"{case.id}: the span {case.span!r} is not in the text"


def test_every_expectation_key_is_one_its_layer_reads():
    for case in CASES:
        assert case.expect, f"{case.id}: an expectation"
        unread = set(case.expect) - set(harness.EVALUATORS[case.layer].expects)
        assert not unread, f"{case.id}: {case.layer} reads no {sorted(unread)} (it reads {harness.EVALUATORS[case.layer].expects})"


def test_every_case_can_be_written_into_a_baseline():
    for case in CASES:
        json.dumps([case.text, case.expect, case.ctx, list(case.refs)], ensure_ascii=False)


def test_every_cited_decision_exists_and_fits_the_status():
    """LIMIT: accepted because of a DECIDED decision; DISPUTED: the user's call, an OPEN one."""
    for case in CASES:
        if case.decision is None:
            assert case.status not in ("LIMIT", "DISPUTED"), f"{case.id}: a {case.status} case names its decision"
            continue
        decision = DECISIONS.get(case.decision)
        assert decision is not None, f"{case.id}: no decision {case.decision!r} in decisions.py"
        if case.status == "LIMIT":
            assert decision.status == "decided", f"{case.id}: LIMIT cites {decision.id}, which is still open"
        if case.status == "DISPUTED":
            assert decision.status == "open", f"{case.id}: DISPUTED cites {decision.id}, which is decided"


def test_the_decisions_register_is_well_formed():
    ids = [decision.id for decision in ALL_DECISIONS]
    assert len(ids) == len(set(ids)), "a decision id is used twice"
    for decision in ALL_DECISIONS:
        assert decision.status in ("open", "decided"), decision.id
        assert (decision.choice is None) == (decision.status == "open"), \
            f"{decision.id}: an open decision has no choice yet, a decided one has"
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", decision.date), decision.id
        assert decision.question and decision.rationale and decision.tradeoff, decision.id


# --- the pins ------------------------------------------------------------------------------------------------------ #
def test_evaluating_leaves_the_analyzer_and_jieba_as_it_found_them(parsing_ctx, monkeypatch):
    """A case pins what the parse depends on and puts it back: it never decides a later test's SANITIZE_JA,
    SKIP_SINGLE_CHARS, LOGIC, the library's name tables, Ignore names' reader (the live settings.json and store) or
    jieba's reinforce tuning (process-wide, and one-way in the app)."""
    import jieba
    from jieba import finalseg
    from app import analyzer, names, token_index

    monkeypatch.setattr(analyzer, "SANITIZE_JA", False)
    monkeypatch.setattr(analyzer, "SKIP_SINGLE_CHARS", False)
    monkeypatch.setitem(analyzer.LOGIC, "parsing_suite_marker", 1)
    marker = {"k": {}, "stamp": "suite-marker"}
    names.use_library_tables(marker)
    jieba.initialize()
    words = harness._reinforced_words()
    before = (set(finalseg.Force_Split_Words), {word: jieba.dt.FREQ.get(word) for word in words}, jieba.dt.total)
    cases = (Case(id="ZH-PIN-001", lang="zh", layer="tokens_zh", category="O", text="他就把书放下了。", span="就把",
                  expect={"seg": "就 / 把"}, basis="pin check", status="LOCK", ctx={"reinforce": True}),
             Case(id="JA-PIN-001", lang="ja", layer="tokens_ja", category="E", text="新幹線に乗った。", span="新幹線",
                  expect={"units": "新幹線[新幹線]"}, basis="pin check", status="LOCK"))
    reader = token_index.ignored_names
    for case in cases:
        assert harness.evaluate(case, parsing_ctx).verdict == "pass", case.id
    assert token_index.ignored_names is reader
    assert analyzer.SANITIZE_JA is False and analyzer.SKIP_SINGLE_CHARS is False
    assert analyzer.LOGIC.get("parsing_suite_marker") == 1
    assert names._library["tables"] is marker and not names._library["pinned"]
    assert (set(finalseg.Force_Split_Words), {word: jieba.dt.FREQ.get(word) for word in words},
            jieba.dt.total) == before


def test_every_variant_loads_and_puts_back_what_it_patches():
    """Variants (variants.py + every variants_<area>.py) patch the pipeline for one scorecard run only: each must
    register, enter, and leave the app exactly as it found it — the guard itself never runs under one."""
    import jieba
    from app import analyzer, anki_match
    from modules.junban import match
    from tests.parsing.evaluators import UNKNOWN_COUNTERS
    from tests.parsing.variants import load_variants

    def state():
        return (analyzer.join_affixes, analyzer.affix_joins, analyzer.see_through_base, jieba.cut,
                analyzer.ChineseTokenizer.tokenize_sentences, anki_match.unknowns_beside, match.unknowns_beside,
                dict(UNKNOWN_COUNTERS))
    variants = load_variants()
    assert {"no-affix-joins", "compound-b", "r2q-same", "r2q-separate", "iii", "giveback", "leans", "zh-hmm-off",
            "zh-asis-via-simplified"} <= set(variants)
    before = state()
    for name, held in variants.items():
        assert held.about.strip(), name
        with held.manager():
            pass
        assert state() == before, f"variant {name} left a patch behind"


def test_the_reinforce_pin_tunes_nothing_since_reinforce_was_retired():
    # ZH-REINFORCE (built 2026-09-30): ChineseTokenizer(reinforce_segmentation=True) tunes no word, so the pin —
    # kept until its cases are re-filed — reads no word and leaves jieba as it found it.
    import jieba
    from jieba import finalseg

    assert harness._reinforced_words() == ()
    with harness.quiet():
        jieba.initialize()
    forced, total = set(finalseg.Force_Split_Words), jieba.dt.total
    with harness.jieba_reinforce(True):
        assert finalseg.Force_Split_Words == forced
    assert finalseg.Force_Split_Words == forced and jieba.dt.total == total


# --- a case that can't be judged here: harness.Skip ------------------------------------------------------------- #
def _installed_patterns_case():
    return Case(id="JA-PAT-900", lang="ja", layer="patterns", category="M", text="違和感", span="",
                expect={"key": "違和感|イワカン"}, basis="skip check", status="LOCK", ctx={"db": "installed:library"})


def test_a_case_reading_an_installed_database_an_older_builder_wrote_is_skipped_saying_why(tmp_path, monkeypatch):
    """The app refuses a パターン database an older builder wrote (patterns_store.open_store), so a case reading the
    installed ones would judge "no database" instead of the lookup until the data is rebuilt. It is skipped with the
    reason instead; the same case runs again, by itself, once the database is the current builder's."""
    import shutil
    import sqlite3
    from modules.junban.patterns_build import BUILDER_VERSION
    from tests.parsing.evaluators_ja_consumers import _built_store

    documents = Case(id="JA-PAT-901", lang="ja", layer="patterns", category="M", text="違和感", span="", expect={},
                     basis="the database's documents", status="LOCK",
                     ctx={"documents": ["彼の話に違和感を覚えた。", "少し違和感を感じる。", "その違和感を覚えている。"]})
    with harness.pinned(documents):
        store = _built_store(documents, harness.Context(str(tmp_path / "build")))
    installed = tmp_path / "appdata"
    installed.mkdir()
    shutil.copy(store.path, str(installed / "patterns_ja.db"))
    store.close()
    monkeypatch.setattr("app.path_utils.persistent_root", lambda: str(installed))   # get_persistent_user_data_path's too
    case = _installed_patterns_case()

    current = harness.evaluate(case, harness.Context(str(tmp_path / "current")))
    assert current.verdict == "pass", current.problems              # the current builder's database: judged

    con = sqlite3.connect(str(installed / "patterns_ja.db"))
    con.execute("UPDATE meta SET value=? WHERE key='builder_version'", (str(BUILDER_VERSION - 1),))
    con.commit()
    con.close()
    stale = harness.evaluate(case, harness.Context(str(tmp_path / "stale")))
    assert stale.verdict == "skip"
    assert stale.problems == [f"the installed パターン database (library) predates builder {BUILDER_VERSION} — rebuild "
                              "it and this case runs again"]
    assert stale.observed == {"skipped": stale.problems[0]}

    # the other installed databases are not the case's ("installed:library"): only the one it reads decides
    shutil.copy(str(installed / "patterns_ja.db"), str(installed / "patterns_ja_balanced.db"))
    con = sqlite3.connect(str(installed / "patterns_ja.db"))
    con.execute("UPDATE meta SET value=? WHERE key='builder_version'", (str(BUILDER_VERSION),))
    con.commit()
    con.close()
    assert harness.evaluate(case, harness.Context(str(tmp_path / "again"))).verdict == "pass"


def test_a_case_reading_installed_databases_where_none_is_installed_is_skipped_and_makes_nothing(tmp_path):
    """Under pytest the roaming root is the test root's (path_utils, S3.1), never the user's %APPDATA% — a case reading
    the installed databases there finds none: skipped saying so, never judged "no database", and the read makes no
    folder outside the test root."""
    import dataclasses
    import os
    case = _installed_patterns_case()
    for name, wanted in ((case.id, "installed:library"), ("JA-PAT-902", "installed")):
        result = harness.evaluate(dataclasses.replace(case, id=name, ctx={"db": wanted}),
                                  harness.Context(str(tmp_path / name)))
        assert result.verdict == "skip" and result.problems[0].startswith("no installed パターン database here")
    persistent = os.path.join(os.environ["SURASURA_TEST_ROOT"], "persistent_root")     # the read's folder: no database
    made = os.listdir(persistent) if os.path.isdir(persistent) else []                  # made (conftest guards the rest)
    assert not any(name.startswith("patterns_") for name in made)


def test_a_case_reading_installed_databases_makes_no_folder_where_none_was_ever_built(tmp_path, monkeypatch):
    """A scorecard run has no test root: the read is the user's real roaming root, and it made that empty folder
    (every test run on the PC then failed its real-root guard). Read only: an absent root stays absent, skipped."""
    import dataclasses
    import os
    absent = tmp_path / "roaming" / "Houseki" / "Surasura"
    monkeypatch.setattr("app.path_utils.persistent_root", lambda: str(absent))
    case = _installed_patterns_case()
    for name, wanted in ((case.id, "installed:library"), ("JA-PAT-903", "installed")):
        result = harness.evaluate(dataclasses.replace(case, id=name, ctx={"db": wanted}),
                                  harness.Context(str(tmp_path / name)))
        assert result.verdict == "skip" and result.problems[0].startswith("no installed パターン database here")
    assert not os.path.exists(str(tmp_path / "roaming"))


def test_the_scorecard_counts_a_skipped_case_apart_and_says_when_it_is_judged_again():
    """A skip is no verdict on the answer: never a LOCK failure, never "fixed" or "broken" — its own column, and its
    own groups in the diff (skipped now / judged again)."""
    from tests.parsing import scorecard
    case = _installed_patterns_case()
    skip = harness.Result({"skipped": "why"}, "skip", ["why"])
    passed = harness.Result({"key": "違和感|イワカン"}, "pass", [])
    record = lambda result: {"cases": {case.id: scorecard._record(case, result)}, "meta": {}}   # noqa: E731

    table = "\n".join(scorecard.summary([case], {case.id: skip}, set()))
    assert table.splitlines()[-1].split()[1:] == ["1", "0", "0", "0", "0", "0", "0", "0", "0", "1", "0"]
    assert scorecard.compare([case], {case.id: skip}, record(passed), True)["skipped"] == [case]
    assert scorecard.compare([case], {case.id: passed}, record(skip), True)["judged"] == [case]
    assert not any(scorecard.compare([case], {case.id: skip}, record(skip), True).values())



# --- the audit's Chinese mode (Chinese_Build_Spec.md §6): built and tested here, run by hand ------------------- #
def _zh_corpus(root):
    """A two-source corpus in the shape of docs/assets/corpora/zh/_text: Tatoeba lines and Leipzig's (counts only)."""
    for source, lines in (("tatoeba", ["我们一起吃了一碗饭。", "大家都开开心心的。", "他今年二十五岁。"]),
                          ("leipzig_news", ["这个问题很重要。", "我们学校有三千五百个学生。"])):
        folder = root / source
        folder.mkdir(parents=True)
        (folder / "lines.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_chinese_audit_samples_general_text_per_source_and_shows_every_token(tmp_path):
    import types
    from tests.parsing import audit
    _zh_corpus(tmp_path / "corpus")
    out = tmp_path / "audit"
    audit.sample(types.SimpleNamespace(lang="zh", source=str(tmp_path / "corpus"), out=str(out), n=4, batches=2,
                                       canaries=1, seed=7))
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    randoms = [item for item in key["items"].values() if item["kind"] == "random"]
    canaries = [item for item in key["items"].values() if item["kind"] == "canary"]
    assert key["lang"] == "zh" and key["library_sentences"] == 5
    assert {item["source"] for item in randoms} == {"tatoeba", "leipzig_news"}, "an equal share per source"
    assert canaries and all(item["case"].startswith("ZH-") for item in canaries)
    parses = {item["text"]: item["parse"] for item in randoms}
    batch = (out / "batch_1.md").read_text(encoding="utf-8")
    assert "Chinese linguist" in batch and "Japanese" not in batch
    for text, parse in parses.items():
        if text == "大家都开开心心的。":
            assert "开开心心【开心】" in parse          # a doubled form is shown at its word
        if text == "我们一起吃了一碗饭。":
            assert "一⊘" in parse and "碗【碗】" in parse    # a number is not counted


def test_the_chinese_audit_locks_verified_lines_but_never_leipzigs(tmp_path, monkeypatch):
    import types
    from tests.parsing import audit
    _zh_corpus(tmp_path / "corpus")
    out = tmp_path / "audit"
    audit.sample(types.SimpleNamespace(lang="zh", source=str(tmp_path / "corpus"), out=str(out), n=6, batches=1,
                                       canaries=0, seed=7))
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    (out / "review_1.jsonl").write_text("\n".join(json.dumps({"id": sid, "ok": True}) for sid in key["items"]),
                                        encoding="utf-8")
    ordinary = tmp_path / "cases_zh_ordinary.py"
    monkeypatch.setattr(audit, "ORDINARY_ZH", str(ordinary))
    audit.lock(types.SimpleNamespace(lang="zh", out=str(out)))
    written = ordinary.read_text(encoding="utf-8")
    namespace = {}
    exec(compile(written, str(ordinary), "exec"), namespace)
    cases = namespace["CASES"]
    assert [case.id for case in cases] == ["ZH-ORD-001", "ZH-ORD-002", "ZH-ORD-003"]
    assert all(case.source == "corpus: tatoeba (CC BY 2.0 FR)" and case.layer == "tokens_zh" for case in cases)
    ctx = harness.Context(str(tmp_path / "scratch"))
    harness.load_evaluators()
    assert all(harness.evaluate(case, ctx).verdict == "pass" for case in cases), "each locked line passes as written"
