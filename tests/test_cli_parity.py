"""The command line and the window agree (P0.3 03; P1.2 rows 1.2.2 and 1.2.6): one argv builder (`app/run_args.py`),
so a headless Generate and the window's hash to the same run signature and skip each other's finished run; and
`junban --dry-run` previews exactly what the 順 window's preview shows.

What a wrong answer would cost: a command-line Generate that hashes differently re-runs the whole analysis every time
the window and Connect take turns (minutes each), and a dry run that disagrees with the window's preview makes Connect
plan a reorder the user never saw.
"""
import os
import queue
from types import SimpleNamespace

import pytest

from app import analyzer, run_args, settings_manager
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.test_settings_signatures import _argv as window_argv

VARIANTS = [
    {},
    {"strategy": "coverage", "target_coverage": 85},
    {"exclude_single": False, "only_i_plus_one": True, "ensure_audio_example": True},
    {"logic": {"context": {"min_chars": 6, "preferred_max_chars": 70, "max_contexts": 5}}},
    {"open_app_mode": True, "theme": "Zen Mode", "zen_limit": 30},          # presentation only: never in the hash
    {"target_language": "zh", "zh_script": "t"},
]


@pytest.mark.parametrize("values", VARIANTS, ids=["defaults", "coverage", "switches", "context", "presentation",
                                                  "chinese, traditional"])
def test_the_window_and_the_command_line_hash_the_same_run(values):
    lang = values.get("target_language", "ja")
    h.seed_library(lang, templates=False)
    h.write_settings(**values)
    loaded = settings_manager.load_settings()
    window, headless = window_argv(lang), run_args.analyzer_args(loaded, lang, headless=True)
    assert "--no-open" in headless and "--app-mode" not in headless, "nothing opens on the desktop"
    found = analyzer.resolve_found_files(lang, verbose=False)
    assert found
    sign = lambda argv: analyzer.compute_run_signature(lang, found, analyzer.parse_analysis_args(argv[1:]))
    assert sign(window) == sign(headless) is not None
    # the builder is the window's own: without `headless` it gives the window's argv exactly
    assert run_args.analyzer_args(loaded, lang) == window


def test_a_setting_that_changes_the_analysis_changes_the_hash_for_both():
    """The parity is not two builders ignoring the same thing: a real change moves both hashes."""
    h.seed_library("ja", templates=False)
    h.write_settings()
    found = analyzer.resolve_found_files("ja", verbose=False)
    sign = lambda argv: analyzer.compute_run_signature("ja", found, analyzer.parse_analysis_args(argv[1:]))
    before = sign(run_args.analyzer_args(settings_manager.load_settings(), "ja", headless=True))
    h.write_settings(only_i_plus_one=True)
    after_cli = sign(run_args.analyzer_args(settings_manager.load_settings(), "ja", headless=True))
    assert before != after_cli == sign(window_argv("ja"))


def test_a_headless_generate_is_skipped_by_the_windows_check_and_the_windows_by_the_command_line(monkeypatch):
    """End to end: `generate` runs once; the window's own "would Generate compute anything?" then says no, and so
    does a second `generate` (`ran: false`)."""
    from app.main import journey_is_current
    h.seed_library("ja")
    h.write_settings()
    code, lines = h.run_cli("generate")
    assert code == 0 and h.answer(lines)["ran"] is True
    assert journey_is_current(window_argv("ja"), "ja") is True
    code, lines = h.run_cli("generate")
    assert code == 0 and h.answer(lines)["ran"] is False


# --------------------------------------------------------------------------- #
# junban --dry-run = the 順 window's preview
# --------------------------------------------------------------------------- #
FAKE_URL = "http://127.0.0.1:18765"         # nothing listens here: only the patched transport answers


@pytest.fixture
def junban_backlog(monkeypatch):
    """The Junban suite's own fake collection (real Japanese words, a list in the results) and saved settings."""
    rep = pytest.importorskip("modules.junban.tests.test_reposition")
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    rep._results(h.root(), progressive=rep._JOURNEY, library=rep._LIBRARY, floor=11)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    cards, notes, _ = rep._collection(["須藤", "散歩", "図書館", "冒険"])
    fake = rep.FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi"))
    saved = rep._settings(junban_order="content", enable_junban=True)
    saved.pop("junban_url", None)
    h.write_settings(**{**saved, "anki_connect_url": FAKE_URL})
    return SimpleNamespace(fake=fake, patched=rep._patched)


def test_the_command_lines_dry_run_is_the_windows_preview(junban_backlog):
    gui = pytest.importorskip("modules.junban.gui")
    with junban_backlog.patched(junban_backlog.fake):
        code, line = h.call("junban", "--dry-run")
        # the window's own worker, on the settings it opens with (saved + the language)
        window = SimpleNamespace(q=queue.Queue(), _is_list_current=lambda args, lang: True,
                                 _context_counts=lambda settings, decks: {})
        settings = dict(settings_manager.load_settings(), target_language="ja")
        gui.JunbanGui._preview_worker(window, settings, "key")
    tag, stats, checks, _key = window.q.get_nowait()
    assert tag == "__PREVIEW__" and checks["ok"], checks
    assert code == 0, line
    assert line["moves"] == stats["to_write"] > 0
    assert line["not_on_list"] == stats["unmatched"]
    assert line["undo"] is None
    assert junban_backlog.fake.writes == [], "a dry run writes nothing"
