"""The sentence dictionary: "Surasura Corpus (ja)", up to 8 of the best sentences for every word in the
library, as a Yomitan dictionary (docs/agent instructions/Sentence_Dictionary_Spec.md).

Two halves, both checked on real Japanese (and Chinese) text:
- the pass (`collect`, `length_range`) — which sentences a word keeps and in what order;
- the dictionary (`export_dictionary`, `build`) — a zip Yomitan will import. Yomitan validates every
  term bank strictly and refuses the WHOLE dictionary over one bad key, so every bank here goes
  through a validator of the schema rules the export uses (Yomitan master @ d34832d, 2026-09-08).
"""

import html
import json
import os
import re
import zipfile

import pytest

from app import analyzer
from app import sentence_corpus as sc

WINDOW = (5, 40, 10, 35)        # the user's own 10–35 characters, ±5 — what length_range() gives
_TOKENIZERS = {}


def _tokenized(lines, language="ja"):
    """A file as the token store keeps it: [(text, [[lemma, reading, surface, orth], ...]), ...] —
    one line per sentence, tokenized by the analyzer's own tokenizer."""
    if language not in _TOKENIZERS:
        analyzer.SANITIZE_JA = (language == "ja")
        _TOKENIZERS[language] = (analyzer.JapaneseTokenizer() if language == "ja"
                                 else analyzer.ChineseTokenizer())
    analyzer.SANITIZE_JA = (language == "ja")
    return [(text, [list(t) for t in tokens])
            for text, tokens in _TOKENIZERS[language].tokenize_sentences("\n".join(lines))]


def _collect(files, known=(), language="ja", window=WINDOW):
    """`files`: {name: [lines]} in library order. `known`: lemmas the learner knows."""
    cache = {name: _tokenized(lines, language) for name, lines in files.items()}
    return sc.collect(list(cache), cache.__getitem__, language, (set(), set(known), set()), window)


def _lemmas(line, language="ja"):
    return {t[0] for _text, tokens in _tokenized([line], language) for t in tokens}


def _best(words, lemma):
    [word] = [w for (l, _r), w in words.items() if l == lemma]
    return word.best.result()


def _texts(best):
    return [c[1] for c in best]


def _files_of(best):
    return [c[2] for c in best]


# ---------------------------------------------------------------------------------------------- #
# Which sentences, in what order
# ---------------------------------------------------------------------------------------------- #
def test_the_length_window_is_the_users_own_setting_widened_by_five():
    """D2: 'good length' is THEIR setting — they may want a different minimum or maximum — with ±5
    characters of leeway, never below one character and never past their hard cap."""
    def context(**kw):
        return {"logic": {"context": kw}}

    assert sc.length_range(context(min_chars=10, preferred_max_chars=35, max_chars=150)) == (5, 40, 10, 35)
    assert sc.length_range(context(min_chars=20, preferred_max_chars=60, max_chars=150)) == (15, 65, 20, 60)
    assert sc.length_range(context(min_chars=3, preferred_max_chars=148, max_chars=150)) == (1, 150, 3, 148)
    assert sc.length_range({}) == (5, 55, 10, 50)        # the shipped defaults, 10–50


def test_the_fewest_unknown_words_come_first_not_the_first_one_met():
    """D3: best first. The second line is all known words apart from 冒険, the first is full of
    words the learner hasn't met — the easy one leads, although it comes later in the file."""
    easy = "明日から冒険に出かけよう。"
    hard = "未知の迷宮で壮絶な冒険が始まった。"
    words = _collect({"第01話.txt": [hard, easy]}, known=_lemmas(easy) - {"冒険"})

    assert _texts(_best(words, "冒険")) == [easy, hard]


def test_the_users_own_range_comes_before_the_leeway_and_outside_lengths_are_left_out():
    """With the same number of unknown words, a sentence inside the user's own 10–35 beats one in the
    ±5 margin (37 characters); 4 and 50 characters are outside the window altogether."""
    lines = ["この本は彼の冒険について書かれているので、ぜひ最後まで読んでみてください。",   # 37
             "冒険だ。",                                                                    # 4
             "彼は毎日冒険に出かけます。",                                                  # 13
             "私たちは新しい冒険を求めているが、その道のりは決して平坦ではなく、多くの困難が待ち受けているだろう。"]  # 50
    assert [len(line) for line in lines] == [37, 4, 13, 50]
    known = set().union(*(_lemmas(line) for line in lines)) - {"冒険"}

    words = _collect({"a.txt": lines}, known=known)

    assert _texts(_best(words, "冒険")) == [lines[2], lines[0]]


