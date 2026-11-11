"""A book's card sentence is the sentence that holds the word (Michi-BS, Mattias's field report 2026-11-12: a card of
カラフル took a 241-character 「…」 speech where Surasura had named one 33-character sentence of it).

Anki Miner's splitter never ends a sentence inside 「…」, so a long speech is one of its units, and the card took the
whole unit. Surasura names the sentence (`line_text`, the analyzer's split, 。！？ inside 「」 included); Anki Miner's
side of the cure (Mattias's PR 0xzerolight/anki_miner#148) cuts the unit around a `line_text` it holds EXACTLY. So the
sentence Surasura sends must be: one sentence, an exact piece of the paragraph as the book writes it (its inner spaces
kept; only line breaks and the paragraph's indent out), and clean — a quote mark the split left with no partner at the
sentence's start or end dropped (「おれは…好い。 → おれは…好い。), which keeps it an exact piece. And, PROVISIONAL (lean,
2026-11-12): a book's word is cut from a sentence within the learner's *Length* (logic.context min_chars /
preferred_max_chars) when it has one there — a longer or shorter one only later, never cut short. Video and audio cards
keep the card-line rules (Michi-CL) unchanged.

What a wrong answer would cost: the learner's book cards carry a paragraph-sized sentence (Mattias's report), a stray
「 or 」 on every seventh card, or a sentence Anki Miner can't find exactly (the whole speech again). Real text:
芥川龍之介「杜子春」 (public domain, `Test Resources/ja/toshisyun_book.txt`) and the suite's `placed_episode.srt`.
"""
import os
import re
from types import SimpleNamespace

import pytest

from app import cues
from app.cli import verbs
from app.connect import pick, runfile

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
BOOK = os.path.join(RESOURCES, "ja", "toshisyun_book.txt")
EPISODE = os.path.join(RESOURCES, "ja", "placed_episode.srt")
# 鉄冠子's speech: one paragraph, one 「…」, five sentences — one unit for Anki Miner
SPEECH = ("「おれはこれから天上へ行つて、西王母に御眼にかかつて来るから、お前はその間ここに坐つて、おれの帰るのを待つてゐるが好い。"
          "多分おれがゐなくなると、いろいろな魔性が現れて、お前をたぶらかさうとするだらうが、たといどんなことが起らうとも、"
          "決して声を出すのではないぞ。もし一言でも口を利いたら、お前は到底仙人にはなれないものだと覚悟をしろ。好いか。"
          "天地が裂けても、黙つてゐるのだぞ。」")
OPENERS, CLOSERS = "「『（", "」』）"


def _paragraphs(path):
    """The book's paragraphs as Anki Miner holds them: each line, its indent and ends out."""
    with open(path, encoding="utf-8") as f:
        return [line.strip().lstrip("　") for line in f.read().splitlines() if line.strip()]


def _cut(paragraphs, needle):
    """Anki Miner's cut (PR #148, `runs.cut_at_named_lines`): the unit holding `needle` exactly becomes the text
    before, the needle and the text after -> the card's sentence, or the whole unit when nothing holds it exactly."""
    for unit in paragraphs:
        if needle in unit:
            return needle
    return next((u for u in paragraphs if "".join(needle.split()) in "".join(u.split())), None)


def _lone(text):
    """The quote marks of `text` with no partner inside it."""
    stack, lone = [], []
    for i, ch in enumerate(text):
        if ch in OPENERS:
            stack.append(i)
        elif ch in CLOSERS:
            if stack and OPENERS.index(text[stack[-1]]) == CLOSERS.index(ch):
                stack.pop()
            else:
                lone.append(i)
    return lone + stack


def _book_words():
    read, tokens = cues.reading(BOOK, "ja")
    return read, tokens, pick.pick(read, tokens, "ja", lambda key: False, mode="unknown")["words"]


