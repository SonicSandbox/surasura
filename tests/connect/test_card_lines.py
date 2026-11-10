"""Which subtitle lines a card holds (app/connect/pick.py `window`, card lines, Sonic 2026-11-09).

Streaming subtitles never end a line in 。 and space lines ~83 ms apart, so the punctuation rule joined nearly every
card across five lines and two speakers. The rule now: a Japanese line runs on by its grammar (its last word, read
from the analyzer's own tokens); a card the punctuation rule makes in 4.5 s or less stays as it is ("a pass between
2 characters"); a card never runs past 8 s; a word prefers an occurrence the cap doesn't cut; a line shown again
counts as the line it repeats. The lines are counted as Anki Miner counts them (it drops a line with no Japanese).

Every line here is written for these tests (natural Japanese, no show's lines). Times are seconds; streaming lines
sit 83 ms apart, as SubsPlease's do.
"""
import pytest

from app import analyzer, cues
from app.connect import pick

GAP = 0.083


@pytest.fixture(autouse=True)
def _a_japanese_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


def _srt(tmp_path, lines, name="episode.ja.srt"):
    """An .srt of `lines` [(start s, end s, text)]."""
    def stamp(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    body = "\n".join(f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n" for n, (a, b, text) in enumerate(lines, 1))
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def _stream(texts, each=2.5, start=0.0):
    """Streaming lines: each `each` s long, 83 ms apart."""
    out, at = [], start
    for text in texts:
        out.append((at, at + each, text))
        at += each + GAP
    return out


def _window(tmp_path, lines, at, language="ja"):
    read = cues.read(_srt(tmp_path, lines), language)
    return pick.window(read, at, pick.Lines(read, cues.tokens(read, language), language))


def _expansion(tmp_path, lines, at, language="ja"):
    before, after, _cut, _ms = _window(tmp_path, lines, at, language)
    return [before, after]


def _by_word(chosen):
    return {w["word"]: w for w in chosen["words"]}


# --------------------------------------------------------------------------- #
# Rule 1: the grammar of a line's end
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, forward, back", [
    ("駅の前で友達に会って", True, True),           # a て-form
    ("雨が降ったら", True, True),                    # 仮定形 (たら)
    ("明日 晴れるなら", True, True),                 # なら
    ("村に恵みをもたらし", True, True),              # 連用形
    ("先生に", True, True),                          # a case particle
    ("駅前の", True, True),                          # の as a case particle runs on…
    ("本当に行くの", False, False),                  # …as a sentence-final one it ends
    ("彼が来るって", False, False),                  # って ends
    ("それは君と…", False, False),                   # the ellipsis ends it before its と
    ("この店は", True, True),                        # a binding particle
    ("そんなことばっかり", True, True),              # an adverbial particle
    ("何も言わず", True, True),                      # ず
    ("あの日から僕はずっと", True, True),            # an adverb after other words
    ("なるほど", False, False),                      # an adverb alone is a reply
    ("会議が終わったのち", True, True),              # a noun-conjunction (のち)
    ("試験に受かるため", True, True),                # ため
    ("お腹すいたから", True, False),                 # a plain から: forward only
    ("だから", True, False),
    ("もう遅いですから", False, False),              # ですから ends
    ("もう決めましたから", False, False),            # …and a polite past or negative before it (adversary #5)
    ("そんなこと知りませんので", False, False),
    ("今日は早く寝ますので", False, False),          # ますので ends (UniDic: の + で)
    ("電車が止まったので", True, False),             # a plain ので: forward only
    ("駅から", True, True),                          # から as "from" is a case particle
    ("どんな理由があるにせよ", True, True),          # a tail
    ("どっちにしろ", True, True),                    # concessive: after a case particle に
    ("まだ子供とはいえ", True, True),                # the other tails, by their text
    ("頭では分かっているものの", True, True),
    ("もう勝手にしろ", False, False),                # an order (the copula's に): ends (adversary #4)
    ("これで何もなきゃ", True, True),                # なきゃ: "if not" as often as "must" (adversary #7: ASK lead)
    ("食べちゃ", True, True),                        # ては: runs on into ダメ
    ("言いたいことは分かるけど", False, False),      # けど ends
    ("こんなに頑張ってるのに", True, True),          # UniDic reads のに as の + に (PROVISIONAL: ASK lead)
    ("今日は寒いし", False, False),
    ("そうだね", False, False),                      # a sentence-final particle
    ("明日また来よう", False, False),                # volitional
    ("早く座れ", False, False),                      # imperative
    ("ほら", False, False),                          # an interjection
    ("田中さん", False, False),                      # a name
    ("それで➡", True, True),                         # an arrow
    ("待ってくれ、", True, True),                    # a comma
    ("本当に知らないんだ…", False, False),           # an ellipsis ends
    ("＜こうして冬は過ぎ＞", False, False),          # a closing ＞ ends, as 》 does
])
def test_a_lines_last_word_says_whether_it_runs_on(tmp_path, text, forward, back):
    read = cues.read(_srt(tmp_path, [(1, 3, text)]), "ja")
    lines = pick.Lines(read, cues.tokens(read, "ja"), "ja")
    assert (lines.runs_on(0, True), lines.runs_on(0, False)) == (forward, back)


