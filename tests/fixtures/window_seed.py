"""The window's synthetic seed (K69; the window's spec 07 §7.2): a library that looks like a learner's — shows split in
parts, a hero, mined and waiting episodes, missing videos, a Goal, a Finished record by month, New arrivals — with
**invented titles only**, at three scales: `SMALL` (about 40 rows), 2,000 files and 20,000 files.

The titles are W0.2's invented ones (the look test's `synth_seed.py`, planning folder `tracks/window/work/w02/`), whose
leak check against the real library found 0 hits; nothing here reads a real library. `leak_check(seed)` proves every
title, folder and path the seed made is built from that closed vocabulary and lives under the seed's own root.

`build(files=…, language=…)` → a `Seed`: the stand-in store's library (`tests/fixtures/standin_store.py`), the plan's
numbers per item (*% known*'s tokens and *N new*: the plan engine's shape, 04 §4.3), the items being mined now (Connect's
status), and the vocabulary. `write_files(seed, ids)` writes small subtitle files with real Japanese / Chinese lines
(`tests/Test Resources/`) for the items a test opens.

Deterministic for a given (files, language, rng seed).
"""
import os
import random
import re
from collections import namedtuple

from tests.fixtures import standin_store

SMALL = 0                                     # build(files=SMALL): the 40-row seed every behaviour test uses

# --- the invented vocabulary (W0.2's; none of it is a real title) --------------------------------------------- #
ANIME_JA = ["星降る街の小さな工房", "雲の上の郵便屋さん", "雷鳴の剣と見習い魔女", "海辺の図書室", "暁を待つ旅団",
            "雪国喫茶ほのか", "七番目の扉", "狐火と商店街", "ガラスの鯨が泳ぐ空", "花畑の騎士団", "空色ラジオ局",
            "紅葉坂の探偵", "鉄道少女と夜の駅", "陽だまり食堂の日々", "竜の子と羊飼い", "水鏡の王国", "細波ノート",
            "紡ぎ屋の娘と銀の糸", "星空キャンプ部", "金木犀の約束", "やまびこ農園物語", "海鳴りの聞こえる町で暮らす二人",
            "茜空の転校生", "蛍の住む町", "月影の配達人は今日も迷う", "風見鶏の鳴く丘"]
DRAMA_JA = ["鑑定士ミナミの事件簿", "街角ラーメン物語"]
NOVEL_JA = ["白銀の書庫番", "微睡みの魔導書と最後の弟子", "灰燼の王と見習い書記", "迷い家の宿帳", "鋼の令嬢は眠らない",
            "花籠の契約者", "蓬生の魔法薬店"]
BOOK_JA = ["夕暮れの手紙", "川辺の散歩道", "旅路のノート", "喫茶店の哲学", "四季の台所", "星読みの教科書",
           "泉のほとりで考えたこと", "ことだまの小さな辞典"]
PODCAST_JA = ["Hanashi Hanashi Radio"]
CHANNELS_JA = ["Tsubasa no Kitchen", "未来経済チャンネル", "毎日にほんご散歩", "Yamanote Walks", "ほのぼの実験室",
               "Kotoba Lab", "歴史ばなし研究所", "Machi Cafe TV", "空の写真館", "Nihongo Chatto", "鉄道ぶらり旅日記",
               "Bunko Review", "かがくの扉", "おしゃべり台所ラジオ", "暮らしの手帖ちゃんねる"]
VIDEO_JA = ["一週間お弁当を作り続けてみた", "駅前の古い喫茶店を巡る休日", "朝五時に起きる生活を一ヶ月続けた結果",
            "知らないと損する冷蔵庫の使い方", "雨の日の散歩で見つけた小さな発見", "百円ショップの道具だけでキャンプ",
            "祖母に教わった味噌汁の作り方", "誰でもできる簡単な家庭菜園", "電車で行ける静かな温泉街",
            "初めての陶芸教室で湯呑みを作る", "ノート術を変えたら勉強が楽になった", "夜行バスで北へ向かう旅",
            "部屋の片付けで暮らしが変わった話", "手作りパンを毎朝焼いてみた", "古本屋で見つけた不思議な一冊",
            "言葉の由来を調べてみたら面白かった", "町の小さな図書館を紹介します", "季節の和菓子を作ってみる",
            "自転車で湖を一周してみた", "なぜ人は行列に並ぶのか", "昔の地図で今の街を歩く", "雑草だけで晩ご飯は作れるか"]
