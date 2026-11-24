"""The sentence table (the sentence choice, SPEC § 3): every candidate sentence of every list word, kept as numbers.

Generate writes it (`results/sentences.bin`) beside the plan file while `plan_rules.SENTENCE_TABLE >= 1`; a reader
opens its head once, then reads only its own words' blocks. A line is kept if and only if its word is a row of the
list, it is a sentence of a file the Generate read, and — but for a file's first sentence of the word, kept with the
OVER mark and never chosen — it is no longer than *Never longer than*. Its text is not kept: a reader takes the text
of the few lines it shows from the token store (`Store.file_tokens`).

What is kept for a line (one row of the table is a line and its word):
  its file (the plan's numbering: its files, then the Finished ones) · its place in the file (the sentence number) ·
  its length in characters · its marks (OVER) · a fingerprint of its text (0 when no other line of the word says the
  same words) · the other words in it that are new, as co-words — each a formula over the list's rows ("known once
  any of these groups of rows is taught"), so "new when studied" is worked out for whatever the order has become ·
  the set phrases in it, as their rows · how many words besides the word it says · where the word starts.

The file: MAGIC, three little-endian 4-byte lengths, the head (zlib JSON: the format's version, the engine, the run's
signature, the language, every list row's (word, reading) and its place in the list, the rows that have lines and
each one's sizes — the head is the index), the sources (zlib JSON: [rel, kind, digest]), the formulas (zlib, four
int32 arrays), then one zlib block a row: its lines' columns one after another, lines in (file, place) order.
Little-endian always; the head's keys in a fixed order; one compression level; no time, path of this PC or process id
inside: the same run writes the same bytes, packed as the walk goes or at the end.

The walk's side is `Packer`: lines are appended as the files are read, words, co-words and phrases by whatever key
the walk holds them by; `finish` resolves the keys (rows, formulas numbered by key) only at the end, so one file's
lines are a function of that file alone. Each line's two numbers can be worked out on other cores (`Cores`, E-CORES:
the walk's order kept, the answers written in at the end).

numpy is imported here only, at its first use (`_np`: never at this module's import — a walk worker and the indexer's
workers read lines and never load it), through `sentence_score.numpy_one_thread` (its BLAS held to one thread); the
cost of a line is E-SCORE's (`app/sentence_score.py`).
"""
import gzip
import json
import os
import re
import struct
import time
import zlib
from array import array
from operator import itemgetter

TABLE_FILE = "sentences.bin"
MAGIC = b"SURATBL\n"
VERSION = 3                     # 3: each row's place in the list · 2: the two word numbers counted (1 wrote 0)
LEVEL = 3                       # zlib: 0.44 s for 7.01 MB at 20,000 files (lighter 7.42 MB, harder 1.15 s: SPEC § 8.2)

OVER = 1 << 2                   # marks: over *Never longer than* (a file's first sentence of the word; never chosen)
STARTS_PAST = 255               # where the word starts: 255 = at or past 255 characters
_SEP = (",", ":")
_numpy = None


def _np():
    """numpy, imported at its first use (a process that only reads lines never pays for it: ~16 MB a walk worker),
    with its BLAS held to one thread — `sentence_score.numpy_one_thread`, the one door to it."""
    global _numpy
    if _numpy is None:
        from app import sentence_score
        _numpy = sentence_score.numpy_one_thread()
    return _numpy


# "Words besides the word" (SPEC § 3.2, decision 9b): the line's content words that are not the word — a place or a
# thing counts, a person the line is about counts (a particle or だ / です follows the name), a person's name said as
# a call does not (it stands free: the line's end, a mark after it, or a word with no particle). The token store keeps
# no part of speech, so grammar is told by its base form, from these fixed lists (general Japanese and jieba's own
# table, never a user's library: the build script says how); a person's name is one of the library's names, the
# lemmas Ignore names reads (`names.name_words`).
# --- grammar words: scripts/build_sentence_words.py writes this block ---
_JA_PARTICLES = (  # ja particles (UniDic 助詞): 73
    "い え か かし かしら から が きり くらい け けれど けん こそ さ さえ し しか しき しも じゃん すけ すら ずつ ぜ ぞ たって たら たり だけ だに ちょ って つつ て てん "
    "で でも と とか とて とも ど どころ な ながら など なんぞ なんて に にて ね ねん の のう のみ のん は ば ばい ばかり へ べい ほど まで も もの や やら よ より わ を "
    "をば"
)
_JA_SUFFIXES = (  # ja suffixes (接尾辞): 179
    "がかる がてら がり がる ごと さん しな たん だらけ ちゃん っこ っこい っぺ っ子 つ ばむ ぽい めく やん 並み 丼 乍ら 亭 付き 令 位 作 個 児 共 兼ねる 冊 冠 刊 制 剤 "
    "勝ち 勢 化 匹 医 卒 博 史 合い 同士 向き 向け 吹き 員 問 器 団 圏 園 型 堂 塗れ 士 大 婦 学 官 宛て 室 寄り 尽くし 屋 展 師 帳 干し 庫 建て 弱 張り 強 弾き 性 "
    "択 持ち 振り 捲り 掛かり 掛け 揚げ 撃 擬き 放し 教 料 族 易い 書 書き 末 材 来 枚 架 校 業 権 歳 歴 殿 毎 氏 気触れ 沿い 派 流 浪 済み 渓 温 滴 漬け 灯 炒め "
    "焼き 煮 犯 状 生 産 用 界 病 症 痛 発 的 省 眼 研 砲 祭 科 立 等 系 紀 級 絡み 置き 羽 腫 臭 菜 葬 蒸し 行き 製 観 記 証 誌 調 費 越し 路 軒 込み 進 遍 "
    "過ぎ 達 野 長 限 隊 隻 集 難い 電 類 飼い 館"
)
_JA_GRAMMAR = (  # ja other grammar: auxiliaries, prefixes, interjections, conjunctions: 220
    "ああ ああん あい あう あかん あちゃ あっ あの あは あはは あばよ あら あれ あん あー あーと いいえ いえ いけ いざ いや いやはや いー うい うう ううん うお うふふ うふん "
    "うむ うわ うん うんと うー えい ええ えっ えへ えー えーと おい おお おおい おっ おっと おや おら おー き きゃあ ぎゃあ くう くそ けえ けり こら ごとし さあ させる さて "
    "さようなら さらば ざます しい しめる じ じゃ すん ず ずら せる そして その そら それ た たい たがる たげる たる だ ちまう ちゃう ちゃる つう てく てらっしゃる てる です "
    "とく とる どい どれ なあ ない なり なんだ なんちゃって ぬ ねえ はあ はい はっ はは ははは はる はん はーん ひい ひえ ひゃあ ひょう ふう ふふ ふふふ ふふん ふむ ふん へい "
    "へえ へん べし ほい ほう ほえ ほっ ほな ほほう ほら ほれ まい ます まー む もしもし やあ やい やがる やす やった やれ やんや よいしょ よう よし よっしゃ よる らし らしい "
    "らむ られる り れる わあ わあい わっしょい んす んっ んー 一大 不 且つ 両 乃至 亜 今日は 今晩は 但し 全 再 初めまして 副 即ち 及び 反 各 向 否 否々 唯 多 好 小 当 御 "
    "御早う 或いは 扠 新 最 有 有り難う 未 殺 汚 活 準 無 然う然う 然し 然も 相 突 第 約 素 細 終 総 義 老 聖 若しくは 計 誤 超 静 非 飛 高"
)
_JA_HELPERS = (  # ja helping verbs (非自立可能): grammar right after て / で: 66
    "いらっしゃる さす そびれる 上げる 下さる 交わす 仕舞う 付く 付ける 出す 出来る 切る 切れる 去る 参る 合う 呉れる 回る 始める 尽くす 居る 得る 御座る 忘れる 慣れる 成る 抜く "
    "抜ける 捲る 掛かる 掛ける 損なう 有る 来たる 来る 果たす 果てる 欲しい 渡る 為さる 為る 無い 熟す 直す 終える 終わる 給う 続く 続ける 置く 致す 良い 行く 見せる 見る 貰う "
    "込む 通す 遅れる 遊ばす 過ぎる 遣る 間違う 間違える 頂く 願う"
)
_ZH_GRAMMAR = (  # zh: jieba's particles, prepositions, conjunctions, interjections: 149
    "不仅 不但 不免 不如 不是 不管 不论 不过 与 与其 与此同时 为 为了 么 之 之所以 也好 了 于 于是 从 从此 从而 以 以为 以便 以及 以外 似的 但 但是 何况 依据 依照 倘若 "
    "关于 再说 凭 即使 即便 及 及其 及时 反而 另一方面 另外 只不过 只怕 只是 只有 只要 可以 可是 同 同时 向 吗 否则 吧 呀 呢 呵 和 哩 啦 嗯 嘛 因 因为 因此 因而 在 在内 "
    "地 如果 如此 对 对于 尽管 并 并且 并非 得 总是 或 或是 或者 所 所以 所说 把 按 按照 据 接着 无论 既 既有 既然 是 替 来看 来说 根 根据 此后 此外 此时 比 然 然后 "
    "然而 用 由 由于 由此 的 的话 着 等 等等 经过 给 而 而且 而已 而是 而言 自 自从 至 至于 般 般的 若 虽然 被 要是 跟 过 还是 还要 通过 针 针对 除 除了 随着 顺"
)
# --- end of the block ---
_TITLES = frozenset(("さん", "君", "くん", "ちゃん", "様", "さま", "氏", "博士", "先生", "夫人", "殿", "卿", "警部", "刑事",
                     "捜査官", "大佐", "中佐", "少佐", "大尉", "中尉", "少尉", "将軍", "提督", "艦長", "船長", "議員", "大統領",
                     "長官", "教授", "王", "女王", "王子", "姫", "軍曹", "保安官", "隊長", "達", "たち", "ら"))   # after a name