def test_two_speakers_83_ms_apart_are_two_cards(tmp_path):
    # The cause: neither line ends in 。, so the punctuation rule joined them (5.1 s, over the pass)
    lines = _stream(["今日は雨が降るらしい", "傘なら玄関にあるよ"])
    assert _expansion(tmp_path, lines, 0) == [0, 0]
    assert _expansion(tmp_path, lines, 1) == [0, 0]


def test_a_te_line_runs_into_its_verb(tmp_path):
    lines = _stream(["駅の前で友達に会って", "一緒に映画を見に行った", "楽しかったよ"])
    assert _expansion(tmp_path, lines, 0) == [0, 1]
    assert _expansion(tmp_path, lines, 1) == [1, 0]          # pulled in from before: the verb's line keeps its て
    assert _expansion(tmp_path, lines, 2) == [0, 0]


def test_a_plain_kara_runs_into_its_main_clause_but_desu_kara_ends(tmp_path):
    plain = _stream(["お腹すいたから", "何か食べに行こう"])
    assert _expansion(tmp_path, plain, 0) == [0, 1]
    assert _expansion(tmp_path, plain, 1) == [0, 0]          # a reason line is never pulled in from before
    polite = _stream(["もう遅いですから", "今日はこれで失礼します"])
    assert _expansion(tmp_path, polite, 0) == [0, 0]


def test_nara_zu_zutto_and_nochi_run_on_and_naruhodo_alone_ends(tmp_path):
    assert _expansion(tmp_path, _stream(["明日 晴れるなら", "海に行こう"]), 0) == [0, 1]
    assert _expansion(tmp_path, _stream(["何も言わず", "部屋を出ていった"]), 0) == [0, 1]
    assert _expansion(tmp_path, _stream(["あの日から僕はずっと", "君を探していた"]), 0) == [0, 1]
    assert _expansion(tmp_path, _stream(["会議が終わったのち", "全員で食事に出かけた"]), 0) == [0, 1]
    naruhodo = _stream(["なるほど", "それで分かったよ"])
    assert _expansion(tmp_path, naruhodo, 0) == [0, 0]
    assert _expansion(tmp_path, naruhodo, 1) == [0, 0]


def test_a_closing_angle_bracket_ends_a_narration_line(tmp_path):
    lines = _stream(["＜こうして冬は過ぎ＞", "＜村に春が来た＞"], each=3.0)
    assert _expansion(tmp_path, lines, 0) == [0, 0]
    assert _expansion(tmp_path, lines, 1) == [0, 0]


