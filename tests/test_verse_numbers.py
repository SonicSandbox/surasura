"""Example sentences lose a leading verse number — never a counted number (ENGINE_REVISION 12).

A scripture-style book in the user's library numbers every verse (「13そこでモーサヤは…」), and 376 of
their 11,199 example sentences (3.4%) began with one — on the report, and on any card Junban adds a
sentence to. The number is cut only when what follows is not what it counts: 「3人で」「2つ目」
「5番目」「10年前」「12月」「100万円」「2、3日」 keep theirs. The three golden-list sentences that
begin with a digit (「１人で…」「５つ子…」) must come out exactly as before.

The sentences are the user's own (Alma, Ether, Moroni) and real everyday Japanese.
"""
import os
import shutil
import sys
import tempfile

import pandas as pd
import pytest

from app import analyzer


@pytest.fixture(scope="module")
def tagger():
    import fugashi
    return fugashi.Tagger()


@pytest.mark.parametrize("raw, shown", [
    ("13そこでモーサヤは、主に命じられたとおりにした。", "そこでモーサヤは、主に命じられたとおりにした。"),
    ("6さて、わたしモロナイはこれらのことについて少々述べたい。", "さて、わたしモロナイはこれらのことについて少々述べたい。"),
    ("19キシはコロムの息子であり、", "キシはコロムの息子であり、"),
    ("29わたしモロナイは、これらの御言葉を聞くと慰めを得て言った。", "わたしモロナイは、これらの御言葉を聞くと慰めを得て言った。"),
    ("１２そこで彼らは荒れ野へ退いた。", "そこで彼らは荒れ野へ退いた。"),
    ("18見よ、わたしはあなたに言う。", "見よ、わたしはあなたに言う。"),
])
def test_a_verse_number_before_the_sentence_is_dropped(tagger, raw, shown):
    assert analyzer.strip_verse_number(raw, tagger) == shown


@pytest.mark.parametrize("sentence", [
    "3人で行こう。", "10人の兵士が来た。", "2つ目の角を曲がって。", "5番目の部屋だ。", "10年前に会った。",
    "12月になった。", "7時に起きた。", "100万円もするの？", "1日中寝てた。", "2、3日で終わる。",
    "4匹の猫がいる。", "6歳の時だった。", "１人で待ってろ。", "５つ子豆知識！", "そこで彼らは退いた。", "",
])
def test_a_number_that_counts_something_stays(tagger, sentence):
    assert analyzer.strip_verse_number(sentence, tagger) == sentence