def test_a_word_in_a_long_quoted_speech_is_named_by_its_own_sentence_without_a_stray_quote_mark():
    # why: Mattias's report — the speech is one unit for Anki Miner, so the sentence Surasura names is all the card
    # can be cut to; with a 「 the split left behind, every first sentence of a speech would carry it onto the card
    _read, _tokens, words = _book_words()
    in_speech = [w for w in words if w["line_text"] in SPEECH]
    lines = {w["line_text"] for w in in_speech}
    assert "おれはこれから天上へ行つて、西王母に御眼にかかつて来るから、お前はその間ここに坐つて、おれの帰るのを待つてゐるが好い。" in lines
    assert "天地が裂けても、黙つてゐるのだぞ。" in lines
    assert len(lines) >= 4, "the speech's sentences, each its own"
    for w in in_speech:
        assert len(re.findall("[。！？]", w["line_text"])) == 1 and w["line_text"][-1] == "。", w["line_text"]
        assert not _lone(w["line_text"]), w["line_text"]
        assert w["surface"] in w["line_text"] and w["line_expansion"] == [0, 0]


def test_every_sentence_a_book_sends_is_an_exact_piece_of_its_paragraph_so_anki_miner_cuts_the_card_to_it():
    # why: PR #148 cuts only around an exact match; a sentence a byte off (a squeezed space, an added 」) gets the
    # whole unit back — the bug again, silently
    paragraphs = _paragraphs(BOOK)
    _read, _tokens, words = _book_words()
    sent = runfile.word_requests(words, ["reading"], book=True)
    assert sent and all(set(s) == {"word", "line_text"} for s in sent)
    for s in sent:
        assert _cut(paragraphs, s["line_text"]) == s["line_text"], s["line_text"]
    assert all(len(_cut(paragraphs, s["line_text"])) < len(SPEECH) for s in sent)


def test_a_sentences_inner_space_is_kept_as_the_book_writes_it_and_its_indent_and_line_breaks_go(tmp_path):
    # why: Anki Miner's unit keeps a space inside a paragraph (「叔父さん‼　只今帰りました。…」, an Aozora novel) and
    # its cut is exact; the old squeezed sentence named no unit exactly (the 6 misses in 4,070 measured on 30 works)
    book = tmp_path / "杜子春.txt"
    book.write_text("　「大丈夫です‼　決して声なぞは出しはしません。」\r\n　今夜は 冒険。　\r\n", encoding="utf-8")
    read, _tokens = cues.reading(str(book), "ja")
    texts = [c.text for c in read]
    assert texts[0] == "「大丈夫です‼　決して声なぞは出しはしません。」", "the full-width space kept, the indent out"
    # a half-width space the tokenizer itself takes out of its sentence: the sentence as the tokenizer gives it, as
    # before (rare in a Japanese book: 31 of 16,371 sentences measured, nearly all a Latin phrase's)
    assert texts[1] == "今夜は冒険。"
    assert all(t == t.strip() and "\n" not in t and "\r" not in t for t in texts)


@pytest.mark.parametrize("line, sent", [
    ("「大丈夫です。", "大丈夫です。"),                                         # a speech's first sentence
    ("命がなくなつても、黙つてゐます。」", "命がなくなつても、黙つてゐます。"),          # its last
    ("「『行くぞ。", "行くぞ。"),                                              # two openers, both alone
    ("それは本当だ。』」", "それは本当だ。"),
    ("「日は暮れるし、腹は減るし――死んでしまつた方がましかも知れない。」",              # a whole quote: kept
     "「日は暮れるし、腹は減るし――死んでしまつた方がましかも知れない。」"),
    ("次第によっては危険なことになりはしないかな」蕗屋はそれを色々と考えて見た。",       # a mark mid-sentence: kept
     "次第によっては危険なことになりはしないかな」蕗屋はそれを色々と考えて見た。"),
    ("「お止しよ」と言って「はい。", "「お止しよ」と言って「はい。"),                   # its lone 「 is inside: kept
    ("「はい。」と言って「お止しよ。", "「はい。」と言って「お止しよ。"),
    ("「　お止しよ。", "お止しよ。"),                                           # the space it leaves goes too
    ("彼は「もう帰る。", "彼は「もう帰る。"),                                     # an opener inside: kept
    ("（注。", "注。"),
    ("「行くぞ。』", "行くぞ。"),                                              # another family's closer: no partner
    ("「", "「"),                                                          # nothing left: as it was
    ("", ""),
])
def test_a_book_line_drops_only_a_lone_quote_mark_at_its_start_or_end(line, sent):
    # why: dropping a lone mark at an end keeps the sentence an exact piece of its paragraph (Anki Miner still cuts to
    # it); adding the partner or dropping one inside would make it no piece at all, and the card the whole speech
    assert pick.book_line(line) == sent