# --------------------------------------------------------------------------- #
# Rule 2: a short pass stays
# --------------------------------------------------------------------------- #
def test_a_pass_between_two_characters_in_4_5_s_stays_as_it_is(tmp_path):
    # よ ends the line, but the punctuation rule's card is 2.6 s: "it's actually fine if it crosses"
    lines = [(10.0, 11.5, "先に行くよ"), (11.583, 12.6, "うん")]
    before, after, cut, ms = _window(tmp_path, lines, 0)
    assert ([before, after], cut, ms) == ([0, 1], False, 2600)


def test_a_card_just_over_the_pass_is_judged_by_its_grammar(tmp_path):
    lines = [(10.0, 12.0, "先に行くよ"), (12.083, 14.6, "うん 待ってるね")]     # 4.6 s
    assert _expansion(tmp_path, lines, 0) == [0, 0]


# --------------------------------------------------------------------------- #
# Rule 3: the 8 s cap · rule 4: the line preference
# --------------------------------------------------------------------------- #
def test_a_9_s_sentence_is_capped_before_8_s_lines_after_first(tmp_path):
    lines = _stream(["昨日 駅前の本屋で", "ずっと探していた小説を", "やっと見つけて", "買ってきた"], each=2.9)
    before, after, cut, ms = _window(tmp_path, lines, 0)
    assert ([before, after], cut) == ([0, 1], True)          # a third line would make it 8.9 s
    assert ms <= pick.CAP_MS
    before, after, cut, _ms = _window(tmp_path, lines, 2)
    assert ([before, after], cut) == ([0, 1], True)          # forward first (as Anki Miner adds), then back


def test_under_the_cap_the_words_own_sentence_comes_before_the_speakers_next_one(tmp_path):
    # A TV caption's 。➡: the sentence ended, the same speaker goes on. The line before is the word's own sentence;
    # the next sentence (9.2 s with both) is left out
    lines = _stream(["あの頃の私たちは 毎日のように", "川で遊んでいました。➡", "夏になると➡"], each=3.0)
    before, after, cut, _ms = _window(tmp_path, lines, 1)
    assert ([before, after], cut) == ([1, 0], False)         # its whole sentence fits: not "cut" (rule 4)
    assert _expansion(tmp_path, lines[1:], 0) == [0, 1]      # with room, the next sentence still joins (as before)


def test_a_single_10_s_line_is_kept_whole(tmp_path):
    lines = [(0.0, 10.0, "あの頃の僕たちは 毎日のように川で遊んで"), (10.083, 12.0, "暗くなるまで帰らなかった")]
    before, after, cut, ms = _window(tmp_path, lines, 0)
    assert ([before, after], ms) == ([0, 0], 10000) and cut   # the word's own line is never cut


def test_a_word_said_in_a_capped_sentence_and_a_short_one_is_cut_from_the_short_one(tmp_path):
    lines = _stream(["昨日 駅前の本屋で", "ずっと探していた小説を", "やっと見つけて", "買ってきた"], each=2.9)
    lines.append((40.0, 42.0, "この小説 本当に面白いね"))
    read = cues.read(_srt(tmp_path, lines), "ja")
    tokens = cues.tokens(read, "ja")
    chosen = _by_word(pick.pick(read, tokens, "ja", lambda key: key[0] != "小説", mode="unknown"))
    assert chosen["小説"]["line_start"] == 40.0 and chosen["小説"]["line_expansion"] == [0, 0]


def test_the_previous_sentence_waits_for_the_words_own_too(tmp_path):
    # the line before ends its own sentence (。➡): the word's sentence runs on after, so that comes first
    lines = _stream(["それは昔の話です。➡", "あの頃の私たちは 毎日のように", "川で遊んでいました。"], each=3.0)
    before, after, cut, _ms = _window(tmp_path, lines, 1)
    assert ([before, after], cut) == ([0, 1], False)