VIDEO_OPEN = ["【検証】", "【初心者向け】", "【完全版】", "【雑談】", "【料理】", "【旅行vlog】", "【解説】", "", "", ""]
CHAPTERS_JA = ["旅立ちの朝", "雨の街角", "忘れられた手紙", "夜明け前", "星の降る丘", "約束の場所", "静かな図書室",
               "風の便り", "嘘と本当", "帰り道", "灯りの消えた家", "二人の秘密", "新しい季節", "遠い記憶", "小さな冒険",
               "最後の頁"]
# Chinese: invented the same way (E14)
ANIME_ZH = ["星落小镇的工坊", "云端邮差", "雷鸣之剑与见习魔女", "海边的图书室", "等待黎明的旅团", "雪国咖啡馆",
            "第七扇门", "狐火商店街", "玻璃鲸鱼游过的天空", "花田骑士团", "天空色电台", "红叶坂侦探", "夜车站的铁道少女",
            "向阳食堂的日子", "龙之子与牧羊人", "水镜王国"]
DRAMA_ZH = ["鉴定师南的事件簿", "街角拉面物语"]
NOVEL_ZH = ["白银书库管理员", "沉睡魔导书与最后的弟子", "灰烬之王与见习书记"]
BOOK_ZH = ["黄昏的信", "河边散步道", "旅途笔记", "咖啡馆的哲学"]
PODCAST_ZH = ["慢慢说中文电台"]
CHANNELS_ZH = ["小厨房频道", "未来经济频道", "每天学中文", "城市漫步", "温和实验室", "历史故事研究所"]
VIDEO_ZH = ["连续一周做便当", "车站前老咖啡馆巡礼", "早上五点起床一个月的结果", "雨天散步的小发现", "奶奶教我的汤",
            "坐火车去安静的温泉小镇", "第一次做陶艺", "每天早上自己烤面包", "在旧书店发现的奇怪的书", "骑车绕湖一圈"]
VIDEO_OPEN_ZH = ["【实测】", "【新手向】", "【完整版】", "【闲聊】", "", "", ""]
CHAPTERS_ZH = ["出发的早晨", "雨中街角", "被遗忘的信", "黎明之前", "星落之丘", "约定之地", "安静的图书室", "风的消息"]
SEASON_JA = "第{n}期"
SEASON_ZH = "第{n}季"
PART_JA = "第{n}部"
PART_ZH = "第{n}部"

TEXT_LINES = {"ja": os.path.join("ja", "phrases_sample.srt"), "zh": os.path.join("zh", "night_market.srt")}

Seed = namedtuple("Seed", "library opener numbers mining root language files vocabulary items works hero_work")


def _vocab(language):
    if language == "zh":
        return dict(anime=ANIME_ZH, drama=DRAMA_ZH, lightnovel=NOVEL_ZH, book=BOOK_ZH, podcast=PODCAST_ZH,
                    channels=CHANNELS_ZH, videos=VIDEO_ZH, video_open=VIDEO_OPEN_ZH, chapters=CHAPTERS_ZH,
                    season=SEASON_ZH, part=PART_ZH)
    return dict(anime=ANIME_JA, drama=DRAMA_JA, lightnovel=NOVEL_JA, book=BOOK_JA, podcast=PODCAST_JA,
                channels=CHANNELS_JA, videos=VIDEO_JA, video_open=VIDEO_OPEN, chapters=CHAPTERS_JA,
                season=SEASON_JA, part=PART_JA)


def vocabulary(language="ja"):
    """Every string a seed title, folder or file name may be built from (the leak check's closed set)."""
    v = _vocab(language)
    words = set()
    for key in ("anime", "drama", "lightnovel", "book", "podcast", "channels", "videos", "chapters", "video_open"):
        words.update(w for w in v[key] if w)
    return words


