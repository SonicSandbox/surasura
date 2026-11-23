"""The journey's cut-over to v3 (J-CUT; journey v3 SPEC §7, §8): Generate writes the v3 page — J-DATA's data
(`journey_render.render`) in J-PAGE's page (`templates/journey/`, its Stepper rail inlined) — into the journey's own file
(`reading_list_static.html`), the door is on, and the render signature carries what the new page reads.

  * a Generate (every theme but Zen) writes the v3 page: its head and chunks, the rail's own code, no marker left, none
    of the old page's data; Zen still writes its own page from the old data;
  * the page's episodes are the library's, in the study order, each with *% known* from THIS Generate (the growth
    snapshot is written before the journey is drawn, as the redraw does), and *Journey ↗ on an episode* finds it;
  * the run's own fugashi tagger is handed to the render (speed row 1: the pitch makes no second one);
  * the render signature: an older (pre-cut) one never matches, so the first Generate after the update draws the new
    page; *Meanings*, the learner's own dictionaries (while Yours is asked) and the page's files re-render it, never a
    re-analysis; SURASURA_DOOR=0 is the pre-cut world (no v3 part);
  * an empty results folder still writes a page (the page's own empty state), never an error.

What a wrong answer would cost a learner: the old page on the day of the release (or a page with no data), a journey
that shows last Generate's *% known*, *Journey ↗* on an episode opening somewhere else, a theme switch that changes
nothing, or a second dictionary load at every Generate. Japanese and Chinese, real text from the bundled samples, each
test under its own SURASURA_TEST_ROOT.
"""
import gzip
import base64
import json
import os
import re
import subprocess
import sys
from unittest.mock import patch

import pytest

from app import analyzer
from app import library_store as ls
from app import static_html_generator as gen
from app.services import journey_door
from tests.plan_file_cases import child_env
from tests.test_journey_stones import REPO, _library
from tests.test_library_store_support import LANGUAGES, roots

HEAD = re.compile(r'<script type="application/json" id="j-head">(.*?)</script>', re.S)


def _page(root):
    with open(os.path.join(root, "results", "reading_list_static.html"), encoding="utf-8") as f:
        return f.read()


def _head(html):
    return json.loads(HEAD.search(html).group(1))


def _chunk_words(html):
    """Every word the page's chunks hold (the chunk JSON's `w` rows' first cell)."""
    words = []
    for blob in re.findall(r'<script type="application/gzip-base64" id="j-c\d+">(.*?)</script>', html):
        chunk = json.loads(gzip.decompress(base64.b64decode(blob)).decode("utf-8"))
        words += [w[0] for w in chunk.get("w", chunk.get("words", []))]
    return words


def ARGS(language):
    return ["analyzer.py", f"--language={language}", "--static", "--no-open", "--min-freq", "1"]