def test_when_every_card_of_a_word_is_capped_the_shortest_is_taken(tmp_path):
    long = _stream(["昨日 駅前の本屋で", "ずっと探していた小説を", "やっと見つけて", "買ってきた"], each=3.9)
    short = _stream(["今朝 図書館の前で", "前から読みたかった小説を", "友達から借りて", "そのまま読んだ"], each=2.9,
                    start=60.0)
    read = cues.read(_srt(tmp_path, long + short), "ja")
    tokens = cues.tokens(read, "ja")
    lines = pick.Lines(read, tokens, "ja")
    assert pick.window(read, 1, lines)[2] and pick.window(read, 5, lines)[2]        # both cut by the cap
    chosen = _by_word(pick.pick(read, tokens, "ja", lambda key: key[0] != "小説", mode="unknown"))
    assert chosen["小説"]["line_start"] == read[5].start / 1000


def test_a_line_no_other_word_took_still_comes_before_the_cap(tmp_path):
    # The cap's preference never outranks i+1's: the uncut card has another new word, so the capped one is taken
    lines = _stream(["昨日 駅前の本屋で", "ずっと探していた小説を", "やっと見つけて", "買ってきた"], each=2.9)
    lines.append((40.0, 42.0, "この小説 本当に面白いね"))
    read = cues.read(_srt(tmp_path, lines), "ja")
    tokens = cues.tokens(read, "ja")
    chosen = _by_word(pick.pick(read, tokens, "ja", lambda key: key[0] not in ("小説", "面白い"), mode="unknown"))
    assert chosen["小説"]["line_start"] != 40.0


# --------------------------------------------------------------------------- #
# Rule 5: a line shown again
# --------------------------------------------------------------------------- #
def test_a_line_shown_again_through_another_speakers_line_runs_to_its_last_copy(tmp_path):
    # Netflix's way: the line stays on screen beside the other speaker's (both at its time), then shows again
    lines = [(7.0, 12.5, "早く逃げろって言ってるだろ"), (7.0, 12.5, "でも 置いていけない"),
             (12.5, 12.75, "早く逃げろって言ってるだろ"), (12.833, 15.0, "いいから行け")]
    before, after, cut, ms = _window(tmp_path, lines, 0)
    assert ([before, after], cut, ms) == ([0, 2], False, 5750)   # the clip ends with the speech
    assert _expansion(tmp_path, lines, 2)[0] == 2                 # from the copy: back to the first showing


def test_a_short_pass_still_ends_with_its_lines_last_copy(tmp_path):
    # adversary #1: the punctuation rule's card is short (kept), but the line it ends on is shown again: the clip
    # runs to the copy's end, so it ends with the speech
    lines = [(10.0, 11.5, "何だって！"), (11.5, 11.75, "何だって！"), (11.5, 11.75, "えっ"), (13.0, 15.0, "どういうこと？")]
    before, after, cut, ms = _window(tmp_path, lines, 0)
    assert ([before, after], ms) == ([0, 1], 1750)


def test_a_run_of_copies_is_capped_too(tmp_path):
    # adversary #2: six showings of one cheer are 9.4 s: only the copies within 8 s, and the card counts as cut
    lines = _stream(["頑張れ"] * 6, each=1.5)
    lines = [(a, b + 0.083 if i < 5 else b, t) for i, (a, b, t) in enumerate(lines)]       # each touches the next
    lines.append((20.0, 22.0, "みんな 頑張れって言ってる"))
    read = cues.read(_srt(tmp_path, lines), "ja")
    tokens = cues.tokens(read, "ja")
    before, after, cut, ms = pick.window(read, 0, pick.Lines(read, tokens, "ja"))
    assert ms <= pick.CAP_MS and cut and after < 5
    before, after, cut, ms = pick.window(read, 5, pick.Lines(read, tokens, "ja"))
    assert ms <= pick.CAP_MS and cut and before < 5                    # from the last showing, back: capped too
    chosen = _by_word(pick.pick(read, tokens, "ja", lambda key: key[0] != "頑張る", mode="unknown"))
    assert chosen["頑張る"]["line_start"] == 20.0                       # the whole sentence that fits wins


