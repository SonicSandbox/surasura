"""Perf guard: importing the analyzer must NOT eagerly load heavy libraries.

jieba (~0.17s to import) and pandas (~0.35s) are lazy-loaded only when actually tokenizing Chinese
or writing the CSVs. A "nothing changed" Generate skip builds no tokenizer and writes no CSV, so it
imports NEITHER and stays ~0.08s. Also: a Japanese run must never load jieba, and a Chinese run must
never load fugashi. These run in clean subprocesses so a stray top-level `import` regression is caught.
"""

import os
import sys
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _modules_loaded_by(code_that_imports, watch):
    """Return which of `watch` modules are in sys.modules after running the given import snippet."""
    code = (code_that_imports +
            "; import sys; print(','.join(m for m in %r if m in sys.modules))" % (tuple(watch),))
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"subprocess failed:\n{r.stderr}"
    return set(filter(None, r.stdout.strip().split(",")))


def test_importing_analyzer_does_not_load_jieba_or_pandas():
    """The expensive libs must stay unloaded on a bare module import (this is the skip fast-path)."""
    loaded = _modules_loaded_by("import app.analyzer", ["jieba", "pandas"])
    assert loaded == set(), f"importing app.analyzer eagerly loaded heavy libs: {sorted(loaded)}"


def test_japanese_tokenizer_does_not_load_jieba():
    """Building the Japanese tokenizer must not drag in the Chinese segmenter."""
    loaded = _modules_loaded_by(
        "import app.analyzer as a; a.JapaneseTokenizer()", ["jieba"])
    assert loaded == set(), "JapaneseTokenizer must not import jieba"


def test_chinese_tokenizer_does_not_load_fugashi():
    """Building + using the Chinese tokenizer must not drag in the Japanese tokenizer library."""
    loaded = _modules_loaded_by(
        "import app.analyzer as a; t=a.ChineseTokenizer(); list(t.tokenize_sentences('冒险。'))",
        ["fugashi"])
    assert loaded == set(), "ChineseTokenizer must not import fugashi"
