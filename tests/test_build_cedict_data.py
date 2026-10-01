"""scripts/build_cedict_data.py — the CC-CEDICT table the Chinese cut reads (app/cedict_data.py).

Toy inputs built from real CC-CEDICT lines and real treebank shapes, so the tests run anywhere (the dictionary and the
treebanks are a gitignored download). What matters: a line is read the way CC-CEDICT writes it (个's classifier sense
in brackets included), a count is a number + a measure word the treebanks cut after the number, grammar is read where
grammar stands, a number written in pieces is one piece, and the module the build writes decodes back to its table.
"""
import importlib.util

import json
import math
import os
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CEDICT_LINES = """# CC-CEDICT
#! version=1
#! date=2026-09-23T10:00:00Z
一 一 [yi1] /one/single/a (article)/as soon as/entire; whole; all; throughout/
一些 一些 [yi1 xie1] /some; a few; a little; (following an adjective) slightly ...er/
一個 一个 [yi1 ge5] /a; an; one/the whole (afternoon, summer vacation etc)/
一方面 一方面 [yi1 fang1 mian4] /on the one hand/
個 个 [ge4] /(classifier used before a noun that has no specific classifier)/(bound form) individual/
十二月 十二月 [Shi2 er4 yue4] /December/twelfth month (of the lunar year)/
吃飯 吃饭 [chi1 fan4] /to have a meal/to eat/to make a living/
月 月 [yue4] /moon/month/monthly/CL:個|个[ge4],輪|轮[lun2]/
本 本 [ben3] /(bound form) root; stem/classifier for books, periodicals, files etc/
碗 碗 [wan3] /bowl/cup/CL:隻|只[zhi1],個|个[ge4]/
這個 这个 [zhe4 ge5] /(pronoun) this/(adjective) this/
電影 电影 [dian4 ying3] /movie; film/CL:部[bu4]/
開心 开心 [kai1 xin1] /to feel happy/to rejoice/to have a great time/to make fun of sb/
"""