def test_a_single_line_over_8_s_does_not_fit_the_cap_for_rule_4(tmp_path):
    # adversary #3: a 10 s line that ends is not cut, but its card doesn't fit: the 2 s occurrence wins
    lines = [(0.0, 10.0, "あの頃の僕たちは 毎日のように川で遊んだよ"), (30.0, 32.0, "また川で遊ぼうよ")]
    read = cues.read(_srt(tmp_path, lines), "ja")
    tokens = cues.tokens(read, "ja")
    chosen = _by_word(pick.pick(read, tokens, "ja", lambda key: key[0] != "川", mode="unknown"))
    assert chosen["川"]["line_start"] == 30.0


def test_a_line_out_of_time_order_is_no_neighbour(tmp_path):
    # adversary #8: an .ass file's events needn't be in time order; a line 8 s later in time but before in the file
    # never runs into this one (nor cuts it)
    lines = [(20.0, 22.0, "それから二人で"), (10.0, 12.0, "駅の前で友達に会って"), (12.083, 14.0, "一緒に映画を見に行った"),
             (22.083, 24.0, "家に帰った")]
    before, after, cut, _ms = _window(tmp_path, lines, 1)
    assert ([before, after], cut) == ([0, 1], False)


def test_two_lines_shown_together_are_neighbours_whichever_starts_first(tmp_path):
    # an .ass caption row: the second event in the file may start a moment before the first
    lines = [(5.0, 7.0, "駅の前で友達に会って"), (4.8, 8.0, "一緒に映画を見に行った")]
    assert _expansion(tmp_path, lines, 0) == [0, 1]


def test_a_neighbours_copies_come_with_it(tmp_path):
    # the line after (and the line before) shown twice counts as one of the two lines a side
    # (each line 2 s: past the 4.5 s pass, so the grammar walk adds them)
    ahead = _stream(["昨日 駅前の本屋で", "前から探していた小説を"], each=2.0)
    ahead += [(4.166, 6.0, "ついに見つけた"), (6.0, 6.2, "ついに見つけた")]
    assert _expansion(tmp_path, ahead, 0) == [0, 3]
    behind = [(0.0, 2.5, "昨日 駅前の本屋で"), (2.5, 2.7, "昨日 駅前の本屋で")]
    behind += _stream(["前から探していた小説を", "ついに見つけた"], each=2.5, start=2.783)
    assert _expansion(tmp_path, behind, 3) == [3, 0]


def test_a_later_copy_with_no_words_of_its_own_runs_on_by_its_first(tmp_path):
    # Generate counts a repeated line once (Kotoba-R): its copy may carry no tokens; the copy still runs on as the
    # line it repeats
    lines = [(0.0, 2.5, "駅の前で友達に会って"), (2.5, 2.7, "駅の前で友達に会って"), (2.783, 5.5, "一緒に映画を見に行った")]
    read = cues.read(_srt(tmp_path, lines), "ja")
    tokens = [t for t in cues.tokens(read, "ja") if t.cue != 1]
    assert pick.window(read, 1, pick.Lines(read, tokens, "ja"))[:2] == (1, 1)


def test_two_lines_with_no_japanese_between_still_count_as_anki_miners_neighbours(tmp_path):
    # with the sign counted, the second line's て would stop at the sign and the third line be lost
    lines = [(0.0, 2.5, "昨日 駅前の本屋で"), (2.583, 5.0, "友達に会って"), (5.083, 5.5, "EXIT"),
             (5.583, 8.0, "映画を見た")]
    assert _expansion(tmp_path, lines, 0) == [0, 2]
    assert _expansion(tmp_path, lines, 3) == [2, 0]          # back past the sign: the sign isn't a line that ends


def test_a_copy_counts_as_its_line_for_joining(tmp_path):
    # the て line shown twice still runs into its verb, and the copy isn't one of the two lines a side
    lines = [(0.0, 2.5, "駅の前で友達に会って"), (2.5, 2.7, "駅の前で友達に会って"),
             (2.783, 5.5, "一緒に映画を見に行った")]
    assert _expansion(tmp_path, lines, 0) == [0, 2]
    assert _expansion(tmp_path, lines, 2) == [2, 0]