@pytest.fixture
def ja_env():
    temp = tempfile.mkdtemp()
    data_dir = os.path.join(temp, "data", "ja")
    for bucket in ("HighPriority", "LowPriority", "GoalContent"):
        os.makedirs(os.path.join(data_dir, bucket))
    user_files = os.path.join(temp, "User Files", "ja")
    os.makedirs(user_files)
    with open(os.path.join(user_files, "KnownWord.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        open(os.path.join(user_files, name), "w", encoding="utf-8").close()
    results = os.path.join(temp, "results")
    os.makedirs(results)

    analyzer.get_data_path = lambda lang=None: data_dir
    analyzer.get_user_files_path = lambda lang=None: user_files
    analyzer.RESULTS_DIR = results
    analyzer.OUTPUT_CSV = os.path.join(results, "priority_learning_list.csv")
    analyzer.OUTPUT_STATS = os.path.join(results, "file_statistics.txt")
    analyzer.OUTPUT_PROGRESSIVE = os.path.join(results, "progressive_learning_list.csv")
    yield {"data": data_dir, "results": results}
    shutil.rmtree(temp, ignore_errors=True)


def test_a_run_shows_the_verse_without_its_number_on_both_lists(ja_env):
    """End to end: the numbered verses of a book and a sentence whose number counts people."""
    with open(os.path.join(ja_env["data"], "HighPriority", "Mosiah_25.txt"), "w", encoding="utf-8") as f:
        f.write("13そこでモーサヤは、主に命じられたとおりにした。\n"
                "14そして彼らは、ゼラヘムラの民と呼ばれた民を発見した。\n"
                "3人で主に祈った。\n")
    sys.argv = ["analyzer.py", "--language", "ja", "--min-freq", "1",
                "--context-min", "0", "--target-coverage", "100"]
    analyzer.main()

    for name in ("priority_learning_list.csv", "progressive_learning_list.csv"):
        df = pd.read_csv(os.path.join(ja_env["results"], name))
        sentences = {str(value) for column in df.columns if column.startswith("Context ")
                     for value in df[column].dropna()}
        assert "そこでモーサヤは、主に命じられたとおりにした。" in sentences, name
        assert "そして彼らは、ゼラヘムラの民と呼ばれた民を発見した。" in sentences, name
        assert "3人で主に祈った。" in sentences, f"{name}: a number that counts stays"
        assert not any(sentence.startswith(("13", "14")) for sentence in sentences), name


# --------------------------------------------------------------------------- #
# A written number is never a verse number (ENGINE_REVISION 36)
# --------------------------------------------------------------------------- #
# 「20,000人が…」 was shown as 「,000人が…」: UniDic cuts 20,000 into 20 / , / 000 and tags the ASCII comma a
# 記号 (and the fullwidth point "．" a noun), neither the 補助記号 that kept 「2、3日」's number — so the first digits
# read as a verse number. The run tags with analyzer.Tagger (it reads ２０ as 20, the text kept as written), Junban's
# backfill may hand a plain fugashi tagger: both must keep the number.

@pytest.fixture(scope="module", params=["fugashi", "analyzer"])
def any_tagger(request):
    if request.param == "analyzer":
        return analyzer.Tagger()
    import fugashi
    return fugashi.Tagger()


@pytest.mark.parametrize("sentence", [
    "20,000人の兵がゼラヘムラに集まった。",       # the reported case: a thousands separator, ASCII
    "20，000人の兵がゼラヘムラに集まった。",       # the same with a fullwidth comma
    "２０，０００人の兵がゼラヘムラに集まった。",   # fullwidth digits and comma
    "2,000年前の話だと言われている。",
    "1,000,000ドルの賞金が懸けられた。",          # two separators
    "20,000の兵が北へ進んだ。",                   # nothing counted after the number: still one number
    "1.5倍の速さで走った。",                      # a decimal point, ASCII
    "１．５倍の速さで走った。",                    # fullwidth: UniDic tags "．" a noun
    "3.14は円周率のはじめの数字だ。",
    "3万人が広場に集まった。",
    "２０００年に生まれた。",
    "1-2を見よ。",                                # a hyphen is a 記号 too
])
def test_a_written_number_at_the_front_stays_whole(any_tagger, sentence):
    assert analyzer.strip_verse_number(sentence, any_tagger) == sentence


@pytest.mark.parametrize("raw, shown", [
    ("13そこでモーサヤは、主に命じられたとおりにした。", "そこでモーサヤは、主に命じられたとおりにした。"),
    ("１２そこで彼らは荒れ野へ退いた。", "そこで彼らは荒れ野へ退いた。"),
    ("2 そこで彼らは主に祈った。", "そこで彼らは主に祈った。"),     # a verse number set off by a space
])
def test_a_verse_number_still_goes_with_either_tagger(any_tagger, raw, shown):
    """The written-number rule looks only at a separator or a point right after the digits: a verse still loses its
    number, whichever tagger reads it."""
    assert analyzer.strip_verse_number(raw, any_tagger) == shown


# A fullwidth space after the number. MeCab skips an ASCII space but tags 「　」 空白, and 空白 kept the number, so
# 「13　そこで…」 stayed whole; and after a fullwidth space UniDic reads 人 as a plain noun ('person'), not a counter —
# so the space is read as none, as an ASCII one is.

@pytest.mark.parametrize("raw, shown", [
    ("13　そこでモーサヤは、主に命じられたとおりにした。", "そこでモーサヤは、主に命じられたとおりにした。"),
    ("１３　そこでモーサヤは、主に命じられたとおりにした。", "そこでモーサヤは、主に命じられたとおりにした。"),
    ("13　　そこで彼らは荒れ野へ退いた。", "そこで彼らは荒れ野へ退いた。"),      # two fullwidth spaces
    ("13 そこで彼らは荒れ野へ退いた。", "そこで彼らは荒れ野へ退いた。"),        # the ASCII space, unchanged
])
def test_a_verse_number_before_a_space_of_either_width_is_dropped(any_tagger, raw, shown):
    assert analyzer.strip_verse_number(raw, any_tagger) == shown


@pytest.mark.parametrize("sentence", [
    "3　人で行こう。",            # 人 after the space is tagged a plain noun: read without the space, it counts
    "３　人で行こう。",
    "10　年前に会った。",
    "２　つ目の角を曲がって。",
    "5　番目の部屋だ。",
    "100　万円もするの？",
    "3 人で行こう。",             # the ASCII space, unchanged
    "13　「そこで」と言った。",    # punctuation after the space still keeps it
    "13　",                        # nothing after the space
])
def test_a_counted_number_before_a_space_of_either_width_stays(any_tagger, sentence):
    assert analyzer.strip_verse_number(sentence, any_tagger) == sentence


def test_a_run_keeps_a_written_number_and_still_drops_the_verse_numbers(ja_env):
    """End to end: a book's numbered verses beside sentences that open with a written number, both widths — the
    Context columns show the verses without their numbers and the written numbers whole."""
    with open(os.path.join(ja_env["data"], "HighPriority", "Alma_2.txt"), "w", encoding="utf-8") as f:
        f.write("13そこでアムリサイ人は、ゼラヘムラの民と戦った。\n"
                "14そして彼らは、その戦いで多くの民を殺した。\n"
                "20,000人の兵がゼラヘムラの丘に集まった。\n"
                "１．５倍の兵がゼラヘムラの丘に集まった。\n")
    sys.argv = ["analyzer.py", "--language", "ja", "--min-freq", "1",
                "--context-min", "0", "--target-coverage", "100"]
    analyzer.main()

    df = pd.read_csv(os.path.join(ja_env["results"], "priority_learning_list.csv"))
    sentences = {str(value) for column in df.columns if column.startswith("Context ")
                 for value in df[column].dropna()}
    assert "そこでアムリサイ人は、ゼラヘムラの民と戦った。" in sentences
    assert "20,000人の兵がゼラヘムラの丘に集まった。" in sentences
    assert "１．５倍の兵がゼラヘムラの丘に集まった。" in sentences
    assert not any(sentence.startswith((",", "．", "13", "14")) for sentence in sentences)