_COPULA = frozenset(("だ", "です"))
_AFTER_TE = frozenset(("て", "で", "って", "ちゃ", "じゃ"))
_NAME_LINKS = frozenset(("・", "･", "＝", "="))     # フランク・ライアン: one name
_NUMERALS = frozenset("〇一二三四五六七八九十百千万億兆")
_KATAKANA = re.compile(r"[\u30a0-\u30ff]+")
_LINK_1, _LINK_2, _LINK_3, _LINK_4 = sorted(_NAME_LINKS)     # asked of a line one by one: no regex call
_ISALPHA = str.isalpha
_LISTS = {}


def _lists(language):
    """(every grammar word, the particles, the helping verbs, the suffixes) by base form, built once a language."""
    found = _LISTS.get(language)
    if found is None:
        if language == "ja":
            particles, suffixes = frozenset(_JA_PARTICLES.split()), frozenset(_JA_SUFFIXES.split())
            found = (particles | suffixes | frozenset(_JA_GRAMMAR.split()), particles, frozenset(_JA_HELPERS.split()),
                     suffixes | _TITLES)
        else:
            try:
                from app.cedict_data import interjections
                said = frozenset(interjections())
            except Exception:
                said = frozenset()
            found = (frozenset(_ZH_GRAMMAR.split()) | said, frozenset(), frozenset(), frozenset())
        _LISTS[language] = found
    return found