class _Builder:
    def __init__(self, language, rng, root):
        self.v = _vocab(language)
        self.language = language
        self.rng = rng
        self.root = root
        self.items, self.works = [], []
        self.cards, self.numbers = {}, {}
        self.mining = set()
        self.next_item = 1
        self.next_piece = 1
        self.ord = {t: 0.0 for t in standin_store.TIERS}
        self.position = 0                       # files placed in Current so far (n_new falls along it)
        self.used = {}

    def title(self, kind):
        pool = self.v[kind]
        base = pool[self.used.get(kind, 0) % len(pool)]
        n = self.used.get(kind, 0) // len(pool) + 1
        self.used[kind] = self.used.get(kind, 0) + 1
        return base if n == 1 else base + " " + self.v["season"].format(n=n)

    def work(self, title, media_type, folder, channel=None, anilist=None):
        w = {"id": len(self.works) + 1, "title": title, "title_by_user": 0, "titles": "[]", "folder_key": folder,
             "anilist_id": anilist, "tmdb_id": None, "youtube_channel": channel, "media_type": media_type,
             "media_type_by": "hato" if anilist else None, "cover_source": "generated", "cover_ref": None,
             "cover_path": None, "cover_fetched_at": None, "cover_locked": 0}
        self.works.append(w)
        return w

    def add(self, work, tier, names, folder, source_type="subtitle", watched=0, mined=0, missing=(), mined_missing=(),
            mining=(), graduated_at=None, pinned=None, numbers=True):
        """One piece: `names` its files' names, in order. -> the items."""
        piece = self.next_piece
        self.next_piece += 1
        out = []
        for k, name in enumerate(names):
            self.ord[tier] += 1024.0
            iid = self.next_item
            self.next_item += 1
            avail = "missing" if (k in missing or k in mined_missing) else "available"
            mined_at = "2026-10-0%dT09:00:00Z" % (1 + k % 6) if (k < mined or k in mined_missing) else None
            row = {"id": iid, "tier": tier, "ord": self.ord[tier], "rel_path": f"{folder}/{name}", "title": name,
                   "parent_folder": folder.split("/", 1)[1] if "/" in folder else None, "source_type": source_type,
                   "availability": avail, "work_id": work["id"], "piece_id": piece, "watched": 1 if k < watched else 0,
                   "mined_at": mined_at, "pinned": pinned, "mine_asked": None, "graduated_at": graduated_at,
                   "in_learning_order": 1, "added_at": "2026-09-01T10:00:00Z", "feed_in": 1}
            self.items.append(row)
            if mined_at:
                self.cards[iid] = [9_000_000 + iid * 100 + c for c in range(self.rng.randint(4, 14))]
            if k in mining:
                self.mining.add(iid)
            if numbers and tier in ("now", "soon", "goal"):
                counted = self.rng.randint(1800, 5200)
                known = int(counted * self.rng.uniform(0.86, 0.995))
                n_new = max(0, int(self.rng.randint(8, 40) * (1.0 / (1 + self.position / 400.0))))
                self.numbers[iid] = (known, counted, n_new)
                if tier in ("now", "soon"):
                    self.position += 1
            out.append(row)
        return out

    def episodes(self, title, first, last, ext=".srt"):
        return [f"{title} - {n:02d}{ext}" for n in range(first, last + 1)]

    def chapters(self, title, n):
        ch = self.v["chapters"]
        return [f"{title} {k + 1:02d} {ch[k % len(ch)]}.txt" for k in range(n)]

    def video(self):
        v = self.v
        name = v["video_open"][self.rng.randrange(len(v["video_open"]))] + v["videos"][self.rng.randrange(len(v["videos"]))]
        return name + f" [{self.rng.randrange(36 ** 6):06x}].srt"


TIER_FOLDER = {"now": "HighPriority", "soon": "LowPriority", "goal": "GoalContent", "graduated": "Graduated",
               "arrivals": "HighPriority/Hato"}