def _script():
    spec = importlib.util.spec_from_file_location("build_cedict_data", os.path.join(ROOT, "scripts",
                                                                                     "build_cedict_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def b():
    return _script()


def test_a_cedict_line_is_read_as_cedict_writes_it(b):
    entries, dated = b.parse_cedict(CEDICT_LINES)
    assert dated == "2026-09-23"
    traditional, pinyin, senses = entries["一个"][0]
    assert (traditional, pinyin) == ("一個", "yi1 ge5")
    assert senses == ["a; an; one", "the whole (afternoon, summer vacation etc)"]
    assert "# CC-CEDICT" not in entries and len(entries["这个"]) == 1


def test_a_classifier_sense_counts_in_brackets_too(b):
    # 个 writes it "(classifier used before a noun …)"; 本 "classifier for books"; 碗 and 月 only name the measure
    # words used WITH them (CL: …), which makes them no classifier.
    entries, _ = b.parse_cedict(CEDICT_LINES)
    assert b.classifier_chars(entries) == {"个", "本"}


def test_the_treebank_counts_whole_and_cut_uses(b, tmp_path):
    ud = tmp_path / "ud"
    ud.mkdir()
    (ud / "toy.conllu").write_text(
        "# text = 我有一个朋友。\n1\t我\t_\n2\t有\t_\n3\t一\t_\n4\t个\t_\n5\t朋友\t_\n6\t。\t_\n\n"
        "# text = 我有一些朋友。\n1\t我\t_\n2\t有\t_\n3\t一些\t_\n4\t朋友\t_\n5\t。\t_\n\n", encoding="utf-8")
    whole, cut = b.ud_number_cuts(str(ud), lambda text: text)
    assert cut["一个"] == 1 and whole["一个"] == 0
    assert whole["一些"] == 1 and cut["一些"] == 0


def test_a_count_is_a_number_and_a_measure_word_the_treebanks_cut(b):
    from collections import Counter
    entries, _ = b.parse_cedict(CEDICT_LINES + "一下 一下 [yi1 xia4] /(used after a verb) give it a go/\n")
    tags = {"个": "q", "下": "q", "方面": "n", "月": "m", "些": "q"}
    whole = Counter({"一些": 82, "一下": 8})
    cut = Counter({"一个": 342, "一方面": 9, "十二月": 2, "一下": 1})
    units = b.numeral_units(entries, whole, cut, tags, b.classifier_chars(entries))
    assert units == {"一个": 1}, "一下 the treebanks keep whole; 一方面, 十二月 have no measure word; 一些 is never cut"


def test_a_number_in_pieces_is_one_piece(b):
    assert b.join_numbers(["一", "万", "二", "千", "名"]) == ["一万二千", "名"]
    assert b.join_numbers(["一", "万一", "千"]) == ["一万一千"]
    assert b.join_numbers(["吃", "了", "饭"]) == ["吃", "了", "饭"]


def test_the_route_never_keeps_the_whole_entry(b):
    freq = {"吃了饭": 50, "吃": 3000, "了": 9000, "饭": 800, "电影": 900, "吧": 700, "电影吧": 20}
    listed = {"电影", "吃饭"}
    logtotal = math.log(sum(freq.values()))
    assert b.recut("吃了饭", freq, logtotal, listed) == ["吃", "了", "饭"]
    assert b.recut("电影吧", freq, logtotal, listed) == ["电影", "吧"]


@pytest.mark.parametrize("pieces, tags, token_tag, holds", [
    (["吃", "了", "饭"], {"吃": "v", "了": "ul", "饭": "n"}, "v", True),        # aspect after its verb
    (["结", "了", "婚"], {"结": "n", "了": "ul", "婚": "n"}, "v", True),        # inside an entry tagged a verb
    (["千", "了", "百", "了"], {"千": "m", "了": "ul", "百": "m"}, "i", False),  # 了 'finish' in an idiom
    (["认真", "地"], {"认真": "ad", "地": "uv"}, "d", True),                    # adverb-making 地
    (["慢慢", "地"], {"慢慢": "d", "地": "uv"}, "d", True),
    (["用", "地"], {"用": "p", "地": "uv"}, "n", False),                        # 地 'land'
    (["农业", "用", "地"], {"农业": "n", "用": "p", "地": "uv"}, "n", False),
    (["地", "安", "门"], {"地": "uv", "安": "a", "门": "n"}, "ns", False),       # never first
    (["跑", "得", "快"], {"跑": "v", "得": "ud", "快": "a"}, "v", True),          # complement between verb and word
    (["录", "得"], {"录": "v", "得": "ud"}, "v", False),                        # 得 last: 'obtain'
    (["电影", "吧"], {"电影": "n", "吧": "y"}, "n", True),                      # a sentence-final particle
    (["甚", "么"], {"甚": "zg", "么": "y"}, "r", False),                        # after an adverb: no particle
    (["很", "多"], {"很": "d", "多": "m"}, "m", True),                          # the degree adverb
    (["一", "碗"], {"一": "m", "碗": "n"}, "m", True),                          # number + classifier (CC-CEDICT)
    (["这", "次"], {"这": "r", "次": "q"}, "r", True),                          # this + measure word
    (["喝", "咖啡"], {"喝": "v", "咖啡": "n"}, "nr", False),                    # no grammar
])
def test_grammar_is_read_where_grammar_stands(b, pieces, tags, token_tag, holds):
    assert b.grammar(pieces, tags, frozenset("碗个本"), token_tag) is holds


def test_the_split_table_spares_what_cedict_lists_names_and_doubled_words(b):
    entries, _ = b.parse_cedict(CEDICT_LINES)
    freq = {"吃了饭": 50, "吃": 3000, "了": 9000, "饭": 800, "这个": 5000, "这": 9000, "个": 9000, "一个": 9000,
            "一": 9000, "王小明": 30, "王": 500, "小": 900, "明": 400, "开开心心": 10, "开": 900, "心": 900,
            "开心": 500, "一碗": 40, "碗": 300}
    tags = {"吃了饭": "v", "吃": "v", "了": "ul", "饭": "n", "这个": "r", "这": "r", "个": "q", "一个": "m",
            "一": "m", "王小明": "nr", "开开心心": "z", "一碗": "m", "碗": "n"}
    table = b.split_table(entries, {"一个": 1}, freq, sum(freq.values()), tags, b.classifier_chars(entries) | {"碗"})
    assert table["吃了饭"] == (1, 1, 1)
    assert table["一个"] == (1, 1), "a count CC-CEDICT lists is cut after its number"
    assert table["一碗"] == (1, 1)
    assert "这个" not in table and "王小明" not in table and "开开心心" not in table


def test_the_built_module_decodes_back_to_its_table(b, tmp_path):
    gold = tmp_path / "zh_gold"
    (gold / "ud").mkdir(parents=True)
    with zipfile.ZipFile(gold / "cedict_1_0_ts_utf-8_mdbg.zip", "w") as archive:
        archive.writestr("cedict_ts.u8", CEDICT_LINES)
    (gold / "ud" / "toy.conllu").write_text("1\t一\t_\n2\t个\t_\n\n1\t一\t_\n2\t个\t_\n", encoding="utf-8")
    freq = {"吃了饭": 50, "吃": 3000, "了": 9000, "饭": 800, "一个": 9000, "一": 9000, "个": 9000}
    tags = {"吃了饭": "v", "吃": "v", "了": "ul", "饭": "n", "一个": "m", "一": "m", "个": "q"}
    output = tmp_path / "cedict_data.py"
    b.main(str(gold), str(output), jieba_data=(freq, sum(freq.values()), tags, "test"))
    spec = importlib.util.spec_from_file_location("cedict_data_built", str(output))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.splits() == {"吃了饭": (1, 1, 1), "一个": (1, 1)}
    assert "CC BY-SA 4.0" in output.read_text(encoding="utf-8")


def test_a_changed_download_stops_the_build(b, tmp_path):
    (tmp_path / "x.zip").write_bytes(b"not the file")
    (tmp_path / "FETCHED.json").write_text(json.dumps([{"file": "x.zip", "sha256": "0" * 64}]), encoding="utf-8")
    with pytest.raises(SystemExit):
        b.check_fetched(str(tmp_path), "x.zip")


def test_a_numbers_only_word_counts_nothing_only_by_a_sense_that_counts_nothing(b):
    entries, _ = b.parse_cedict(
        "千萬 千万 [qian1 wan4] /ten million/countless/many/one must by all means/\n"
        "萬一 万一 [wan4 yi1] /just in case/if by any chance/contingency/\n"
        "百十 百十 [bai3 shi2] /a hundred or so/\n"
        "十一 十一 [Shi2 Yi1] /PRC National Day (October 1st)/\n"
        "十一 十一 [shi2 yi1] /eleven/11/\n"
        "二十 二十 [er4 shi2] /twenty; 20/\n")
    assert b.not_counts(entries) == {"千万", "万一"}, "百十 is a quantity; 十一's other sense is a name; 二十 a number"



def test_a_gloss_word_matches_by_its_stem(b):
    assert b.stem("aspects") == b.stem("aspect")
    assert b.stem("hurriedly") == b.stem("hurried")
    assert b.stem("happiness") == b.stem("happy")
    assert b.stem("moving") == b.stem("move") == b.stem("movements")
    assert b.stem("families") == b.stem("family") and b.stem("classes") == b.stem("class")
    assert b.gloss_words("(idiom) all aspects; every side") == {b.stem(w) for w in ("all", "aspect", "every", "side")}


DOUBLED_LINES = """\
馬馬虎虎 马马虎虎 [ma3 ma3 hu1 hu1] /careless/casual/vague/not so bad/so-so/tolerable/fair/
馬虎 马虎 [ma3 hu5] /careless/sloppy/negligent/skimpy/
高高興興 高高兴兴 [gao1 gao1 xing4 xing4] /cheerful and optimistic/in a good mood/gaily/
高興 高兴 [gao1 xing4] /happy/glad/willing (to do sth)/in a cheerful mood/
方方面面 方方面面 [fang1 fang1 mian4 mian4] /all aspects/
方面 方面 [fang1 mian4] /respect/aspect/field/side/
開心 开心 [kai1 xin1] /to feel happy/to rejoice/to have a great time/to make fun of sb/
三兩 三两 [san1 liang3] /two or three/
哈哈 哈哈 [ha1 ha1] /(onom.) laughing out loud/
哈哈哈 哈哈哈 [ha1 ha1 ha1] /ha ha ha/
好好 好好 [hao3 hao3] /in perfectly good condition/well; thoroughly; carefully; properly/
汪汪 汪汪 [wang1 wang1] /gleaming with tears/woof woof (sound of a dog barking)/
"""


def test_a_doubled_form_folds_unless_it_has_a_meaning_of_its_own(b):
    entries, _ = b.parse_cedict(DOUBLED_LINES)
    assert b.own_meaning("马马虎虎", "马虎", entries), "one of seven senses shares a word"
    assert not b.own_meaning("高高兴兴", "高兴", entries)
    assert not b.own_meaning("方方面面", "方面", entries), "aspects ~ aspect"
    assert not b.own_meaning("开开心心", "开心", entries), "a form CC-CEDICT doesn't list is its base's"
    freq = {"马马虎虎": 30, "高高兴兴": 40, "方方面面": 50, "开开心心": 20, "三三两两": 20, "形形色色": 10, "吃饭": 900}
    folds, own = b.fold_table(entries, freq, lambda text: text)
    assert folds == {"高高兴兴", "方方面面", "开开心心"}, "形形色色's base isn't listed; 三三两两 is the numbers'"
    assert own == {"马马虎虎"}


def test_a_run_folds_only_to_a_sound(b):
    entries, _ = b.parse_cedict(DOUBLED_LINES)
    assert b.sound_runs(entries) == {"哈哈", "汪汪"}, "好好 'well' is no sound; 哈哈哈 isn't 哈's shortest"
