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
lines are a function of that file alone — a pool of workers could each pack its share and the main process join
them by key, in the plan's file order (SPEC § 8.3; not built).

numpy is imported here only (it arrives with pandas); the cost of a line is E-SCORE's (`app/sentence_score.py`).
"""
import json
import os
import re
import struct
import zlib
from array import array

import numpy as np

TABLE_FILE = "sentences.bin"
MAGIC = b"SURATBL\n"
VERSION = 3                     # 3: each row's place in the list · 2: the two word numbers counted (1 wrote 0)
LEVEL = 3                       # zlib: 0.44 s for 7.01 MB at 20,000 files (lighter 7.42 MB, harder 1.15 s: SPEC § 8.2)

OVER = 1 << 2                   # marks: over *Never longer than* (a file's first sentence of the word; never chosen)
STARTS_PAST = 255               # where the word starts: 255 = at or past 255 characters
_SEP = (",", ":")

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
    is one name, held by its first piece — and the word itself when the word is one of its pieces."""
    __slots__ = ("keys", "at", "head", "counted", "total")

    def __init__(self, tokens, text, language, people=frozenset()):
        grammar, particles, helpers, titles = _lists(language)
        n, pos = len(tokens), 0
        self.keys, self.at, ends = [], [], []
        for lemma, reading, surface, _orth in tokens:
            a = text.find(surface, pos)
            if a >= 0:
                pos = a + len(surface)
            else:
                a = pos                         # a token the line's text doesn't hold (a quote mark cut off): here
            self.keys.append((lemma, reading))
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

    def _own(self, indices):
        return sum(self.counted[h] for h in {self.head[i] for i in indices})

    def of_word(self, key):
        """(words besides the word `key`, where it first starts)."""
        mine = [i for i, k in enumerate(self.keys) if k == key]
        return self.total - self._own(mine), self.at[mine[0]] if mine else 0

    def of_span(self, a, b):
        """(words besides the set phrase on tokens a..b-1, where it starts)."""
        return self.total - self._own(range(a, min(b, len(self.keys)))), self.at[a] if a < len(self.at) else 0

# One block's columns, in the order written: (name, little-endian dtype). `src` is written as the step from the line
# before (mostly 0) and read back whole.
COLUMNS = (("src", "<i4"), ("number", "<i4"), ("chars", "<u2"), ("marks", "u1"), ("ncow", "<u2"), ("nphr", "<u2"),
           ("fp", "<u4"), ("besides", "u1"), ("starts", "u1"))
_BYTES = sum(np.dtype(t).itemsize for _n, t in COLUMNS)