class LineWords:
    """One line's two numbers for each word in it: how many words besides the word it says, and where the word starts
    (in characters). Made once a line, from the token store's tokens (lemma, reading, surface, spelling) and its text;
    `people`: the library's people's names (lemmas). A name of several pieces (フランク・ライアン, linked by ・ or =)
    is one name, held by its first piece — and the word itself when the word is one of its pieces.

    Made for every line the table keeps (a million at 20,000 files), so in one pass over the tokens, the tests done in
    C where the language has them; a line that holds a name link (・ ･ ＝ =) takes `_linked`, the rule written out
    whole. Both give the same numbers: tests/test_sentence_table_speed.py checks them on every line it has."""
    __slots__ = ("tokens", "at", "head", "counted", "total")

    def __init__(self, tokens, text, language, people=frozenset()):
        grammar, particles, helpers, titles = _lists(language)
        self.tokens = tokens
        if _LINK_1 in text or _LINK_2 in text or _LINK_3 in text or _LINK_4 in text:   # a name link
            self._linked(tokens, text, grammar, particles, helpers, titles, people)
            return
        pos, find = 0, text.find
        at, counted, later = [], [], None
        put, mark = at.append, counted.append
        before = before_surface = None          # the token before's lemma and surface
        for lemma, _reading, surface, _orth in tokens:
            start = pos
            a = find(surface, pos)
            if a < 0:
                a = pos                         # a token the line's text doesn't hold (a quote mark cut off): here
            else:
                pos = a + len(surface)
            put(a)
            if lemma in grammar or not (surface.isalpha() or any(map(_ISALPHA, surface))):
                mark(False)                     # grammar · a mark
            elif (lemma in helpers and before is not None and a == start and before_surface in _AFTER_TE
                  and before in particles):
                mark(False)                     # a helping verb right after て / で: 見ている, 来てくれる
            elif len(surface) == 1 and a and (text[a - 1].isdigit() or text[a - 1] in _NUMERALS):
                mark(False)                     # a counter after its number (the number is no token): 三人, ２０分
            elif lemma in people:               # a person: counted unless a call, by what follows (below)
                if later is None:
                    later = []
                later.append(len(counted))
                mark(False)
            else:
                mark(True)
            before, before_surface = lemma, surface
        self.at, self.counted, self.head = at, counted, range(len(at))
        if later is not None:
            for i in later:
                counted[i] = self._about(i, text, particles, titles, people)
        self.total = sum(counted)

    def _gap(self, text, i):
        """The text between token i - 1 and token i (one the text doesn't hold ends where it starts)."""
        a, surface = self.at[i - 1], self.tokens[i - 1][2]
        return text[a + len(surface) if text.startswith(surface, a) else a:self.at[i]]

    def _about(self, i, text, particles, titles, people):
        """The person at token i is what the line is about — a particle or だ / です after the name and its titles —
        not a call (the line's end, a mark, or a word with no particle after it)."""
        tokens, j, n = self.tokens, i + 1, len(self.tokens)
        while j < n and (tokens[j][0] in people or tokens[j][0] in titles) and not self._gap(text, j).strip():
            j += 1                              # its title (ルーサー警部), or more of the name
        return j < n and not self._gap(text, j).strip() and (tokens[j][0] in particles or tokens[j][0] in _COPULA)

    def _linked(self, tokens, text, grammar, particles, helpers, titles, people):
        """A line that may hold a name link: the rule written out whole (a name of several pieces is one)."""
        n, pos = len(tokens), 0
        self.at, ends = [], []
        for lemma, reading, surface, _orth in tokens:
            a = text.find(surface, pos)
            if a >= 0:
                pos = a + len(surface)
            else:
                a = pos                         # a token the line's text doesn't hold (a quote mark cut off): here
            self.at.append(a)
            ends.append(pos)
        at = self.at

        def gap(i):                             # the text between token i - 1 and token i
            return text[ends[i - 1]:at[i]]

        def named(i):
            return tokens[i][0] in people or _KATAKANA.fullmatch(tokens[i][2]) is not None

        head = self.head = list(range(n))
        for i in range(1, n):
            if gap(i) in _NAME_LINKS and named(i - 1) and named(i):
                head[i] = head[i - 1]
        counted = [False] * n
        for i, (lemma, _r, surface, _o) in enumerate(tokens):
            if head[i] != i or lemma in grammar or not any(ch.isalpha() for ch in surface):
                continue                        # a later piece of a name (counted once, at its first) · grammar · a mark
            if lemma in helpers and i and not gap(i) and tokens[i - 1][2] in _AFTER_TE and tokens[i - 1][0] in particles:
                continue                        # a helping verb: 見ている, 来てくれる
            if len(surface) == 1 and at[i] and (text[at[i] - 1].isdigit() or text[at[i] - 1] in _NUMERALS):
                continue                        # a counter after its number (the number is no token): 三人, ２０分
            j = i + 1
            while j < n and head[j] == i:
                j += 1
            if any(tokens[k][0] in people for k in range(i, j)):
                while j < n and (tokens[j][0] in people or tokens[j][0] in titles) and not gap(j).strip():
                    j += 1                      # its title (ルーサー警部), or more of the name
                if not (j < n and not gap(j).strip() and (tokens[j][0] in particles or tokens[j][0] in _COPULA)):
                    continue                    # a call: the line's end, a mark, or a word with no particle after it
            counted[i] = True
        self.counted, self.total = counted, sum(counted)

    @property
    def keys(self):
        """Each token's (lemma, reading)."""
        return [(t[0], t[1]) for t in self.tokens]

    def _own(self, indices):
        return sum(self.counted[h] for h in {self.head[i] for i in indices})

    def of_word(self, key):
        """(words besides the word `key`, where it first starts)."""
        lemma, reading = key
        mine = [i for i, t in enumerate(self.tokens) if t[0] == lemma and t[1] == reading]
        if not mine:
            return self.total, 0
        return self.total - (self.counted[self.head[mine[0]]] if len(mine) == 1 else self._own(mine)), self.at[mine[0]]

    def of_span(self, a, b):
        """(words besides the set phrase on tokens a..b-1, where it starts)."""
        return self.total - self._own(range(a, min(b, len(self.tokens)))), self.at[a] if a < len(self.at) else 0


# One block's columns, in the order written: (name, little-endian dtype). `src` is written as the step from the line
# before (mostly 0) and read back whole.
COLUMNS = (("src", "<i4"), ("number", "<i4"), ("chars", "<u2"), ("marks", "u1"), ("ncow", "<u2"), ("nphr", "<u2"),
           ("fp", "<u4"), ("besides", "u1"), ("starts", "u1"))
_BYTES = sum(int(t[-1]) for _n, t in COLUMNS)    # (a type's last digit is its width in bytes: "<i4" 4)


# A line as the walk packs it (31 bytes, one `struct` call a line): its word's provisional id, its source, its place,
# its length, how many co-words and phrases follow, its hash, its marks, besides, where the word starts — and the
# same as numpy's type (`_LINE_COLUMNS`).
_LINE = struct.Struct("<iiiiiiIBBB")
_LINE_COLUMNS = [("word", "<i4"), ("src", "<i4"), ("number", "<i4"), ("chars", "<i4"), ("ncow", "<i4"),
                 ("nphr", "<i4"), ("hash", "<u4"), ("marks", "u1"), ("besides", "u1"), ("starts", "u1")]


