"""The journey's shown names kept between renders (L2-WASTE, 3.0.19): the word memo (`results/journey_words.json`)
holds each file's shown name (`static_html_generator.shown_name`, LM1a's `episode_names.identity`), so a redraw — a
process of its own, whose `identity` keeps nothing from the last one — reads 20,000 names instead of parsing each
again (1.6–1.8 s profiled of the redraw's 3.3 s journey render at 20,000 files; 0.8 s unprofiled).

What a wrong answer would cost a learner: a file shown under an old name after the reading rule changed (a new build,
a fix to LM1a), or a page that differs when the memo answers (a warm render must be the cold one). Japanese and
Chinese, real show names in the shapes the libraries hold.
"""
import json
import os
import sys

import pytest

from app import build_info, episode_names
from app import journey_render as jr
from tests.test_journey_render_shape import _rows, _stats
from tests.test_journey_render_speed import _all

LANGUAGES = ("ja", "zh")
# Real names as libraries hold them: a release's tags, Japanese and Chinese episode marks, a season, a text's part,
# a special, a YouTube video's [id]
NAMES = {"ja": ["[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].ja.srt", "葬送のフリーレン 第06話.srt",
                "ぼっち・ざ・ろっく！ S01E07.ja.srt", "銀河鉄道の夜_02.txt", "葬送のフリーレン OVA 01.srt",
                "【公式】文化祭の準備 [dQw4w9WgXcQ].ja.srt"],
         "zh": ["夜市人生 第03集.srt", "[Nekomoe] 台北故事 - 04 [1080p].zh.srt", "牛肉面之歌 S02E05.zh.srt",
                "欢迎来到台北_01.txt", "珍珠奶茶 SP 01.srt", "排队的人 [aB3dE5fG7hI].zh.srt"]}


def _page(language, n=6):
    """A list and file statistics naming the first `n` real files."""
    names = NAMES[language][:n]
    rows = _rows(language, n)
    for row in rows:
        row["Source File"] = names[int(row["Sequence"]) - 1]
        for k in [k for k in row if k.startswith("Src ")]:       # a sentence's source: `Show/epNN.srt`
            row[k] = "Show/" + names[int(row[k][len("Show/ep"):-len(".srt")]) - 1]
    stats = _stats(n)
    for e, s in enumerate(stats):
        s["File"] = names[e]
    return rows, stats


def _memo(path, language, key=None):
    return jr.WordMemo(path, *jr.memo_keys(language), jr.names_key() if key is None else key)


def _render(language, page, memo=None):
    return jr.build(language, *page, pitch=jr.Pitch(language), memo=memo)


def _shown(out):
    return [e[2] for e in out.head["eps"]]


@pytest.fixture
def asked(monkeypatch):
    """Every name LM1a's reading is asked for (`episode_names.identity`, kept or not), counted — and each render a new
    process: its cache emptied first."""
    got = []
    real = episode_names.identity
    real.cache_clear()
    monkeypatch.setattr(episode_names, "identity", lambda *a, **k: got.append(a[0]) or real(*a, **k))
    yield got
    real.cache_clear()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_warm_render_reads_every_files_shown_name_from_the_memo_and_is_the_cold_render(language, tmp_path, asked):
    # why: every redraw is a process of its own, so each of its 20,000 files' names was read from nothing again
    path = str(tmp_path / jr.WORD_MEMO)
    page = _page(language)
    plain = _render(language, page)
    assert set(asked) == set(NAMES[language]), "a render with no memo reads every file's name"
    cold_memo = _memo(path, language)
    cold = _render(language, page, cold_memo)
    cold_memo.save()
    assert _all(cold) == _all(plain)
    assert json.load(open(path, encoding="utf-8"))["n"] == dict(zip(NAMES[language], _shown(plain)))
    asked.clear()
    warm = _render(language, page, _memo(path, language))
    assert asked == [], f"a warm render read {len(asked)} names again"
    assert _all(warm) == _all(plain)
    assert _shown(plain)[0] == ("Sousou no Frieren · Ep 5" if language == "ja" else "夜市人生 · Ep 3")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_memo_of_another_reading_rule_a_damaged_one_or_one_unkeyed_reads_the_names_again(language, tmp_path, asked):
    # why: a new build or a fix to LM1a may read a name another way — an old memo's name must never be shown then
    path = str(tmp_path / jr.WORD_MEMO)
    page = _page(language)
    memo = _memo(path, language, key="1:build:an-older-build")
    plain = _render(language, page, memo)
    memo.save()
    for key in ("1:build:this-build", "?"):
        asked.clear()
        again = _render(language, page, _memo(path, language, key=key))
        assert set(asked) == set(NAMES[language]) and _all(again) == _all(plain), key
    unkeyed = _memo(path, language, key="?")        # written while the code's files could not be read
    _render(language, page, unkeyed)
    unkeyed.save()
    asked.clear()
    _render(language, page, _memo(path, language, key="?"))
    assert set(asked) == set(NAMES[language]), "a memo keyed ? is never served"
    memo = _memo(path, language, key="1:build:an-older-build")
    _render(language, page, memo)
    memo.save()
    held = json.load(open(path, encoding="utf-8"))
    held["n"] = {name: 5 for name in held["n"]}         # not a name: read again, never shown
    with open(path, "w", encoding="utf-8") as f:
        json.dump(held, f)
    asked.clear()
    assert _all(_render(language, page, _memo(path, language, key="1:build:an-older-build"))) == _all(plain)
    assert set(asked) == set(NAMES[language])
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"v": 1, "n_key": ')                   # cut mid-write
    assert _all(_render(language, page, _memo(path, language, key="1:build:an-older-build"))) == _all(plain)


