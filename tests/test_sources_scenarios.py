"""PROVISIONAL (Sonic 2026-10-21, accepted for building, to be checked in use): this test is where a grouping rule is
re-judged; every new layout Sonic reports becomes a row here first.

3.0's Sources, the grouping rules against real folder layouts (the laptop fixes' scenario matrix): each row is a
folder shape a learner's library really holds — seasons, a `synced/` folder, `Subs/`, a split cour, specials, a
Plex / Sonarr tree, a BD rip, a backup full of config files, two releases in one folder — read by the REAL scan
(`sources.scan`, through `_look`: nothing under a source folder written) into an empty 3.0 library.

The rules under test (as decided, 2026-10-21):
1. A subfolder joins its show only when it is NAMED as a versions folder (`synced`, `sync`, `resync(ed)`, `retimed`,
   `timed`, `versions`, `alt`, `alternate`); any other subfolder (`Part 2`, `Movie`, `2期` …) stays its own show. A
   versions folder always stays with its show; a new number in it is the show's next episode.
2. `Subs/`, `Subtitles/` (and `Subs/<language>/`) are listed with the videos above them; so is a folder named only for
   our language (`JP/`, `[Japanese]`) and one named as the show folder itself; `<video>.ja.synced.srt` is a version.
3. Of one episode's subtitles: named exactly like its video AND holding our language first, then our language's tag,
   then the versions folder, then `.ass` before `.srt`, then the name.
4. A text with none of our language's script is skipped; a loose `.txt` / `.md` under 1,000 characters of the script
   is skipped. Seasons stay separate shows (S12).

Each row states what a LEARNER would want (`why`); the open cases (marked `open n`) assert the answer Sonic accepted,
naming the LM1b row that changes it where one does: the shows, the items, and which file each item's copy is (by its
bytes) and which video it is paired with. After the last look a Refresh (`full=True`) must change nothing. Every row
runs in a Japanese and a Chinese library (the language rule mirrored). Show names are made up; the texts are real
Japanese / Chinese from tests/Test Resources/, the videos a few bytes each (each its own).
"""
import hashlib
import json
import os
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, RESOURCES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _settle, _write  # noqa: F401

WAIT = "waiting"
_NAMES = {"ja": {"S": "Hoshizora Kissa", "S2": "Tsukikage Tabibito", "N": "星の図書館", "T": "ja", "TU": "JA",
                 "HUA": "話"},
          "zh": {"S": "Lanterns of Qinghe", "S2": "Yeshi Xiaoji", "N": "灯下书简", "T": "zh", "TU": "ZH", "HUA": "话"}}
# A language's own subtitle folders that are not `Subs/` (the open case: a learner's `JP/` beside the videos)
_LANG_FOLDERS = {"ja": ("JP", "ja", "[Japanese]", "Japanese Subs"), "zh": ("CHS", "zh", "[Chinese]", "中文字幕")}
_SUBS_LANG = {"ja": "Japanese", "zh": "Chinese"}
_REGION_FOLDERS = {"ja": ("ja-JP", "ja_JP"), "zh": ("zh_CN", "zh-Hant")}
# The common Chinese subtitle-folder names (a Chinese library only), and Japanese ones beside them (a Japanese one)
_ZH_FOLDERS = ("简体中文", "繁體中文", "Chinese (Simplified)", "中文字幕(简体)", "CHS&CHT")
_JA_FOLDERS = ("日本語字幕", "JPN_Subs")
_RES = {"ja": ("placed_episode.srt", "library_episode.ass", "phrases_sample.srt", "tv_captions.ass"),
        "zh": ("night_market.srt", "chinese_text_1.txt", "traditional_news.txt", "mixed_script_transcript.txt")}
_OTHER = {"ja": "zh", "zh": "ja"}
ENGLISH = ("1\n00:00:01,000 --> 00:00:03,000\nWhere did you put the lantern?\n\n"
           "2\n00:00:04,000 --> 00:00:06,500\nBy the river, where we left it last night.\n\n"
           "3\n00:00:07,000 --> 00:00:09,000\nThen we'd better hurry before the tide comes in.\n")
CONFIG = ("# look: plain\nbackground = plain.png\nfont_color = 255,255,255\nshow_covers = 1\n"
          "cover_style = flat\nlayout = grid4\n")
# A6: a signs-only track in our language (two dialogue lines) beside the episode's full subtitle (`FULL`)
_THIN = {"ja": "[Events]\nFormat: Layer, Start, End, Style, Text\n"
               "Dialogue: 0,0:00:01.00,0:00:03.00,Sign,喫茶ほしぞら　ひらいています　どうぞおはいりください\n"
               "Dialogue: 0,0:00:05.00,0:00:07.00,Sign,つぎのかい　ほしのよるに　またおあいしましょう\n",
         "zh": "[Events]\nFormat: Layer, Start, End, Style, Text\n"
               "Dialogue: 0,0:00:01.00,0:00:03.00,Sign,青河灯会今晚开始欢迎各位朋友光临\n"
               "Dialogue: 0,0:00:05.00,0:00:07.00,Sign,下一集我们在河边的夜市再见面吧\n"}
_FULL = {"ja": "placed_episode.srt", "zh": "night_market.srt"}
# a songs track, one line per sung line (sixty), each its own text
_SONGS = {"ja": "".join(f"Dialogue: 0,0:0{n // 10}:{n % 10}0.00,0:0{n // 10}:{n % 10}5.00,Song,ほしのうたを　うたいましょう"
                        f"　{n}ばんめ\n" for n in range(60)),
          "zh": "".join(f"Dialogue: 0,0:0{n // 10}:{n % 10}0.00,0:0{n // 10}:{n % 10}5.00,Song,我们一起唱河边的歌第{n}句\n"
                        for n in range(60))}


def _read(language, name):
    with open(os.path.join(RESOURCES, language, name), encoding="utf-8") as f:
        return f.read()


def _content(code, language, rel):
    """A file's bytes by its code: `J` our language's subtitle text (each file its own: its path appended), `X` the
    other language's, `EN` English, `CFG` a loader's config, `SHORT` a short text of ours (a track list: under 1,000
    script characters), `LONG` a long one of ours (a novel: over 1,000), `FULL` an episode's full subtitle of ours
    (its cues), `THIN` a signs-only track of ours (two lines: A6)."""
    pick = int(hashlib.sha256(rel.encode("utf-8")).hexdigest(), 16)
    if code == "FULL":
        return _read(language, _FULL[language]) + f"\n{rel}\n"
    if code == "THIN":
        return _THIN[language] + f"; {rel}\n"
    if code == "SONGS":
        return "[Events]\nFormat: Layer, Start, End, Style, Text\n" + _SONGS[language] + f"; {rel}\n"
    if code == "J":
        return _read(language, _RES[language][pick % 4]) + f"\n{rel}\n"
    if code == "X":
        other = _OTHER[language]
        return _read(other, _RES[other][pick % 4]) + f"\n{rel}\n"
    if code == "SHORT":
        return _read(language, "context_test.txt") + f"\n{rel}\n"
    if code == "LONG":
        body = _read("zh", "chinese_text_1.txt") if language == "zh" else \
            "\n".join(_read("ja", n) for n in _RES["ja"] + ("context_test.txt", "runaway_transcript.txt")) * 2
        return body + f"\n{rel}\n"
    return {"EN": ENGLISH, "CFG": CONFIG}[code] + f"\n# {rel}\n"


def _make(src, files, language, made):
    """The layout under the drive `src`: `V` a video (its own bytes), `D` an empty folder, else a text (`_content`);
    `made` gathers {sha256 of a text: its rel} so an item's copy names the file it came from."""
    for rel, code in files:
        path = os.path.join(src, *rel.split("/"))
        if code == "D":
            os.makedirs(path, exist_ok=True)
        elif code == "V":
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"\x1a\x45\xdf\xa3 fake matroska " + rel.encode("utf-8"))
            t = time.time() - 60                         # settled: a video written in the last seconds holds its text
            os.utime(path, (t, t))
        else:
            text = _content(code, language, rel)
            _write(path, text)
            made[hashlib.sha256(text.encode("utf-8")).hexdigest()] = rel
    _settle(src)