class Packer:
    """The walk's side: lines appended as the files are read, as compact bytes (no Python object per line) — one
    `_LINE` a line, and the co-words' and phrases' ids one after another."""

    def __init__(self):
        self._ids, self._keys = {}, []          # any key (a word, a co-word) -> its provisional id; id -> key
        self._lines = bytearray()
        self._cow, self._phr = array("i"), array("i")     # co-words: provisional ids · set phrases: the walk's numbers
        self._held = ((), [])                   # the last line's co-words and their ids (a line offered for several words)

    def _id(self, key):
        found = self._ids.get(key)
        if found is None:
            found = self._ids[key] = len(self._keys)
            self._keys.append(key)
        return found

    def __len__(self):
        return len(self._lines) // _LINE.size

    def add(self, word, src, number, chars, text_hash, cowords=(), phrases=(), besides=0, starts=0, over=False):
        """One candidate line of `word` (the key its row is found by): sentence `number` of source `src`, `chars`
        long, its text's `text_hash` (`plan_rules.text_hash_of`), its other new words `cowords` (keys: a collection
        the caller does not change once passed, as the walk's sets) and set phrases `phrases`, the words `besides`
        the word it says, where the word `starts`; `over` *Never longer than*."""
        w = self._ids.get(word)
        if w is None:
            w = self._id(word)
        held = self._held
        if held[0] is cowords:
            ids = held[1]
        else:
            get = self._ids.get
            ids = [get(c) for c in cowords]
            if None in ids:
                ids = [self._id(c) for c in cowords]
            self._held = (cowords, ids)
        self._lines += _LINE.pack(w, src, number, chars, len(ids), len(phrases), text_hash & 0xFFFFFFFF,
                                  OVER if over else 0, besides if besides < 255 else 255,
                                  starts if starts < STARTS_PAST else STARTS_PAST)
        if ids:
            self._cow.extend(ids)
        if phrases:
            self._phr.extend(phrases)

    def fill(self, first, numbers):
        """The two numbers of the lines from `first` on (`numbers`: two bytes a line, as `numbers_of` makes them),
        packed 0 by the walk while another core worked them out (`Cores`)."""
        n = len(numbers) // 2
        if n:
            np = _np()
            lines = np.frombuffer(self._lines, _LINE_COLUMNS, n, first * _LINE.size)
            try:
                two = np.frombuffer(numbers, np.uint8).reshape(n, 2)
                lines["besides"] = two[:, 0]
                lines["starts"] = two[:, 1]
            finally:
                del lines           # the bytearray exported no longer: the walk may add again

    def finish(self, keys, row_of, clauses_of, own_row, key_order, phrase_row, sources, head, places=None):
        """-> the Table. `keys`: every list row's (word, reading), by row · `row_of(word key)` -> its row or None
        (not a row: its lines are dropped) · `clauses_of(co-word key)` -> its formula (`plan_rules` clauses; TRUE:
        known from the start, left out) · `own_row(co-word key)` -> its own row or -1 · `key_order(co-word key)`:
        the order co-words are numbered in (the plan's `_coword_key`) · `phrase_row(phrase)` -> its row or None ·
        `sources`: [[rel, kind, digest]] · `head`: {engine, run_signature, language} · `places`: each row's place in
        the list Generate wrote (the study order: 0 first), -1 off it; none given: every row -1.

        Worked on the packed arrays' own widths (views of them, not copies), each piece let go once used: it runs at
        the end of a Generate, when the run holds the most it will (SPEC § 6.2's peak)."""
        from app import plan_rules
        np = _np()
        if places is not None and len(places) != len(keys):
            raise ValueError(f"{len(places)} places for {len(keys)} rows")
        n_ids = len(self._keys)
        rows = np.full(n_ids, -1, np.int32)
        for p, key in enumerate(self._keys):
            k = row_of(key)
            if k is not None and k >= 0:
                rows[p] = k
        lines = np.frombuffer(self._lines, _LINE_COLUMNS) if self._lines else np.zeros(0, _LINE_COLUMNS)
        word, src, number, chars, ncow, nphr = (lines[c] for c in ("word", "src", "number", "chars", "ncow", "nphr"))
        line_row = rows[word]
        keep = line_row >= 0
        # every line once for its row, in (row, file, place) order — a line the walk offered twice is kept once
        order = np.lexsort((number, src, line_row))
        order = order[keep[order]]
        if len(order):
            r, s, n = line_row[order], src[order], number[order]
            same = np.zeros(len(order), bool)
            same[1:] = (r[1:] == r[:-1]) & (s[1:] == s[:-1]) & (n[1:] == n[:-1])
            order = order[~same]
            del r, s, n, same

        # co-words: only those a kept line names, numbered by key; known from the start (TRUE) left out
        cow = _view(self._cow, np.int32)
        cow_line = np.repeat(np.arange(len(ncow), dtype=np.int32), ncow)
        used = np.zeros(n_ids, bool)
        used[cow[keep[cow_line]]] = True
        formulas, final = [], np.full(n_ids, -1, np.int32)
        named = sorted((key_order(self._keys[p]), p) for p in np.flatnonzero(used).tolist())
        for _order, p in named:
            clauses = clauses_of(self._keys[p])
            if clauses != plan_rules.TRUE:
                final[p] = len(formulas)
                formulas.append((own_row(self._keys[p]), clauses))
        cow_ids, cow_at = _regroup(cow_line, final[cow], order, len(ncow))
        del cow, cow_line, used, final

        phr = _view(self._phr, np.int32)
        prow = {int(x): phrase_row(int(x)) for x in np.unique(phr).tolist()}
        mapped = np.fromiter(((-1 if prow[x] is None else prow[x]) for x in phr.tolist()), np.int32, len(phr))
        phr_ids, phr_at = _regroup(np.repeat(np.arange(len(nphr), dtype=np.int32), nphr), mapped, order, len(nphr))
        del phr, mapped

        line_row = line_row[order]
        hashes = lines["hash"][order]
        # the fingerprint: kept only where another line of the same word says the same words (never 0 then)
        if len(order):
            _u, inverse, counts = np.unique((line_row.astype(np.int64) << 32) | hashes, return_inverse=True,
                                            return_counts=True)
            fp = np.where(counts[inverse] > 1, np.maximum(hashes, 1), 0).astype(np.uint32)
            del _u, inverse, counts
        else:
            fp = hashes
        cols = {"src": src[order], "number": number[order], "chars": np.minimum(chars[order], 0xFFFF),
                "ncow": np.diff(cow_at), "nphr": np.diff(phr_at), "fp": fp}
        for name in ("marks", "besides", "starts"):
            cols[name] = lines[name][order]
        del lines, word, src, number, chars, ncow, nphr, keep, hashes
        t = Table()
        with_lines, starts = np.unique(line_row, return_index=True)
        bounds = np.append(starts, len(line_row)).tolist()
        t.head = {"v": VERSION, "engine": head["engine"], "run_signature": head["run_signature"],
                  "language": head["language"], "keys": [[k[0], k[1]] for k in keys],
                  "places": [-1] * len(keys) if places is None else [int(p) for p in places],
                  "rows": with_lines.tolist(), "lines": np.diff(bounds).tolist()}
        t._sources = [list(s) for s in sources]
        t._form = _pack_formulas(formulas)
        t._parts = {}
        for i, k in enumerate(t.head["rows"]):
            a, b = bounds[i], bounds[i + 1]
            ca, cb, pa, pb = int(cow_at[a]), int(cow_at[b]), int(phr_at[a]), int(phr_at[b])
            t._parts[k] = ({name: cols[name][a:b] for name, _t in COLUMNS}, cow_ids[ca:cb], phr_ids[pa:pb])
        return t


def _view(values, dtype):
    """A packed array as numpy sees it: a view while it has values (no copy), an empty array of that type else."""
    np = _np()
    return np.frombuffer(values, dtype) if len(values) else np.zeros(0, dtype)


def _regroup(line, ids, order, n_lines):
    """A flat list of per-line ids (`line`: each one's line, ascending), -1 dropped, each line's ids ascending, lines
    taken in `order` -> (the ids, each taken line's start among them, one more at the end). One sort of one key a
    co-word (its line's place in `order`, then its id): the memory of two arrays the length of the ids, not six."""
    np = _np()
    pos = np.full(n_lines, -1, np.int64)
    pos[order] = np.arange(len(order), dtype=np.int64)
    at = pos[line] if len(line) else np.zeros(0, np.int64)
    del pos
    good = (ids >= 0) & (at >= 0)
    at, ids = at[good], ids[good]
    del good
    counts = np.bincount(at, minlength=len(order))
    size = int(ids.max()) + 1 if len(ids) else 1
    at *= size
    at += ids
    del ids
    at.sort()
    ids = (at % size).astype(np.int32)
    del at
    starts = np.concatenate(([0], np.cumsum(counts, dtype=np.int64)))
    return ids, starts