def test_at_most_two_sentences_come_from_one_file_when_others_have_the_word():
    """Variety: eight sentences from eight different moments beat eight from one episode."""
    adventure = ["冒険は続く。", "新しい冒険が始まる。", "冒険の準備をしよう。", "冒険は危険だが、価値がある。",
                 "素晴らしい冒険が待っているはずだ。", "今夜は冒険の話をしよう。"]
    words = _collect({"第01話.txt": adventure,
                      "第02話.txt": ["彼は毎日冒険に出かけます。", "冒険の準備はできていますか？"],
                      "第03話.txt": ["私たちは新しい冒険を求めている。", "この本は彼の冒険について書かれている。"],
                      "第04話.txt": ["冒険家として非常に有名です。", "冒険したい。"]})

    best = _best(words, "冒険")
    assert len(best) == 8
    assert _files_of(best).count(0) == 2, "the first episode filled more than two places"


def test_one_files_sentences_fill_up_when_there_arent_enough_others():
    """…unless the word is in too few files: then the best of the rest take the empty places, rather
    than leaving the learner with three sentences out of eight."""
    adventure = ["冒険は続く。", "新しい冒険が始まる。", "冒険の準備をしよう。", "冒険は危険だが、価値がある。",
                 "素晴らしい冒険が待っているはずだ。", "今夜は冒険の話をしよう。"]
    words = _collect({"第01話.txt": adventure, "第02話.txt": ["彼は毎日冒険に出かけます。"]})

    best = _best(words, "冒険")
    assert len(best) == 7
    assert _files_of(best).count(0) == 6
    assert [c[0] for c in best] == sorted(c[0] for c in best), "not best-first"


def test_the_same_sentence_is_kept_once():
    """A line repeated across episodes (an opening song, a catchphrase) is one example, not three."""
    line = "冒険は危険だが、価値がある。"
    words = _collect({"第01話.txt": [line], "第02話.txt": [line], "第03話.txt": [line, "冒険は続く。"]})

    assert _texts(_best(words, "冒険")).count(line) == 1


def test_known_words_still_get_their_sentences():
    """Every word in the library — hovering a word you know shows how your own content uses it."""
    words = _collect({"a.txt": ["彼は毎日冒険に出かけます。"]}, known={"冒険"})

    assert _texts(_best(words, "冒険")) == ["彼は毎日冒険に出かけます。"]


def test_particles_are_skipped_and_single_kanji_are_kept():
    """One-character kana are particles and endings (が, の, を) — never an entry. One-character kanji
    are real words (猫) and keep theirs."""
    words = _collect({"a.txt": ["猫が窓の外を見ている。"]})
    listed = {l for (l, _r), w in words.items() if w.listed}

    assert "猫" in listed and "外" in listed
    assert not {"が", "の", "を"} & listed


def test_a_word_without_a_good_length_sentence_gets_no_entry(tmp_path):
    """C: a word met only in a 50-character sentence has no sentence worth showing — no entry at all,
    rather than an entry without sentences."""
    long_line = "私たちは新しい冒険を求めているが、その道のりは決して平坦ではなく、多くの困難が待ち受けているだろう。"
    words = _collect({"a.txt": [long_line, "彼は毎日冒険に出かけます。"]})
    assert not [w for (l, _r), w in words.items() if l == "困難" and w.best.kept]

    out = str(tmp_path / "corpus.zip")
    sc.export_dictionary(words, [("a", "HighPriority/a.txt")], out, "ja")
    terms = {e[0] for e in _entries(out)}
    assert "冒険" in terms and "困難" not in terms


def test_chinese_keeps_single_characters_and_has_no_readings(tmp_path):
    """I5: Jieba's most common words are single characters, and Chinese has no reading to fill."""
    lines = ["我今天去图书馆看书。", "我们明天一起去公园散步吧。"]
    words = _collect({"第一章.txt": lines}, language="zh")
    assert "我" in {l for (l, _r), w in words.items() if w.listed and w.best.kept}

    out = str(tmp_path / "corpus.zip")
    sc.export_dictionary(words, [("第一章", "HighPriority/第一章.txt")], out, "zh")
    entries = _entries(out)
    assert entries and all(e[1] == "" and e[3] == "" for e in entries)
    assert all(e[5][0]["content"]["lang"] == "zh" for e in entries)
    assert _index(out)["title"] == "Surasura Corpus (zh)"


# ---------------------------------------------------------------------------------------------- #
# The dictionary Yomitan imports
# ---------------------------------------------------------------------------------------------- #
_DICTIONARY_FORM_RULES = {"v1", "v5", "vk", "vs", "vz", "adj-i"}
_CONTAINER_KEYS = {"tag", "content", "data", "style", "title", "open", "lang"}
_STYLE_ENUMS = {"fontStyle": {"normal", "italic"}, "fontWeight": {"normal", "bold"}}
_STYLE_KEYS = set(_STYLE_ENUMS) | {
    "fontSize", "color", "background", "backgroundColor", "textDecorationLine", "textDecorationStyle",
    "textDecorationColor", "borderColor", "borderStyle", "borderRadius", "borderWidth", "clipPath",
    "verticalAlign", "textAlign", "textEmphasis", "textShadow", "margin", "marginTop", "marginLeft",
    "marginRight", "marginBottom", "padding", "paddingTop", "paddingLeft", "paddingRight",
    "paddingBottom", "wordBreak", "whiteSpace", "cursor", "listStyleType"}