def _state(store, data_dir, src, made):
    """(the shows, {an item's place under Library/: the source file its copy holds [@ its video] | 'waiting'})."""
    items, works = {}, {}
    rows = store.conn.execute("SELECT id, rel_path, availability, work_id FROM items ORDER BY id").fetchall()
    for item_id, rel, availability, work in rows:
        place = rel[len(ls.CONTENT_FOLDER) + 1:] if rel.startswith(ls.CONTENT_FOLDER + "/") else rel
        works.setdefault(work, set()).add(os.path.dirname(place))
        if availability != "available":
            items[place] = availability
            continue
        with open(os.path.join(data_dir, rel), "rb") as f:
            got = made.get(hashlib.sha256(f.read()).hexdigest(), "?")
        seen = set()
        for (pairing,) in store.conn.execute("SELECT pairing FROM pairings WHERE item_id = ?", (item_id,)):
            record = (json.loads(pairing) or {}) if pairing else {}
            video = None if record.get("version") else record.get("video_path")   # another version's is no one's
            if video:
                seen.add(os.path.relpath(video, src).replace("\\", "/"))
        items[place] = got + "".join(f" @ {v}" for v in sorted(seen))
    return sorted(" + ".join(sorted(d)) for d in works.values()), items


def _ep(sub, video=None):
    return sub + (f" @ {video}" if video else "")


def _pairs(folder, stems, sub_ext, sub_folder=None):
    """Videos `folder/<stem>.mkv` and their subtitles `<sub_folder or folder>/<stem><sub_ext>`."""
    files = []
    for stem in stems:
        files.append((f"{folder}/{stem}.mkv", "V"))
        files.append((f"{sub_folder or folder}/{stem}{sub_ext}", "J"))
    return files


# --- the rows ------------------------------------------------------------------------------------------------------ #
# Each row: (id, whose shape: "laptop try" | "convention", the shape in words, root (the folder added, below the drive),
# files, files arriving before a later look (or None), the items a learner wants, why). `{S}` `{S2}` a show, `{N}` a
# novel, `{T}` our language's tag, `{TU}` it upper-cased, `{LF}` a language folder's name.