def _as_the_child(monkeypatch, root):
    """This process reads the data folders the child Generate wrote — its token store above all (the recorded
    signature): the child keeps it under `<root>/index` (SURASURA_TEST_ROOT), where conftest's `_isolate_token_store`
    points this process elsewhere, so it is pointed back, as `test_journey_stones_quiet` does."""
    from app import token_index
    env = child_env(root)
    for key in ("APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(key, env[key])
    monkeypatch.setattr(token_index, "store_path_for", lambda lang: os.path.join(root, "index", f"token_store_{lang}.db"))


@pytest.fixture(autouse=True)
def _no_anki_miner(tmp_path, monkeypatch):
    # The learner's own Anki Miner folder is never read here: an empty one of the test's (a test makes its files)
    monkeypatch.setenv("ANKI_MINER_HOME", str(tmp_path / "anki_miner"))


def _generate(root, language, *args, env=None):
    cmd = [sys.executable, os.path.join(REPO, "app", "analyzer.py"), f"--language={language}", "--static",
           "--no-open", "--min-freq", "1", *args]
    p = subprocess.run(cmd, cwd=REPO, env=env or child_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    return p.stdout


# --- the switch -------------------------------------------------------------------------------------------------- #

def test_the_page_its_settings_and_the_door_turn_on_together_and_off_together_for_a_run(monkeypatch):
    # One switch (journey_door.ON), read by the generator through journey_settings.v3(): never a page without its door
    from app.services import journey_settings
    monkeypatch.delenv(journey_door.ENV, raising=False)
    assert gen.journey_v3() and journey_settings.v3() and journey_door.enabled()
    monkeypatch.setenv(journey_door.ENV, "0")
    assert not gen.journey_v3() and not journey_settings.v3() and not journey_door.enabled()


def test_the_template_has_its_rail_inlined_once_and_its_data_marker_left_for_the_render():
    from app import journey_render
    page = gen.journey_template()
    with open(os.path.join(REPO, "templates", "journey", "rail-stepper.js"), encoding="utf-8") as f:
        rail = f.read()
    assert gen.RAIL_MARK not in page and rail in page and page.count(journey_render.MARKER) == 1


# --- a Generate writes the v3 page --------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_generate_writes_the_v3_page_with_the_librarys_episodes_and_this_generates_known(language, monkeypatch):
    store, ids, names = _library(language)
    store.close()
    root = os.environ["SURASURA_TEST_ROOT"]
    said = _generate(root, language)
    assert "Writing the journey (v3)" in said
    html = _page(root)
    assert "let globalData" not in html and "<!--JOURNEY-" not in html, "the v3 page, every marker filled"
    head = _head(html)
    assert head["lang"] == language and head["v"] == 1
    order = ["A1", "A2", "A3", "B1", "B2", "B3"]
    assert [e[0] for e in head["eps"][:6]] == [ids[k] for k in order], "the study order, by the store's item id"
    assert [e[1] for e in head["eps"][:6]] == [names[k] for k in order], "each named as #file= names it"
    # *% known* is this Generate's: on a library's first Generate there is no older snapshot to show
    assert all(isinstance(e[6], (int, float)) for e in head["eps"][:6]), [e[6] for e in head["eps"][:6]]
    store = ls.open_store(language, *roots(language))
    try:
        last = store.growth_of([ids[k] for k in order], kinds=("last",))
    finally:
        store.close()
    from app.services.view_rows import pct_of
    for e in head["eps"][:6]:
        snap = last[e[0]]["last"]
        assert e[6] == round(pct_of(snap["known"], snap["counted"]), 1)
    assert _chunk_words(html), "the words are in the chunks"
    # *Journey ↗ on an episode* (the window's `open_journey`): the page holds it, by the name `#file=` matches
    with patch.object(gen, "get_user_file", lambda name: os.path.join(root, name)):
        assert gen.report_holds(names["B2"]) and not gen.report_holds("第99話.srt")
    # and the run signed what it drew: the report is current, nothing to re-render
    _as_the_child(monkeypatch, root)
    assert analyzer.report_is_current(ARGS(language), language) is True


@pytest.mark.parametrize("language", LANGUAGES)
def test_before_the_cut_the_same_generate_writes_the_old_page_and_signs_without_the_v3_part(language, monkeypatch):
    store, _ids, names = _library(language)
    store.close()
    root = os.environ["SURASURA_TEST_ROOT"]
    _generate(root, language, env=dict(child_env(root), SURASURA_DOOR="0"))
    html = _page(root)
    assert "let globalData = {" in html and 'id="j-head"' not in html
    with patch.object(gen, "get_user_file", lambda name: os.path.join(root, name)):
        assert gen.report_holds(names["A1"]), "the old page's names still read"
    # The update: the signature the pre-cut run recorded never matches the cut-over's, so the first Generate after the
    # update draws the new page (a re-render, never a re-analysis)
    args = ARGS(language)
    _as_the_child(monkeypatch, root)
    monkeypatch.setenv("SURASURA_DOOR", "0")
    assert analyzer.report_is_current(args, language) is True
    monkeypatch.delenv("SURASURA_DOOR")
    assert analyzer.report_is_current(args, language) is False
    said = _generate(root, language)
    assert "Writing the journey (v3)" in said and "Saved progressive" not in said, "re-drawn, not re-analysed"
    assert 'id="j-head"' in _page(root)


def _chunk_records(html):
    """Every word record the page's chunks hold: [word, orth, reading, kana, forms, episode, marks, count ahead, …]."""
    records = []
    for blob in re.findall(r'<script type="application/gzip-base64" id="j-c\d+">(.*?)</script>', html):
        chunk = json.loads(gzip.decompress(base64.b64decode(blob)).decode("utf-8"))
        records += chunk.get("w", chunk.get("words", []))
    return records


def _plan_counts(root, eps):
    """{page episode index: {word: count}} straight from the plan file the Generate wrote (its per-file tables, every
    reading of a word together) — what *its count in the next few episodes* adds up."""
    from app import plan_engine
    from app.path_utils import report_name
    plan = plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE), pools=False)
    at = {report_name(entry[0]): f for f, entry in enumerate(plan.files)}
    out = {}
    for e, ep in enumerate(eps):
        line, counts = plan.per_file[at[ep[1]]], {}
        for table in (line["main"], line["ph"]):
            for k, n in zip(table[0::2], table[1::2]):
                counts[plan.keys[k][0]] = counts.get(plan.keys[k][0], 0) + n
        out[e] = counts
    return out, {k[0] for k in plan.keys if sum(1 for j in plan.keys if j[0] == k[0]) > 1}


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_words_count_ahead_is_its_own_episodes_and_the_next_two_read_from_the_plan_file(language, monkeypatch):
    # The lead's ruling: the plan file is the one source — a count of the word's own episode only is wrong on the page.
    # Drawn after the plan is written, in a Generate and in the reuse path's re-render alike (the redraw: the byte for
    # byte check in test_services_journey).
    store, _ids, _names = _library(language)
    store.close()
    root = os.environ["SURASURA_TEST_ROOT"]
    _generate(root, language)
    html = _page(root)
    eps = _head(html)["eps"]
    per_ep, homographs = _plan_counts(root, eps)
    records = [r for r in _chunk_records(html) if r[0] not in homographs]
    assert records
    for r in records:
        word, e, count = r[0], r[5], r[7]
        assert count == sum(per_ep.get(e + d, {}).get(word, 0) for d in range(3)), (word, e, count)
    assert any(r[7] > per_ep[r[5]].get(r[0], 0) for r in records), "some word comes back in the next two episodes"
    # The reuse path (nothing to analyse, a look the old signature still held): the same counts from the same file
    _generate(root, language, "--theme", "Modern Light")
    assert [r[7] for r in _chunk_records(_page(root)) if r[0] not in homographs] == [r[7] for r in records]