def _check_node(node):
    """Structured content, per dictionary-term-bank-v3-schema.json: `additionalProperties: false` on
    every element, `data` values strings, `style` a closed list."""
    if isinstance(node, str):
        return
    if isinstance(node, list):
        for child in node:
            _check_node(child)
        return
    assert isinstance(node, dict), node
    tag = node["tag"]
    if tag == "br":
        assert set(node) <= {"tag", "data"}, node
    else:
        assert tag in {"span", "div", "ol", "ul", "li", "details", "summary"}, tag
        assert set(node) <= _CONTAINER_KEYS, set(node) - _CONTAINER_KEYS
    for key, value in node.get("data", {}).items():
        assert isinstance(key, str) and isinstance(value, str), (key, value)
    for key, value in node.get("style", {}).items():
        assert key in _STYLE_KEYS, key
        assert value in _STYLE_ENUMS.get(key, {value}), (key, value)
    for key in ("title", "lang"):
        if key in node:
            assert isinstance(node[key], str)
    if "content" in node:
        _check_node(node["content"])


def _check_entry(entry):
    assert isinstance(entry, list) and len(entry) == 8, entry
    term, reading, definition_tags, rules, score, definitions, sequence, term_tags = entry
    assert isinstance(term, str) and term
    assert isinstance(reading, str)
    assert definition_tags is None or isinstance(definition_tags, str)
    assert isinstance(rules, str) and set(rules.split()) <= _DICTIONARY_FORM_RULES, rules
    assert isinstance(score, (int, float)) and not isinstance(score, bool)
    assert isinstance(definitions, list) and len(definitions) == 1, "one block, or compact mode adds ' | '"
    [definition] = definitions
    assert set(definition) == {"type", "content"} and definition["type"] == "structured-content"
    _check_node(definition["content"])
    assert isinstance(sequence, int) and not isinstance(sequence, bool)
    assert isinstance(term_tags, str)


def _entries(path):
    with zipfile.ZipFile(path) as zf:
        return [e for name in sorted(zf.namelist()) if re.fullmatch(r"term_bank_\d+\.json", name)
                for e in json.loads(zf.read(name))]


def _index(path):
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("index.json"))


def _library(*files, settings=None, known=()):
    """A real library in the test sandbox: {name: [lines]} files in NOW (no manifest — the analyzer
    falls back to the folder), optional settings.json and KnownWord.json."""
    root = os.environ["SURASURA_TEST_ROOT"]
    now = os.path.join(root, "data", "ja", "HighPriority")
    os.makedirs(now, exist_ok=True)
    for name, lines in files:
        with open(os.path.join(now, name), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    user_files = os.path.join(root, "User Files", "ja")
    os.makedirs(user_files, exist_ok=True)
    with open(os.path.join(user_files, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]}, f,
                  ensure_ascii=False)
    if settings is not None:
        with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(settings, f)
    return root