def _pack_formulas(formulas):
    """[(own row or -1, clauses of rows)] -> (own, clauses a co-word, rows a clause, the rows) as int32 arrays."""
    np = _np()
    own = np.array([f[0] for f in formulas], "<i4")
    ncl = np.array([len(f[1]) for f in formulas], "<i4")
    cl_len = np.array([len(c) for f in formulas for c in f[1]], "<i4")
    cl_rows = np.array([r for f in formulas for c in f[1] for r in c], "<i4")
    return own, ncl, cl_len, cl_rows


def _zjson(value):
    return zlib.compress(json.dumps(value, separators=_SEP, ensure_ascii=False, sort_keys=True).encode("utf-8"), LEVEL)


class Table:
    """The table, made by `Packer.finish` or read by `open_table` (the head; blocks on demand)."""

    def __init__(self):
        self.head, self.path = None, None
        self._sources = self._form = None
        self._parts, self._blocks, self._at = {}, {}, None

    # ---- written by Generate ------------------------------------------------------------------------------- #
    def write(self, path):
        """Write the table whole through a temp file and `os.replace` -> its bytes. On any error the temp is removed,
        an older table stays as it was, and the error is raised for the caller to log."""
        np = _np()
        blobs, cows, phrs = [], [], []
        for k in self.head["rows"]:
            cols, cow, phr = self._parts[k]
            src = cols["src"].astype(np.int64)
            step = src.copy()
            step[1:] -= src[:-1]
            data = [(step if name == "src" else cols[name]).astype(t).tobytes() for name, t in COLUMNS]
            blobs.append(zlib.compress(b"".join(data + [cow.astype("<i4").tobytes(), phr.astype("<i4").tobytes()]),
                                       LEVEL))
            cows.append(len(cow))
            phrs.append(len(phr))
        form = zlib.compress(b"".join(x.astype("<i4").tobytes() for x in self._form), LEVEL)
        head = _zjson(dict(self.head, cows=cows, phrs=phrs, sizes=[len(b) for b in blobs],
                           form=[len(x) for x in self._form]))
        sources = _zjson(self._sources)
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(MAGIC + struct.pack("<III", len(head), len(sources), len(form)))
                for part in (head, sources, form, *blobs):
                    f.write(part)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        return os.path.getsize(path)

    # ---- read ---------------------------------------------------------------------------------------------- #
    def sources(self):
        """[[rel, kind, digest]]: the plan's files, then the Finished ones."""
        if self._sources is None:
            with open(self.path, "rb") as f:
                f.seek(self._at[0])
                self._sources = json.loads(zlib.decompress(f.read(self._at[1])))
        return self._sources

    def formulas(self):
        """The co-words' formulas: (own row, clauses a co-word, rows a clause, the rows), int32 arrays."""
        if self._form is None:
            np = _np()
            with open(self.path, "rb") as f:
                f.seek(self._at[0] + self._at[1])
                data = zlib.decompress(f.read(self._at[2]))
            out, at = [], 0
            for n in self.head["form"]:
                out.append(np.frombuffer(data, "<i4", n, at))
                at += 4 * n
            self._form = tuple(out)
        return self._form

    def block(self, row):
        """Row `row`'s lines: ({column: array}, its co-words' ids, its phrases' rows) — each line's co-words are the
        next `ncow` ids, its phrases the next `nphr` rows. None when the row has no line."""
        found = self._parts.get(row)
        if found is not None or row not in self._blocks:
            return found
        off, size, lines, cows, phrs = self._blocks[row]
        with open(self.path, "rb") as f:
            f.seek(off)
            data = zlib.decompress(f.read(size))
        if len(data) != lines * _BYTES + 4 * (cows + phrs):
            raise ValueError("a block of the wrong size")
        np = _np()
        cols, at = {}, 0
        for name, t in COLUMNS:
            cols[name] = np.frombuffer(data, t, lines, at)
            at += lines * np.dtype(t).itemsize
        cols["src"] = np.cumsum(cols["src"], dtype=np.int64)
        cow = np.frombuffer(data, "<i4", cows, at)
        phr = np.frombuffer(data, "<i4", phrs, at + 4 * cows)
        return cols, cow, phr

    def places(self):
        """Each row's place in the list this Generate wrote (by row, as `head['keys']`; -1: not on it) — what is taught
        before a word when the caller passes no order. A move's redraw rewrites the list, never the table: after a
        move the caller passes the order (SPEC § 5)."""
        return self.head["places"]

    def rows(self):
        """{(word, reading): row} for the rows that have lines."""
        keys = self.head["keys"]
        return {(keys[k][0], keys[k][1]): k for k in self.head["rows"]}

    def as_read(self, src, root):
        """Is source `src`'s file the one the Generate read: there, its digest (path, time, size, kind) the table's
        (SPEC § 5.4)? `root`: the language's data folder, a relative source's. No digest, gone, any error: False —
        nothing of it is shown, never a line of another file. (The rule of the score's `as_read` for a source with a
        digest, `app/sentence_score.py`; the word card's, E-HOVER.)"""
        try:
            from app import plan_rules
            if src < 0:
                return False
            rel, kind, digest = self.sources()[src]
            if digest is None:
                return False
            path = rel if os.path.isabs(rel) else os.path.join(root, "") + rel.replace("/", os.sep)
            st = os.stat(path)
            return any(plan_rules.file_digest([signed, [st.st_mtime, st.st_size], None, None, kinds]) == digest
                       for signed in dict.fromkeys((os.path.join(root, rel), path))
                       for kinds in ((kind, None) if not kind else (kind,)))
        except Exception:
            return False


