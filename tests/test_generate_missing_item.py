"""A missing item keeps counting in Generate (E2.2, RUNBOOK K2; L2.2 05 §5.10, 9b "until he chooses it keeps counting").

Why this matters: the token store keeps a missing item's tokens counted (the indexer hands it the library store's
counted list, a missing item included), so the Rarity slider and automatic rarity count it. Generate must count the same
library — read the missing file from its cached tokens — or the cut-off the slider shows and the list Generate writes
come from two different libraries. A missing file's list, sentences and journey are what they were while it was there;
Generate keeps its row (it is listed), and the journey checks list it too, so a Generate is current afterwards.
Real Japanese and Chinese text from the samples, in a library store under the test root.
"""

import os
import subprocess
import sys

import pytest

from tests.plan_file_cases import child_env
from tests.test_library_store_support import LANGUAGES
from tests.test_token_store_kept import _library

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPARED = ("priority_learning_list.csv", "progressive_learning_list.csv")


def _generate(root, language):
    cmd = [sys.executable, os.path.join(REPO, "app", "analyzer.py"), f"--language={language}", "--static", "--no-open"]
    p = subprocess.run(cmd, cwd=REPO, env=child_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language", language],
                   cwd=REPO, env=child_env(root), capture_output=True)
    out = {}
    for name in COMPARED:
        with open(os.path.join(root, "results", name), "rb") as f:
            out[name] = f.read()
    return out


def _child(root, code):
    """The last line `code` prints in a process with Generate's environment (its token store, its library store)."""
    p = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=child_env(root), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-500:]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_missing_item_keeps_counting_in_generate(language):
    """A NOW file gone from the disk (the library store marks it missing): the next Generate writes the same lists as
    while it was there, from its cached tokens; the token store still holds it counted; and the journey reads current
    after that Generate (the checks list the missing file as Generate does)."""
    root = os.environ["SURASURA_TEST_ROOT"]
    store, data_dir, ids = _library(language)
    now1, now2, *_rest = list(ids)
    store.close()
    present = _generate(root, language)

    os.remove(now2)                                                    # gone from the disk: a missing item
    from app import library_store as ls
    store = ls.open_store(language, data_dir, os.path.join(root, "User Files", language))
    store.sync_disk()
    store.close()
    missing = _generate(root, language)

    assert missing == present, "the missing file's words, sentences and places still count"
    held = _child(root, f"from app import token_index as ti; s = ti.open_store('{language}'); "
                        f"print(ti._norm({now2!r}) in s.counted_files())")
    assert held == "True", "Generate keeps the missing file's row: it listed it"
    current = _child(root, "from app import analyzer; print(analyzer.journey_check("
                           f"['analyzer.py', '--language={language}', '--static', '--no-open'], '{language}'))")
    assert current == "True", "the journey checks list the missing file as Generate did"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_missing_file_is_kept_only_from_the_library_store_schedule(language):
    """A scheduled file gone from the disk is kept under missing=True only when the schedule came from the library
    store (`schedule=`). From a plain master_manifest.json (JSON mode, no store) it is skipped as before, missing or
    not — there is no store that says the user keeps it, so nothing may count it."""
    import json
    from app import analyzer

    data_dir = analyzer.get_data_path(language)
    user_dir = analyzer.get_user_files_path(language)
    os.makedirs(os.path.join(data_dir, "HighPriority"), exist_ok=True)
    os.makedirs(user_dir, exist_ok=True)
    text = {"ja": "今日は天気がいいので、友達と公園へ散歩に行きました。",
            "zh": "今天天气很好，我和朋友去公园散步了。"}[language]
    with open(os.path.join(data_dir, "HighPriority", "a.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    schedule = {"PHASE_1_NOW": [{"physical_path": "HighPriority/a.txt"},
                                {"physical_path": "HighPriority/gone.txt"}],
                "PHASE_2_SOON": [], "PHASE_3_LATER": []}
    with open(os.path.join(user_dir, "master_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"schedule": schedule}, f, ensure_ascii=False)

    def names(found):
        return [os.path.basename(path) for path, *_rest in found]

    json_mode = analyzer.resolve_found_files(language, verbose=False, read_store=False, missing=True)
    assert names(json_mode) == ["a.txt"], "JSON mode skips the missing file even with missing=True"
    store_mode = analyzer.resolve_found_files(language, verbose=False, schedule=schedule, missing=True)
    assert names(store_mode) == ["a.txt", "gone.txt"], "the library store's schedule keeps the missing file"
    not_asked = analyzer.resolve_found_files(language, verbose=False, schedule=schedule)
    assert names(not_asked) == ["a.txt"], "without missing=True a store-scheduled missing file is still skipped"


@pytest.mark.parametrize("language", LANGUAGES)
def test_cancellable_tokenizer_keeps_read_text_and_tokenize_text(language, monkeypatch):
    """With --progress-json on, the cancel point wrapper keeps the real tokenizer's `read_text` and `tokenize_text`:
    a kept file, or a missing one read back from its kept text, is read through them. It never passes `pool_spec`,
    because a pool's workers would run with no cancel point."""
    from app import analyzer, token_index as ti
    monkeypatch.setitem(analyzer._PROGRESS, "on", True)    # the flag --progress-json sets
    base = ti.make_tokenizer(language)
    wrapped = analyzer._cancellable(base)
    assert wrapped.read_text is base.read_text, "a kept file is read through the same reader"
    assert wrapped.tokenize_text is base.tokenize_text, "a kept file's text is tokenized the same way"
    assert not hasattr(wrapped, "pool_spec"), "a pool would pass no cancel point"