def test_the_journey_reads_only_this_runs_plan_and_none_for_zen_or_before_the_cut(tmp_path, monkeypatch):
    from app import plan_engine
    monkeypatch.delenv("SURASURA_DOOR", raising=False)
    header = {"format": plan_engine.FORMAT, "run_signature": "run-1"}
    seen = []
    monkeypatch.setattr(plan_engine, "load", lambda path, **kw: seen.append(kw) or plan_engine.Plan(
        header, [], [], [], [], []))
    args = analyzer.parse_analysis_args(["--language=ja", "--static", "--no-open"])
    assert analyzer._journey_plan(args, "run-1", str(tmp_path)).header is header
    assert seen == [{"pools": False, "trusted": True}], "the numbers only: the sentence tables stay undecoded"
    assert analyzer._journey_plan(args, "run-2", str(tmp_path)) is None, "another run's plan is never read"
    assert analyzer._journey_plan(args, "", str(tmp_path)) is None
    zen = analyzer.parse_analysis_args(["--language=ja", "--static", "--no-open", "--theme", "Zen Mode"])
    assert analyzer._journey_plan(zen, "run-1", str(tmp_path)) is None
    monkeypatch.setenv("SURASURA_DOOR", "0")
    assert analyzer._journey_plan(args, "run-1", str(tmp_path)) is None
    monkeypatch.delenv("SURASURA_DOOR")
    monkeypatch.setattr(plan_engine, "load", lambda path, **kw: (_ for _ in ()).throw(plan_engine.PlanError("gone")))
    assert analyzer._journey_plan(args, "run-1", str(tmp_path)) is None, "no plan: each word's own episode"


def test_zen_keeps_its_own_page(tmp_path):
    from tests.test_journey_stones import _render
    html = _render(tmp_path, "ja", ["第01話.srt", "第02話.srt"], theme="Zen Mode")
    assert 'id="j-head"' not in html and "let globalData = {" in html and "zen" in html.lower()


