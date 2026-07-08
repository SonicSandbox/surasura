"""Raw .epub / .html dropped straight into a content folder must be IGNORED by the analyzer.
Ebooks and web pages are expected to go through the content importer (which converts and chunks
them into normalized .txt). This guards against the analyzer scanning them directly and leaking
their words — or raw ZIP/markup bytes — into the frequency list.
"""
import os
import sys
import shutil
import tempfile

import pytest
import pandas as pd

from app import analyzer


@pytest.fixture
def ja_env():
    temp = tempfile.mkdtemp()
    data_dir = os.path.join(temp, "data", "ja")
    for bucket in ("HighPriority", "LowPriority", "GoalContent"):
        os.makedirs(os.path.join(data_dir, bucket))
    uf = os.path.join(temp, "User Files", "ja")
    os.makedirs(uf)
    with open(os.path.join(uf, "KnownWord.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        open(os.path.join(uf, name), "w", encoding="utf-8").close()
    results = os.path.join(temp, "results")
    os.makedirs(results)

    analyzer.get_data_path = lambda lang=None: data_dir
    analyzer.get_user_files_path = lambda lang=None: uf
    analyzer.RESULTS_DIR = results
    analyzer.OUTPUT_CSV = os.path.join(results, "priority_learning_list.csv")
    analyzer.OUTPUT_STATS = os.path.join(results, "file_statistics.txt")
    analyzer.OUTPUT_PROGRESSIVE = os.path.join(results, "progressive_learning_list.csv")
    yield {"data": data_dir, "results": results}
    shutil.rmtree(temp, ignore_errors=True)


def _write_epub(path, sentence):
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("surasura-ignore-test")
    book.set_title("本")
    book.set_language("ja")
    ch = epub.EpubHtml(title="c", file_name="c.xhtml", lang="ja")
    ch.content = f"<html><body><p>{sentence}</p></body></html>"
    book.add_item(ch)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.toc = (ch,)
    book.spine = ["nav", ch]
    epub.write_epub(path, book)


def test_epub_and_html_in_content_folder_are_ignored(ja_env):
    pytest.importorskip("ebooklib")  # epub construction needs it; it's a shipped dependency
    hp = os.path.join(ja_env["data"], "HighPriority")

    # A normal .txt IS analyzed (marker word: 電車, which appears nowhere else).
    with open(os.path.join(hp, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("電車に乗って学校へ行く。\n")

    # Raw .html and .epub carry their own distinct marker words that must NOT surface.
    with open(os.path.join(hp, "page.html"), "w", encoding="utf-8") as f:
        f.write("<html><body><p>美術館で絵を見る。</p></body></html>")
    _write_epub(os.path.join(hp, "book.epub"), "図書館で本を読む。")

    sys.argv = ["analyzer.py", "--language", "ja", "--min-freq", "1",
                "--context-min", "0", "--target-coverage", "100"]
    analyzer.main()

    df = pd.read_csv(os.path.join(ja_env["results"], "priority_learning_list.csv"))
    words = set(df["Word"].tolist())

    assert "電車" in words, "the .txt content should be analyzed"
    assert "美術館" not in words, "the raw .html file must be ignored (it should go through the importer)"
    assert "図書館" not in words, "the raw .epub file must be ignored (it should go through the importer)"
