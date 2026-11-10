# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview under a Chinese `zh_script` (WP-Z5).

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md §4 (youtube_downloader row).

The preview scores a video against the library's cached frequency map, which the analyzer wrote in
the library's script. The video therefore has to be tokenized in that same script, and known words
and lists read in it, or every word of a Traditional video would look new against a library read
as Simplified. A deep link from the video's own sentence must still point at the transcript's own
wording.

Hermetic: the user-files folder is a temp dir and the source map is stubbed. Nothing reads the
developer's library (testing.md §5.1).
"""
import json

import pytest

from modules.youtube_downloader import preview as pv


@pytest.fixture
def user_files(tmp_path, monkeypatch):
    uf = tmp_path / "User Files" / "zh"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(json.dumps(
        {"words": [{"dictForm": "學習", "knownStatus": "KNOWN"}]}, ensure_ascii=False), encoding="utf-8")
    (uf / "IgnoreList.txt").write_text("東西\n", encoding="utf-8")
    monkeypatch.setattr(pv, "get_user_files_path", lambda language: str(uf))
    # _build_tokenizer_and_known sets the analyzer's run globals, as a full run would; put them back.
    monkeypatch.setattr(pv.az, "SANITIZE_JA", pv.az.SANITIZE_JA)
    monkeypatch.setattr(pv.az, "SKIP_SINGLE_CHARS", pv.az.SKIP_SINGLE_CHARS)
    return uf


def test_known_words_and_lists_are_read_in_the_librarys_script(user_files):
    tok, _tuples, lemmas, ignore = pv._build_tokenizer_and_known(
        "zh", {"target_language": "zh", "zh_script": "s"})
    assert tok.script == "s"
    assert "学习" in lemmas and "學習" not in lemmas
    assert ignore == {"东西"}


def test_as_is_reads_everything_as_written(user_files):
    """No zh_script in settings.json — every existing install."""
    tok, _tuples, lemmas, ignore = pv._build_tokenizer_and_known("zh", {"target_language": "zh"})
    assert tok.script == "asis"
    assert "學習" in lemmas and ignore == {"東西"}


def test_an_ignored_entry_in_the_known_words_file_is_ignored_in_the_librarys_script(user_files):
    """KnownWord.json's IGNORED entries (Migaku's status) are ignored words, as Generate reads them — so a
    video's words are scored against the same list (the user, 2026-09-29)."""
    (user_files / "KnownWord.json").write_text(json.dumps({"words": [
        {"dictForm": "學習", "knownStatus": "KNOWN"}, {"dictForm": "電腦", "knownStatus": "IGNORED"}]},
        ensure_ascii=False), encoding="utf-8")
    _tok, _tuples, lemmas, ignore = pv._build_tokenizer_and_known("zh", {"target_language": "zh", "zh_script": "s"})
    assert ignore == {"东西", "电脑"} and "电脑" not in lemmas


def test_the_videos_own_sentence_links_to_the_transcripts_wording(tmp_path, monkeypatch):
    """The preview's sentence is converted text; the ▶ link needs the transcript's own words."""
    transcript = tmp_path / "vid [abcdefghijk].txt"
    transcript.write_text("我們每天都在學習新的東西。\n", encoding="utf-8")
    monkeypatch.setattr("app.static_html_generator._load_source_map", lambda: {})
    words = [{"Word": "学习", "Context 1": "我们每天都在学习新的东西。", "Src 1": pv.VIDEO_SOURCE}]
    settings = {"target_language": "zh", "zh_script": "s", "source_display": "icon"}

    pv._resolve_preview_sources([(transcript.name, words, str(transcript))], settings)
    frag = words[0].get("Frag 1")
    assert frag and frag in "我們每天都在學習新的東西。"