def test_a_line_between_at_another_time_breaks_the_copy(tmp_path):
    # the other speaker's line is on screen at neither copy's time: the second 大丈夫だよ is said again, not shown again
    lines = [(0.0, 5.0, "大丈夫だよ"), (5.0, 6.0, "本当に？"), (5.05, 5.5, "大丈夫だよ")]
    assert _expansion(tmp_path, lines, 0) == [0, 0]


def test_a_copy_never_starts_before_the_line_it_repeats(tmp_path):
    # an .ass file's events needn't be in time order: the same text shown earlier on screen is not a copy of it
    lines = [(5.0, 10.0, "大丈夫だよ"), (4.0, 4.5, "大丈夫だよ")]
    assert _expansion(tmp_path, lines, 0) == [0, 0]


def test_the_same_text_said_again_later_is_not_a_copy(tmp_path):
    lines = [(0.0, 2.5, "大丈夫だよ"), (2.583, 5.0, "本当に？"), (6.0, 8.0, "大丈夫だよ")]
    assert _expansion(tmp_path, lines, 0) == [0, 0]


# --------------------------------------------------------------------------- #
# Anki Miner's lines · Chinese · books
# --------------------------------------------------------------------------- #
def test_a_line_with_no_japanese_is_not_counted_as_anki_miners_line(tmp_path):
    # Anki Miner 3.10.1+ drops it, so [0, 1] reaches 一緒に… in its list, not the sign
    lines = [(0.0, 2.5, "駅の前で友達に会って"), (2.583, 3.0, "EXIT"), (3.083, 5.5, "一緒に映画を見に行った")]
    assert _expansion(tmp_path, lines, 0) == [0, 1]


def test_chinese_keeps_the_punctuation_rule(tmp_path):
    lines = _stream(["我觉得", "这家店的面条很好吃。", "我们明天再来吧。"])
    assert _expansion(tmp_path, lines, 0, "zh") == [0, 1]      # unfinished: runs on, as before
    assert _expansion(tmp_path, lines, 2, "zh") == [0, 0]


def test_chinese_is_capped_too(tmp_path):
    lines = _stream(["昨天我在车站前面的书店里", "找到了我一直在找的那本小说", "然后我就马上买了下来", "回家看了一晚上"],
                    each=2.9)
    before, after, cut, _ms = _window(tmp_path, lines, 0, "zh")
    assert ([before, after], cut) == ([0, 1], True)


def test_a_last_word_the_tagger_gave_no_node_says_nothing_runs_on(tmp_path):
    # a token whose node couldn't be matched (cues._read): the line ends, as a line with no words does
    read = cues.read(_srt(tmp_path, [(1, 3, "駅の前で友達に会って")]), "ja")
    tokens = cues.tokens(read, "ja")
    tokens[-1] = tokens[-1]._replace(node=None)
    assert pick.Lines(read, tokens, "ja").runs_on(0) is False


def test_a_books_sentence_is_its_own_card_even_when_it_has_no_end_mark(tmp_path):
    # a book's sentence that a line break ends, not a 。: still its own card, never its neighbour's
    path = tmp_path / "book.txt"
    path.write_text("駅の前で友達に会って\n一緒に映画を見に行った。", encoding="utf-8")
    read, _tokens = cues.reading(str(path), "ja")
    assert len(read) == 2 and pick.window(read, 0) == (0, 0, False, 0)


def test_a_books_sentence_is_its_own_card(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text("駅の前で友達に会って、一緒に映画を見に行った。とても楽しかった。", encoding="utf-8")
    read, _tokens = cues.reading(str(path), "ja")
    assert read.units and pick.window(read, 0) == (0, 0, False, 0)
    assert pick.line_expansion(read, 0) == [0, 0]