def _rows():
    rows = []
    ep = lambda n, s="{S}": f"[Grp] {s} - {n:02d} (1080p)"          # noqa: E731

    # (a) the laptop try's layouts, by shape (made-up names)
    crc = {9: "1A2B3C4D", 10: "5E6F7A8B", 11: "9C0D1E2F"}
    s2 = [f"[Grp] {{S}} S2 - {n:02d} (1080p) [{crc[n]}]" for n in (9, 10, 11)]
    for root, what in (("{S} S2", "the season's download folder read itself"),
                       ("", "the folder above the season's download folder read")):
        rows.append((f"season download, {'itself' if root else 'nested'}", "laptop try",
                     f"`<Show> S2/[G] <Show> S2 - 09 (1080p) [crc].mkv` + `.ja.srt` (09–11); {what}", root,
                     _pairs("{S} S2", s2, ".{T}.srt"), None,
                     {f"{{S}} S2/{s}.{{T}}.srt": _ep(f"{{S}} S2/{s}.{{T}}.srt", f"{{S}} S2/{s}.mkv") for s in s2},
                     "one show `<Show> S2`, three episodes, each its own subtitle paired with its video"))
    s03 = [ep(n, "{S} S03") for n in (1, 2, 3)]
    rows.append(("season + synced/ + main series", "laptop try",
                 "`<Show>/` (the main series) beside `<Show> S03/` (videos + `.ja.srt`) holding `synced/` (the same "
                 "names, re-timed)", "",
                 _pairs("{S}", [ep(1), ep(2)], ".{T}.srt") + _pairs("{S} S03", s03, ".{T}.srt")
                 + [(f"{{S}} S03/synced/{s}.{{T}}.srt", "J") for s in s03], None,
                 {**{f"{{S}}/{s}.{{T}}.srt": _ep(f"{{S}}/{s}.{{T}}.srt", f"{{S}}/{s}.mkv") for s in (ep(1), ep(2))},
                  **{f"{{S}} S03/{s}.{{T}}.srt": _ep(f"{{S}} S03/synced/{s}.{{T}}.srt", f"{{S}} S03/{s}.mkv")
                     for s in s03}},
                 "two shows (main, S03: seasons apart); S03's synced/ is its own versions, not a third show; the "
                 "re-timed text is the one read"))
    tags = {1: "WEB 1080p HEVC AAC", 2: "WEB 1080p HEVC AAC", 3: "TV 1080p HEVC AAC", 4: "TV 1080p AVC AAC"}
    sei = [f"[Raws] {{S}} - {n:02d}{' END' if n == 4 else ''} ({tags[n]})" for n in (1, 2, 3, 4)]
    sei_files = [(f"{{S}}/{s}{x}", c) for s in sei for x, c in ((".mkv", "V"), (".{T}.srt", "J"), (".{T}.ass", "J"))]
    for root, what in (("", "in the show's folder"), ("{S}", "the show's folder read itself (loose files)")):
        rows.append((f"two release tags, {'folder' if not root else 'loose'}", "laptop try",
                     f"one show, release tag `(WEB …)` for 01–02 and `(TV …)` for 03–04 END, a `.ja.srt` and a "
                     f"`.ja.ass` beside each video; {what}", root, sei_files, None,
                     {f"{{S}}/{s}.{{T}}.ass": _ep(f"{{S}}/{s}.{{T}}.ass", f"{{S}}/{s}.mkv") for s in sei},
                     "one show of four episodes (the tag change is no new show); one subtitle each, `.ass` first"))
    rows.append(("card backup with config files", "laptop try",
                 "`<Backups>/<Card Dump>/launcher/looks/<name>/look.txt` (ASCII config) beside a show", "",
                 _pairs("{S}", [ep(1)], ".{T}.srt")
                 + [("Backups/Card Dump/launcher/looks/plain/look.txt", "CFG"),
                    ("Backups/Card Dump/launcher/looks/night/look.txt", "CFG")], None,
                 {f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.srt", f"{{S}}/{ep(1)}.mkv")},
                 "the config files are no episodes (no word of our language): only the show's episode"))
    net = ["[Grp] {S} - 01 (1080p) [0A1B2C3D]", "[Grp] {S} - 02 (1080p) [4E5F6A7B]",
           "[Grp] {S} - 03v2 (1080p) [8C9D0E1F]"]
    rows.append(("flat show + v2 names + a tool's test folder", "laptop try (test folder)",
                 "`<Show>/[G] <Show> - 01 (1080p) [crc].mkv` + `.ja.ass`, an episode `- 03v2` on both files; a "
                 "leftover `_<tool>_test/` with one `.srt` and empty folders", "",
                 _pairs("{S}", net, ".{T}.ass") + [("{S}/_tool_test/_copy_src.srt", "J"),
                                                   ("{S}/_tool_test/lib/Now", "D"), ("{S}/_tool_test/lib/Soon", "D")],
                 None,
                 {**{f"{{S}}/{s}.{{T}}.ass": _ep(f"{{S}}/{s}.{{T}}.ass", f"{{S}}/{s}.mkv") for s in net},
                  "{S}/_tool_test/_copy_src.srt": "{S}/_tool_test/_copy_src.srt"},
                 "three episodes paired (03v2 is episode 3); the test folder's file is its own show (no rule tells "
                 "it from a show; *Never read this folder* takes it out)"))

    # (b) common conventions
    for kind, (one, two) in {"Season 1/2": ("Season 1", "Season 2"), "S01/S02": ("S01", "S02"),
                             "第1期/第2期": ("第1期", "第2期")}.items():
        rows.append((f"season folders {kind}", "convention",
                     f"`<Show>/{one}/` and `<Show>/{two}/`, each with videos + `.ja.srt` numbered from 01", "",
                     _pairs(f"{{S}}/{one}", ["{S} - 01"], ".{T}.srt") + _pairs(f"{{S}}/{two}", ["{S} - 01"], ".{T}.srt"),
                     None,
                     {f"{{S}}/{f}/{{S}} - 01.{{T}}.srt": _ep(f"{{S}}/{f}/{{S}} - 01.{{T}}.srt", f"{{S}}/{f}/{{S}} - 01.mkv")
                      for f in (one, two)},
                     "seasons stay separate shows (S12): two shows, each its own episode 1"))
    rows.append(("season folders, the show read itself", "convention",
                 "the show's folder added itself, holding `Season 1/` and `Season 2/`", "{S}",
                 _pairs("{S}/Season 1", ["{S} - 01"], ".{T}.srt") + _pairs("{S}/Season 2", ["{S} - 01"], ".{T}.srt"),
                 None,
                 {f"{{S}}/{f}/{{S}} - 01.{{T}}.srt": _ep(f"{{S}}/{f}/{{S}} - 01.{{T}}.srt", f"{{S}}/{f}/{{S}} - 01.mkv")
                  for f in ("Season 1", "Season 2")},
                 "the show's name goes in front of a season folder: `<Show>/Season 1`, `<Show>/Season 2`"))
    for part in ("Part 2", "2nd Cour", "2期", "Final Season"):
        rows.append((f"{part} named like part 1", "convention (LF-1)",
                     f"`<Show>/` videos + `.ja.srt` 01–02; `<Show>/{part}/` subtitles only, named exactly like "
                     f"part 1's", "",
                     _pairs("{S}", [ep(1), ep(2)], ".{T}.srt") + [(f"{{S}}/{part}/{ep(n)}.{{T}}.srt", "J") for n in (1, 2)],
                     None,
                     {**{f"{{S}}/{ep(n)}.{{T}}.srt": _ep(f"{{S}}/{ep(n)}.{{T}}.srt", f"{{S}}/{ep(n)}.mkv")
                         for n in (1, 2)},
                      **{f"{{S}}/{part}/{ep(n)}.{{T}}.srt": f"{{S}}/{part}/{ep(n)}.{{T}}.srt" for n in (1, 2)}},
                     f"`{part}` is another part, never versions of part 1: two shows, each its own text"))
    for extra in ("Specials", "SP", "OVA", "Extras", "Bonus"):
        rows.append((f"{extra} folder numbered from 01", "convention",
                     f"`<Show>/` episode 01; `<Show>/{extra}/` video + `.ja.srt` also numbered 01", "",
                     _pairs("{S}", [ep(1)], ".{T}.srt") + _pairs(f"{{S}}/{extra}", [ep(1)], ".{T}.srt"), None,
                     {f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.srt", f"{{S}}/{ep(1)}.mkv"),
                      f"{{S}}/{extra}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{extra}/{ep(1)}.{{T}}.srt",
                                                            f"{{S}}/{extra}/{ep(1)}.mkv")},
                     f"`{extra}`'s 01 is not the show's episode 1: its own show beside it"))
    rows.append(("Movie folder", "convention",
                 "`<Show>/Movie/<Show> Movie (1080p).mkv` + `.ja.srt` beside the episodes", "",
                 _pairs("{S}", [ep(1)], ".{T}.srt") + _pairs("{S}/Movie", ["{S} Movie (1080p)"], ".{T}.srt"), None,
                 {f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.srt", f"{{S}}/{ep(1)}.mkv"),
                  "{S}/Movie/{S} Movie (1080p).{T}.srt": _ep("{S}/Movie/{S} Movie (1080p).{T}.srt",
                                                             "{S}/Movie/{S} Movie (1080p).mkv")},
                 "the movie is its own show, never an episode"))
    # open case 5 (LM1b, A32): an NCOP / NCED / PV / CM / Menu video never makes a waiting item
    rows.append(("NCOP / NCED videos only", "convention (open 5, LM1b)",
                 "`<Show>/NCOP/NCOP1.mkv`, `<Show>/NCED/NCED1.mkv` (creditless openings, no subtitles)", "",
                 _pairs("{S}", [ep(1)], ".{T}.srt") + [("{S}/NCOP/NCOP1.mkv", "V"), ("{S}/NCED/NCED1.mkv", "V")], None,
                 {f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.srt", f"{{S}}/{ep(1)}.mkv")},
                 "the episode alone: a creditless opening or ending is nothing to read, never a waiting item"))
    for layout, sub in (("Subs/", "{S}/Subs/{S} - 01.{T}.srt"), ("Subtitles/", "{S}/Subtitles/{S} - 01.{T}.srt"),
                        ("Subs/<lang>/", "{S}/Subs/{T}/{S} - 01.srt"), ("Subs/<Language>/", "{S}/Subs/{LANG}/{S} - 01.srt"),
                        ("SUBS/ upper case", "{S}/SUBS/{S} - 01.{T}.srt")):
        rows.append((f"subtitle folder {layout}", "convention",
                     f"`<Show>/<Show> - 01.mkv` + `{layout}` holding its subtitle", "",
                     [("{S}/{S} - 01.mkv", "V"), (sub, "J")], None,
                     {f"{{S}}/{sub.rsplit('/', 1)[1]}": _ep(sub, "{S}/{S} - 01.mkv")},
                     "the subtitle folder is the show's: one show, the episode paired with its video"))
    # open case 6 (LM1b, A11): `Subs/<video>/` belongs to that video; its copy is named as the video
    rows.append(("Subs/<video name>/ per video", "convention (open 6, LM1b)",
                 "`<Show>/<Show> - 01.mkv` + `Subs/<Show> - 01/2_Japanese.srt` and `3_English.srt` (a rip's layout)",
                 "", [("{S}/{S} - 01.mkv", "V"), ("{S}/Subs/{S} - 01/2_{LANG}.srt", "J"),
                      ("{S}/Subs/{S} - 01/3_English.srt", "EN"), ("{S}/{S} - 02.mkv", "V"),
                      ("{S}/Subs/{S} - 02/2_{LANG}.srt", "J"), ("{S}/Subs/{S} - 02/3_English.srt", "EN")], None,
                 {f"{{S}}/{{S}} - {n:02d}.srt": _ep(f"{{S}}/Subs/{{S}} - {n:02d}/2_{{LANG}}.srt", f"{{S}}/{{S}} - {n:02d}.mkv")
                  for n in (1, 2)},
                 "each folder is its video's: one show, each episode its Japanese file, paired; English skipped"))
    for i in range(4):
        rows.append((f"language folder {i + 1} beside the videos", "convention (open 1)",
                     "`<Show>/` videos only + `<Show>/<language folder>/` (`JP/`, `ja/`, `[Japanese]`, "
                     "`Japanese Subs/`) holding their subtitles, named like the videos", "",
                     [(f"{{S}}/{ep(n)}.mkv", "V") for n in (1, 2)]
                     + [(f"{{S}}/{{LF{i}}}/{ep(n)}.{{T}}.srt", "J") for n in (1, 2)], None,
                     {f"{{S}}/{ep(n)}.{{T}}.srt": _ep(f"{{S}}/{{LF{i}}}/{ep(n)}.{{T}}.srt", f"{{S}}/{ep(n)}.mkv")
                      for n in (1, 2)},
                     "a folder named for our language beside the videos holds their subtitles, like `Subs/`: one "
                     "show, each episode paired"))
    for name in ("synced", "sync", "Resynced", "retimed", "timed", "versions", "alt", "alternate"):
        rows.append((f"versions folder {name}", "convention",
                     f"`<Show>/` videos + `.ja.srt` 01–02; `<Show>/{name}/` the same names", "",
                     _pairs("{S}", [ep(1), ep(2)], ".{T}.srt") + [(f"{{S}}/{name}/{ep(n)}.{{T}}.srt", "J") for n in (1, 2)],
                     None,
                     {f"{{S}}/{ep(n)}.{{T}}.srt": _ep(f"{{S}}/{name}/{ep(n)}.{{T}}.srt", f"{{S}}/{ep(n)}.mkv")
                      for n in (1, 2)},
                     f"`{name}/` holds versions of the show's episodes: one show, the versions folder's text read"))
    # open case 3, accepted in 3.0: a bracketed group name is no versions name, so the folder is a show of its own
    # (Never read this folder or a join fixes it); asked again with LM2 (the show's group)
    rows.append(("a release group's folder of versions", "convention (open 3)",
                 "`<Show>/` videos + `.ja.srt` 01–02; `<Show>/[Other]/[Other] <Show> - 01.ja.srt` … (another "
                 "group's subtitles of the same episodes)", "",
                 _pairs("{S}", [ep(1), ep(2)], ".{T}.srt")
                 + [(f"{{S}}/[Other]/[Other] {{S}} - {n:02d}.{{T}}.srt", "J") for n in (1, 2)], None,
                 {**{f"{{S}}/{ep(n)}.{{T}}.srt": _ep(f"{{S}}/{ep(n)}.{{T}}.srt", f"{{S}}/{ep(n)}.mkv") for n in (1, 2)},
                  **{f"{{S}}/[Other]/[Other] {{S}} - {n:02d}.{{T}}.srt":
                     f"{{S}}/[Other]/[Other] {{S}} - {n:02d}.{{T}}.srt" for n in (1, 2)}},
                 "accepted in 3.0: the show's episodes keep their own; the group's folder is a show of its own"))
    rows.append(("synced/ with names of its own", "convention",
                 "`<Show>/` videos + `.ja.srt`; `<Show>/synced/[Other] <Show> - 01 [synced].ja.srt` (another "
                 "release's name)", "",
                 _pairs("{S}", [ep(1)], ".{T}.srt") + [("{S}/synced/[Other] {S} - 01 [synced].{T}.srt", "J")], None,
                 {f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.srt", f"{{S}}/{ep(1)}.mkv")},
                 "one show, one item: the subtitle named like the video first (T2-A1), synced/'s is another version"))
    rows.append(("synced/ but only subtitles in it", "convention",
                 "`<Show>/` videos only; `<Show>/synced/` holding their subtitles (the folder's own were moved out)",
                 "", [(f"{{S}}/{ep(n)}.mkv", "V") for n in (1, 2)]
                 + [(f"{{S}}/synced/{ep(n)}.{{T}}.srt", "J") for n in (1, 2)], None,
                 {f"{{S}}/{ep(n)}.{{T}}.srt": _ep(f"{{S}}/synced/{ep(n)}.{{T}}.srt", f"{{S}}/{ep(n)}.mkv")
                  for n in (1, 2)},
                 "the versions folder is always the show's: each episode paired with its video, none waiting"))
    rows.append(("a .synced file beside the video", "convention (open 4)",
                 "`<Show>/[G] <Show> - 01 (1080p).mkv` + `.ja.srt` + `.ja.synced.srt` (a re-timer's output)", "",
                 _pairs("{S}", [ep(1)], ".{T}.srt") + [(f"{{S}}/{ep(1)}.{{T}}.synced.srt", "J")], None,
                 {f"{{S}}/{ep(1)}.{{T}}.synced.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.synced.srt", f"{{S}}/{ep(1)}.mkv")},
                 "ONE item for the episode (never two); the re-timed one read"))
    # open case 2: a subfolder named as the show folder is a subtitle folder (its texts the show's), each paired with
    # its video by its episode's number (LM1b, A4); one named like the archive stays a show of its own
    jimaku = lambda folder, n: f"{{S}}/{folder}/{{S}}.S01E{n:02d}.WEBRip.{{T}}.srt"      # noqa: E731
    rows.append(("jimaku zip unpacked like the show", "convention (open 2, LM1b)",
                 "`<Show>/` videos only; `<Show>/<Show>/` the downloaded subtitles, named their own way "
                 "(`<Show>.S01E01.WEBRip.ja.srt`)", "",
                 [(f"{{S}}/{ep(n)}.mkv", "V") for n in (1, 2)] + [(jimaku("{S}", n), "J") for n in (1, 2)], None,
                 {f"{{S}}/{{S}}.S01E{n:02d}.WEBRip.{{T}}.srt": _ep(jimaku("{S}", n), f"{{S}}/{ep(n)}.mkv") for n in (1, 2)},
                 "the subtitles are the show's: one show, one item per episode, each paired with its video by its "
                 "number"))
    rows.append(("jimaku zip unpacked like the archive", "convention (open 2, LM1b)",
                 "`<Show>/` videos only; `<Show>/<Show> [archive]/` the downloaded subtitles, named their own way",
                 "", [(f"{{S}}/{ep(n)}.mkv", "V") for n in (1, 2)]
                 + [(jimaku("{S} [Jimaku ja]", n), "J") for n in (1, 2)], None,
                 {**{jimaku("{S} [Jimaku ja]", n): jimaku("{S} [Jimaku ja]", n) for n in (1, 2)},
                  **{f"{{S}}/{ep(n)}.mkv": WAIT for n in (1, 2)}},
                 "accepted: an archive-named folder is a show of its own, the videos wait"))
    rows.append(("Sonarr / Plex tree", "convention",
                 "`<Show> (2023)/Season 01/<Show> - S01E01 - <Title>.mkv` + `.ja.srt`, `.ja.forced.srt`, `.en.srt`; "
                 "`Season 02/` the same", "",
                 [(f"{{S}} (2023)/Season {s:02d}/{{S}} - S{s:02d}E01 - The First Words{x}", c)
                  for s in (1, 2) for x, c in ((".mkv", "V"), (".{T}.srt", "J"), (".{T}.forced.srt", "J"), (".en.srt", "EN"))],
                 None,
                 {f"{{S}} (2023)/Season {s:02d}/{{S}} - S{s:02d}E01 - The First Words.{{T}}.srt":
                  _ep(f"{{S}} (2023)/Season {s:02d}/{{S}} - S{s:02d}E01 - The First Words.{{T}}.srt",
                      f"{{S}} (2023)/Season {s:02d}/{{S}} - S{s:02d}E01 - The First Words.mkv") for s in (1, 2)},
                 "two season shows; each episode its plain subtitle (forced and English passed over)"))
    rows.append(("BD rip with Scans and CDs", "convention",
                 "`<Show> [BD]/` videos + `.ja.ass`; `Scans/` (images), `CDs/<Show> OST/` (music + a short "
                 "Japanese track list `.txt`)", "",
                 _pairs("{S} [BD]", ["[Grp] {S} - 01 [BD 1080p]"], ".{T}.ass")
                 + [("{S} [BD]/Scans/01.jpg", "CFG"), ("{S} [BD]/CDs/{S} OST/tracklist.txt", "SHORT"),
                    ("{S} [BD]/CDs/{S} OST/01 Opening.flac", "CFG")], None,
                 {"{S} [BD]/[Grp] {S} - 01 [BD 1080p].{T}.ass": _ep("{S} [BD]/[Grp] {S} - 01 [BD 1080p].{T}.ass",
                                                                    "{S} [BD]/[Grp] {S} - 01 [BD 1080p].mkv")},
                 "the episode only: a CD's short track list is no book (under 1,000 characters)"))
    rows.append(("nested Show/Season/Subs and Show/Season/synced", "convention",
                 "`<Show>/Season 2/` videos; `Season 2/Subs/` the subtitle of 01, `Season 2/synced/` a re-timed 02 "
                 "beside 02's own", "",
                 [("{S}/Season 2/{S} - 01.mkv", "V"), ("{S}/Season 2/Subs/{S} - 01.{T}.srt", "J"),
                  ("{S}/Season 2/{S} - 02.mkv", "V"), ("{S}/Season 2/{S} - 02.{T}.srt", "J"),
                  ("{S}/Season 2/synced/{S} - 02.{T}.srt", "J")], None,
                 {"{S}/Season 2/{S} - 01.{T}.srt": _ep("{S}/Season 2/Subs/{S} - 01.{T}.srt", "{S}/Season 2/{S} - 01.mkv"),
                  "{S}/Season 2/{S} - 02.{T}.srt": _ep("{S}/Season 2/synced/{S} - 02.{T}.srt",
                                                       "{S}/Season 2/{S} - 02.mkv")},
                 "one show `<Show>/Season 2`, both episodes paired, 02 the re-timed text"))
    rows.append(("mixed case", "convention",
                 "`[GRP] <Show> - 01 (1080p).MKV` + `.JA.SRT`; `SYNCED/` its re-timed copy; `SUBS/` 02's subtitle",
                 "", [("{S}/[GRP] {S} - 01 (1080p).MKV", "V"), ("{S}/[GRP] {S} - 01 (1080p).{TU}.SRT", "J"),
                      ("{S}/SYNCED/[GRP] {S} - 01 (1080p).{T}.srt", "J"), ("{S}/[GRP] {S} - 02 (1080p).MKV", "V"),
                      ("{S}/SUBS/[GRP] {S} - 02 (1080p).{TU}.SRT", "J")], None,
                 {"{S}/[GRP] {S} - 01 (1080p).{T}.srt": _ep("{S}/SYNCED/[GRP] {S} - 01 (1080p).{T}.srt",
                                                            "{S}/[GRP] {S} - 01 (1080p).MKV"),
                  "{S}/[GRP] {S} - 02 (1080p).{TU}.SRT": _ep("{S}/SUBS/[GRP] {S} - 02 (1080p).{TU}.SRT",
                                                             "{S}/[GRP] {S} - 02 (1080p).MKV")},
                 "case never matters: one show, both paired, 01 the re-timed text"))
    stem = "{S} - 05"
    rows.append((".ja.srt + .ass + English .srt, one video", "convention",
                 "`<Show> - 05.mkv` + `<Show> - 05.ja.srt` + `<Show> - 05.ass` (ours, untagged) + `<Show> - 05.srt` "
                 "(English, untagged)", "",
                 [(f"{{S}}/{stem}.mkv", "V"), (f"{{S}}/{stem}.{{T}}.srt", "J"), (f"{{S}}/{stem}.ass", "J"),
                  (f"{{S}}/{stem}.srt", "EN")], None,
                 {f"{{S}}/{stem}.{{T}}.srt": _ep(f"{{S}}/{stem}.{{T}}.srt", f"{{S}}/{stem}.mkv")},
                 "one item: named like the video and ours, then the tag: the `.ja.srt`"))
    for code, lang_word in (("EN", "English"), ("X", "the other language's")):
        rows.append((f"untagged {lang_word} named like the video + ours named otherwise", "convention (LF-9)",
                     f"`<Show> - 05.mkv` + `<Show> - 05.srt` ({lang_word}, untagged, the video's exact name) + "
                     "`[JP] <Show> - 05.ja.srt`", "",
                     [(f"{{S}}/{stem}.mkv", "V"), (f"{{S}}/{stem}.srt", code), ("{S}/[JP] {S} - 05.{T}.srt", "J")],
                     None,
                     {"{S}/[JP] {S} - 05.{T}.srt": _ep("{S}/[JP] {S} - 05.{T}.srt", f"{{S}}/{stem}.mkv")},
                     "the text in our language is the episode, paired by its number (LM1b); a text we can't read "
                     "never is"))
    rows.append(("only an English subtitle beside the video", "convention",
                 "`<Show> - 05.mkv` + `<Show> - 05.srt` (English, untagged)", "",
                 [(f"{{S}}/{stem}.mkv", "V"), (f"{{S}}/{stem}.srt", "EN")], None,
                 {f"{{S}}/{stem}.mkv": WAIT},
                 "the video waits for a subtitle in our language"))
    rows.append(("two shows loose in a downloads folder", "convention",
                 "`Downloads/[G] <A> - 01 (1080p).mkv` + `.ja.srt` and `[G] <B> - 03 …` side by side, the folder "
                 "read itself", "Downloads",
                 _pairs("Downloads", [ep(1), ep(3, "{S2}")], ".{T}.srt"), None,
                 {f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"Downloads/{ep(1)}.{{T}}.srt", f"Downloads/{ep(1)}.mkv"),
                  f"{{S2}}/{ep(3, '{S2}')}.{{T}}.srt": _ep(f"Downloads/{ep(3, '{S2}')}.{{T}}.srt",
                                                           f"Downloads/{ep(3, '{S2}')}.mkv")},
                 "each file's show is read from its name: two shows"))
    rows.append(("a novel and a short note", "convention",
                 "`<Novel>/<Novel>.txt` (a long text) and `<Show>/notes.txt` (a few lines) beside an episode", "",
                 [("{N}/{N}.txt", "LONG"), ("{S}/notes.txt", "SHORT")] + _pairs("{S}", [ep(1)], ".{T}.srt"), None,
                 {"{N}/{N}.txt": "{N}/{N}.txt",
                  f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.srt", f"{{S}}/{ep(1)}.mkv")},
                 "the novel is a book; a loose note under 1,000 characters is not"))

    # (c) the delta adversary's layouts (2026-10-21, after the fix round)
    eps = [ep(1), ep(2)]
    for inner in ("Subs", "synced", "{LF0}"):
        # D1: a torrent saved into a folder of the same name: the inner folder is the outer one's, and so is the
        # pack's own subtitle folder inside it
        rows.append((f"show inside its namesake, with {inner.replace('{LF0}', 'a language folder')}", "convention (D1)",
                     f"`<Show>/<Show>/` videos, its subtitles in `<Show>/<Show>/{inner.replace('{LF0}', 'JP')}/`", "",
                     [(f"{{S}}/{{S}}/{s}.mkv", "V") for s in eps]
                     + [(f"{{S}}/{{S}}/{inner}/{s}.{{T}}.srt", "J") for s in eps], None,
                     {f"{{S}}/{s}.{{T}}.srt": _ep(f"{{S}}/{{S}}/{inner}/{s}.{{T}}.srt", f"{{S}}/{{S}}/{s}.mkv")
                      for s in eps},
                     "one show, each episode paired: nothing waits"))
    for show in ("JP-Story", "Ja_Ja Days", "Chi-Bi Nights"):
        # D2: a show whose name begins with a language code is a show, never a subtitle folder
        rows.append((f"show named {show}", "convention (D2)",
                     f"a show folder `{show}/` (`Episode 01.mkv` + `.ja.srt`) beside another show", "",
                     _pairs(show, ["Episode 01", "Episode 02"], ".{T}.srt") + _pairs("{S2}", ["Episode 01"], ".{T}.srt"),
                     None,
                     {**{f"{show}/Episode {n:02d}.{{T}}.srt": _ep(f"{show}/Episode {n:02d}.{{T}}.srt",
                                                                  f"{show}/Episode {n:02d}.mkv") for n in (1, 2)},
                      "{S2}/Episode 01.{T}.srt": _ep("{S2}/Episode 01.{T}.srt", "{S2}/Episode 01.mkv")},
                     "each show by its own name; its episodes never loose files of the folder above"))
    for i in range(2):
        # D2: a language-and-region folder beside the videos is our language's folder
        rows.append((f"language and region folder {i + 1} beside the videos", "convention (D2)",
                     "`<Show>/` videos only + `<Show>/ja-JP/` (ja: `ja-JP`, `ja_JP`; zh: `zh_CN`, `zh-Hant`) "
                     "holding their subtitles", "",
                     [(f"{{S}}/{s}.mkv", "V") for s in eps] + [(f"{{S}}/{{RF{i}}}/{s}.{{T}}.srt", "J") for s in eps],
                     None,
                     {f"{{S}}/{s}.{{T}}.srt": _ep(f"{{S}}/{{RF{i}}}/{s}.{{T}}.srt", f"{{S}}/{s}.mkv") for s in eps},
                     "the folder is our language's: one show, each episode paired"))
    for name in ("Synced Subs", "[Synced]", "synced_{T}", "Retimed ({LF0})"):
        # D3: a versions folder's name written with marks is still a versions folder
        rows.append((f"versions folder {name.replace('{T}', 'ja').replace('{LF0}', 'JP')}", "convention (D3)",
                     f"`<Show>/` videos + `.ja.srt` 01–02; `<Show>/{name.replace('{T}', 'ja').replace('{LF0}', 'JP')}/`"
                     " the same names", "",
                     _pairs("{S}", eps, ".{T}.srt") + [(f"{{S}}/{name}/{s}.{{T}}.srt", "J") for s in eps], None,
                     {f"{{S}}/{s}.{{T}}.srt": _ep(f"{{S}}/{name}/{s}.{{T}}.srt", f"{{S}}/{s}.mkv") for s in eps},
                     "versions of the show's episodes: one item per episode, the versions folder's text read"))
    for name in _ZH_FOLDERS + _JA_FOLDERS:
        # D4: the common Chinese subtitle-folder names (and the Japanese ones that held) beside the videos
        rows.append((f"subtitle folder named {name}", "convention (D4)",
                     f"`<Show>/` videos only + `<Show>/{name}/` holding their subtitles"
                     f" ({'Chinese' if name in _ZH_FOLDERS else 'Japanese'} library only)", "",
                     [(f"{{S}}/{s}.mkv", "V") for s in eps] + [(f"{{S}}/{name}/{s}.{{T}}.srt", "J") for s in eps],
                     None,
                     {f"{{S}}/{s}.{{T}}.srt": _ep(f"{{S}}/{name}/{s}.{{T}}.srt", f"{{S}}/{s}.mkv") for s in eps},
                     "the folder is our language's: one show, each episode paired, nothing waits"))
    rows.append(("an untagged English v2 beside our v1", "convention (D6)",
                 "`<Show> - 05.mkv` + `<Show> - 05.ja.srt` + `<Show> - 05v2.srt` (English, untagged)", "",
                 [("{S}/{S} - 05.mkv", "V"), ("{S}/{S} - 05.{T}.srt", "J"), ("{S}/{S} - 05v2.srt", "EN")], None,
                 {"{S}/{S} - 05.{T}.srt": _ep("{S}/{S} - 05.{T}.srt", "{S}/{S} - 05.mkv")},
                 "a v2 we can't read never keeps our v1 out: episode 5 is ours after ONE look"))
    rows.append(("a category folder named for the language", "convention (D9)",
                 "`<Japanese>/<Show>/` episodes, and loose episodes of another show directly in `<Japanese>/`", "",
                 _pairs("{LANG}/{S}", [ep(1)], ".{T}.srt") + _pairs("{LANG}", [ep(1, "{S2}")], ".{T}.srt"), None,
                 # today's behaviour, recorded: the category folder is the source root's subtitle folder, so its
                 # subfolders are shows as before (`Japanese/<Show>`) and its loose files are read like the root's own
                 # (their show from their names)
                 {f"{{LANG}}/{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{LANG}}/{{S}}/{ep(1)}.{{T}}.srt",
                                                          f"{{LANG}}/{{S}}/{ep(1)}.mkv"),
                  f"{{S2}}/{ep(1, '{S2}')}.{{T}}.srt": _ep(f"{{LANG}}/{ep(1, '{S2}')}.{{T}}.srt",
                                                           f"{{LANG}}/{ep(1, '{S2}')}.mkv")},
                 "shows named as before; the loose files read by their names (recorded)"))
    rows.append(("a show named with a leading dot, Mac copies and a tiny .ts", "convention (LF-21)",
                 "`.<title>/.<title> - 01.mkv` + `.ja.srt`; beside another show: `._<ep>.mkv`, `._<ep>.ja.srt`, "
                 "`.AppleDouble/`, and a `.ts` under 1 MB", "",
                 _pairs(".zero Line", [".zero Line - 01"], ".{T}.srt") + _pairs("{S}", ["{S} - 01"], ".{T}.srt")
                 + [("{S}/._{S} - 01.mkv", "V"), ("{S}/._{S} - 01.{T}.srt", "J"),
                    ("{S}/.AppleDouble/{S} - 01.{T}.srt", "J"), ("{S}/{S} - 02.ts", "V")], None,
                 {".zero Line/.zero Line - 01.{T}.srt": _ep(".zero Line/.zero Line - 01.{T}.srt",
                                                            ".zero Line/.zero Line - 01.mkv"),
                  "{S}/{S} - 01.{T}.srt": _ep("{S}/{S} - 01.{T}.srt", "{S}/{S} - 01.mkv")},
                 "a title starting with a dot is read; a Mac's copies are not; a tiny .ts is no video (no waiting "
                 "item)"))

    # (d) LM1b's layouts: one episode per key per show (PROVISIONAL, Sonic 2026-10-21)
    rows.append(("two releases' videos of one episode + a jimaku subtitle", "convention (LM1b, A5)",
                 "`[A] <Show> - 05 (1080p) [Dual Audio].mkv`, `[B] <Show> - 05 (720p).mkv` and `<title> 第5話.ja.srt`",
                 "", [("{S}/[A] {S} - 05 (1080p) [Dual Audio].mkv", "V"), ("{S}/[B] {S} - 05 (720p).mkv", "V"),
                      ("{S}/{N} 第5{HUA}.{T}.srt", "J")], None,
                 {"{S}/{N} 第5{HUA}.{T}.srt": _ep("{S}/{N} 第5{HUA}.{T}.srt", "{S}/[B] {S} - 05 (720p).mkv")},
                 "one episode with two videos: the subtitle joins it by number, on the video of our audio"))
    rows.append(("two releases' videos of one episode, no subtitle yet", "convention (LM1b, A5)",
                 "`[A] <Show> - 05 (1080p).mkv` and `[B] <Show> - 05 (720p).mkv`, nothing else", "",
                 [("{S}/[A] {S} - 05 (1080p).mkv", "V"), ("{S}/[B] {S} - 05 (720p).mkv", "V")], None,
                 {"{S}/[A] {S} - 05 (1080p).mkv": WAIT},
                 "one episode waits for its subtitle, never two"))
    rows.append(("a creditless opening beside a waiting episode", "convention (LM1b, A32)",
                 "`<Show> - 01.mkv` and `<Show> - NCOP1.mkv`, no subtitles", "",
                 [("{S}/{S} - 01.mkv", "V"), ("{S}/{S} - NCOP1.mkv", "V")], None,
                 {"{S}/{S} - 01.mkv": WAIT},
                 "only the episode waits"))
    rows.append(("subtitle folder named sub / 字幕", "convention (LM1b, A11)",
                 "`<Show>/<Show> - 01.mkv` + `sub/`, `<Show> - 02.mkv` + `字幕/` each holding its subtitle", "",
                 [("{S}/{S} - 01.mkv", "V"), ("{S}/sub/{S} - 01.{T}.srt", "J"), ("{S2}/{S2} - 02.mkv", "V"),
                  ("{S2}/字幕/{S2} - 02.{T}.srt", "J")], None,
                 {"{S}/{S} - 01.{T}.srt": _ep("{S}/sub/{S} - 01.{T}.srt", "{S}/{S} - 01.mkv"),
                  "{S2}/{S2} - 02.{T}.srt": _ep("{S2}/字幕/{S2} - 02.{T}.srt", "{S2}/{S2} - 02.mkv")},
                 "the subtitle folder is the show's: each episode paired, nothing waits"))
    rows.append(("a signs track and the full subtitle, both untagged", "convention (LM1b, A6)",
                 "`<Show> - 05.mkv` + `<Show> - 05.ass` (two sign lines) + `<Show> - 05.srt` (the dialogue)", "",
                 [("{S}/{S} - 05.mkv", "V"), ("{S}/{S} - 05.ass", "THIN"), ("{S}/{S} - 05.srt", "FULL")], None,
                 {"{S}/{S} - 05.srt": _ep("{S}/{S} - 05.srt", "{S}/{S} - 05.mkv")},
                 "the dialogue is the episode's text, never a track of signs (`.ass` first only between equals)"))
    # PROVISIONAL: single files win wherever they are; a double episode is a version only where
    # singles cover every number it claims
    rows.append(("a double episode and its second number's own file", "convention (LM1b, A13)",
                 "`<Show> - 05-06.ja.srt` and another group's `<Show> - 06.ja.ass`, no videos", "",
                 [("{S}/{S} - 05-06.{T}.srt", "J"), ("{S}/{S} - 06.{T}.ass", "J")], None,
                 {"{S}/{S} - 05-06.{T}.srt": "{S}/{S} - 05-06.{T}.srt", "{S}/{S} - 06.{T}.ass": "{S}/{S} - 06.{T}.ass"},
                 "episode 5 is only in the double file: it stays an item; 6 keeps its own file"))
    rows.append(("a double episode beside each number's video and subtitle", "convention (LM1b, A13)",
                 "videos `<Show> - 05.mkv`, `- 06.mkv`; subtitles `- 05.ja.srt`, `- 06.ja.srt` and `[J] <Show> - 05-06.ja.ass`",
                 "", _pairs("{S}", ["{S} - 05", "{S} - 06"], ".{T}.srt") + [("{S}/[J] {S} - 05-06.{T}.ass", "J")], None,
                 {f"{{S}}/{{S}} - {n:02d}.{{T}}.srt": _ep(f"{{S}}/{{S}} - {n:02d}.{{T}}.srt", f"{{S}}/{{S}} - {n:02d}.mkv")
                  for n in (5, 6)},
                 "each video keeps the subtitle made for it: two items; the double file is a version"))
    rows.append(("a folder of several shows' loose episodes", "convention (LM1b, A4)",
                 "`Watching/<A> - 01.mkv`, `Watching/<B> - 01.mkv` and `Watching/<title> 第1話.ja.srt` (whose?)", "",
                 [("Watching/{S} - 01.mkv", "V"), ("Watching/{S2} - 01.mkv", "V"), ("Watching/{N} 第1{HUA}.{T}.srt", "J")],
                 None, {"Watching/{N} 第1{HUA}.{T}.srt": "Watching/{N} 第1{HUA}.{T}.srt"},
                 "two shows' videos: a number joins no video (it could be either's); the subtitle is read, unpaired"))
    rows.append(("two remakes' episodes in one downloads folder", "convention (LM1b, A3)",
                 "`Downloads/<Show> (2009) - 05.ja.srt` and `<Show> (2023) - 05.ja.srt`, the folder read itself",
                 "Downloads", [("Downloads/{S} (2009) - 05.{T}.srt", "J"), ("Downloads/{S} (2023) - 05.{T}.srt", "J")],
                 None,
                 {"{S}/{S} (2009) - 05.{T}.srt": "Downloads/{S} (2009) - 05.{T}.srt",
                  "{S}/{S} (2023) - 05.{T}.srt": "Downloads/{S} (2023) - 05.{T}.srt"},
                 "the year keeps the remakes' episodes apart: two items"))
    rows.append(("a tagged .txt beside a video", "convention (LM1b, T2-B3)",
                 "`<Show> - 02.mkv` + `<Show> - 02.ja.txt` (a long text of ours), beside episode 01 paired", "",
                 _pairs("{S}", ["{S} - 01"], ".{T}.srt") + [("{S}/{S} - 02.mkv", "V"), ("{S}/{S} - 02.{T}.txt", "LONG")],
                 None,
                 {"{S}/{S} - 01.{T}.srt": _ep("{S}/{S} - 01.{T}.srt", "{S}/{S} - 01.mkv"),
                  "{S}/{S} - 02.{T}.txt": "{S}/{S} - 02.{T}.txt"},
                 "a text pairs with a video only by its exact name: the .txt is no subtitle of that video"))
    rows.append(("another group's subtitle with a title arrives for an episode in", "convention (LM1b)",
                 "a show 01 paired; later `[Other] <Show> - 01 - <Title>.ja.ass`", "",
                 _pairs("{S}", [ep(1)], ".{T}.srt"), [("{S}/[Other] {S} - 01 - The First Words.{T}.ass", "J")],
                 {f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.srt", f"{{S}}/{ep(1)}.mkv")},
                 "another version of episode 1: never a second item"))
    rows.append(("another group's v2 arrives for an episode in", "convention (LM1b, A8)",
                 "a show 01 paired (`[Grp]`); later `[Other] <Show> - 01v2.ja.srt`", "",
                 [(f"{{S}}/{ep(1)}.mkv", "V"), (f"{{S}}/{ep(1)}.{{T}}.srt", "FULL")],
                 [("{S}/[Other] {S} - 01v2.{T}.srt", "FULL")],
                 {f"{{S}}/{ep(1)}.{{T}}.srt": _ep(f"{{S}}/{ep(1)}.{{T}}.srt", f"{{S}}/{ep(1)}.mkv")},
                 "the pick sticks: another group's v2 is a version, never written over our text"))
    rows.append(("an episode's video arrives after its subtitle", "convention (LM1b, A19)",
                 "a show 01–02 paired and 03's subtitle alone; later 03's video", "",
                 _pairs("{S}", [ep(1), ep(2)], ".{T}.srt") + [(f"{{S}}/{ep(3)}.{{T}}.srt", "J")],
                 [(f"{{S}}/{ep(3)}.mkv", "V")],
                 {f"{{S}}/{ep(n)}.{{T}}.srt": _ep(f"{{S}}/{ep(n)}.{{T}}.srt", f"{{S}}/{ep(n)}.mkv") for n in (1, 2, 3)},
                 "episode 3 gets its video: three items, all paired"))

    # (e) a songs track, an extra, a second release, a year, `Subs/<video>/`
    rows.append(("a songs track out-lining the dialogue", "convention (LM1b)",
                 "`<Show> - 05.mkv` + `<Show> - 05.ja.srt` (the dialogue) + `<Show> - 05.ja.songs.ass` (sixty sung lines)",
                 "", [("{S}/{S} - 05.mkv", "V"), ("{S}/{S} - 05.{T}.srt", "FULL"), ("{S}/{S} - 05.{T}.songs.ass", "SONGS")],
                 None, {"{S}/{S} - 05.{T}.srt": _ep("{S}/{S} - 05.{T}.srt", "{S}/{S} - 05.mkv")},
                 "a flagged track never takes the dialogue's place, however many lines it has"))
    rows.append(("a creditless opening named after episode 1's number", "convention (LM1b)",
                 "`<Show> - 01.mkv`, `<Show> - 01 - NCOP.mkv`, `<Show> - 02.mkv` and `<title> 第1話.ja.srt`", "",
                 [("{S}/{S} - 01.mkv", "V"), ("{S}/{S} - 01 - NCOP.mkv", "V"), ("{S}/{S} - 02.mkv", "V"),
                  ("{S}/{N} 第1{HUA}.{T}.srt", "J")], None,
                 {"{S}/{N} 第1{HUA}.{T}.srt": _ep("{S}/{N} 第1{HUA}.{T}.srt", "{S}/{S} - 01.mkv")},
                 "episode 1's subtitle goes with episode 1's video, never the creditless opening's"))
    rows.append(("a subtitle named like the second release's waiting video", "convention (LM1b)",
                 "`[A] <Show> - 05 (1080p).mkv` and `[B] <Show> - 05 (720p).mkv` wait; later `[B] … (720p).ja.srt`",
                 "", [("{S}/[A] {S} - 05 (1080p).mkv", "V"), ("{S}/[B] {S} - 05 (720p).mkv", "V")],
                 [("{S}/[B] {S} - 05 (720p).{T}.srt", "J")],
                 {"{S}/[B] {S} - 05 (720p).{T}.srt": _ep("{S}/[B] {S} - 05 (720p).{T}.srt", "{S}/[B] {S} - 05 (720p).mkv")},
                 "the waiting episode takes its subtitle in place: one item, never a second beside the waiting one"))
    rows.append(("a year-named and a yearless subtitle of one episode", "convention (LM1b)",
                 "`<Show> (2019) - 05.ja.srt` (a Plex name) and `[Grp] <Show> - 05.ja.srt` (a fansub's), no videos", "",
                 [("{S}/{S} (2019) - 05.{T}.srt", "J"), ("{S}/[Grp] {S} - 05.{T}.srt", "J")], None,
                 {"{S}/{S} (2019) - 05.{T}.srt": "{S}/{S} (2019) - 05.{T}.srt"},
                 "one year in the show: the year is no remake's, one episode, the first by name (PROVISIONAL)"))
    rows.append(("Subs/<video>/ beside a jimaku .ass", "convention (LM1b)",
                 "`<Show> - 01.mkv` + `Subs/<Show> - 01/3_Japanese.srt` + `<title> 第1話.ja.ass` beside the video", "",
                 [("{S}/{S} - 01.mkv", "V"), ("{S}/Subs/{S} - 01/3_{LANG}.srt", "J"), ("{S}/{N} 第1{HUA}.{T}.ass", "J")],
                 None, {"{S}/{S} - 01.srt": _ep("{S}/Subs/{S} - 01/3_{LANG}.srt", "{S}/{S} - 01.mkv")},
                 "the file made for that video counts as named like it (T2-A1): it is the episode's text"))

    # (f) LM2's layouts: one subtitle group per show, picked once (PROVISIONAL, Sonic 2026-10-21: LM-1a, T2-A1, A29)
    grp = lambda g, n, x: f"{{S}}/[Subs{g}] {{S}} - {n:02d}.{{T}}.{x}"                     # noqa: E731
    rows.append(("two groups' subtitles for a whole show", "convention (LM2)",
                 "`[SubsA] <Show> - 01.ja.srt` + `[SubsB] <Show> - 01.ja.ass`, then 02–03 with the formats the other "
                 "way round (A `.ass`, B `.srt`), no videos", "",
                 [(grp("A", 1, "srt"), "J"), (grp("B", 1, "ass"), "J")]
                 + [(grp(g, n, x), "J") for n in (2, 3) for g, x in (("A", "ass"), ("B", "srt"))], None,
                 {grp("B", 1, "ass"): grp("B", 1, "ass"), **{grp("B", n, "srt"): grp("B", n, "srt") for n in (2, 3)}},
                 "the first episode's pick decides the show's group: every episode from B, never A for 02–03 because "
                 "their A file is an `.ass`"))
    rows.append(("the show's group and a subtitle named like its video", "convention (LM2, T2-A1)",
                 "as above for 01 and 03; 02 has the video `[SubsA] <Show> - 02 (1080p).mkv` and its own "
                 "`[SubsA] <Show> - 02 (1080p).ja.srt` beside `[SubsB] <Show> - 02.ja.ass`", "",
                 [(grp("A", 1, "srt"), "J"), (grp("B", 1, "ass"), "J"), (grp("A", 3, "ass"), "J"),
                  (grp("B", 3, "srt"), "J"), ("{S}/[SubsA] {S} - 02 (1080p).mkv", "V"),
                  ("{S}/[SubsA] {S} - 02 (1080p).{T}.srt", "J"), (grp("B", 2, "ass"), "J")], None,
                 {grp("B", 1, "ass"): grp("B", 1, "ass"), grp("B", 3, "srt"): grp("B", 3, "srt"),
                  "{S}/[SubsA] {S} - 02 (1080p).{T}.srt": _ep("{S}/[SubsA] {S} - 02 (1080p).{T}.srt",
                                                              "{S}/[SubsA] {S} - 02 (1080p).mkv")},
                 "a subtitle made for its video comes first (timed to it); the show's group decides only the rest"))
    rows.append(("the show's group and a songs track", "convention (LM2)",
                 "`[SubsA] <Show> - 01.ja.ass` + `[SubsB] … - 01.ja.srt` (A's: `.ass` first); 02 has A's "
                 "`.ja.songs.ass` (sixty sung lines) and B's `.ja.srt` (the dialogue), no videos", "",
                 [(grp("A", 1, "ass"), "J"), (grp("B", 1, "srt"), "J"),
                  ("{S}/[SubsA] {S} - 02.{T}.songs.ass", "SONGS"), (grp("B", 2, "srt"), "FULL")], None,
                 {grp("A", 1, "ass"): grp("A", 1, "ass"), grp("B", 2, "srt"): grp("B", 2, "srt")},
                 "the show's group never makes a songs track the text: 02 is B's dialogue"))
    rows.append(("another group's subtitles arrive for a show in", "convention (LM2)",
                 "`[SubsA] <Show> - 01.ja.srt`, `- 02.ja.srt` in; later B's `.ass` for 01–03 and A's `- 03.ja.srt`",
                 "", [(grp("A", n, "srt"), "J") for n in (1, 2)],
                 [(grp("B", n, "ass"), "J") for n in (1, 2, 3)] + [(grp("A", 3, "srt"), "J")],
                 {grp("A", n, "srt"): grp("A", n, "srt") for n in (1, 2, 3)},
                 "the show is A's: B's are other versions of 01–02, and 03 comes from A too"))
    rows.append(("a show starting mid-season with two groups", "convention (LM2, A29)",
                 "first `[SubsA] <Show> - 13.ja.srt` + `[SubsB] <Show> - 13.ja.ass`; later A's `- 01.ja.ass` (A alone) "
                 "and 14 from both (A `.ass`, B `.srt`)", "",
                 [(grp("A", 13, "srt"), "J"), (grp("B", 13, "ass"), "J")],
                 [(grp("A", 1, "ass"), "J"), (grp("A", 14, "ass"), "J"), (grp("B", 14, "srt"), "J")],
                 {grp("B", 13, "ass"): grp("B", 13, "ass"), grp("A", 1, "ass"): grp("A", 1, "ass"),
                  grp("B", 14, "srt"): grp("B", 14, "srt")},
                 "the group fixed at the first take-in two groups met in (13: B) stays; episode 1 arriving later "
                 "from A alone changes nothing"))

    # the two regressions over two looks
    three = [ep(n) for n in (1, 2, 3)]
    first = _pairs("{S}", three, ".{T}.srt") + [(f"{{S}}/synced/{s}.{{T}}.srt", "J") for s in three]
    want = {f"{{S}}/{s}.{{T}}.srt": _ep(f"{{S}}/synced/{s}.{{T}}.srt", f"{{S}}/{s}.mkv") for s in three}
    rows.append(("synced/ gains episode 4 with its video", "convention (LF-2)",
                 "a show + `synced/` (01–03); later the video of 04 and `synced/`'s 04 arrive", "", first,
                 [(f"{{S}}/{ep(4)}.mkv", "V"), (f"{{S}}/synced/{ep(4)}.{{T}}.srt", "J")],
                 {**want, f"{{S}}/{ep(4)}.{{T}}.srt": _ep(f"{{S}}/synced/{ep(4)}.{{T}}.srt", f"{{S}}/{ep(4)}.mkv")},
                 "the show's next episode: 4 items, never 01–03 twice"))
    rows.append(("synced/ gains episode 4 alone", "convention (LF-2)",
                 "a show + `synced/` (01–03); later only `synced/`'s 04 arrives (no video yet)", "", first,
                 [(f"{{S}}/synced/{ep(4)}.{{T}}.srt", "J")],
                 {**want, f"{{S}}/{ep(4)}.{{T}}.srt": f"{{S}}/synced/{ep(4)}.{{T}}.srt"},
                 "the show's next episode: 4 items, never 01–03 twice"))
    rows.append(("Part 2 named like part 1, arriving later", "convention (LF-1)",
                 "a show 01–02; later `Part 2/` with subtitles named exactly like part 1's", "",
                 _pairs("{S}", [ep(1), ep(2)], ".{T}.srt"), [(f"{{S}}/Part 2/{ep(n)}.{{T}}.srt", "J") for n in (1, 2)],
                 {**{f"{{S}}/{ep(n)}.{{T}}.srt": _ep(f"{{S}}/{ep(n)}.{{T}}.srt", f"{{S}}/{ep(n)}.mkv") for n in (1, 2)},
                  **{f"{{S}}/Part 2/{ep(n)}.{{T}}.srt": f"{{S}}/Part 2/{ep(n)}.{{T}}.srt" for n in (1, 2)}},
                 "part 1's items keep their text; Part 2 its own show"))
    return rows


ROWS = _rows()


def _fill(value, language):
    names = dict(_NAMES[language], LANG=_SUBS_LANG[language],
                 **{f"LF{i}": f for i, f in enumerate(_LANG_FOLDERS[language])},
                 **{f"RF{i}": f for i, f in enumerate(_REGION_FOLDERS[language])})
    return value.format(**names)


def _languages(row):
    """A row naming a folder of one language's own (D4) runs in that language's library only; the rest in both."""
    folder = row[0][len("subtitle folder named "):] if row[0].startswith("subtitle folder named ") else None
    return ("zh",) if folder in _ZH_FOLDERS else ("ja",) if folder in _JA_FOLDERS else LANGUAGES


CASES = [pytest.param(row, language, id=f"{row[0]}-{language}") for row in ROWS for language in _languages(row)]


@pytest.mark.parametrize("row,language", CASES)
def test_a_layout_is_read_as_a_learner_would_want(row, language, record_property):
    """One row of the scenario matrix, end to end through the real scan: the shows, each item and the file its copy
    holds (by bytes) with the video it is paired with — after the first look, after the later files' look, and the
    same after a Refresh."""
    _id, _whose, _shape, root, files, later, want, _why = row
    store, data_dir = _empty(language)
    drive = _drive("Anime")
    made = {}
    _make(drive, [(_fill(p, language), c) for p, c in files], language, made)
    want = {_fill(k, language): _fill(v, language) for k, v in want.items()}
    with store:
        rid = store.add_source(os.path.join(drive, _fill(root, language)) if root else drive)
        _look(store, language, rid, first=True)
        if later:
            _make(drive, [(_fill(p, language), c) for p, c in later], language, made)
            _look(store, language, rid)
        got = _state(store, data_dir, drive, made)
        record_property("actual", json.dumps({"shows": got[0], "items": got[1]}, ensure_ascii=False))
        _look(store, language, rid, full=True)
        again = _state(store, data_dir, drive, made)
    shows = sorted({os.path.dirname(k) for k in want})
    assert got == (shows, want)
    assert again == got, "a Refresh changed what the looks made"