def build(files=SMALL, language="ja", rng_seed=7, root=None, mode="store", reason=None, current_share=None):
    """The seed. `files`: SMALL (≈ 40 rows, every state the mock shows) or a file count (2,000, 20,000: the same rows,
    then the library filled to that many files with shows and single videos, in the mock's shares — Current ≈ 13 % of
    the files, Goal ≈ 80 %; `current_share` (0–1) puts more in Current, for a stress run)."""
    rng = random.Random(rng_seed)
    root = root or os.environ.get("SURASURA_TEST_ROOT") or os.getcwd()
    b = _Builder(language, rng, root)
    v = b.v

    def show(tier, kind="anime", eps=12, title=None, first=1, **kw):
        t = title or b.title(kind)
        folder = f"{TIER_FOLDER[tier]}/{t}"
        w = kw.pop("work", None) or b.work(t, kind, folder)
        numbers_list = kw.pop("numbers_list", None)
        if kind in ("anime", "drama"):
            names = b.episodes(t, first, first + eps - 1)
        elif kind == "podcast":
            names = [f"{t} #{n}.srt" for n in (numbers_list or range(first, first + eps))]
        else:
            names = b.chapters(t, eps)
        b.add(w, tier, names, folder, source_type="subtitle" if kind in ("anime", "drama", "podcast") else "text", **kw)
        return w

    def videos(tier, n):
        ch = v["channels"][rng.randrange(len(v["channels"]))]
        vw = b.work(ch, "youtube", f"{TIER_FOLDER[tier]}/{ch}", channel=ch)
        b.add(vw, tier, [b.video() for _ in range(n)], f"{TIER_FOLDER[tier]}/{ch}", source_type="youtube",
              numbers=tier != "graduated", graduated_at="2026-06-01T20:00:00Z" if tier == "graduated" else None)
        return vw

    # Current (NOW), from the top: the rows every screen state needs (the top-20 line falls after row 5)
    t = b.title("anime")                                     # 1 the hero: from hato; 2 watched, 3 mined (Ep 2's video
    hero = b.work(t, "anime", f"HighPriority/Hato/{t}", anilist=101)   # removed after), Ep 4 being mined
    b.add(hero, "now", b.episodes(t, 1, 8), f"HighPriority/Hato/{t}", watched=2, mined=3, mined_missing={1},
          mining={3})
    videos("now", 1)                                         # 2 a single video, waiting in the top 20
    t = b.title("anime")                                     # 3 a show split in two parts: this one all in Anki
    split = b.work(t, "anime", f"HighPriority/{t}")
    b.add(split, "now", b.episodes(t, 1, 4), f"HighPriority/{t}", mined=4)
    show("now", "anime", eps=8, missing={2, 5, 7})           # 4 three with no video in the top 20 (A2 #5)
    show("now", "lightnovel", eps=3)                         # 5 the 20th available file: the line after it
    show("now", "anime", eps=8, mined=8, mined_missing={6})  # 6 all mined; Ep 7's video removed after (A2 #7, #8)
    b.add(split, "now", b.episodes(t, 5, 8), f"HighPriority/{t}")   # 7 the split show's second part, apart
    show("now", "drama", eps=6, missing=set(range(6)))       # 8 no video at all, below the line
    videos("now", 3)                                         # 9 a channel: three videos
    show("now", "podcast", eps=5, numbers_list=(1, 2, 3, 4, 6))   # 10 a podcast with a gap (#1–4, 6)
    # Soon (the Soon line before it)
    show("soon", "book", eps=5)
    show("soon", "anime", eps=10, missing={9})
    videos("soon", 1)
    # Goal: three titles, one in two parts
    g = show("goal", "anime", eps=12)
    show("goal", "lightnovel", eps=4)
    t2 = g["title"]
    show("goal", "anime", eps=12, title=t2, first=13, work=g)
    show("goal", "book", eps=6)
    # Finished: over four months, newest first; one with cards, one studying its cards first, one with no date
    for when, mined in (("2026-10-03", 99), ("2026-09-21", 0), ("2026-09-08", 0), ("2026-08-15", 0),
                        ("2026-07-02", 0)):
        show("graduated", "anime", eps=rng.randint(6, 12), watched=99, mined=mined, graduated_at=when + "T20:00:00Z",
             numbers=False)
    t = b.title("book")
    fw = b.work(t, "book", f"Graduated/{t}")
    b.add(fw, "graduated", b.chapters(t, 3), f"Graduated/{t}", watched=99, mined=3, graduated_at="2026-09-28T20:00:00Z",
          pinned="2026-09-29T08:00:00Z", numbers=False)
    show("graduated", "anime", eps=12, watched=99, graduated_at=None, numbers=False)   # finished before Surasura
    # New arrivals: a hato show
    t = b.title("anime")
    aw = b.work(t, "anime", f"HighPriority/Hato/{t}", anilist=202)
    b.add(aw, "arrivals", b.episodes(t, 1, 6), f"HighPriority/Hato/{t}", numbers=False)

    # Scale: fill to `files`, in the mock's shares (Current's tail in Soon, most in Goal) or `current_share`
    target = files if files and files > len(b.items) else 0
    tiers = ("soon", "goal", "graduated")
    share = 0.13 if current_share is None else current_share
    weights = (share, max(0.0, 0.93 - share), 0.07)
    while target and len(b.items) < target:
        tier = rng.choices(tiers, weights)[0]
        room = target - len(b.items)
        if rng.random() < 0.3:
            videos(tier, min(room, rng.randint(1, 3)))
        else:
            kind = rng.choices(("anime", "drama", "lightnovel", "book", "podcast"), (0.45, 0.1, 0.2, 0.15, 0.1))[0]
            n = min(room, rng.randint(2, 24))
            show(tier, kind, eps=n, missing={k for k in range(n) if rng.random() < 0.02},
                 numbers=tier != "graduated",
                 graduated_at=f"2026-0{rng.randint(1, 6)}-{rng.randint(1, 28):02d}T20:00:00Z" if tier == "graduated"
                 else None)

    now_files = sum(1 for r in b.items if r["tier"] == "now")
    meta = {"mine_line": standin_store.MINE_LINE_DEFAULT, "soon_line": now_files, "arrivals_on": 1}
    library = standin_store.StandinLibrary(b.items, b.works, meta=meta, cards=b.cards, mode=mode, reason=reason)
    numbers = _Numbers(b.numbers)
    mining = _Mining(b.mining)
    return Seed(library=library, opener=standin_store.StandinOpener(library), numbers=numbers, mining=mining,
                root=root, language=language, files=len(b.items), vocabulary=vocabulary(language), items=b.items,
                works=b.works, hero_work=hero["id"])


