"""LM1a: ONE episode identity — every reader of a file name asks `app/episode_names.identity`.

Why these matter: seven readers each read a file name their own way (the look's `_tag`, `_episode_of`, `_release`,
`_SEASON`, the store's `show_of_name`, the window's `episode_number`, Connect's `names_for`, the covers' `_SEASON`) and
they disagreed: `Show - 05 - Title 12` was episode 12 in the window and 5 in the look, a `[CHS]` subtitle was Japanese,
season 2's episode 5 and a part 2 could be taken for another version of one episode. PINNED is what each reader answered
on these names: written first, on the readers as they were, then each row the shared rule moved marked `# moved`
with the adversary's row that moves it (the rest answer as before). All titles and groups are made up.
"""

import os
import unicodedata

import pytest

from app import episode_names as en
from app import library_store as ls
from app import sources
from app.connect import videos
from app.services import covers
from app.services import view_rows as vr
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _OTHER, _OURS, _SHOWS, _drive, _empty, _items, _look, _sha, _text, _write


PINNED = [
    ('[Kumorisubs] Hoshizora Kissa - 16 (1080p) [ABCD1234].ja.ass',
     ('[Kumorisubs] Hoshizora Kissa - 16 (1080p) [ABCD1234]', 'ja', set()), (16, 1), 'hoshizora kissa - 16',
     'Hoshizora Kissa', 16,
     ('[Kumorisubs] Hoshizora Kissa - 16 (1080p) [ABCD1234]', '[Kumorisubs] Hoshizora Kissa - 16 (1080p) [ABCD1234].ja')),
    ('[Kumorisubs] Hoshizora Kissa - 12v2 (1080p) [0F1E2D3C].ass',
     ('[Kumorisubs] Hoshizora Kissa - 12v2 (1080p) [0F1E2D3C]', None, set()), (12, 2), 'hoshizora kissa - 12',
     'Hoshizora Kissa', 12, ('[Kumorisubs] Hoshizora Kissa - 12v2 (1080p) [0F1E2D3C]',)),
    ('[Tsukiraws] Hoshizora Kissa S01E13 (1080p).ass', ('[Tsukiraws] Hoshizora Kissa S01E13 (1080p)', None, set()),
     (13, 1), 'hoshizora kissa s01e13', 'Hoshizora Kissa', 13, ('[Tsukiraws] Hoshizora Kissa S01E13 (1080p)',)),
    ('Hoshizora Kissa E13.srt', ('Hoshizora Kissa E13', None, set()), (13, 1), 'hoshizora kissa e13',
     'Hoshizora Kissa', 13, ('Hoshizora Kissa E13',)),
    ('Hoshizora Kissa #13.srt', ('Hoshizora Kissa #13', None, set()), (13, 1), 'hoshizora kissa #13',
     'Hoshizora Kissa', 13, ('Hoshizora Kissa #13',)),
    ('Hoshizora_Kissa_-_14_[720p].ja-JP.srt', ('Hoshizora_Kissa_-_14_[720p]', 'ja', set()), (14, 1),
     'hoshizora kissa - 14', 'Hoshizora Kissa', 14,
     ('Hoshizora_Kissa_-_14_[720p]', 'Hoshizora_Kissa_-_14_[720p].ja-JP')),   # moved: a video's name without `.ja-JP` (one tag of 5+ letters)
    ('Hoshizora.Kissa.S01E15.1080p.WEB.mkv', ('Hoshizora.Kissa.S01E15.1080p.WEB', None, set()), (15, 1),
     'hoshizora.kissa.s01e15. .web', 'Hoshizora Kissa', 15,
     ('Hoshizora.Kissa.S01E15.1080p', 'Hoshizora.Kissa.S01E15.1080p.WEB')),
    ('月影の旅人 第05話.srt', ('月影の旅人 第05話', None, set()), (5, 1), '月影の旅人 第05話', '月影の旅人', 5, ('月影の旅人 第05話',)),
    ('月影の旅人\u3000＃０５.ja.srt', ('月影の旅人\u3000＃０５', 'ja', set()), (5, 1), '月影の旅人 #05', '月影の旅人', 5,
     ('月影の旅人\u3000＃０５', '月影の旅人\u3000＃０５.ja')),
    ('某部电视剧 第13集.zh.srt', ('某部电视剧 第13集', 'zh', set()), (13, 1), '某部电视剧 第13集', '某部电视剧', 13,
     ('某部电视剧 第13集', '某部电视剧 第13集.zh')),
    ('【星の歌】 第05話.ass', ('【星の歌】 第05話', None, set()), (5, 1), '【星の歌】 第05話', '【星の歌】', 5, ('【星の歌】 第05話',)),
    ('[Kumorisubs] Hoshizora Kissa S2 - 05 (1080p) [ABCD1234].ass',
     ('[Kumorisubs] Hoshizora Kissa S2 - 05 (1080p) [ABCD1234]', None, set()), (5, 1), 'hoshizora kissa s2 - 05',
     'Hoshizora Kissa S2', 5, ('[Kumorisubs] Hoshizora Kissa S2 - 05 (1080p) [ABCD1234]',)),
    ('[Tsukiraws] Hoshizora Kissa S02E05 (1080p).ass', ('[Tsukiraws] Hoshizora Kissa S02E05 (1080p)', None, set()),
     (5, 1), 'hoshizora kissa s02e05', 'Hoshizora Kissa S2', 5, ('[Tsukiraws] Hoshizora Kissa S02E05 (1080p)',)),
    ('Hoshizora Kissa S01E05.ass', ('Hoshizora Kissa S01E05', None, set()), (5, 1), 'hoshizora kissa s01e05',
     'Hoshizora Kissa', 5, ('Hoshizora Kissa S01E05',)),
    ('月影の旅人 第2期 第05話.srt', ('月影の旅人 第2期 第05話', None, set()), (5, 1), '月影の旅人 第2期 第05話', '月影の旅人 第2期', 5,
     ('月影の旅人 第2期 第05話',)),
    ('[Group] Some Show II - 03 (720p).ass', ('[Group] Some Show II - 03 (720p)', None, set()), (3, 1),
     'some show ii - 03', 'Some Show II', 3, ('[Group] Some Show II - 03 (720p)',)),
    ('[Group] Some Show 2nd Season - 03.ass', ('[Group] Some Show 2nd Season - 03', None, set()), (3, 1),
     'some show 2nd season - 03', 'Some Show 2nd Season', 3, ('[Group] Some Show 2nd Season - 03',)),
    ('Some Show Season 2 - 03.ass', ('Some Show Season 2 - 03', None, set()), (3, 1), 'some show season 2 - 03',
     'Some Show Season 2', 3, ('Some Show Season 2 - 03',)),
    ('[Group] Robo Kissa 100 - 05 (1080p).ass', ('[Group] Robo Kissa 100 - 05 (1080p)', None, set()), (5, 1),
     'robo kissa 100 - 05', 'Robo Kissa 100', 5, ('[Group] Robo Kissa 100 - 05 (1080p)',)),
    ('05.srt', ('05', None, set()), (None, 1), '05', None, 5, ('05',)),
    ('第05話.srt', ('第05話', None, set()), (5, 1), '第05話', None, 5, ('第05話',)),
    ('星降る街 - 05.srt', ('星降る街 - 05', None, set()), (5, 1), '星降る街 - 05', '星降る街', 5, ('星降る街 - 05',)),
    ('雲の上の郵便屋さん 第7話.ass', ('雲の上の郵便屋さん 第7話', None, set()), (7, 1), '雲の上の郵便屋さん 第7話', '雲の上の郵便屋さん', 7,
     ('雲の上の郵便屋さん 第7話',)),
    ('show_ep03_final.srt', ('show_ep03_final', None, set()), (3, 1), 'show ep03 final', 'show', 3,
     ('show_ep03_final',)),
    ('Hanashi Radio #28.srt', ('Hanashi Radio #28', None, set()), (28, 1), 'hanashi radio #28', 'Hanashi Radio',
     28, ('Hanashi Radio #28',)),
    ('白銀の書庫番 02 雨の街角.txt', ('白銀の書庫番 02 雨の街角', None, set()), (None, 1), '白銀の書庫番 02 雨の街角', '白銀の書庫番 02 雨の街角', 2,
     ('白銀の書庫番 02 雨の街角',)),
    ('なぜ人は行列に並ぶのか.srt', ('なぜ人は行列に並ぶのか', None, set()), (None, 1), 'なぜ人は行列に並ぶのか', 'なぜ人は行列に並ぶのか', None,
     ('なぜ人は行列に並ぶのか', 'なぜ人は行列に並ぶのか')),   # moved: A24: its NFD form too
    ('雨音の庭 (2019).srt', ('雨音の庭 (2019)', None, set()), (None, 1), '雨音の庭', '雨音の庭', None, ('雨音の庭 (2019)',)),
    ('Hanashi Radio 2026-09-02.srt', ('Hanashi Radio 2026-09-02', None, set()), (None, 1),
     'hanashi radio 2026-09-02', 'Hanashi Radio 2026-09-02', None, ('Hanashi Radio 2026-09-02',)),
    ('海辺の図書室 - 05 [1080p] x264.mkv', ('海辺の図書室 - 05 [1080p] x264', None, set()), (5, 1), '海辺の図書室 - 05 x264',
     '海辺の図書室', 5, ('海辺の図書室 - 05 [1080p] x264',)),
    ('[Kumorisubs] 海辺の図書室 - 01 (1080p) [E04F4EFB].mkv',
     ('[Kumorisubs] 海辺の図書室 - 01 (1080p) [E04F4EFB]', None, set()), (1, 1), '海辺の図書室 - 01', '海辺の図書室', 1,
     ('[Kumorisubs] 海辺の図書室 - 01 (1080p) [E04F4EFB]',)),
    ('Show S01E05 [ABCD1234].mkv', ('Show S01E05 [ABCD1234]', None, set()), (5, 1), 'show s01e05', 'Show', 5,
     ('Show S01E05 [ABCD1234]',)),
    ('Show - 05 - Title 12.srt', ('Show - 05 - Title 12', None, set()), (5, 1), 'show - 05 - title 12', 'Show', 5,
     ('Show - 05 - Title 12',)),   # moved: A33: the window read 12
    ('Show - 12.5.srt', ('Show - 12.5', None, set()), (12.5, 1), 'show - 12.5', 'Show', 12.5, ('Show - 12.5',)),   # moved: A33: the window read 12
    ('Show OVA 01.srt', ('Show OVA 01', None, set()), (1, 1), 'show ova 01', 'Show OVA', 1, ('Show OVA 01',)),   # moved: A33: a special's own number; the look read none
    ('Show OVA - 01.ass', ('Show OVA - 01', None, set()), (1, 1), 'show ova - 01', 'Show OVA', 1,
     ('Show OVA - 01',)),
    ('Show - 01 (OVA).ass', ('Show - 01 (OVA)', None, set()), (1, 1), 'show - 01', 'Show', 1,
     ('Show - 01 (OVA)',)),
    ('Show - 05 Part 1.srt', ('Show - 05 Part 1', None, set()), (5, 1), 'show - 05 part 1', 'Show', 5,
     ('Show - 05 Part 1',)),   # moved: A3: the window read the part
    ('Show - 05 Part 2.srt', ('Show - 05 Part 2', None, set()), (5, 1), 'show - 05 part 2', 'Show', 5,
     ('Show - 05 Part 2',)),   # moved: A3: the window read the part
    ('星空喫茶 第5話 前編.srt', ('星空喫茶 第5話 前編', None, set()), (5, 1), '星空喫茶 第5話 前編', '星空喫茶', 5, ('星空喫茶 第5話 前編',)),
    ('星空喫茶 第5話 後編.srt', ('星空喫茶 第5話 後編', None, set()), (5, 1), '星空喫茶 第5話 後編', '星空喫茶', 5, ('星空喫茶 第5話 後編',)),
    ('Show - 05a.srt', ('Show - 05a', None, set()), (5, 1), 'show - 05a', 'Show', 5, ('Show - 05a',)),   # moved: A3: 05a is episode 5, part 1
    ('Show - 05-06.srt', ('Show - 05-06', None, set()), (5, 1), 'show - 05-06', 'Show', 5, ('Show - 05-06',)),   # moved: A13: the window read 6
    ('Show - 05.signs.ass', ('Show - 05', None, {'signs'}), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05.signs')),   # moved: A6: a flag
    ('Show - 05 [Signs & Songs].ass', ('Show - 05', None, {'signs', 'songs'}), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05 [Signs & Songs]')),   # moved: A6
    ('Show - 05 [Forced].ass', ('Show - 05', None, {'forced'}), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05 [Forced]')),   # moved: A6
    ('Show - 05.ja.forced.srt', ('Show - 05', 'ja', {'forced'}), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05.ja.forced')),   # moved: the video's name without its tags
    ('Show - 05.sdh.srt', ('Show - 05', None, {'sdh'}), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05.sdh')),
    ('[Grp][Show][05][GB_JP][1080P].ass', ('[Grp][Show][05][1080P]', None, set()), (5, 1), '', 'Show', 5,
     ('[Grp][Show][05][1080P]', '[Grp][Show][05][GB_JP][1080P]')),   # moved: A7: bilingual; the bracketed layout's show and number
    ('Show - 05 [CHS].ass', ('Show - 05', 'zh', set()), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05 [CHS]')),   # moved: A7: Chinese
    ('Show - 05.chs&jpn.ass', ('Show - 05', None, set()), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05.chs&jpn')),   # moved: A7: bilingual
    ('3_Japanese.srt', ('3_Japanese', 'ja', set()), (None, 1), '3 japanese', None, None, ('3_Japanese',)),   # moved: A11 / A33: a track
    ('4_English.srt', ('4_English', 'other', set()), (None, 1), '4 english', None, None, ('4_English',)),   # moved: A11 / A33: a track
    ('Show - 05_track3_[jpn].srt', ('Show - 05', 'ja', set()), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05_track3_[jpn]')),   # moved: A7
    ('Show - 05 [jpn].srt', ('Show - 05', 'ja', set()), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05 [jpn]')),   # moved: A7
    ('[A] Show 01.srt', ('[A] Show 01', None, set()), (None, 1), 'show 01', 'Show 01', 1, ('[A] Show 01',)),
    ('Show_05_[1080p].srt', ('Show_05_[1080p]', None, set()), (None, 1), 'show 05', 'Show 05', 5,
     ('Show_05_[1080p]',)),
    ('Show 2019 05.srt', ('Show 2019 05', None, set()), (None, 1), 'show 2019 05', 'Show 2019 05', 5,
     ('Show 2019 05',)),
    ('星空喫茶 第05話「出会い」.ass', ('星空喫茶 第05話「出会い」', None, set()), (5, 1), '星空喫茶 第05話「出会い」', '星空喫茶', 5,
     ('星空喫茶 第05話「出会い」',)),
    ('[Kumorisubs] Show - 05 (1080p) [CRC12345].srt', ('[Kumorisubs] Show - 05 (1080p) [CRC12345]', None, set()),
     (5, 1), 'show - 05', 'Show', 5, ('[Kumorisubs] Show - 05 (1080p) [CRC12345]',)),
    ('Show - 05.japanese.srt', ('Show - 05', 'ja', set()), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05.japanese')),   # moved: the video's name without its tag
    ('Show - 05.zh-Hans.srt', ('Show - 05', 'zh', set()), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05.zh-Hans')),   # moved: the video's name without its tag
    ('Show - 05.ja.srt', ('Show - 05', 'ja', set()), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05.ja')),
    ('[字幕组][某部电视剧][05][简体][1080P].mp4', ('[字幕组][某部电视剧][05][1080P]', 'zh', set()), (5, 1), '', '某部电视剧', 5,
     ('[字幕组][某部电视剧][05][1080P]', '[字幕组][某部电视剧][05][简体][1080P]')),   # moved: A7: Chinese; the bracketed layout's show and number
    ('某部电视剧 第05集 [简日双语].ass', ('某部电视剧 第05集', None, set()), (5, 1), '某部电视剧 第05集', '某部电视剧', 5,
     ('某部电视剧 第05集', '某部电视剧 第05集 [简日双语]')),   # moved: A7: bilingual
    ('Show - 05.eng.srt', ('Show - 05', 'other', set()), (5, 1), 'show - 05', 'Show', 5,
     ('Show - 05', 'Show - 05.eng')),
    ('Show - 12 [END].srt', ('Show - 12 [END]', None, set()), (12, 1), 'show - 12', 'Show', 12,
     ('Show - 12 [END]',)),
    ('Show - 12 [Fin].srt', ('Show - 12 [Fin]', None, set()), (12, 1), 'show - 12', 'Show', 12,
     ('Show - 12 [Fin]',)),
    ('Show NCOP.mkv', ('Show NCOP', None, set()), (None, 1), 'show ncop', 'Show NCOP', None, ('Show NCOP',)),
    ('Show - 05.mkv', ('Show - 05', None, set()), (5, 1), 'show - 05', 'Show', 5, ('Show - 05',)),
    ('ep01.director.srt', ('ep01.director', None, set()), (1, 1), 'ep01.director', None, 1, ('ep01.director',)),
    ('Show 1.5.srt', ('Show 1.5', None, set()), (None, 1), 'show 1.5', 'Show 1.5', None, ('Show 1.5',)),   # moved: A33: no `Show 1` (1.5 is no tag, no bare number)
]

# (folder, the look's season folder, the covers') before the rule was shared: now one reading, either's yes
PINNED_FOLDERS = [
    ('Season 1', True, True), ('Season 2', True, True), ('S2', True, True), ('2nd Season', True, False),
    ('Specials', True, False), ('SPs', True, False), ('Extras', True, False), ('OVA', True, False),
    ('第2期', True, True), ('2期', False, True), ('第二期', False, True), ('シーズン2', False, True),
    ('Season 2 - Arc', False, True), ('Series 3', True, True), ('Show', False, False), ('Subs', False, False),
    ('season02', True, True), ('S01', True, True),
]


def _stems(name):
    return tuple(sorted({v.rsplit(".", 1)[0] for v in videos.names_for(name)}))


@pytest.mark.parametrize("row", PINNED, ids=[r[0] for r in PINNED])
def test_every_reader_answers_each_name_as_pinned(row):
    """Each reader's answer on a made-up name: the look's tag, episode and release, the store's show, the window's
    number and the video names Connect looks for."""
    name, tag, episode, release, show, number, stems = row
    assert sources._tag(name) == tag
    assert sources._episode_of(name) == episode
    assert sources._release(name) == release
    assert ls.show_of_name(name) == show
    assert vr.episode_number(name) == number
    assert _stems(name) == tuple(sorted(stems))


@pytest.mark.parametrize("folder, look, cover", PINNED_FOLDERS, ids=[f[0] for f in PINNED_FOLDERS])
def test_a_season_folder_is_read_as_pinned(folder, look, cover):
    """The look's season or specials folder (its show gets the source's name in front) and the covers' (art is looked
    for one folder up) were two patterns, each missing some of the other's (`2期`, `Specials`): one reading now, a
    season folder wherever either read one."""
    assert (en.season_folder(folder) is not None) is (look or cover)


# --- the one rule: identity (pure) ------------------------------------------------------------------------------- #

def _key(name, **kw):
    return en.identity(name, **kw).key


def test_seasons_are_kept_apart_and_each_spelling_of_a_season_is_one():
    """A2: season 2's episode 5 is never season 1's (a `v2` of it never follows season 1's copy); `S02E05`, `S2 - 05`,
    `Season 2 - 05`, `2nd Season - 05` and `II - 05` are one season; season 1 is the show itself; a season folder
    gives a name without one its season."""
    assert _key("Hoshizora.Kissa.S01E05.mkv") != _key("Hoshizora.Kissa.S02E05.mkv")
    assert _key("S01E05.srt") != _key("S02E05.srt")
    two = {_key(n) for n in ("[Tsukiraws] Hoshizora Kissa S02E05 (1080p).ass", "Hoshizora Kissa S2 - 05.srt",
                             "Hoshizora Kissa Season 2 - 05.srt", "Hoshizora Kissa 2nd Season - 05.ass",
                             "Hoshizora Kissa II - 05.srt")}
    assert len(two) == 1 and en.identity("Hoshizora Kissa II - 05.srt").season == 2
    assert _key("Hoshizora Kissa S01E05.srt") == _key("Hoshizora Kissa - 05.srt")
    assert en.identity("月影の旅人 第2期 第05話.srt").season == 2
    assert en.identity("月影の旅人 2期 - 05.srt").season == 2
    assert en.identity("月影の旅人 第05話.srt", folder_name="Season 2").season == 2
    assert en.identity("月影の旅人 第05話.srt", folder_name="第2期").key == en.identity("月影の旅人 第2期 第05話.srt").key
    assert en.identity("月影の旅人 第05話.srt").season is None


def test_a_part_is_part_of_the_episode():
    """A3: `Part n`, `Pt n`, `前編 / 中編 / 後編`, `CD1`, `05a / 05b` (in brackets too) — two parts are two episodes; a
    part written before the episode number is the show's (`Final Season Part 2 - 05`)."""
    one, two = en.identity("Hoshizora Kissa - 05 Part 1.srt"), en.identity("Hoshizora Kissa - 05 Part 2.srt")
    assert (one.episode, one.part, two.episode, two.part) == (5, 1, 5, 2) and one.key != two.key
    assert en.identity("Hoshizora Kissa - 05 Pt.2.srt").part == 2
    assert en.identity("Hoshizora Kissa - 05 (Part 2).srt").part == 2
    assert [en.identity(f"星空喫茶 第5話 {p}.srt").part for p in ("前編", "中編", "後編")] == [1, 2, 3]
    assert (en.identity("Hoshizora Kissa - 05a.srt").episode, en.identity("Hoshizora Kissa - 05a.srt").part) == (5, 1)
    assert en.identity("Hoshizora Kissa - 05b.srt").part == 2
    assert en.identity("Hoshizora Kissa - 05 CD2.srt").part == 2
    assert en.identity("Hoshizora Kissa - 05.srt").part is None
    late = en.identity("Hoshizora Kissa Final Season Part 2 - 05.srt")
    assert (late.episode, late.part, late.show) == (5, None, "Hoshizora Kissa Final Season Part 2")


def test_a_range_claims_every_number_in_it():
    """A13: a double episode claims both numbers; a range that runs backwards is no range."""
    assert en.identity("Hoshizora Kissa - 05-06.srt").episodes == (5, 6)
    assert en.identity("Hoshizora Kissa - 05-06.srt").episode == 5
    assert en.identity("Hoshizora Kissa S01E05-E06.mkv").episodes == (5, 6)
    assert en.identity("Hoshizora Kissa S01E05E06.mkv").episodes == (5, 6)
    assert en.identity("月影の旅人 第5-6話.srt").episodes == (5, 6)
    assert en.identity("Hoshizora Kissa - 05.srt").episodes == (5,)
    assert en.identity("Hoshizora Kissa - 06-05.srt").episodes == (6,)
    assert en.identity("なぜ人は行列に並ぶのか.srt").episodes == ()


@pytest.mark.parametrize("name, mark", [
    ("Hoshizora Kissa - 01 (OVA).ass", "OVA"), ("Hoshizora Kissa OVA - 01.ass", "OVA"),
    ("Hoshizora Kissa OAD 2.srt", "OAD"), ("Hoshizora Kissa SP1.srt", "SP"),
    ("Hoshizora Kissa Special - 01.srt", "SPECIAL"), ("Hoshizora Kissa The Movie.srt", "MOVIE"),
    ("劇場版 星空喫茶.srt", "劇場版"), ("星空喫茶 総集編.srt", "総集編"), ("星空喫茶 特別編.srt", "特別編"),
    ("星空喫茶 番外編 第1話.srt", "番外編"), ("Hoshizora Kissa Recap.srt", "RECAP"),
    ("[Kumorisubs] Hoshizora Kissa - NCOP1 (1080p).mkv", "NCOP"), ("Hoshizora Kissa NCED.mkv", "NCED"),
    ("Hoshizora Kissa [PV].mkv", "PV"), ("Hoshizora Kissa CM01.mkv", "CM"), ("Hoshizora Kissa [Menu].mkv", "MENU"),
    ("Hoshizora Kissa - 05 Preview.mkv", "PREVIEW"),
])
def test_a_special_is_marked_wherever_its_mark_is(name, mark):
    """A4: OVA OAD SP Special Movie 劇場版 総集編 特別編 番外編 Recap NCOP NCED PV CM Menu Preview — anywhere, brackets
    included; a special's episode is never the show's episode of that number."""
    n = en.identity(name)
    assert n.special == mark
    if n.episode is not None:
        assert n.key != en.identity(f"Hoshizora Kissa - {int(n.episode):02d}.srt").key


def test_no_special_where_no_mark_is_whole():
    """A mark inside a word is no mark (`Spice`, `Spring`, `5cm`), and the plain episode is no special."""
    for name in ("Hoshizora Kissa - 05.srt", "Spice Kissa - 05.srt", "Spring Rain - 05.srt", "Kissa 5cm.srt",
                 "Hoshizora Kissa - 12 [END].srt", "Hoshizora Kissa - 05 [Signs & Songs].ass"):
        assert en.identity(name).special is False, name


@pytest.mark.parametrize("name, flags", [
    ("Hoshizora Kissa - 05.signs.ass", {"signs"}), ("Hoshizora Kissa - 05 [Signs & Songs].ass", {"signs", "songs"}),
    ("Hoshizora Kissa - 05 [Forced].ass", {"forced"}), ("Hoshizora Kissa - 05 [S&S].ass", {"s&s"}),
    ("Hoshizora Kissa - 05_karaoke.ass", {"karaoke"}), ("Hoshizora Kissa - 05.ja.sdh.srt", {"sdh"}),
    ("Hoshizora Kissa - 05 (Commentary).srt", {"commentary"}), ("Hoshizora Kissa - 05.lyrics.ass", {"lyrics"}),
    ("Hoshizora Kissa - 05 [OP].ass", {"op"}), ("Hoshizora Kissa - 05.ed.ass", {"ed"}),
    ("Hoshizora Kissa - 05.ja.srt", set()),
])
def test_a_tracks_flags_are_read_in_a_dot_tag_a_bracket_or_after_an_underscore(name, flags):
    """A6: a signs-only, songs, karaoke, commentary or lyrics track is flagged, never read as the episode's text."""
    n = en.identity(name)
    assert n.flags == frozenset(flags) and n.episode == 5


@pytest.mark.parametrize("name, language, bilingual", [
    ("Hoshizora Kissa - 05 [CHS].ass", "zh", False), ("Hoshizora Kissa - 05 [CHT].ass", "zh", False),
    ("Hoshizora Kissa - 05 [jpn].srt", "ja", False), ("Hoshizora Kissa - 05 (JPN).srt", "ja", False),
    ("Hoshizora Kissa - 05_track3_[jpn].srt", "ja", False), ("Hoshizora Kissa - 05 [ENG].srt", "other", False),
    ("3_Japanese.srt", "ja", False), ("4_English.srt", "other", False), ("5_Chinese.srt", "zh", False),
    ("[字幕组][某部电视剧][05][简体][1080P].ass", "zh", False), ("[字幕组][某部电视剧][05][繁體][1080P].ass", "zh", False),
    ("某部电视剧 第05集 [BIG5].ass", "zh", False), ("某部电视剧 第05集.sc.ass", "zh", False),
    ("[Grp][Hoshizora Kissa][05][GB_JP][1080P].ass", None, True), ("Hoshizora Kissa - 05.chs&jpn.ass", None, True),
    ("某部电视剧 第05集 [简日双语].ass", None, True), ("Hoshizora Kissa - 05 [CHS_JP].ass", None, True),
    ("Hoshizora Kissa - 05.ja.srt", "ja", False), ("Hoshizora Kissa - 05.srt", None, False),
    ("Hoshizora Kissa - 12 [END].srt", None, False), ("Hoshizora Kissa - 12 [Fin].srt", None, False),
    ("[Kumorisubs] Hoshizora Kissa - 05 (1080p) [ABCD1234].srt", None, False),
])
def test_language_marks_are_read_where_releases_write_them(name, language, bilingual):
    """A7: a closing bracket group, `_track3_[jpn]`, `N_Language`, the Chinese fansub marks; two languages in one mark
    are bilingual (both languages kept); `[END]` / `[Fin]` and a release's hash are no language."""
    n = en.identity(name)
    assert (n.language, n.bilingual) == (language, bilingual)
    if bilingual:
        assert len(n.languages) == 2
    if language:
        assert n.languages == {language}


def test_a_track_named_by_its_language_alone_has_no_episode_of_its_own():
    """A11 / A33: `Subs/<video>/3_Japanese.srt` — the 3 is a track, never episode 3 (its folder's video says which)."""
    for bare in (False, True):
        n = en.identity("3_Japanese.srt", bare_numbers=bare)
        assert (n.episode, n.show, n.language) == (None, None, "ja")


def test_a_bare_number_is_the_episode_only_when_the_caller_says_so():
    """A10: `[A] Show 01` and `[B] Show - 01` are one episode when the folder's names all read a bare number; never a
    year, a date or a resolution; never without the caller's word (the look's own reading stays K4's)."""
    assert en.identity("[A] Hoshizora Kissa 01.srt").episode is None
    a = en.identity("[A] Hoshizora Kissa 01.srt", bare_numbers=True)
    assert (a.episode, a.show) == (1, "Hoshizora Kissa") and a.key == _key("[B] Hoshizora Kissa - 01.ja.srt")
    assert en.identity("Hoshizora_Kissa_05_[1080p].srt", bare_numbers=True).episode == 5
    assert en.identity("Hoshizora Kissa 2019 05.srt", bare_numbers=True).episode == 5
    assert en.identity("Hoshizora Kissa 2019.srt", bare_numbers=True).episode is None
    assert en.identity("Hanashi Radio 2026-09-02.srt", bare_numbers=True).episode is None
    assert en.identity("Hoshizora Kissa 1080p.mkv", bare_numbers=True).episode is None


def test_names_are_compared_in_one_unicode_form():
    """A24: a name written in NFD (from a Mac or a zip) is the NFC name's episode, show and group; the video names a
    subtitle looks for hold both forms."""
    nfc = "ガール - 01.ja.srt"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc and en.identity(nfd).key == en.identity(nfc).key
    assert en.identity(nfd).show == en.identity(nfc).show == "ガール"
    assert en.identity(nfd).group == en.identity(nfc).group
    stems = en.video_stems(nfc)
    assert unicodedata.normalize("NFD", "ガール - 01") in stems and "ガール - 01" in stems


def test_a_release_groups_pattern_ignores_everything_after_the_number():
    """A28: the group is the leading [tag], the name before the episode marker and the folder: two episodes of one
    release share it whatever their titles, hashes and tags; another group's release has another."""
    a5 = en.identity("[Kumorisubs] Hoshizora Kissa - 05 (1080p) [ABCD1234].srt", folder_name="Hoshizora Kissa")
    a6 = en.identity("[Kumorisubs] Hoshizora Kissa - 06 (1080p) [1A2B3C4D].ja.srt", folder_name="Hoshizora Kissa")
    b5 = en.identity("[Tsukiraws] Hoshizora Kissa - 05 (720p).srt", folder_name="Hoshizora Kissa")
    assert a5.group == a6.group != b5.group and a5.group[0] == "kumorisubs"
    t5, t6 = en.identity("星空喫茶 第05話「出会い」.ass"), en.identity("星空喫茶 第06話「別れの朝」.ass")
    assert t5.group == t6.group and t5.group[1] == "星空喫茶"
    assert en.identity("x.srt", folder_name="A").group != en.identity("x.srt", folder_name="B").group


def test_the_bracketed_fansub_layout_reads_its_show_and_episode():
    """`[group][show][05][marks]`: the number in brackets is the episode, the bracket before it the show."""
    n = en.identity("[字幕组][某部电视剧][05][简体][1080P].mp4")
    assert (n.show, n.episode, n.group[0], n.language) == ("某部电视剧", 5, "字幕组", "zh")


def test_identity_of_nothing_is_nothing():
    """None or an empty name: no show, no episode, no marks."""
    for name in (None, ""):
        n = en.identity(name)
        assert (n.show, n.episode, n.episodes, n.language, n.special, n.bilingual) == \
            (None, None, (), None, False, False)


@pytest.mark.parametrize("folder, season", [
    ("Season 1", 1), ("Season 2", 2), ("S2", 2), ("season02", 2), ("Series 3", 3), ("2nd Season", 2), ("第2期", 2),
    ("2期", 2), ("第二期", 2), ("シーズン2", 2), ("Season 2 - Arc", 2), ("Specials", "special"), ("SPs", "special"),
    ("Extras", "special"), ("OVA", "special"), ("Hoshizora Kissa", None), ("Subs", None), ("synced", None),
])
def test_a_season_or_specials_folder_is_read_one_way(folder, season):
    """The look's season folder (its show gets the source's name in front) and the covers' (art one folder up) are one
    reading."""
    assert en.season_folder(folder) == season


# --- every reader on one rule ------------------------------------------------------------------------------------ #

AGREE = [r[0] for r in PINNED] + [
    "Hoshizora Kissa Episode 5.srt", "某部电视剧 第05集 [简日双语].ass", "Hoshizora Kissa - 05 [CHS].ass",
    "夜市小记 - 03.zh-Hans.srt", "夜市小记 第3集.cht.srt", "[字幕组][夜市小记][03][繁體][1080P].ass", "3_Chinese.srt",
    "Hoshizora Kissa - 05 Part 2.srt", "Hoshizora Kissa - 05-06.srt", "Hoshizora Kissa OVA 01.srt",
]


@pytest.mark.parametrize("name", AGREE)
def test_every_reader_reads_a_name_by_the_one_rule(name):
    """A33: the look, the store, the window and Connect read one episode, show and language from a name: the window
    reads a bare number too (it has no folder to ask), and where the look reads a number the window reads the same."""
    n, bare = en.identity(name), en.identity(name, bare_numbers=True)
    assert sources._episode_of(name) == (n.episode, n.version)
    assert sources._tag(name) == (n.stem, n.language, set(n.flags))
    assert ls.show_of_name(name) == n.show
    assert vr.episode_number(name) == bare.episode
    if n.episode is not None:
        assert vr.episode_number(name) == n.episode
    assert n.stem in _stems(name)


@pytest.mark.parametrize("folder", [f for f, _l, _c in PINNED_FOLDERS] + ["Season 2 Part 2", "シーズン3"])
def test_the_look_and_the_covers_read_one_season_folder(folder):
    """A season or specials folder is one reading for the look (`_show_of`: the source's name in front) and the covers
    (`_folders`: art looked for one folder up)."""
    is_season = en.season_folder(folder) is not None
    assert sources._show_of("C:/src/Root", [folder], "x.srt").startswith("Root/") is is_season
    assert ("Library/Show" in covers._folders([f"Library/Show/{folder}/x.srt"])) is is_season


# --- the look, reading by the one rule (real text, made-up shows) ---------------------------------------------- #

@pytest.fixture
def _fresh_look():
    """A look test starts as a new run of the app: no look made yet this run, no scan running."""
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()




@pytest.mark.usefixtures("_fresh_look")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_subtitle_bracket_marked_with_another_language_is_skipped(language):
    """A7: `Show - 01 [CHS].ass` in a Japanese library (`[JPN]` in a Chinese one) is another language's subtitle — it
    was read as untagged, so a Chinese file counted as Japanese; a pair of languages neither of them ours (`.eng&kor`,
    a bilingual `.chs&eng`) is skipped too."""
    store, _data = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    mark = {"ja": "CHS", "zh": "JPN"}[language]
    _write(os.path.join(src, show, f"[Grp] {show} - 01 [{mark}].ass"), _text(_OTHER[language], 1))
    _write(os.path.join(src, show, f"[Grp] {show} - 03.eng&kor.ass"), _text(_OTHER[language], 3))
    pair = {"ja": "chs&eng", "zh": "jpn&eng"}[language]                   # two languages, neither ours
    _write(os.path.join(src, show, f"[Grp] {show} - 04.{pair}.ass"), _text(_OTHER[language], 4))
    _write(os.path.join(src, show, f"[Grp] {show} - 02.srt"), _text(language, 2))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 1 and _items(store) == 1, result
        assert store.item(result["ids"][0])["rel_path"].endswith(" - 02.srt")


@pytest.mark.usefixtures("_fresh_look")
@pytest.mark.parametrize("language", LANGUAGES)
def test_season_twos_v2_never_follows_season_ones_episode(language):
    """A2: `S01E05.srt` is in; `S02E05v2.srt` arrives — another season's episode, its own item, never a v2 written over
    season 1's copy."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, show, "S01E05.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        first = _look(store, language, root, first=True)["ids"][0]
        copy = os.path.join(data_dir, *store.item(first)["rel_path"].split("/"))
        before = _sha(copy)
        _write(os.path.join(src, show, "S02E05v2.srt"), _text(language, 2))
        result = _look(store, language, root, full=True)
        assert (result["added"], result["attached"], result["recopied"]) == (1, 0, 0), result
        assert _items(store) == 2 and _sha(copy) == before


@pytest.mark.usefixtures("_fresh_look")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_signs_track_and_a_bilingual_file_are_one_episode_with_the_plain_subtitle(language):
    """A6 / A7: `- 01.signs.ass` and `- 01.chs&jpn.ass` are the episode `- 01.<ours>.srt` is (they were read as other
    names: three items for one episode); the plain one in our language is its text."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, show, f"[Grp] {show} - 01.signs.ass"), _text(language, 7))
    _write(os.path.join(src, show, f"[Grp] {show} - 01.chs&jpn.ass"), _text(language, 8))
    plain = _write(os.path.join(src, show, f"[Grp] {show} - 01.{_OURS[language]}.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 1 and _items(store) == 1, result
        copy = os.path.join(data_dir, *store.item(result["ids"][0])["rel_path"].split("/"))
        assert _sha(copy) == _sha(plain)


@pytest.mark.usefixtures("_fresh_look")
@pytest.mark.parametrize("language", LANGUAGES)
def test_an_ova_and_a_second_part_are_episodes_of_their_own(language):
    """A4 / A3: `- 01 (OVA).ass` is not episode 1, `- 05 (Part 2).srt` not part 1 — their marks in brackets came off
    as release marks, so one of each pair was skipped as another release of the other (the OVA's text winning)."""
    store, _data = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, show, f"{show} - 01.srt"), _text(language, 1))
    _write(os.path.join(src, show, f"{show} - 01 (OVA).ass"), _text(language, 2))
    _write(os.path.join(src, show, f"{show} - 05 (Part 1).srt"), _text(language, 3))
    _write(os.path.join(src, show, f"{show} - 05 (Part 2).srt"), _text(language, 4))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 4 and _items(store) == 4, result


@pytest.mark.usefixtures("_fresh_look")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_bilingual_file_is_taken_only_where_no_file_of_one_language_is(language):
    """A7: of one episode's `- 01.srt` (untagged) and `- 01.chs&jpn.ass`, the one-language file is the text, though an
    `.ass` comes before an `.srt`; with only the bilingual file it is taken (ours is one of its languages)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    plain = _write(os.path.join(src, show, f"{show} - 01.srt"), _text(language, 1))
    _write(os.path.join(src, show, f"{show} - 01.chs&jpn.ass"), _text(language, 2))
    both = _write(os.path.join(src, show, f"{show} - 02.chs&jpn.ass"), _text(language, 3))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 2 and _items(store) == 2, result
        copies = {_sha(os.path.join(data_dir, *store.item(i)["rel_path"].split("/"))) for i in result["ids"]}
        assert copies == {_sha(plain), _sha(both)}


def test_a_half_episodes_no_video_line_looks_for_its_own_number(tmp_path):
    """The window now reads `Show - 12.5` as 12.5 (the look always did): Needs you's *Find the video* says so, and a
    video named `- 12.5` is its answer, never episode 12's."""
    from app.services import needs
    show = tmp_path / "data" / "HighPriority" / "Hoshizora Kissa"
    show.mkdir(parents=True)
    line = needs.NeedLine("k", "", 1, "Ep 12.5", vr.episode_number("Hoshizora Kissa - 12.5.srt"),
                          "HighPriority/Hoshizora Kissa/Hoshizora Kissa - 12.5.srt", ())
    assert line.number == 12.5
    label, path, why = needs._find_one(line, str(tmp_path / "data"), [], "Hoshizora Kissa", needs._Lister())
    assert (path, why) == (None, '✗ nothing with "12.5" in its name')
    (show / "Hoshizora Kissa - 12.mkv").write_bytes(b"\x1a\x45\xdf\xa3 fake")
    (show / "Hoshizora Kissa - 12.5.mkv").write_bytes(b"\x1a\x45\xdf\xa3 fake")
    _label, path, _why = needs._find_one(line, str(tmp_path / "data"), [], "Hoshizora Kissa", needs._Lister())
    assert os.path.basename(path) == "Hoshizora Kissa - 12.5.mkv"
