"""The journey v3 page's test data: J-DATA's shape v1 (head, chunks, blobs) built from `tests/Test Resources` — real
Japanese lines from the analyzer's expected output, real Chinese lines from the subtitle samples — at any size, and the
page assembled from `templates/journey/` the way the render does it (the chosen rail inlined, the data at its marker).

Until J-DATA's render is in the build this is what the page's self-checks and speed rows run on; the shape is J-DATA's
SHAPE.md (version 1), field for field, so the page never learns a shape of its own.

    python tests/journey_page_fixture.py ja 2000 out.html      (a page to open by hand)
"""
import base64
import csv
import gzip
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "Test Resources")
TEMPLATES = os.path.join(os.path.dirname(HERE), "templates", "journey")
DATA_MARK = "<!--JOURNEY-DATA-->"
RAIL_MARK = "<!--JOURNEY-RAIL-->"


def _json(obj):
    """UTF-8 JSON as the render writes it: never ASCII-escaped, `</` never closing the script element."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")


def _gz64(obj):
    return base64.b64encode(gzip.compress(_json(obj).encode("utf-8"), 6)).decode("ascii")


# ---- real words and lines -------------------------------------------------------------------------------------------

def _hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def _ja_vocab():
    """(word, orth, reading, kana, forms, [lines]) from the analyzer's expected output: its own Context columns."""
    out = []
    with open(os.path.join(RES, "ja", "expected_output.csv"), encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lines = [row.get(f"Context {i}") for i in (1, 2, 3)]
            lines = [s for s in lines if s and row["Word"] in s]
            if not lines:
                continue
            forms = [x for x in (row.get("Forms") or "").split("|") if x and x != row["Word"]]
            out.append((row["Word"], "" if row["Orth"] == row["Word"] else row["Orth"], _hira(row["Reading"] or ""),
                        "", forms, lines))
    return out + _ja_met_forms()


def _ja_met_forms(n=3):
    """The first `n` words of the analyzer's output met only in an inflected form (下りる in 下りろ): their lines hold a
    Forms entry, never the word, as the render keeps them (J-FIX 2: search finds a word by a form it was met in)."""
    out = []
    with open(os.path.join(RES, "ja", "expected_output.csv"), encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lines = [s for s in (row.get(f"Context {i}") for i in (1, 2, 3)) if s]
            forms = [x for x in (row.get("Forms") or "").split("|") if x and x != row["Word"]]
            if any(row["Word"] in s for s in lines):
                continue
            met = [s for s in lines if any(x in s for x in forms)]
            if met and len(out) < n:
                out.append((row["Word"], "" if row["Orth"] == row["Word"] else row["Orth"],
                            _hira(row["Reading"] or ""), "", forms, met))
    return out


# Chinese: words found in the subtitle samples' own lines, with their CC-CEDICT pinyin and glosses.
_ZH = [
    ("夜市", "yè shì", "44", "night market"), ("牛肉面", "niú ròu miàn", "244", "beef noodle soup"),
    ("频道", "pín dào", "24", "channel; frequency band"), ("今天", "jīn tiān", "11", "today"),
    ("台北", "tái běi", "23", "Taipei"), ("非常", "fēi cháng", "12", "very; extraordinary"),
    ("有名", "yǒu míng", "32", "famous; well-known"), ("每天", "měi tiān", "31", "every day"),
    ("珍珠奶茶", "zhēn zhū nǎi chá", "1132", "bubble tea"), ("味道", "wèi dao", "45", "flavor; taste"),
    ("价格", "jià gé", "42", "price"), ("合理", "hé lǐ", "23", "reasonable; rational"),
    ("喜欢", "xǐ huan", "35", "to like"), ("影片", "yǐng piàn", "34", "film; video"),
    ("记得", "jì de", "45", "to remember"), ("知道", "zhī dao", "15", "to know"),
    ("原来", "yuán lái", "22", "so it turns out; originally"), ("明天", "míng tiān", "12", "tomorrow"),
    ("捷运", "jié yùn", "24", "rapid transit; metro (Taiwan)"), ("门口", "mén kǒu", "23", "doorway; entrance"),
    ("听说", "tīng shuō", "11", "to hear (that)"), ("下雨", "xià yǔ", "43", "to rain"),
    ("臭豆腐", "chòu dòu fu", "445", "stinky tofu"), ("摊位", "tān wèi", "14", "stall; booth"),
    ("老板", "lǎo bǎn", "33", "boss; shop owner"), ("招牌", "zhāo pai", "15", "signboard; shop sign"),
    ("顺便", "shùn biàn", "44", "on the way; while at it"), ("清楚", "qīng chu", "15", "clear; to understand"),
    ("恭喜", "gōng xǐ", "13", "congratulations"), ("再见", "zài jiàn", "44", "goodbye"),
]


def _zh_lines():
    lines = []
    for name in ("night_market.srt", "utterances_sample.srt", "repeated_lines.zh.srt"):
        with open(os.path.join(RES, "zh", name), encoding="utf-8-sig") as f:
            for raw in f.read().splitlines():
                raw = re.sub(r"</?i>", "", raw).strip()
                if raw and not raw.isdigit() and "-->" not in raw and raw != "OK":
                    lines.append(raw)
    with open(os.path.join(RES, "zh", "chinese_text_1.txt"), encoding="utf-8-sig") as f:
        lines += [s for s in re.split(r"(?<=[。！？])", f.read().replace("\n", "")) if 4 < len(s) < 60]
    return lines


def _zh_vocab():
    lines = _zh_lines()
    out = []
    for word, pinyin, tones, _gloss in _ZH:
        hits = [s for s in lines if word in s] or [f"{word}。"]
        out.append((word, "", pinyin, "", [], hits[:5]))
    return out


_JA_GLOSS = {
    "極楽": [["noun", ["paradise", "Sukhavati (Amitabha's Pure Land)"]]],
    "御釈迦様": [["noun", ["Buddha", "Shakyamuni"]]],
    "血の池": [["noun", ["pool of blood (in hell)"]]],
    "地獄": [["noun", ["hell", "inferno"]]],
    "蜘蛛": [["noun", ["spider"]]],
    "罪人": [["noun", ["criminal", "sinner"]]],
    "蓮池": [["noun", ["lotus pond"]]],
}
_JA_PITCH = {"極楽": "0", "地獄": "3,0", "蜘蛛": "1", "罪人": "k:0", "蓮池": "0"}
_KANJI = {
    "極": ["poles; settlement; conclusion", "キョク、ゴク", "きわ.める", "極端"],
    "楽": ["music; comfort; ease", "ガク、ラク", "たの.しい", "楽しい"],
    "地": ["ground; earth", "チ、ジ", "", "地図"], "獄": ["prison; jail", "ゴク", "", ""],
    "血": ["blood", "ケツ", "ち", "血"], "池": ["pond; cistern", "チ", "いけ", "池"],
    "蜘": ["spider", "チ", "", ""], "蛛": ["spider", "チュ", "", ""],
    "罪": ["guilt; sin; crime", "ザイ", "つみ", "罪"], "人": ["person", "ジン、ニン", "ひと", "人"],
}

# Long titles (JOURNEY-NAMES: a long name cuts with … in its own box, never under a button or into the word pane).
# (the first show's name, the name its files carry, the second show's name): the first show's files are named apart
# from its show (as a release's file names often are), so each episode's own part is the whole long name; the second's
# part is short and its show's name long.
LONG_NAMES = {
    "ja": ("夜明けの旅団 〜はるかなる海の約束〜 第二期 黄昏の港町と七つの灯台編",
           "【劇場先行版】夜明けの旅団〜はるかなる海の約束〜 第二期 黄昏の港町と七つの灯台編",
           "星屑ステーション ～僕らが最後に見上げた夏の夜空と、まだ名前のない星座の話～"),
    "zh": ("台北美食日记：从夜市小吃到米其林餐厅的一百个故事与老板们的人生",
           "【完整版】台北美食日记 从夜市小吃到米其林餐厅的一百个故事与老板们的人生",
           "夜市人生之城南旧事：捷运沿线每一站的老店、新店和那些不会再回来的味道"),
    "en": ("The Lighthouse Keeper and the Very Long Journey Across the Northern Sea",
           "The.Lighthouse.Keeper.and.the.Very.Long.Journey.Across.the.Northern.Sea.S01.1080p",
           "Notes From a Small Station at the End of the Line, Where Nobody Gets Off Anymore"),
}

_SHOWS = {
    "ja": [("夜明けの旅団 〜はるかなる海の約束〜", "anime", "sapphire", "第{}話"), ("星屑ステーション", "anime", "sapphire", "第{}話"),
           ("蜘蛛の糸", "book", "emerald", "第{}章"), ("図書館の一日", "youtube", "ruby", "#{}"),
           ("杜子春", "audiobook", "emerald", "{}"), ("ほしまつり", "drama", "sapphire", "第{}話"),
           ("劇場版 夜明けの旅団", "movie", "sapphire", ""), ("風の便り", "lightnovel", "emerald", "第{}章")],
    "zh": [("夜市人生", "drama", "sapphire", "第{}集"), ("台北美食日记", "youtube", "ruby", "#{}"),
           ("城南旧事", "book", "emerald", "第{}章"), ("捷运故事", "anime", "sapphire", "第{}集"),
           ("老板的招牌", "podcast", "emerald", "第{}期"), ("顺便去旅行", "movie", "sapphire", "")],
}


def build(lang="ja", n_eps=40, seed=7, words_per_ep=None, sentences=3, meanings="en", stamp="1763700000000",
          library="lib-fixture", first_meeting=None, long_names=None):
    """SHAPE v1's parts for a library of `n_eps` episodes: {"head", "chunks", "meanings", "kanji", "yours", "stones"}.
    `long_names` ("ja" / "zh" / "en"): the first two shows get LONG_NAMES' titles (JOURNEY-NAMES)."""
    rng = random.Random(seed)
    vocab = _ja_vocab() if lang == "ja" else _zh_vocab()
    shows_src = list(_SHOWS[lang])
    files = {}                                        # a show's title in its file names, where it differs from its own
    if long_names:
        first, named, second = LONG_NAMES[long_names]
        shows_src[0] = (first,) + shows_src[0][1:]
        shows_src[1] = (second,) + shows_src[1][1:]
        files[first] = named
    shows, eps, plan = [], [], []                     # plan: (ep index, n words)
    sizes = [12, 52, 6, 24, 1, 30, 200, 8] if n_eps > 60 else [6, 12, 6, 8, 1, 7]
    i = 0
    s = 0
    while i < n_eps:
        title, kind, gem, fmt = shows_src[s % len(shows_src)]
        if s >= len(shows_src):
            title = f"{title} {s // len(shows_src) + 1}"
        size = min(sizes[s % len(sizes)] if fmt else 1, n_eps - i)
        shows.append([f"w{s + 1}", title, kind, gem])
        for k in range(size):
            tier = 0 if i < n_eps * 0.3 else (1 if i < n_eps * 0.7 else 2)
            watched = tier == 0 and k < size // 3
            name = f"{title}/{k + 1:03d}.srt"
            shown = files.get(title, title)
            label = f"{shown} · {fmt.format(k + 1)}" if fmt else shown
            eps.append([1000 + i, name, label, s, tier, kind, None, 0, 0, "rock", 0, None, None, watched])
            i += 1
        s += 1
    # words: each episode not watched gets some, fewer further on (a real plan: most new words come early)
    w = 0
    for idx, e in enumerate(eps):
        watched = e.pop()
        if watched:
            n = 0
        elif words_per_ep is not None:
            n = words_per_ep
        else:
            n = rng.choice([0, 1, 2, 3, 4, 6, 8, 10, 14]) if n_eps <= 2000 else rng.choice([0, 0, 1, 2, 3, 4, 5])
        e[7], e[8] = n, w
        plan.append(n)
        w += n
        has_cards = (not watched) and rng.random() < 0.4
        e[10] = (1 if watched else 0) | (4 if has_cards or watched else 0) | (2 if rng.random() < 0.01 else 0)
        e[9] = "cut" if watched else ("raw" if has_cards and n else ("nothing" if n == 0 else "rock"))
        e[6] = round(rng.uniform(84, 98.5), 1)
        if rng.random() < 0.05 and not watched:
            e[11] = ["2026-11-20", rng.choice(["end", "press"])]
        if rng.random() < 0.6:
            added = round(e[6] - rng.uniform(0.5, 12), 1)
            g = [added, rng.randint(40, 300), "2026-10-02", 1 if rng.random() < 0.2 else 0, None, None, None,
                 rng.randint(5, 40)]
            if watched:
                g[4], g[5], g[6] = e[6], g[7], "2026-11-01"
            e[12] = g
    total = w
    # sources the browser can't play (J-CLIP): the first episode with words is an .mkv, so ▶ on its lines asks clip/cut,
    # and so is the next one (some of its words' lines come from it: an ahead ask must leave them out)
    clip_ep = next((k for k, e in enumerate(eps) if e[7] >= 3), None)
    # the chunks: ≤100 episodes, or ~240 KB of JSON
    chunks, parts = [], []
    meanings, kanji = {}, {}
    cur = None
    for idx, e in enumerate(eps):
        if cur is None or cur["eps"] >= 100 or cur["size"] > 240_000:
            cur = {"w0": e[8], "src": [], "srcmap": {}, "w": [], "eps": 0, "size": 0}
            parts.append(cur)
        cur["eps"] += 1
        for k in range(e[7]):
            wid = e[8] + k
            word, orth, reading, kana, forms, lines = vocab[(wid * 7 + idx) % len(vocab)]
            marks = (1 if wid % 5 == 0 else 0) | (2 if wid % 11 == 3 else 0) | (4 if wid % 13 == 4 else 0) | \
                (8 if wid % 4 == 1 else 0)
            out_lines = []
            for j, text in enumerate(lines[:sentences]):
                src_ep = idx if j == 0 else rng.randrange(len(eps))
                # the list's first line is the first meeting's (analyzer note 35) but under Only i+1: there every
                # sixth word's first line is from another episode, with the first meeting second or not shown at all
                if wid % 6 in (2, 5) and len(eps) > 1:
                    src_ep = (idx + 1) % len(eps) if j == 0 else (idx if j == 1 and wid % 6 == 5 else src_ep)
                key = (src_ep, j == 2)
                if key not in cur["srcmap"]:
                    se = eps[src_ep]
                    base = se[1].split('/')[-1].rsplit('.', 1)[0]
                    play = f"0/{base}.mkv" if clip_ep is not None and src_ep in (clip_ep, clip_ep + 1) else (f"0/{base}.mp3" if src_ep % 3 == 0 else "")
                    cur["srcmap"][key] = len(cur["src"])
                    # SHAPE 1.1: the row's store item (here its episode's id; every 7th row a file the store doesn't hold)
                    cur["src"].append([se[2], se[5], src_ep, play, "", None if src_ep % 7 == 6 else se[0]])
                at = round(rng.uniform(5, 1300), 2)
                out_lines.append([text, cur["srcmap"][key], at, round(at + rng.uniform(1.5, 4.5), 2)])
            pitch = (_JA_PITCH.get(word) if lang == "ja" else next((t for z, _p, t, _g in _ZH if z == word), None))
            if lang == "ja" and pitch is None and wid % 3:
                pitch = str(len(reading) and wid % max(1, len(reading)))
            cur["w"].append([word, orth, reading, kana, forms, idx, marks, 1 + (wid % 9), pitch, out_lines])
            cur["size"] += 120 + sum(len(t[0]) * 3 for t in out_lines)
            gloss = _JA_GLOSS.get(word) if lang == "ja" else \
                next(([["", [g]]] for z, _p, _t, g in _ZH if z == word), None)
            if gloss:
                meanings[str(wid)] = gloss
            if lang == "ja":
                for ch in word:
                    if ch in _KANJI:
                        kanji[ch] = _KANJI[ch]
    for p in parts:
        n = len(p["w"])
        if not n:
            continue
        chunks.append({"w0": p["w0"], "src": p["src"], "w": p["w"]})
    freq = list(range(total))
    rng.shuffle(freq)
    yours = {}
    if meanings != "en":
        for k in list(meanings)[:50]:
            yours[k] = ["大辞林", "（名）" + "；".join(meanings[k][0][1])]
    finished = [[shows[0][0] + "f", shows_src[-1][0] + "（完）", shows_src[-1][1], shows_src[-1][2], 12, True]] \
        if n_eps > 10 else []
    head = {
        "v": 1, "minor": 1, "lang": lang, "stamp": stamp, "library": library,
        "settings": dict({"sentences": sentences, "meanings": meanings},
                         **({} if first_meeting is None else {"first_meeting": first_meeting})),
        "shows": shows, "eps": eps, "finished": finished, "orders": {"freq": freq},
        "chunks": [[c["w0"], len(c["w"])] for c in chunks],
        "dirs": ["file:///H:/Surasura-usage/tmp/journey-media/"],
        "blobs": ["meanings"] + (["kanji"] if lang == "ja" else []) + (["yours"] if yours else []),
        "counts": {"eps": len(eps), "words": total, "shows": len(shows), "with_new": sum(1 for n in plan if n)},
    }
    return {"head": head, "chunks": chunks, "meanings": meanings, "kanji": kanji, "yours": yours, "stones": {}}


def data_html(parts):
    """The elements the render puts at `<!--JOURNEY-DATA-->`, in SHAPE.md's order."""
    out = [f'<script type="application/json" id="j-head">{_json(parts["head"])}</script>']
    for i, c in enumerate(parts["chunks"]):
        out.append(f'<script type="application/gzip-base64" id="j-c{i}">{_gz64(c)}</script>')
    for name in ("meanings", "kanji", "yours"):
        if name in parts["head"]["blobs"]:
            out.append(f'<script type="application/gzip-base64" id="j-{name}">{_gz64(parts[name])}</script>')
    out.append(f'<script type="application/json" id="j-stones">{_json(parts["stones"])}</script>')
    return "\n".join(out)


def rail_html(name="stepper", css=None, js=None):
    """The chosen rail inlined (SPEC §1.1b): its own `.css` and `.js`, nothing else of the page changes."""
    if css is None:
        with open(os.path.join(TEMPLATES, f"rail-{name}.css"), encoding="utf-8") as f:
            css = f.read()
    if js is None:
        with open(os.path.join(TEMPLATES, f"rail-{name}.js"), encoding="utf-8") as f:
            js = f.read()
    return f"<style>\n{css}\n</style>\n<script>\n{js}\n</script>"


def assemble(parts, rail="stepper", rail_css=None, rail_js=None, extra_js=None):
    """The page as the render writes it; `extra_js` (the self-checks) goes in after the rail, before the page runs."""
    with open(os.path.join(TEMPLATES, "page.html"), encoding="utf-8") as f:
        page = f.read()
    assert page.count(DATA_MARK) == 1 and page.count(RAIL_MARK) == 1
    extra = f"\n<script>\n{extra_js}\n</script>" if extra_js else ""
    page = page.replace(RAIL_MARK, rail_html(rail, rail_css, rail_js) + extra)
    return page.replace(DATA_MARK, data_html(parts))


if __name__ == "__main__":
    lang, n, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(assemble(build(lang, n)))
    print(out, os.path.getsize(out))