class _Numbers:
    """The plan's numbers, as the reader asks for them: `()` → (version, {item_id: (known, counted, n_new)})."""

    def __init__(self, table):
        self.table = dict(table)
        self.version = 1

    def __call__(self):
        return self.version, self.table

    def set(self, item_id, value):
        self.table = dict(self.table)
        self.table[item_id] = value
        self.version += 1


class _Mining:
    def __init__(self, ids):
        self.ids = set(ids)

    def __call__(self):
        return tuple(self.ids)


_SEASON = re.compile(r" 第\d+[期季]$")             # the season suffix the builder adds to a reused title


def leak_check(seed):
    """-> a list of problems (empty: clean). Every work's title is the vocabulary's (a season suffix allowed), every
    item's file name starts with its work's title or is one of the seed's video / chapter names, and no path leaves the
    seed's tiers."""
    vocab = seed.vocabulary
    problems = []
    for w in seed.works:
        base = _SEASON.sub("", w["title"])
        if base not in vocab:
            problems.append(f"work title not invented: {w['title']!r}")
    titles = {w["id"]: w["title"] for w in seed.works}
    for r in seed.items:
        top = r["rel_path"].split("/", 1)[0]
        if top not in ("HighPriority", "LowPriority", "GoalContent", "Graduated"):
            problems.append(f"path outside the tiers: {r['rel_path']!r}")
        name = r["title"]
        if not (name.startswith(titles[r["work_id"]]) or any(x in name for x in vocab)):
            problems.append(f"file name not invented: {name!r}")
    return problems


def write_files(seed, item_ids):
    """Write the named items' files under `seed.root`'s `data/<lang>/` with real lines from `tests/Test Resources/`
    (a test that opens one). -> {item_id: absolute path}."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(here, "Test Resources", TEXT_LINES[seed.language])
    with open(src, encoding="utf-8-sig") as f:
        text = f.read()
    out = {}
    by_id = {r["id"]: r for r in seed.items}
    for iid in item_ids:
        rel = by_id[iid]["rel_path"]
        path = os.path.join(seed.root, "data", seed.language, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        out[iid] = path
    return out