def test_a_books_word_is_cut_from_a_sentence_within_the_learners_length_before_an_earlier_one_outside_it(tmp_path):
    # why (PROVISIONAL, lean: cards honour the Length setting too): Mattias set 10–50 and got a 200-character card;
    # among a word's sentences one in the range comes first, as the report's examples do — a word whose sentences are
    # all outside it still gets the earliest, whole, never cut short. 空 in three sentences: 51, 3 and 38 characters
    book = tmp_path / "杜子春.txt"
    book.write_text("　空には、もう細い月が、うらうらと靡いた霞の中に、まるで爪の痕かと思ふ程、かすかに白く浮んでゐるのです。\n"
                    "　空だ。\n"
                    "　しかし杜子春は相変らず、門の壁に身を凭せて、ぼんやり空ばかり眺めてゐました。\n", encoding="utf-8")
    read, tokens = cues.reading(str(book), "ja")
    key = next((t.lemma, t.reading) for t in tokens if t.surface == "空")

    def line(lengths):
        # every other word known: each sentence is i+1 for 空, so only the Length tells them apart
        got = pick.pick(read, tokens, "ja", lambda k: k != key, mode="list", listed={key: 0}, sentence_length=lengths)
        return got["words"][0]["line_text"]
    assert line(None).startswith("空には、"), "no setting handed in: as before, the earliest"
    assert line((10, 50)).startswith("しかし杜子春は"), "the one within 10–50"
    assert line((10, 60)).startswith("空には、"), "both within: the earliest"
    assert line((0, 4)) == "空だ。", "a short range: the short one"
    assert line((40, 45)).startswith("空には、"), "none within: too long before too short, as the report's go"
    assert line((60, 80)).startswith("空には、"), "every one too short: the earliest, whole"
    assert line((3, 37)) == "空だ。", "its bounds are inside it: 3 characters is not too short for 3"
    assert line((4, 38)).startswith("しかし杜子春は"), "nor 38 too long for 38"


def test_a_videos_card_lines_never_read_the_length():
    # why: video and audio cards keep Michi-CL's rules (the line, its expansion, the 8 s cap) — a sentence length
    # there would move a learner's video mining
    read = cues.read(EPISODE, "ja")
    tokens = cues.tokens(read, "ja")
    plain = pick.pick(read, tokens, "ja", lambda k: False, mode="unknown")
    for lengths in ((10, 50), (0, 4), (60, 80)):
        assert pick.pick(read, tokens, "ja", lambda k: False, mode="unknown", sentence_length=lengths) == plain


class _Picked(Exception):
    pass


@pytest.mark.parametrize("logic, lengths", [
    ({"context": {"min_chars": 12, "preferred_max_chars": 40}}, (12, 40)),
    ({}, (10, 50)),                                         # the settings' own defaults
])
def test_the_pick_verb_hands_a_books_pick_the_learners_length(monkeypatch, logic, lengths):
    # why: the setting reaches a book's pick only through the verb — a pick never handed it orders as before
    got = {}
    monkeypatch.setattr(verbs, "settings", lambda: {"target_language": "ja", "logic": logic})
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda *a, **k: None)
    monkeypatch.setattr(verbs, "_known_test", lambda *a: (lambda key: False))
    monkeypatch.setattr(pick, "carded", lambda *a, **k: (set(), "anki"))

    def picked(*a, **kw):
        got.update(kw)
        raise _Picked()
    monkeypatch.setattr(pick, "pick", picked)
    for reading, want in ((BOOK, lengths), (None, None)):
        got.clear()
        with pytest.raises(_Picked):
            verbs.pick(SimpleNamespace(lang="ja", file=BOOK if reading else EPISODE, video=None, words="unknown",
                                       job="bs", wait=0.0, made=set(), listed={}, reading=reading))
        assert got["sentence_length"] == want