def _context_lines(ja_resources_dir):
    with open(os.path.join(ja_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def test_every_term_bank_is_one_yomitan_will_import(ja_resources_dir, tmp_path):
    """I3: one bad key and Yomitan refuses the whole dictionary. A real export of real text,
    every entry through the schema's rules."""
    _library(("第01話.txt", _context_lines(ja_resources_dir)),
             ("第02話.txt", ["猫が窓の外を見ている。", "長い旅の末に、ついに城へ辿り着いた。",
                            "この道を行けば、必ず海に辿り着く。"]))
    out = str(tmp_path / "Surasura Corpus (ja).zip")

    written = sc.build("ja", out, progress=lambda message: None)

    entries = _entries(out)
    assert written > 10 and len(entries) >= written
    for entry in entries:
        _check_entry(entry)
    by_term = {e[0]: e for e in entries}
    assert by_term["辿り着く"][1:4] == ["たどりつく", "", "v5"]
    assert by_term["冒険"][1] == "ぼうけん"


def test_sources_are_written_only_when_asked_for_and_either_way_it_imports(ja_resources_dir, tmp_path):
    """The export dialog's two answers, end to end: every sentence's hover is its file's path; the
    short name follows each sentence only when asked for; every entry passes the schema's rules."""
    name = "[SubsPlease] Kage no Jitsuryokusha - 01 (1080p) [A1B43109].txt"
    _library((name, _context_lines(ja_resources_dir)))

    for show_source in (False, True):
        out = str(tmp_path / f"corpus_{show_source}.zip")
        sc.build("ja", out, progress=lambda message: None, show_source=show_source)

        entries = _entries(out)
        for entry in entries:
            _check_entry(entry)
        lines = [line for e in entries for line in e[5][0]["content"]["content"]]
        assert {line["title"] for line in lines} == {"HighPriority/" + name}
        sources = {line["content"][-1]["content"] for line in lines
                   if isinstance(line["content"][-1], dict) and line["content"][-1]["data"]["surasura"] == "source"}
        assert sources == ({"　（Kage no Jitsuryokusha - 01）"} if show_source else set())


def test_the_zip_holds_its_index_styles_and_term_banks_at_the_root(ja_resources_dir, tmp_path):
    _library(("第01話.txt", _context_lines(ja_resources_dir)))
    out = str(tmp_path / "corpus.zip")

    written = sc.build("ja", out, progress=lambda message: None)

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        css = zf.read("styles.css").decode("utf-8")
    assert names == {"index.json", "styles.css", "term_bank_1.json"}
    assert css.strip(), "an empty styles.css fails the whole import"
    index = _index(out)
    assert index["title"] == "Surasura Corpus (ja)"
    assert index["format"] == 3 and index["sequenced"] is True
    assert isinstance(index["revision"], str) and index["revision"]
    assert index["sourceLanguage"] == index["targetLanguage"] == "ja"
    assert "personal" in index["attribution"]
    assert f"{written:,} words" in index["description"]
    assert "isUpdatable" not in index, "it would need indexUrl and downloadUrl"
    assert not os.path.exists(out + ".tmp")


def test_a_full_term_bank_rolls_over_into_the_next(ja_resources_dir, tmp_path, monkeypatch):
    """Banks hold 10,000 entries; the next one starts when one is full. Shown with a bank size of 5
    rather than 10,001 real words, so the test stays cheap."""
    monkeypatch.setattr(sc, "TERMS_PER_BANK", 5)
    _library(("第01話.txt", _context_lines(ja_resources_dir)))
    out = str(tmp_path / "corpus.zip")

    sc.build("ja", out, progress=lambda message: None)

    with zipfile.ZipFile(out) as zf:
        banks = sorted(n for n in zf.namelist() if n.startswith("term_bank_"))
        sizes = [len(json.loads(zf.read(n))) for n in banks]
    assert len(banks) >= 2 and all(size == 5 for size in sizes[:-1]) and 1 <= sizes[-1] <= 5
    for entry in _entries(out):
        _check_entry(entry)


def test_the_export_reads_the_users_length_setting_every_time(tmp_path):
    """D2, end to end: the same 32-character sentence is out with a maximum of 20 (+5 = 25) and in
    with 30 (+5 = 35) — the setting is read on each export, not baked in."""
    line = "明日の朝までに城へ辿り着けば、きっと約束の時間に間に合うだろう。"
    assert len(line) == 32
    out = str(tmp_path / "corpus.zip")

    _library(("第01話.txt", [line, "この道を行けば、必ず海に辿り着く。"]),
             settings={"logic": {"context": {"min_chars": 10, "preferred_max_chars": 20, "max_chars": 150}}})
    sc.build("ja", out, progress=lambda message: None)
    assert "約束" not in {e[0] for e in _entries(out)}

    _library(settings={"logic": {"context": {"min_chars": 10, "preferred_max_chars": 30, "max_chars": 150}}})
    sc.build("ja", out, progress=lambda message: None)
    assert "約束" in {e[0] for e in _entries(out)}


def test_an_empty_library_writes_nothing(tmp_path):
    _library()
    out = str(tmp_path / "corpus.zip")
    messages = []

    assert sc.build("ja", out, progress=messages.append) == 0
    assert not os.path.exists(out)
    assert any("add content" in m for m in messages)


def test_a_failed_export_leaves_no_file_behind(tmp_path, monkeypatch):
    """Built in <name>.tmp and renamed: a run that fails half-way leaves neither a half dictionary
    where the user will look for it nor a stray temp file."""
    words = _collect({"a.txt": ["彼は毎日冒険に出かけます。", "猫が窓の外を見ている。"]})
    calls = []

    def fail_on_the_second(best, sources, language, show_source=False):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return {"tag": "div", "content": ""}

    monkeypatch.setattr(sc, "_content", fail_on_the_second)
    out = str(tmp_path / "corpus.zip")
    with pytest.raises(OSError):
        sc.export_dictionary(words, [("a", "HighPriority/a.txt")], out, "ja")
    assert not os.path.exists(out) and not os.path.exists(out + ".tmp")


# ---------------------------------------------------------------------------------------------- #
# Spellings, readings, rules — so the entry appears where the learner hovers
# ---------------------------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def tag():
    return sc._default_tagger()


def test_a_verbs_spellings_are_its_entries_but_not_its_potential_form(tag):
    """辿り着く and たどり着く are how the content spells it; たどりつく is found through the kanji
    entry's reading; 辿り着ける is its potential form, which Yomitan de-inflects by itself."""
    orths = {"辿り着く": 5, "辿り着ける": 4, "たどりつく": 3, "たどり着く": 2}

    assert sc._japanese_terms("辿り着く", "タドリツク", orths, tag) == [
        ("辿り着く", "たどりつく", "v5"), ("たどり着く", "たどりつく", "v5")]


def test_a_spelling_takes_its_own_reading_and_class(tag):
    """感じる is filed under the lemma 感ずる (かんずる, サ変) but is itself かんじる, a 一段 verb — which
    is what groups it with JMdict's 感じる and lets 感じた find it."""
    assert sc._japanese_terms("感ずる", "カンズル", {"感じる": 3}, tag) == [("感じる", "かんじる", "v1")]


def test_a_homograph_keeps_its_own_reading(tag):
    """上手 tagged alone comes back as じょうず; the 上手 read かみて (stage left) must not."""
    assert sc._japanese_terms("上手", "カミテ", {"上手": 2}, tag) == [("上手", "かみて", "")]
    assert sc._japanese_terms("上手", "ジョウズ", {"上手": 9}, tag) == [("上手", "じょうず", "")]


def test_kana_words_have_no_reading_and_names_read_as_written(tag):
    """A kana-only term carries no reading (as 大辞林's テレビ); スドウ is the lemma, 須藤 what the
    content writes."""
    assert sc._japanese_terms("テレビ", "テレビ", {"テレビ": 3}, tag) == [("テレビ", "", "")]
    assert sc._japanese_terms("やがる", "ヤガル", {"やがる": 2}, tag) == [("やがる", "", "v5")]
    assert sc._japanese_terms("スドウ", "スドウ", {"須藤": 3}, tag) == [("須藤", "すどう", "")]


def test_rules_follow_the_conjugation_type():
    assert sc._rules("五段-カ行", "辿り着く") == "v5"
    assert sc._rules("下一段-カ行", "受ける") == "v1"
    assert sc._rules("上一段-ザ行", "感じる") == "v1"
    assert sc._rules("カ行変格", "来る") == "vk"
    assert sc._rules("サ行変格", "する") == "vs"
    assert sc._rules("サ行変格", "信ずる") == "vz"
    assert sc._rules("形容詞", "美しい") == "adj-i"
    assert sc._rules("", "勉強") == ""
    assert sc._rules("助動詞-ナイ", "ない") == ""


# ---------------------------------------------------------------------------------------------- #
# How an entry reads — styled, and as plain text
# ---------------------------------------------------------------------------------------------- #
_SOURCES = [("第01話", "HighPriority/陰の実力者/第01話.txt"), ("第02話", "HighPriority/陰の実力者/第02話.txt")]


def _two_sentences():
    return [((0, 0, 0, 0), "明日から冒険に出かけよう。", 0, "冒険"),
            ((0, 0, 1, 0), "彼は毎日冒険に出かけます。", 1, "冒険")]


def _html(node):
    """Structured content as Yomitan renders it: data keys become data-sc-* attributes."""
    if isinstance(node, str):
        return html.escape(node, quote=False)
    if isinstance(node, list):
        return "".join(_html(child) for child in node)
    attrs = "".join(f' data-sc-{k}="{html.escape(v)}"' for k, v in node.get("data", {}).items())
    if "title" in node:
        attrs += f' title="{html.escape(node["title"])}"'
    return f"<{node['tag']}{attrs}>{_html(node.get('content', ''))}</{node['tag']}>"


def _yomitan_plain(markup):
    """anki-template-renderer.js _getText, the conversion behind Yomitan's {glossary-plain}."""
    text = re.sub(r"<(div|li|ol|ul|br|details|summary|hr)(\s.*?>|>)", "\n", markup)
    text = re.sub(r"<(span|a|ruby)(\s.*?>|>)", " ", text)
    text = re.sub(r"<rt(\s.*?>|>)", "[", text).replace("</rt>", "]")
    text = re.sub(r"<.*?>", "", text, flags=re.S)
    text = text.replace("<", "&lt;").replace(">", "&rt;")
    text = re.sub(r"\n+", "<br>", text)
    text = re.sub(r"^(\s*<br>\s*|\s)*", "", text)
    return text.replace("<br>", "<br>\n")


def test_each_sentence_is_its_own_line_with_a_number_the_word_and_its_file_on_hover():
    """By default (the export dialog's box unticked) nothing follows a sentence — file names crowded
    the popup — but hovering the sentence still shows the file it came from."""
    lines = sc._content(_two_sentences(), _SOURCES, "ja")["content"]

    assert lines[0]["content"] == [
        "① 明日から",
        {"tag": "span", "data": {"surasura": "target"}, "style": {"fontWeight": "bold"}, "content": "冒険"},
        "に出かけよう。"]
    assert lines[0]["title"] == "HighPriority/陰の実力者/第01話.txt"
    assert lines[1]["content"][0] == "② 彼は毎日"
    assert lines[1]["title"] == "HighPriority/陰の実力者/第02話.txt"


def test_the_source_follows_each_sentence_only_when_asked_for():
    """Ticked: '　（short name）' at the end of each line, small and grey — the full-width space is the
    gap before it. The hover stays."""
    content = sc._content(_two_sentences(), _SOURCES, "ja", show_source=True)
    lines = content["content"]

    assert [line["content"][-1]["content"] for line in lines] == ["　（第01話）", "　（第02話）"]
    assert lines[0]["content"][-1]["data"] == {"surasura": "source"}
    assert lines[0]["content"][:3] == sc._content(_two_sentences(), _SOURCES, "ja")["content"][0]["content"]
    assert lines[0]["title"] == "HighPriority/陰の実力者/第01話.txt"
    _check_node(content)


def test_a_thin_line_divides_the_sentences_wherever_the_entry_is_shown():
    """Besides the numbers, a faint line between sentences — none under the last. It is an INLINE
    style, since a dictionary's stylesheet only reaches Yomitan's own popup, and it uses only style
    keys Yomitan's schema accepts."""
    three = _two_sentences() + [((0, 0, 2, 0), "冒険家として非常に有名です。", 1, "冒険")]
    content = sc._content(three, _SOURCES, "ja")

    assert [line.get("style") for line in content["content"]] == [sc._DIVIDER, sc._DIVIDER, None]
    assert sc._DIVIDER["borderStyle"] == "solid" and sc._DIVIDER["borderWidth"] == "0 0 1px 0"
    assert "border" not in sc.CORPUS_CSS
    _check_node(content)
    [alone] = sc._content(three[:1], _SOURCES, "ja")["content"]
    assert "style" not in alone


def test_it_still_reads_well_as_plain_text():
    """D4 / I8: many displays show only text. Tags stripped, each sentence is still numbered; through
    Yomitan's own converter every sentence is a line (the bold word costs a space there). The divider
    is a style, which plain text simply drops — the line breaks already part the sentences. Asked
    for, the source costs a space too, which only widens the gap before it."""
    markup = _html(sc._content(_two_sentences(), _SOURCES, "ja"))
    sourced = _html(sc._content(_two_sentences(), _SOURCES, "ja", show_source=True))

    assert re.sub(r"<[^>]+>", "", markup) == "① 明日から冒険に出かけよう。② 彼は毎日冒険に出かけます。"
    assert _yomitan_plain(markup).split("<br>\n") == ["① 明日から 冒険に出かけよう。", "② 彼は毎日 冒険に出かけます。"]
    assert _yomitan_plain(sourced).split("<br>\n") == [
        "① 明日から 冒険に出かけよう。 　（第01話）", "② 彼は毎日 冒険に出かけます。 　（第02話）"]


def test_the_word_is_highlighted_only_where_it_is_written():
    """The surface comes from that very sentence; if it can't be found as written (a cleaned line),
    nothing is highlighted rather than something guessed."""
    candidates = [((0, 0, 0, 0), "冒険は続く。", 0, "冒険"), ((0, 0, 0, 1), "旅は続く。", 0, "冒険")]
    lines = sc._content(candidates, _SOURCES, "ja")["content"]

    assert any(isinstance(p, dict) and p["data"]["surasura"] == "target" for p in lines[0]["content"])
    assert not any(isinstance(p, dict) and p["data"]["surasura"] == "target" for p in lines[1]["content"])


def test_line_breaks_and_invisible_characters_are_cleaned_from_sentences_and_labels():
    """Yomitan keeps line breaks, and private-use glyphs (a real Src label carried U+F00D) show as
    boxes."""
    candidates = [((0, 0, 0, 0), "冒険は\n続く。\ue00d", 0, "冒険")]
    content = sc._content(candidates, [(sc._clean("第01話\uf00d"), "HighPriority/第01話.txt")], "ja",
                          show_source=True)
    text = "".join(p if isinstance(p, str) else p["content"] for p in content["content"][0]["content"])

    assert text == "① 冒険は 続く。　（第01話）"


@pytest.mark.parametrize("stem, label", [
    # Fansub releases: the group, broadcaster / quality tags, a CRC, an extractor's track + language.
    ("[NanakoRaws] Seihantai na Kimi to Boku - 01 (TBS 1080p HEVC AAC).3.und",
     "Seihantai na Kimi to Boku - 01"),
    ("[Coalgirls]_Code_Geass_01_(1920x1080_Blu-ray_FLAC)_[A1B43109]", "Code_Geass_01"),
    # A streaming rip: the series and episode number stay, the episode's own title goes.
    ("ようこそ実力至上主義の教室へ.S01E01.悪とは何か.WEBRip.Netflix.ja[cc]", "ようこそ実力至上主義の教室へ.S01E01"),
    ("三体.S01E01.chs", "三体.S01E01"),
    # Too long: the MIDDLE goes, so the episode number survives.
    ("The Irregular at Magic High School.S01E25.JA", "The Irregular at M…hool.S01E25"),
    # YouTube downloads lose the video id — and the timestamps a Graduate / Demote clash appends.
    ("【日本語ポッドキャスト】週末の過ごし方について話します [Qx7Lm2Pz9Ka]", "【日本語ポッドキャスト】週末の過ごし方について話します"),
    ("ゆるっと日本語 - 【聞き流し】リスナーさんからの質問に全部答えます [Rt5Yu8Io3Pw]_20260301120000_20260302093015",
     "ゆるっと日本語 - 【聞き流し】リス…らの質問に全部答えます"),
    ("S01E13.薫子と凛太郎.ja_20260304015308", "S01E13.薫子と凛太郎"),
    # Already short: kept as written, a volume in brackets included.
    ("陰の実力者-2_12", "陰の実力者-2_12"),
    ("Bleach - 340", "Bleach - 340"),
    ("こころ (上)", "こころ (上)"),
    ("第一章", "第一章"),
    # Nothing left but a tag: the name as it was, rather than nothing.
    ("[SubsPlease]", "[SubsPlease]"),
])
def test_a_source_is_its_files_short_name(stem, label):
    """The source line is only worth its space if it says where a sentence is from — not which group
    released it, at what resolution, under which id."""
    assert sc._short_label(sc._clean(stem)) == label


# ---------------------------------------------------------------------------------------------- #
# The button, and the process it launches
# ---------------------------------------------------------------------------------------------- #
class _Var:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def _dashboard_stub():
    """The empty-library check and the export itself need only the language and run_command_async —
    no window."""
    from unittest.mock import MagicMock
    from app.main import MasterDashboardApp
    app = MasterDashboardApp.__new__(MasterDashboardApp)
    app.var_language = _Var("ja")
    app.run_command_async = MagicMock()
    return app


def _widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _widgets(child)


def _recording_tooltips(monkeypatch):
    """{widget path: tooltip text} for every ToolTip the dashboard makes from here on."""
    import app.main as main_module
    real_tooltip, tipped = main_module.ToolTip, {}

    def recording(widget, text, *args, **kwargs):
        tipped[str(widget)] = text
        return real_tooltip(widget, text, *args, **kwargs)

    monkeypatch.setattr(main_module, "ToolTip", recording)
    return tipped


def test_the_button_asks_first_whether_to_show_sources_and_remembers_the_answer(monkeypatch):
    """Settings → Data & System → Export Sentence Dictionary opens a small dialog first. Its box starts
    unticked — file names crowded the popup. Cancel exports nothing and forgets a changed box; Export
    saves the answer with the settings, hands it to the export, and the next start reads it back. GUI
    guidelines: Esc closes the dialog; the button, the box and both dialog buttons carry tooltips. One
    dashboard for all of it (testing.md §5.4: one root per file)."""
    import tkinter as tk
    from tkinter import ttk
    from unittest.mock import MagicMock
    import app.main as main_module
    from app import settings_manager

    _library(("第01話.txt", ["彼は毎日冒険に出かけます。"]))
    saved = []
    monkeypatch.setattr(settings_manager, "save_settings", lambda s, **k: saved.append(s))
    # The save dialog must never open for real: it would wait for a click that never comes.
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: "")
    tipped = _recording_tooltips(monkeypatch)
    root = tk.Tk()
    root.withdraw()
    # The dashboard makes its Tk variables without a master, so they belong to the DEFAULT root — in
    # the app, the dashboard's own. In a full run an earlier test can leave another root as the
    # default, and the checkbox would then set a variable in a different interpreter from the one the
    # dashboard reads.
    monkeypatch.setattr(tk, "_default_root", root)
    try:
        app = main_module.MasterDashboardApp(root)
        app._export_sentence_dictionary = MagicMock()
        app.create_settings_window()
        [button] = [b for b in _widgets(app.settings_window)
                    if isinstance(b, ttk.Button) and b.cget("text") == "Export Sentence Dictionary"]
        assert "Yomitan" in tipped.get(str(button), "")
        assert "Data & System" in button.master.cget("text")

        def open_dialog():
            button.invoke()
            [dialog] = [w for w in root.winfo_children()
                        if isinstance(w, tk.Toplevel) and w.title() == "Export Sentence Dictionary"]
            widgets = list(_widgets(dialog))
            [box] = [w for w in widgets if isinstance(w, ttk.Checkbutton)]
            buttons = {w.cget("text"): w for w in widgets if isinstance(w, ttk.Button)}
            return dialog, box, buttons

        dialog, box, buttons = open_dialog()
        assert box.cget("text") == "Show where each sentence came from"
        assert not box.instate(["selected"])
        assert set(buttons) == {"Cancel", "Export"}
        assert all(tipped.get(str(w)) for w in (box, *buttons.values()))
        assert dialog.bind("<Escape>")
        box.invoke()                                # tick it, then change your mind
        buttons["Cancel"].invoke()
        assert not dialog.winfo_exists()
        app._export_sentence_dictionary.assert_not_called()
        assert app.var_sentence_dictionary_source.get() is False
        assert not any(s["sentence_dictionary_source"] for s in saved)

        dialog, box, buttons = open_dialog()
        assert not box.instate(["selected"]), "Cancel kept the tick"
        box.invoke()                                # tick it
        buttons["Export"].invoke()

        assert not dialog.winfo_exists()
        assert saved[-1]["sentence_dictionary_source"] is True
        app._export_sentence_dictionary.assert_called_once_with("ja", True)

        _library(settings=saved[-1])                # what that save writes, read on the next start
        app.var_sentence_dictionary_source.set(False)
        app.load_settings()
        assert app.var_sentence_dictionary_source.get() is True
    finally:
        root.destroy()


def test_the_answer_is_a_setting_that_never_forces_a_new_analysis():
    """Off by default, and export-only: changing it must not make the next Generate re-analyse the
    library."""
    from types import SimpleNamespace
    from app import settings_manager

    assert settings_manager.DEFAULT_SETTINGS["sentence_dictionary_source"] is False
    args = SimpleNamespace(language="ja", min_freq=2, target_coverage=90, only_i_plus_one=False,
                           ensure_audio_example=False, include_single_chars=False,
                           exclude_freq_one=False, reinforce=False, context_min=10, context_max=50,
                           max_contexts=3)
    root = _library(settings={"target_language": "ja"})
    base = analyzer.compute_run_signature("ja", [], args)

    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:     # only the setting
        json.dump({"target_language": "ja", "sentence_dictionary_source": True}, f)

    assert settings_manager.load_settings()["sentence_dictionary_source"] is True     # the file it reads
    assert base is not None and analyzer.compute_run_signature("ja", [], args) == base


def test_the_frozen_build_knows_the_command():
    """A frozen build launches `Surasura.exe sentence_corpus`: the dashboard's map and app_entry's
    dispatch must agree on that word, or the button opens a second dashboard instead."""
    import inspect
    import app_entry
    from app.main import MasterDashboardApp

    assert "'sentence_corpus.py': 'sentence_corpus'" in inspect.getsource(MasterDashboardApp.run_command_async)
    dispatch = inspect.getsource(app_entry.main)
    assert "command == 'sentence_corpus'" in dispatch and "sentence_corpus.main()" in dispatch


def test_an_empty_library_says_so_without_launching_anything(monkeypatch):
    from unittest.mock import MagicMock
    import app.main as main_module
    _library()
    box, dialog = MagicMock(), MagicMock()
    monkeypatch.setattr(main_module, "messagebox", box)
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", dialog)
    app = _dashboard_stub()

    app.export_sentence_dictionary()

    box.showwarning.assert_called_once()
    dialog.assert_not_called()
    app.run_command_async.assert_not_called()


def test_the_export_runs_as_its_own_process_and_reports_what_it_made(ja_resources_dir, tmp_path,
                                                                     monkeypatch):
    """The dashboard launches the export like Generate (its own process, output in the log) with the
    dialog's answer on its command line and, when it ends, tells the user how to import it — or,
    when no fresh zip exists, that it failed."""
    from unittest.mock import MagicMock
    import app.main as main_module
    _library(("第01話.txt", _context_lines(ja_resources_dir)))
    out = str(tmp_path / "Surasura Corpus (ja).zip")
    box = MagicMock()
    monkeypatch.setattr(main_module, "messagebox", box)
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: out)
    app = _dashboard_stub()

    app._export_sentence_dictionary("ja", True)
    app._export_sentence_dictionary("ja", False)

    sourced, call = app.run_command_async.call_args_list
    assert sourced.args[0] == ["sentence_corpus.py", "--language", "ja", "--output", out, "--show-source"]
    assert call.args[0] == ["sentence_corpus.py", "--language", "ja", "--output", out]
    assert call.kwargs["capture_output"] is True
    on_complete = call.kwargs["on_complete"]

    on_complete()                                   # the process ended without writing anything
    box.showerror.assert_called_once()

    sc.build("ja", out, progress=lambda message: None)
    on_complete()
    message = box.showinfo.call_args.args[1]
    assert "Surasura Corpus (ja) is ready." in message and "words" in message
    assert "Delete it in Yomitan first" in message


def test_the_process_the_dashboard_launches_writes_the_dictionary(ja_resources_dir, tmp_path):
    """Source mode, end to end: `python app/sentence_corpus.py` with the dashboard's own child
    environment, its output read as strict UTF-8 exactly as run_command_async reads the pipe — and
    the dialog's "show sources" answer arriving as --show-source."""
    import subprocess
    import sys
    from app.main import build_subprocess_env
    _library(("第01話.txt", _context_lines(ja_resources_dir)))
    out = tmp_path / "Surasura Corpus (ja).zip"
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "app", "sentence_corpus.py")

    proc = subprocess.run([sys.executable, script, "--language", "ja", "--output", str(out), "--show-source"],
                          env=build_subprocess_env(False), capture_output=True, timeout=180)

    output = proc.stdout.decode("utf-8")
    assert proc.returncode == 0, output + proc.stderr.decode("utf-8", "replace")
    assert "Saved Surasura Corpus (ja)" in output
    entries = _entries(str(out))
    assert entries and "　（第01話）" in _html(entries[0][5][0]["content"])