def open_table(path, language=None, engine=None, run_signature=None):
    """The table at `path`, its head read (blocks on demand) — or None: no file, a damaged or half-written one,
    another format's version, or (when asked) another language, engine or run. Never raises."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if f.read(len(MAGIC)) != MAGIC:
                return None
            hl, sl, fl = struct.unpack("<III", f.read(12))
            head = json.loads(zlib.decompress(f.read(hl)))
        if head.get("v") != VERSION:
            return None
        for name, want in (("language", language), ("engine", engine), ("run_signature", run_signature)):
            if want is not None and head.get(name) != want:
                return None
        t = Table()
        t.head, t.path = head, path
        start = len(MAGIC) + 12 + hl
        t._at = (start, sl, fl)
        off = start + sl + fl
        for k, n, lines, cows, phrs in zip(head["rows"], head["sizes"], head["lines"], head["cows"], head["phrs"]):
            t._blocks[k] = (off, n, lines, cows, phrs)
            off += n
        if off != size or len(head["rows"]) != len(head["sizes"]) or len(head["places"]) != len(head["keys"]):
            return None                         # half-written, or more than one table's bytes
        return t
    except (OSError, ValueError, KeyError, TypeError, AttributeError, struct.error, zlib.error):
        return None


# --- The two numbers counted once, when a file is indexed (E-INDEX) ------------------------------------------------- #
# The token store keeps, beside each file's tokens, what `LineWords` gives a line with no person in it (its `words`
# column; `file_words` writes it in the indexer's own workers, while the switch is on): the line's total, and for each
# token where it starts and whether it counts. The walk then asks only which tokens are the word (`KeptWords.of_word`)
# — and, in a line holding one of the library's people (known only after a whole index), the person rule for those
# tokens alone (`LineWords._about`, as the one pass asks it). A line holding a name link (the rule reads the people all
# through) is kept as "count at the walk"; so is, at the walk, a sentence a name table joined as the store was read,
# and every line of a row with none — each is counted by `LineWords` as before. The numbers, and the table's bytes,
# are the same whichever way they came (tests/test_sentence_table_index.py).
# Rebuilding the lists or changing the rule bumps WORDS_RULE too (a row of another rule reads as none: the walk
# counts it) and, once the switch is on in the tree, token_index.SCHEMA_VERSION (every file indexed again).
WORDS_RULE = 1
_UNCOUNTED = 0xFFFF             # a line's total: counted at the walk
_AT_MAX = 1 << 15               # a token's code: where it starts << 1 | counted, in two bytes (a longer line: the walk)
_WORDS_HEAD = struct.Struct("<HI")      # the rule, the file's sentences; then each one's end, total and codes
_LITTLE = struct.pack("=H", 1) == struct.pack("<H", 1)
_FIRST = itemgetter(0)


def file_words(sentences, language):
    """-> bytes, the token store's `words` for a file's `sentences` ([(text, tokens)], as indexed): each line counted
    by `LineWords` with no person, once. Never raises for a line: one it can't count is kept as "count at the walk"."""
    ends, totals, codes = array("I"), array("H"), array("H")
    for text, tokens in sentences:
        try:
            words = LineWords(tokens, text, language)
            if type(words.head) is not range or words.total >= _UNCOUNTED or (words.at and words.at[-1] >= _AT_MAX):
                raise ValueError        # a name link (the rule reads the people), or more than the columns hold
            codes.extend([a << 1 | c for a, c in zip(words.at, words.counted)])
            totals.append(words.total)
        except Exception:
            totals.append(_UNCOUNTED)
        ends.append(len(codes))
    if not _LITTLE:
        for column in (ends, totals, codes):
            column.byteswap()
    return _WORDS_HEAD.pack(WORDS_RULE, len(totals)) + ends.tobytes() + totals.tobytes() + codes.tobytes()


def read_file_words(raw, language, joined=()):
    """The `FileWords` of a store row's `words` (decompressed) — or None: no row, another rule's, damaged."""
    if not raw:
        return None
    try:
        return FileWords(raw, language, joined)
    except (ValueError, struct.error):
        return None


class FileWords:
    """A file's lines as the indexer counted them (`file_words`); `joined`: the sentences a name table joined as the
    store was read (their tokens are not the indexed ones)."""
    __slots__ = ("ends", "totals", "codes", "joined", "n", "language")

    def __init__(self, raw, language, joined=()):
        rule, n = _WORDS_HEAD.unpack_from(raw)
        if rule != WORDS_RULE:
            raise ValueError("another rule's count")
        at = _WORDS_HEAD.size
        self.ends, self.totals, self.codes = array("I"), array("H"), array("H")
        self.ends.frombytes(raw[at:at + 4 * n])
        self.totals.frombytes(raw[at + 4 * n:at + 6 * n])
        self.codes.frombytes(raw[at + 6 * n:])
        if not _LITTLE:
            for column in (self.ends, self.totals, self.codes):
                column.byteswap()
        if len(self.totals) != n or len(self.ends) != n or (self.ends[-1] if n else 0) != len(self.codes):
            raise ValueError("cut short")
        self.joined, self.n, self.language = joined, n, language

    def line(self, no, tokens, text, people=frozenset()):
        """The numbers of sentence `no`, whose text and tokens at the walk are `text` and `tokens` — a `KeptWords`, a
        `LineWords` when a person is in it — or None: count it at the walk (`LineWords`), as before."""
        if no >= self.n or no in self.joined:
            return None
        total = self.totals[no]
        if total == _UNCOUNTED:
            return None
        start = self.ends[no - 1] if no else 0
        if self.ends[no] - start != len(tokens):
            return None
        lemmas = list(map(_FIRST, tokens))
        if people and not people.isdisjoint(lemmas):
            return self._with_people(tokens, lemmas, text, start, people)
        return KeptWords(tokens, lemmas, self.codes, start, total)

    def _with_people(self, tokens, lemmas, text, start, people):
        """A line holding a person: the kept numbers, with the person rule asked of its people's tokens alone — as
        `LineWords`' one pass asks it of a token it would otherwise count."""
        codes = self.codes[start:start + len(tokens)]
        words = LineWords.__new__(LineWords)
        words.tokens, words.at, words.head = tokens, [c >> 1 for c in codes], range(len(tokens))
        counted = [c & 1 for c in codes]
        _grammar, particles, _helpers, titles = _lists(self.language)
        for i, lemma in enumerate(lemmas):
            if counted[i] and lemma in people:
                counted[i] = words._about(i, text, particles, titles, people)
        words.counted, words.total = counted, sum(counted)
        return words


class KeptWords:
    """`LineWords`' answers for a line with no person and no name link, from what the indexer kept: each token's code
    (`codes[start + i]`) is where it starts << 1 | whether it counts."""
    __slots__ = ("tokens", "lemmas", "codes", "start", "total")

    def __init__(self, tokens, lemmas, codes, start, total):
        self.tokens, self.lemmas, self.codes, self.start, self.total = tokens, lemmas, codes, start, total

    def of_word(self, key):
        """(words besides the word `key`, where it first starts)."""
        lemma, reading = key
        lemmas, tokens, codes, start = self.lemmas, self.tokens, self.codes, self.start
        first, own, i = -1, 0, -1
        index = lemmas.index
        try:
            while True:
                i = index(lemma, i + 1)
                if tokens[i][1] == reading:
                    if first < 0:
                        first = i
                    own += codes[start + i] & 1
        except ValueError:
            pass
        if first < 0:
            return self.total, 0
        return self.total - own, codes[start + first] >> 1

    def of_span(self, a, b):
        """(words besides the set phrase on tokens a..b-1, where it starts)."""
        n, codes, start = len(self.lemmas), self.codes, self.start
        if a >= n:
            return self.total, 0
        return self.total - sum(c & 1 for c in codes[start + a:start + min(b, n)]), codes[start + a] >> 1