class Packer:
    """The walk's side: lines appended as the files are read, as compact arrays (no Python object per line)."""

    def __init__(self):
        self._ids, self._keys = {}, []          # any key (a word, a co-word) -> its provisional id; id -> key
        self.word, self.src, self.number = array("i"), array("i"), array("i")
        self.chars, self.marks, self.hash = array("i"), array("B"), array("I")
        self.besides, self.starts = array("B"), array("B")
        self.ncow, self.cow = array("i"), array("i")      # co-words: provisional ids
        self.nphr, self.phr = array("i"), array("i")      # set phrases: the walk's own numbers

    def _id(self, key):
        found = self._ids.get(key)
        if found is None:
            found = self._ids[key] = len(self._keys)
            self._keys.append(key)
        return found

    def __len__(self):
        return len(self.word)

    def add(self, word, src, number, chars, text_hash, cowords=(), phrases=(), besides=0, starts=0, over=False):
        """One candidate line of `word` (the key its row is found by): sentence `number` of source `src`, `chars`
        long, its text's `text_hash` (`plan_rules.text_hash_of`), its other new words `cowords` (keys) and set phrases
        `phrases`, the words `besides` the word it says, where the word `starts`; `over` *Never longer than*."""
        self.word.append(self._id(word))
        self.src.append(src)
        self.number.append(number)
        self.chars.append(chars)
        self.marks.append(OVER if over else 0)
        self.hash.append(text_hash & 0xFFFFFFFF)
        self.besides.append(min(besides, 255))
        self.starts.append(min(starts, STARTS_PAST))
        ids = [self._id(c) for c in cowords]
        self.ncow.append(len(ids))
        self.cow.extend(ids)
        self.nphr.append(len(phrases))
        self.phr.extend(phrases)

    def finish(self, keys, row_of, clauses_of, own_row, key_order, phrase_row, sources, head, places=None):
        """-> the Table. `keys`: every list row's (word, reading), by row · `row_of(word key)` -> its row or None
        (not a row: its lines are dropped) · `clauses_of(co-word key)` -> its formula (`plan_rules` clauses; TRUE:
        known from the start, left out) · `own_row(co-word key)` -> its own row or -1 · `key_order(co-word key)`:
        the order co-words are numbered in (the plan's `_coword_key`) · `phrase_row(phrase)` -> its row or None ·
        `sources`: [[rel, kind, digest]] · `head`: {engine, run_signature, language} · `places`: each row's place in
        the list Generate wrote (the study order: 0 first), -1 off it; none given: every row -1."""
        from app import plan_rules
        if places is not None and len(places) != len(keys):
            raise ValueError(f"{len(places)} places for {len(keys)} rows")
        n_ids = len(self._keys)
        rows = np.full(n_ids, -1, np.int64)
        for p, key in enumerate(self._keys):
            k = row_of(key)
            if k is not None and k >= 0:
                rows[p] = k
        word = _np(self.word, np.int64)
        line_row = rows[word] if len(word) else np.zeros(0, np.int64)
        keep = line_row >= 0
        src, number = _np(self.src, np.int64), _np(self.number, np.int64)
        # every line once for its row, in (row, file, place) order — a line the walk offered twice is kept once
        order = np.lexsort((number, src, line_row))
        order = order[keep[order]]
        if len(order):
            same = np.zeros(len(order), bool)
            same[1:] = ((line_row[order][1:] == line_row[order][:-1]) & (src[order][1:] == src[order][:-1])
                        & (number[order][1:] == number[order][:-1]))
            order = order[~same]

        # co-words: only those a kept line names, numbered by key; known from the start (TRUE) left out
        ncow, cow = _np(self.ncow, np.int64), _np(self.cow, np.int64)
        cow_line = np.repeat(np.arange(len(ncow), dtype=np.int64), ncow)
        used = np.zeros(n_ids, bool)
        used[cow[keep[cow_line]]] = True
        formulas, final = [], np.full(n_ids, -1, np.int64)
        named = sorted((key_order(self._keys[p]), p) for p in np.flatnonzero(used).tolist())
        for _order, p in named:
            clauses = clauses_of(self._keys[p])
            if clauses != plan_rules.TRUE:
                final[p] = len(formulas)
                formulas.append((own_row(self._keys[p]), clauses))
        cow_ids, cow_at = _regroup(ncow, final[cow] if len(cow) else cow, order)

        nphr, phr = _np(self.nphr, np.int64), _np(self.phr, np.int64)
        prow = {int(x): phrase_row(int(x)) for x in np.unique(phr).tolist()}
        mapped = np.fromiter(((-1 if prow[x] is None else prow[x]) for x in phr.tolist()), np.int64, len(phr))
        phr_ids, phr_at = _regroup(nphr, mapped, order)

        line_row = line_row[order]
        hashes = _np(self.hash, np.int64)[order]
        # the fingerprint: kept only where another line of the same word says the same words (never 0 then)
        if len(order):
            _u, inverse, counts = np.unique((line_row << 32) | hashes, return_inverse=True, return_counts=True)
            fp = np.where(counts[inverse] > 1, np.maximum(hashes, 1), 0)
        else:
            fp = hashes
        cols = {"src": src[order], "number": number[order],
                "chars": np.minimum(_np(self.chars, np.int64)[order], 0xFFFF), "marks": _np(self.marks, np.int64)[order],
                "ncow": np.diff(cow_at), "nphr": np.diff(phr_at), "fp": fp,
                "besides": _np(self.besides, np.int64)[order], "starts": _np(self.starts, np.int64)[order]}
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


def _np(values, dtype):
    return np.frombuffer(values, dtype=values.typecode and np.dtype(values.typecode)).astype(dtype) \
        if len(values) else np.zeros(0, dtype)


def _regroup(counts, ids, order):
    """A flat list of per-line ids (`counts` a line), -1 dropped, each line's ids ascending, lines taken in `order`
    -> (the ids, each taken line's start among them, one more at the end)."""
    line = np.repeat(np.arange(len(counts), dtype=np.int64), counts)
    pos = np.full(len(counts), -1, np.int64)
    pos[order] = np.arange(len(order), dtype=np.int64)
    at = pos[line] if len(line) else line
    good = (ids >= 0) & (at >= 0)
    at, ids = at[good], ids[good]
    by = np.lexsort((ids, at))
    at, ids = at[by], ids[by]
    starts = np.concatenate(([0], np.cumsum(np.bincount(at, minlength=len(order)), dtype=np.int64)))
    return ids, starts


def _pack_formulas(formulas):
    """[(own row or -1, clauses of rows)] -> (own, clauses a co-word, rows a clause, the rows) as int32 arrays."""
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