@pytest.mark.parametrize("language", LANGUAGES)
def test_names_alone_new_to_the_memo_are_saved(language, tmp_path, asked):
    # why: a page whose words the memo already holds but whose names it lacks (a memo from before L2-WASTE) must
    # still keep its names, or every redraw reads them again
    path = str(tmp_path / jr.WORD_MEMO)
    page = _page(language)
    memo = _memo(path, language)
    _render(language, page, memo)
    memo.save()
    held = json.load(open(path, encoding="utf-8"))
    held["n"] = {}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(held, f, ensure_ascii=False)
    names_only = _memo(path, language)
    _render(language, page, names_only)
    names_only.save()
    asked.clear()
    _render(language, page, _memo(path, language))
    assert asked == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_memo_keeps_only_this_pages_names_and_a_new_file_is_read_once(language, tmp_path, asked):
    # why: a file gone from the list leaves the memo (20,000 names a page, never every name ever seen); a file come
    # in is the one name read
    path = str(tmp_path / jr.WORD_MEMO)
    memo = _memo(path, language)
    _render(language, _page(language, 4), memo)
    memo.save()
    asked.clear()
    more = _memo(path, language)
    _render(language, _page(language, 5), more)
    more.save()
    assert asked == [NAMES[language][4]]
    fewer = _memo(path, language)
    _render(language, _page(language, 2), fewer)
    fewer.save()
    assert sorted(json.load(open(path, encoding="utf-8"))["n"]) == sorted(NAMES[language][:2])


def test_an_empty_library_keeps_no_names_reads_none_and_makes_a_valid_page(tmp_path, asked):
    for language in LANGUAGES:
        memo = _memo(str(tmp_path / f"{language}.json"), language)
        out = jr.build(language, [], [], pitch=jr.Pitch(language, kanjium={}), memo=memo)
        memo.save()
        assert out.head["eps"] == [] and asked == []
        assert not (tmp_path / f"{language}.json").exists()      # nothing to keep: nothing written


def test_the_names_key_is_the_reading_codes_own_a_freezes_build_or_the_source_files(tmp_path, monkeypatch):
    # why: the memo may answer only while the code that reads a name is the code that wrote it
    key = jr.names_key()
    assert key.startswith(f"{jr.MEMO_FORMAT}:") and key.count("|") == 2 and "?" not in key
    assert jr.names_key() == key, "the same code, the same key"
    rule = tmp_path / "episode_names.py"
    rule.write_text("# LM1a, as it was\n", encoding="utf-8")
    monkeypatch.setattr(episode_names, "__file__", str(rule))
    before = jr.names_key()
    rule.write_text("# LM1a, as it is!\n", encoding="utf-8")       # the same size, written later
    st = os.stat(rule)
    os.utime(rule, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    assert jr.names_key() != before, "a changed rule file is another key, its size the same"
    monkeypatch.setattr(episode_names, "__file__", str(tmp_path / "gone.py"))
    assert jr.names_key() == "?", "a rule file that can't be read keys nothing"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(build_info, "BUILD_ID", "20261124-a1b2c3")
    assert jr.names_key() == f"{jr.MEMO_FORMAT}:build:20261124-a1b2c3"
    monkeypatch.setattr(build_info, "BUILD_ID", None)
    assert jr.names_key() == "?", "a freeze with no build id keys nothing"
    assert os.path.exists(episode_names.__spec__.origin)