def line_words(kept, no, tokens, text, language, people=frozenset(), counted=None):
    """Line `no`'s words for the table's two numbers: as the indexer counted them (`kept`, the file's `FileWords`, or
    None), else counted here (`LineWords`) — the same numbers. A line it can't count reads as none (0, 0): the table
    never fails the run. `counted`, a list: [lines read from the kept counts, lines counted here] is added to."""
    words = None
    if kept is not None:
        try:
            words = kept.line(no, tokens, text, people)
        except Exception:
            pass                        # counted here instead
    if words is not None:
        if counted is not None:
            counted[0] += 1
        return words
    if counted is not None:
        counted[1] += 1
    try:
        return LineWords(tokens, text, language, people)
    except Exception:
        return LineWords((), "", language)


# --- The walk's two numbers on the other cores (E-CORES, SPEC § 8.3) ------------------------------------------------ #
# A line's two numbers (the words besides the word, where the word starts) are a function of its file's cached tokens,
# the file's kept counts and the library's people alone; which lines are offered is the walk's (it reads what earlier
# files left: a word's first sentence in a file, a phrase known as a whole). So with `Cores` the walk still offers
# every line to `Packer.add` in its own order, with the numbers 0, and asks `Cores` instead of `line_words`: each
# question is kept as (sentence number, its tokens, its characters, the word's key or the phrase's span). A batch of
# files' questions goes to a worker, which reads each file from the token store itself (`Store.file_words`: the same
# sentences the walk read) and answers with two bytes a question; `settle` writes the answers into the packed lines in
# the walk's order — the order workers finish in never matters. A file a worker reads otherwise than the walk did (its
# lines' tokens or lengths differ) is answered here, read again as the walk reads it. One process when the PC has one
# core, or under CORES_MIN_FILES files (`token_index.pool_workers`' rule after it, *Use every core* included); every
# failure to start is today's single-process path.
CORES_BATCH = 2000              # questions sent to a worker at a time (files are never split)
CORES_MAX = 2                   # workers at most: one kept up at 2,000 files; 24 allowed spawned 15 on the zh root
CORES_WAIT_S = 300              # the walk's end waits this long in all for the batches still out, then answers the
                                # rest itself (stuck workers never hang it: once, never once a batch)
CORES_MIN_FILES = 8000          # fewer files: one process (the timed gate, E-CORES 2: the gain passes 5 % of a Generate
                                # near here — 0.5 s at 2,000, 6.6 s at 20,000 — a worker ~38 MB) unless settings ask N
_NUMBERS = struct.Struct("BB")
_CORE = {}


def numbers_of(sentences, kept, asked, language, people=frozenset(), counted=None):
    """-> bytes, two a question of `asked` ([(sentence number, tokens, characters, key) or (…, start, end)], as
    `Cores` keeps them): the words besides the word and where it starts, clipped as `Packer.add` clips them — or None
    when a question's line is not in `sentences` as the walk read it."""
    out, pack = bytearray(), _NUMBERS.pack
    held, line, words, n_lines = -1, None, None, len(sentences)
    for q in asked:
        no = q[0]
        if no != held:
            if no >= n_lines:
                return None
            text, tokens = sentences[no]
            if not q[1]:
                tokens = ()     # a song line the walk read with no words (`songs_left_out`): counted as it did
            held, line = no, (len(tokens), len(text))
            words = line_words(kept, no, tokens, text, language, people, counted)
        if q[1] != line[0] or q[2] != line[1]:
            return None
        besides, starts = words.of_word(q[3]) if len(q) == 4 else words.of_span(q[3], q[4])
        out += pack(besides if besides < 255 else 255, starts if starts < STARTS_PAST else STARTS_PAST)
    return bytes(out)


def _cores_start(store_path, language, people, switches):
    """A worker's start: the token store opened to read only, the run's name switches. It never outlives the walk's
    process (as the indexer's workers: `token_index._pool_start`)."""
    import gc
    import multiprocessing
    import threading
    gc.disable()                        # a batch's objects make no cycles (the engine map's § Heavy work)
    parent = multiprocessing.parent_process()
    if parent is not None:
        def watch():
            parent.join()
            os._exit(1)
        threading.Thread(target=watch, name="cores-parent-watch", daemon=True).start()
    from app import token_index
    store = token_index.open_reader(language, store_path)
    if store is not None:
        store.switches = switches
    _CORE.update(store=store, language=language, people=people)


def _cores_answer(batch):
    """[(path, questions)] -> [(the file's answers or None, [lines read from the kept counts, lines counted here])]."""
    store, language, people = _CORE["store"], _CORE["language"], _CORE["people"]
    out = []
    for path, asked in batch:
        counted = [0, 0]
        try:
            sentences, kept = store.file_words(path) if store is not None else ([], None)
            out.append((numbers_of(sentences, kept, asked, language, people, counted), counted))
        except Exception:
            out.append((None, counted))
    return out


def cores_wanted(n_files):
    """How many workers a walk of `n_files` files takes: 1 (this process alone) under CORES_MIN_FILES files, else
    `token_index.pool_workers`' rule (*Use every core*), at most CORES_MAX; settings' `index_pool_workers` N asks for
    N at any size, as it does of the indexer."""
    from app import token_index
    try:
        from app import settings_manager
        setting = settings_manager.load_settings().get("index_pool_workers")
        asked = int(setting) if setting is not None else None
    except Exception:
        setting = asked = None
    if asked is None and n_files < CORES_MIN_FILES:
        return 1
    return min(token_index.pool_workers(n_files, setting, every=token_index.every_core()), CORES_MAX)