def test_an_empty_results_folder_still_writes_the_page_its_empty_state_never_an_error(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    out = results / "reading_list_static.html"
    with patch.object(gen, "RESULTS_DIR", str(results)), \
            patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")), \
            patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
            patch.object(gen, "OUTPUT_FILE", str(out)):
        gen.generate_static_html(theme="default", open_browser=False, language="zh")
    head = _head(out.read_text(encoding="utf-8"))
    assert head["lang"] == "zh" and head["counts"]["words"] == 0


# --- guarantees the old renderer's tests held, held on v3 (J-CUT, the lead's ruling: the coverage table) ---------- #

def _empty_results(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    return results, (patch.object(gen, "RESULTS_DIR", str(results)),
                      patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")),
                      patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")),
                      patch.object(gen, "OUTPUT_FILE", str(results / "reading_list_static.html")))


@pytest.mark.parametrize("open_browser", [False, True])
def test_the_automatic_generate_writes_the_journey_without_opening_it(tmp_path, open_browser):
    # test_html_regression's: a background Generate (--no-open) never pops a browser; a press opens the page it wrote
    results, patches = _empty_results(tmp_path)
    opened = []
    with patches[0], patches[1], patches[2], patches[3], patch.object(gen.webbrowser, "open", opened.append), \
            patch.object(gen, "open_as_app", opened.append):
        gen.generate_static_html(open_browser=open_browser, language="ja")
    assert (results / "reading_list_static.html").exists()
    assert len(opened) == (1 if open_browser else 0)


def test_the_journey_is_signed_with_the_marks_read_before_it_was_drawn_and_an_unread_read_signs_nothing(tmp_path):
    # test_journey_stones' S-1: a mark landing mid-render is the next press's re-render, never a page recorded as
    # current that shows the wrong stones; a read that failed (library_store.UNREAD) signs "" (`signed_render`)
    from app import journey_render
    reads = iter([[("ShowA_ep01.srt", "HighPriority", True, True)], [("ShowA_ep02.srt", "HighPriority", True, True)]])
    real = journey_render.render

    def landing(lang, **kw):
        analyzer.journey_marks(lang)                 # a mark lands while the page is drawn
        return real(lang, **kw)
    results, patches = _empty_results(tmp_path)
    with patches[0], patches[1], patches[2], patches[3], patch.object(analyzer, "journey_marks", lambda _l: next(reads)), \
            patch.object(journey_render, "render", landing):
        drawn = gen.generate_static_html(open_browser=False, language="ja")
    assert drawn == [("ShowA_ep01.srt", "HighPriority", True, True)], "the marks read before the render"
    with patches[0], patches[1], patches[2], patches[3]:
        assert gen.generate_static_html(open_browser=False, language="ja", marks=ls.UNREAD) == ls.UNREAD
    args = analyzer.parse_analysis_args(["--language=ja", "--static", "--no-open"])
    assert analyzer.signed_render(args, ls.UNREAD, True) == ""


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_sentence_or_a_file_name_holding_a_script_close_never_breaks_the_page(language, monkeypatch):
    # test_html_report's: data written into the page can't end its <script> early — the head's JSON (episode names)
    # and the chunks (base64) stay whole, so the page still reads
    store, _ids, names = _library(language)
    store.close()
    root = os.environ["SURASURA_TEST_ROOT"]
    _generate(root, language)
    html = _page(root)
    head = HEAD.search(html).group(1)
    assert "</script" not in head.lower()
    from app import journey_render
    assert journey_render._json({"t": "第1話</script><script>alert(1)</script>"}).count("</") == 0
    assert json.loads(journey_render._json({"t": "</script>"}))["t"] == "</script>", "the text itself unchanged"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_episode_carries_its_shown_name_and_its_file_name_stays_the_key(language):
    # test_journey_names' (Fresh-U 13): each episode shows as its show and episode, `#file=` keeps the file name
    from app.static_html_generator import shown_name
    store, ids, names = _library(language)
    store.close()
    root = os.environ["SURASURA_TEST_ROOT"]
    _generate(root, language)
    eps = _head(_page(root))["eps"]
    assert {e[1] for e in eps[:6]} == set(names.values())
    for e in eps[:6]:
        assert e[2] == shown_name(e[1]) and e[2], (e[1], e[2])


@pytest.mark.parametrize("setting, file", [("anki_backlog_on_generate", None), (None, "anki_backlog.json"),
                                           (None, "junban_pairs.json")])
def test_anki_labels_re_render_the_v3_page_only_while_the_label_is_on(setting, file, tmp_path, monkeypatch):
    # test_anki_backlog_label's: the backlog, Junban's "same word?" answers and the switch re-render (the v3 render
    # reads `anki_backlog_keys`), never re-analyse; with the label off a backlog change draws nothing
    monkeypatch.delenv("SURASURA_DOOR", raising=False)
    user = tmp_path / "User Files" / "ja"
    user.mkdir(parents=True)
    monkeypatch.setattr(analyzer, "get_user_files_path", lambda _lang: str(user))
    plain = _sig()
    if setting:
        assert _sig(**{setting: False}) != plain
        return
    (user / file).write_text(json.dumps({"words": ["勉強"]}, ensure_ascii=False), encoding="utf-8")
    assert _sig() != plain, f"{file}: a re-render"
    assert _sig(anki_backlog_on_generate=False) == _sig(anki_backlog_on_generate=False, words_per_day=9), \
        "label off: nothing read"
    before = _sig(anki_backlog_on_generate=False)
    (user / file).write_text("{}", encoding="utf-8")
    assert _sig(anki_backlog_on_generate=False) == before, "label off: a backlog change draws nothing"


# --- the run's tagger ---------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_render_gets_the_runs_own_tagger_in_japanese_and_none_in_chinese(language, tmp_path):
    from app import journey_render
    seen = []
    real = journey_render.render

    def spy(lang, **kw):
        seen.append(kw.get("tagger"))
        return real(lang, **kw)
    given = object()                             # the run's tagger (the render only hands it on)
    results = tmp_path / "results"
    results.mkdir()
    with patch.object(journey_render, "render", spy), patch.object(gen, "RESULTS_DIR", str(results)), \
            patch.object(gen, "PRIORITY_CSV", str(results / "p.csv")), \
            patch.object(gen, "PROGRESSIVE_CSV", str(results / "q.csv")), \
            patch.object(gen, "OUTPUT_FILE", str(results / "reading_list_static.html")):
        gen.generate_static_html(open_browser=False, language=language, tagger=given)
    assert seen == [given if language == "ja" else None], "the run's tagger in Japanese; none in Chinese"


def test_a_full_generate_hands_its_tokenizers_tagger_to_the_journey():
    # The one place (analyzer.main's static step): the tagger its own tokenizer made, never a second one
    with open(os.path.join(REPO, "app", "analyzer.py"), encoding="utf-8") as f:
        source = f.read()
    step = source[source.index("# --- STATIC GENERATION ---"):source.index("# All outputs are now written")]
    assert 'tagger=tokenizer.tagger if language == "ja" else None' in step
    assert step.index("record_analysed(") < step.index("write_plan_file(") < step.index("generate_static_html("),         "the snapshot, then the plan file, then the journey drawn from both"
    assert "plan=_journey_plan(args, _run_sig)" in step


# --- the render signature's new inputs ----------------------------------------------------------------------------- #

def _sig(language="ja", **settings):
    args = analyzer.parse_analysis_args([f"--language={language}", "--static", "--no-open"])
    with patch.object(analyzer.settings_manager, "load_settings", lambda: dict(settings)):
        return analyzer.compute_render_signature(args, marks=[], made=None)


def test_meanings_re_render_and_a_look_the_page_applies_itself_does_not(monkeypatch):
    monkeypatch.delenv("SURASURA_DOOR", raising=False)
    plain = _sig()
    assert _sig(journey_meanings="yours_en") != plain, "Meanings: the render reads Yours"
    assert _sig(journey_pitch="hidden") == plain and _sig(journey_word_size="l") == plain, \
        "a look the page applies (J-SET's LOOKS), read back through the door: no re-render"
    monkeypatch.setenv("SURASURA_DOOR", "0")
    assert _sig(journey_meanings="yours_en") == _sig(), "before the cut nothing reads Meanings"


def _zsig(theme, **settings):
    args = analyzer.parse_analysis_args(["--language=ja", "--static", "--no-open", f"--theme={theme}"])
    with patch.object(analyzer.settings_manager, "load_settings", lambda: dict(settings)):
        return analyzer.compute_render_signature(args, marks=[], made=None)


@pytest.mark.parametrize("old_option", [
    {"source_display": "full"}, {"words_per_day": 12}, {"show_words_per_day": False}, {"zen_limit": 20},
    {"word_search_enabled": False}, {"word_search_category": "anime"}, {"study_order": "priority"},
    {"enable_koe": True}, {"logic": {"hide_audio_button": True, "inline_completed_files": True, "chunk_size": 20}}])
def test_a_look_change_moves_no_signature_and_zen_in_or_out_does(old_option, monkeypatch):
    # The Redraw rule (the lead's ruling): the v3 page applies its looks itself and reads none of the old page's
    # options, so changing one draws nothing; Zen is its own page (a saved look), so Zen in or out re-renders
    monkeypatch.delenv("SURASURA_DOOR", raising=False)
    plain = _zsig("default")
    assert _zsig("modern-light") == plain and _zsig("midnight-vibrant") == plain, "one look to another"
    assert _zsig("default", **old_option) == plain, f"the old page's {old_option}: nothing on v3 reads it"
    assert _zsig("zen-focus") != plain and _zsig("Zen Mode") != plain, "Zen in (and so out) re-renders"
    assert _zsig("zen-focus", source_display="full") != _zsig("zen-focus"), "a saved Zen look still re-renders on it"
    assert _zsig("default", line_player=False) != plain, "a setting the v3 render reads still re-renders"
    monkeypatch.setenv("SURASURA_DOOR", "0")
    assert _zsig("modern-light") != _zsig("default"), "before the cut the old page drew its theme"


def _anki_miner(home, dict_id="jitendex"):
    os.makedirs(os.path.join(home, "dicts", dict_id), exist_ok=True)
    with open(os.path.join(home, "gui_config.json"), "w", encoding="utf-8") as f:
        json.dump({"dictionary_chain": [{"dict_id": dict_id, "enabled": True}]}, f)
    path = os.path.join(home, "dicts", dict_id, "index.sqlite")
    with open(path, "wb") as f:
        f.write(b"SQLite format 3\x00" + "辞書".encode("utf-8"))
    return path


def test_the_learners_own_dictionaries_re_render_only_while_yours_is_asked(tmp_path, monkeypatch):
    monkeypatch.delenv("SURASURA_DOOR", raising=False)
    home = str(tmp_path / "anki_miner")
    monkeypatch.setenv("ANKI_MINER_HOME", home)
    path = _anki_miner(home)
    english, yours = _sig(), _sig(journey_meanings="yours")
    with open(path, "ab") as f:
        f.write("更新".encode("utf-8"))              # a dictionary updated in Anki Miner
    os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns + 10_000_000))
    assert _sig(journey_meanings="yours") != yours
    assert _sig() == english, "with English, the learner's dictionaries are never read"


def test_the_kanjium_copy_re_renders_japanese_only(tmp_path, monkeypatch):
    monkeypatch.delenv("SURASURA_DOOR", raising=False)
    home = str(tmp_path / "anki_miner")
    monkeypatch.setenv("ANKI_MINER_HOME", home)
    ja, zh = _sig("ja"), _sig("zh")
    copy = os.path.join(home, "pitch", "kanjium-pitch", "source.txt")
    os.makedirs(os.path.dirname(copy))
    with open(copy, "w", encoding="utf-8") as f:
        f.write("日本\tにほん\t2\n")
    assert _sig("ja") != ja and _sig("zh") == zh


def test_a_change_to_the_pages_files_re_renders(tmp_path, monkeypatch):
    monkeypatch.delenv("SURASURA_DOOR", raising=False)
    import shutil
    templates = tmp_path / "templates"
    shutil.copytree(os.path.join(REPO, "templates"), templates)
    monkeypatch.setattr(analyzer, "get_resource", lambda rel: str(tmp_path / rel))
    before = _sig()
    with open(templates / "journey" / "rail-stepper.css", "a", encoding="utf-8") as f:
        f.write("\n/* 次の話 */\n")
    assert _sig() != before