class Cores:
    """The walk's side of the workers (above). `file(path, packer)` before a file's lines are offered; then each
    offered line asks `line(text, tokens, number)` — this object, whose `of_word(key)` / `of_span(a, b)` keep the
    question and answer (0, 0) — and `settle(packer, read, …)` before `Packer.finish` writes every answer in."""

    def __init__(self, pool):
        self._pool = pool
        self._sent = []                 # ([(path, questions, first line)], the worker's Future)
        self._batch, self._size = [], 0
        self._path, self._first, self._asked = None, 0, []
        self._line = self._wrong = self._packer = None
        self.counted = [0, 0]
        self.here = 0                   # files a worker couldn't answer, answered here
        self._read = self._language = self._people = None

    @classmethod
    def start(cls, n_files, store, language, people):
        """The workers for a walk of `n_files` files over `store` — or None: one process (one core, a small library, a
        store with no file to read again, a pool that won't start)."""
        try:
            size = cores_wanted(n_files)
            if size < 2 or store is None or not getattr(store, "path", None):
                return None
            import multiprocessing
            from concurrent.futures import ProcessPoolExecutor
            from app import token_index
            pool = ProcessPoolExecutor(     # a worker that dies raises (BrokenProcessPool): its files answered here
                size, mp_context=multiprocessing.get_context("spawn"), initializer=_cores_start,
                initargs=(store.path, language, frozenset(people), token_index._library_switches(language)))
        except Exception as e:
            print(f"Sentence table: one process ({e}).")
            return None
        print(f"Sentence table: the lines' words in {size} processes.")
        return cls(pool)

    def file(self, path, packer):
        """The next file's lines follow."""
        self._packer = packer
        self._close_file(packer)
        self._path, self._first = path, len(packer)

    def _close_file(self, packer):
        asked = self._asked
        if asked:
            if len(packer) - self._first != len(asked):
                self._wrong = self._path        # never the run's failure: the table's, at `settle`
            self._batch.append((self._path, asked, self._first))
            self._size += len(asked)
            if self._size >= CORES_BATCH:
                self._send()
            self._asked = []

    def _send(self):
        batch = self._batch
        if batch:
            result = None
            if self._pool is not None:
                try:
                    result = self._pool.submit(_cores_answer, [(path, asked) for path, asked, _first in batch])
                except Exception:
                    result = None           # a broken pool: answered here, at `settle`
            self._sent.append((batch, result))
        self._batch, self._size = [], 0
        while self._sent and self._sent[0][1] is not None and self._sent[0][1].done() and self._read is not None:
            self._take(*self._sent.pop(0))  # answers in: their questions let go as the walk goes

    def _take(self, batch, result, wait=0):
        """One batch's answers written in; a file (or a batch) no worker answered, answered here."""
        try:
            answers = result.result(timeout=wait) if result is not None else None
        except Exception:
            answers = None
        for i, (path, asked, first) in enumerate(batch):
            numbers, counted = answers[i] if answers is not None else (None, [0, 0])
            if numbers is None:
                counted = [0, 0]
                sentences, kept = self._read(path)
                numbers = numbers_of(sentences, kept, asked, self._language, self._people, counted)
                if numbers is None:
                    raise ValueError(f"{path}: its lines are not the ones the walk read")
                self.here += 1
            self._packer.fill(first, numbers)
            self.counted[0] += counted[0]
            self.counted[1] += counted[1]

    def line(self, text, tokens, number):
        self._line = (number, len(tokens), len(text))
        return self

    def of_word(self, key):
        self._asked.append(self._line + (key,))
        return 0, 0

    def of_span(self, a, b):
        self._asked.append(self._line + (a, b))
        return 0, 0

    def reads(self, read, language, people):
        """How a file no worker answered is read here: `read(path)` -> (sentences, kept counts), as the walk reads it."""
        self._read, self._language, self._people = read, language, people

    def settle(self, packer):
        """Every answer written into `packer`'s lines (a file a worker couldn't answer, answered here). The workers
        end."""
        try:
            self._packer = packer
            self._close_file(packer)
            if self._wrong is not None:
                raise ValueError(f"{self._wrong}: a line offered without its question")
            self._send()
            end = time.monotonic() + CORES_WAIT_S
            while self._sent:
                self._take(*self._sent.pop(0), wait=max(0.0, end - time.monotonic()))
            if self.here:
                print(f"Sentence table: {self.here:,} files answered by the walk itself.")
        finally:
            self._sent = []
            self.close()

    def close(self):
        pool, self._pool = self._pool, None
        if pool is not None:
            processes = list((getattr(pool, "_processes", None) or {}).values())   # (shutdown lets go of them)
            pool.shutdown(wait=False, cancel_futures=True)   # a stuck worker never holds the run; each one ends with it
            for process in processes:
                try:
                    process.join(5)
                    if process.is_alive():
                        process.terminate()
                except Exception:
                    pass


class TableFirsts:
    """The word card (Hover-W) at level 2 (`plan_rules.SENTENCE_TABLE >= 2`, E-HOVER): each listed word's first sentence in a file
    from the sentence table beside the plan (`app/sentence_table.py`) — the word's block, its lines of that file, the
    lowest place (SPEC § 5.2): a read, never a ranking. The walk keeps a word's first sentence of each file there, with
    the OVER mark when over *Never longer than*, so it is the plan's `FirstSentences`' answer (`app/plan_engine.py`, kept pure: this read lives here). `of_files({f: rows})` -> {f: {k:
    (sentence number, None, its length)}} for each file's `rows`, each row's block read once for all the files (a
    title's words: one read a word, not one a word and file), for a file that is the one the Generate read
    (`Table.as_read`; else {}): a line said once keeps no hash, so None in its place — the file's digest and the line's
    length (`title_words.sentence_of`) stand for it. `of(f, rows)`: one file's. `files` the table's sources' rel paths (the plan's files, then the Finished ones); `key` the plan's
    (mtime_ns, size). A table file replaced since it was opened (its stamp moved) answers nothing: its blocks are not
    where the head read them."""

    def __init__(self, table, root, key):
        self._table, self._root, self.key = table, root, key
        st = os.stat(table.path)
        self._stamp = (st.st_mtime_ns, st.st_size)
        self.files = [source[0] for source in table.sources()]

    def _same_table(self):
        try:
            st = os.stat(self._table.path)
        except OSError:
            return False
        return (st.st_mtime_ns, st.st_size) == self._stamp

    def of(self, f, rows=()):
        return self.of_files({f: rows}).get(f, {})

    def of_files(self, asked):
        out, wanted = {f: {} for f in asked}, {}
        if not self._same_table():
            return out
        for f, rows in asked.items():
            if 0 <= f < len(self.files) and self._table.as_read(f, self._root):
                for k in rows:
                    wanted.setdefault(k, []).append(f)
        for k, files in wanted.items():
            try:
                block = self._table.block(k)
                if block is None:
                    continue
                src, number, chars = block[0]["src"], block[0]["number"], block[0]["chars"]   # (file, place) order
                for f in files:
                    i = int(src.searchsorted(f))
                    if i < len(src) and src[i] == f:
                        out[f][k] = (int(number[i]), None, int(chars[i]))
            except Exception:
                return {f: {} for f in asked}        # a damaged table: nothing, never a guess (nor an error)
        return out


def table_firsts(path, data_dir):
    """`TableFirsts` for the plan at `path`: only its header line read (its language, engine and run), the table
    beside it opened for that run — or None: no plan, its language, engine or run not named, no table, another run's
    or engine's, a damaged one. The plan's format is not asked: the table is told by its run (release 2's plan keeps no
    first sentences of its own)."""
    try:
        st = os.stat(path)
        with gzip.open(path, "rb") as fh:
            header = json.loads(fh.readline())
        language, engine, run = header.get("language"), header.get("engine"), header.get("run_signature")
        if not language or not engine or not run:
            return None                              # (open_table checks only what it is given: all three, always)
        table = open_table(os.path.join(os.path.dirname(path), TABLE_FILE), language=language, engine=engine,
                           run_signature=run)
        if table is None or not data_dir:
            return None
        return TableFirsts(table, data_dir, (st.st_mtime_ns, st.st_size))
    except Exception:
        return None


def table_stamp(path):
    """The (mtime_ns, size) of the sentence table beside the plan at `path`, or None: none there. The word card keeps
    its reader only while this holds too (a table written after the plan, E-HOVER)."""
    try:
        st = os.stat(os.path.join(os.path.dirname(path), TABLE_FILE))
        return st.st_mtime_ns, st.st_size
    except Exception:
        return None
