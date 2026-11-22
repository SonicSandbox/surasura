"""The flagged sentences, Send report's list (`app/services/flags.py`; journey v3 SPEC §4, J-FLAGS): what a flag
holds, the one line per source + key + word, the cap, the lock between writers, the unreadable file, the clear after a
confirmed send, and the door's route and reader. Lines are real ones from `tests/Test Resources/ja` and `zh`.

What a wrong answer would cost: a path (the learner's home folder, their name in it) kept in a flag and sent; two
presses at once losing one flag; a full list silently dropping the oldest flags; a broken list overwritten (the
learner's flags gone); a sent flag left on the list, so it goes again and again — or one flagged again with a new note
after the zip was made taken off before that note ever went.
"""
import json
import os
import threading

import pytest

from app import path_utils
from app.services import flags

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "Test Resources")


def _srt_lines(language, name):
    """The text lines of a real subtitle file (no numbers, no times, no blank lines)."""
    text = path_utils.read_text(os.path.join(RES, language, name), language)
    return [x.strip() for x in text.splitlines() if x.strip() and not x.strip().isdigit() and "-->" not in x]


JA = _srt_lines("ja", "placed_episode.srt")          # 文化祭まで、あと三日しかないよ。 …
ZH = _srt_lines("zh", "night_market.srt")            # 大家好，歡迎回到我的頻道。 今天我们要去台北的夜市吃东西。 …


def _file(language):
    with open(os.path.join(path_utils.get_user_files_path(language), flags.FILE), encoding="utf-8") as f:
        return json.load(f)


def test_a_flag_holds_its_line_word_show_episode_time_reasons_and_note_and_reads_back():
    rec = flags.add("ja", JA[0], "文化祭", "journey", key="e12:1.0", show="放課後の教室", episode="第3話", at=1.0,
                    reasons=["too_long", "parsing", "nonsense"], note="「あと」が別の単語に見える")
    (got,) = flags.read("ja")
    assert got == rec
    assert (got["line"], got["word"], got["show"], got["episode"], got["at"]) == (JA[0], "文化祭", "放課後の教室",
                                                                                   "第3話", 1.0)
    assert got["reasons"] == ["parsing", "too_long"]            # known reasons only, in their own order
    assert got["source"] == "journey" and got["key"] == "e12:1.0" and len(got["id"]) == 12
    assert _file("ja")["format"] == flags.FORMAT
    assert flags.count("ja") == 1 and flags.read("zh") == []     # one list per language


def test_a_source_given_as_a_path_keeps_only_its_folder_and_file_names(tmp_path):
    """The loop may only know the card's file: it is kept as show + episode, never the path (nor the home folder
    in it, nor the name of the person whose folder it is)."""
    path = os.path.join(str(tmp_path), "Users", "Zoë Tanaka-Probe", "Videos", "夜市の話", "night_market - 02.srt")
    flags.add("zh", ZH[0], "夜市", "loop", key="note:1712", path=path, reasons=["parsing"])
    (got,) = flags.read("zh")
    assert (got["show"], got["episode"]) == ("夜市の話", "night_market - 02")
    raw = json.dumps(_file("zh"), ensure_ascii=False)
    assert "Zoë" not in raw and "Users" not in raw and str(tmp_path) not in raw


@pytest.mark.parametrize("given, kept", [
    ("C:\\Users\\Zoë\\Videos\\進撃の巨人", "進撃の巨人"),     # a drive path: its last part only
    ("\\\\DESKTOP-PROBE7\\share\\第3話", "第3話"),            # a share
    ("/home/zoe/anime/夜市", "夜市"),                         # a root
    ("Fate/Zero", "Fate/Zero"),                              # a title with a slash stays a title
    ("Dr. Stone", "Dr. Stone"),                              # a dot is no extension in a name
])
def test_a_show_or_episode_that_is_a_path_keeps_only_its_last_part(given, kept):
    flags.add("ja", JA[1], "授業", "journey", key="k", show=given, episode=given)
    (got,) = flags.read("ja")
    assert got["show"] == kept and got["episode"] == kept


def test_flagged_again_it_is_one_line_with_the_new_reasons_and_note():
    first = flags.add("ja", JA[2], "ぼーっと", "journey", key="e1:6.4", reasons=["parsing"])
    again = flags.add("ja", JA[2], "ぼーっと", "journey", key="e1:6.4", reasons=["bad_audio"], note="音が途切れる")
    (got,) = flags.read("ja")
    assert got["id"] == first["id"] and got["reasons"] == ["bad_audio"] and got["note"] == "音が途切れる"
    assert again["changed_ns"] > first["changed_ns"]
    same = flags.add("ja", JA[2], "ぼーっと", "journey", key="e1:6.4", reasons=["bad_audio"], note="音が途切れる")
    assert same["changed_ns"] == again["changed_ns"]            # nothing new: not a change
    flags.add("ja", JA[2], "気がつく", "journey", key="e1:6.4")    # the same line for another word: its own flag
    flags.add("ja", JA[2], "ぼーっと", "loop", key="e1:6.4")       # ... and from the loop
    assert flags.count("ja") == 3


def test_unflag_takes_off_only_that_line():
    flags.add("ja", JA[3], "準備", "journey", key="a")
    flags.add("ja", JA[4], "遅く", "journey", key="b")
    assert flags.unflag("ja", "journey", "a", "準備") is True
    assert flags.unflag("ja", "journey", "a", "準備") is False
    assert [x["word"] for x in flags.read("ja")] == ["遅く"]


def test_at_the_cap_a_new_flag_is_refused_and_none_is_dropped(monkeypatch):
    monkeypatch.setattr(flags, "MAX_LINES", 3)
    for i in range(3):
        flags.add("ja", JA[i], f"w{i}", "journey", key=str(i))
    with pytest.raises(flags.Full):
        flags.add("ja", JA[5], "大砲", "journey", key="new")
    assert [x["key"] for x in flags.read("ja")] == ["0", "1", "2"]
    flags.add("ja", JA[0], "w0", "journey", key="0", note="まだ変えられる")   # one already there still changes
    assert flags.read("ja")[0]["note"] == "まだ変えられる"


@pytest.mark.parametrize("line, source", [("", "journey"), ("   ", "journey"), (JA[6], "window")])
def test_no_line_or_an_unknown_source_flags_nothing(line, source):
    with pytest.raises(ValueError):
        flags.add("ja", line, "腑に落ちる", source)
    assert not os.path.exists(os.path.join(path_utils.get_user_files_path("ja"), flags.FILE))


def test_a_long_line_and_note_are_cut_and_crlf_is_one_line():
    flags.add("zh", (ZH[1] + "\r\n") * 100, "夜市", "journey", key="k", note="长" * 2000)
    (got,) = flags.read("zh")
    assert len(got["line"]) == flags.LINE_MAX and "\r" not in got["line"] and "\n" not in got["line"]
    assert len(got["note"]) == flags.NOTE_MAX


def test_an_unreadable_list_is_set_aside_never_overwritten():
    folder = path_utils.get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, flags.FILE)
    broken = b"\x81\x00\xfe\xfa{\"lines\": [\xff"
    with open(path, "wb") as f:
        f.write(broken)
    assert flags.read("ja") == [] and flags.count("ja") == 0     # read: nothing, and nothing written
    with open(path, "rb") as f:
        assert f.read() == broken
    flags.add("ja", JA[7], "看板", "journey", key="k")
    kept = [n for n in os.listdir(os.path.join(folder, ".trash")) if n.startswith("flagged_lines.")]
    assert len(kept) == 1
    with open(os.path.join(folder, ".trash", kept[0]), "rb") as f:
        assert f.read() == broken
    assert [x["word"] for x in flags.read("ja")] == ["看板"]


def test_json_that_isnt_the_list_is_set_aside_too():
    folder = path_utils.get_user_files_path("zh")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, flags.FILE), "w", encoding="utf-8") as f:
        json.dump(["今天"], f)
    flags.add("zh", ZH[0], "今天", "journey", key="k")
    assert any(n.startswith("flagged_lines.") for n in os.listdir(os.path.join(folder, ".trash")))
    assert flags.count("zh") == 1


def test_two_writers_at_once_never_lose_a_flag():
    """The door's threads (and the loop) write the same file: each add reads it again under the lock."""
    errors = []

    def writer(n):
        try:
            for i in range(5):
                flags.add("ja", JA[(n + i) % len(JA)], f"w{n}-{i}", "journey", key=f"{n}:{i}")
        except Exception as e:                                   # (a lost race would show as a missing line)
            errors.append(e)
    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert flags.count("ja") == 30


def test_clear_sent_takes_off_only_the_lines_sent_unchanged():
    a = flags.add("ja", JA[0], "文化祭", "journey", key="a", reasons=["parsing"])
    b = flags.add("ja", JA[1], "授業", "journey", key="b")
    flags.add("ja", JA[2], "ぼーっと", "journey", key="c")                 # flagged after the zip: not in it
    sent = {a["id"]: a["changed_ns"], b["id"]: b["changed_ns"]}
    flags.add("ja", JA[1], "授業", "journey", key="b", note="送った後のメモ")  # changed after the zip
    assert flags.clear_sent("ja", sent) == 1
    assert sorted(x["key"] for x in flags.read("ja")) == ["b", "c"]
    assert flags.clear_sent("ja", {}) == 0


def test_for_report_holds_exactly_the_fields_and_splits_only_a_parsing_line():
    flags.add("ja", JA[6], "腑に落ちる", "journey", key="e7:18.0", show="放課後の教室", episode="第3話", at=18.0,
              reasons=["parsing"], note="腑に落ちた が分かれてる")
    flags.add("ja", JA[5], "大砲", "journey", key="e7:15.0", reasons=["bad_audio"])
    (_, _, parsing), (_, _, audio) = flags.for_report("ja")
    assert set(parsing) == {"line", "word", "show", "episode", "at", "reasons", "note", "added", "source", "split"}
    assert set(audio) == set(parsing) - {"split"}
    assert "".join(t[0] for t in parsing["split"]) == "先生の説明やっと腑に落ちた"   # its words, the marks left out
    assert ["落ち", "落ちる"] in parsing["split"]                  # [surface, the word the list counts]


def test_a_chinese_parsing_line_is_split_by_jieba():
    flags.add("zh", ZH[1], "夜市", "journey", key="k", reasons=["parsing"])        # 今天我们要去台北的夜市吃东西。
    ((_, _, line),) = flags.for_report("zh")
    assert any(t[0] == "夜市" for t in line["split"])


def test_a_split_that_fails_leaves_null_and_the_line_still_goes():
    flags.add("ja", JA[8], "看板", "journey", key="k", reasons=["parsing"])

    def broken(language, text):
        raise RuntimeError("no tagger")
    ((_, _, line),) = flags.for_report("ja", split=broken)
    assert line["split"] is None and line["line"] == JA[8]


def test_the_lit_flags_read_back_are_the_journeys_whole_set():
    flags.add("ja", JA[0], "文化祭", "journey", key="e1:1.0")
    flags.add("ja", JA[1], "授業", "loop", key="note:9")
    assert flags.door_state("ja", None, None) == {"flagged": [["e1:1.0", "文化祭"]]}
    assert flags.door_state("zh", None, None) == {"flagged": []}


class _App:
    def __init__(self, lang="ja"):
        self.lang = lang

    def language(self):
        return self.lang


def test_the_door_route_flags_unflags_refuses_full_and_skips_a_stale_press(monkeypatch):
    door = pytest.importorskip("app.door")              # (J-DOOR's transport; its registry names this route)
    journey_door = pytest.importorskip("app.services.journey_door")
    body = {"line_id": "e3:12.0", "word": "看板", "line": JA[7], "show": "放課後の教室", "episode": "第3話",
            "time": 21.0, "reasons": ["wrong_sentence"], "note": "", "on": True}
    assert flags.door_route(body, _App()) == {"flagged": True}
    assert flags.door_state("ja", None, None) == {"flagged": [["e3:12.0", "看板"]]}
    changed = flags.read("ja")[0]["changed_ns"]
    with pytest.raises(door.RouteError) as stale:            # a queued press from before that change
        flags.door_route(dict(body, on=False, at=changed // 1_000_000 - 5000), _App())
    assert stale.value.kind == journey_door.STALE
    assert flags.door_route(dict(body, on=False), _App()) == {"flagged": False}
    assert flags.count("ja") == 0
    monkeypatch.setattr(flags, "MAX_LINES", 0)
    with pytest.raises(door.RouteError) as full:
        flags.door_route(body, _App())
    assert full.value.kind == "full"
    with pytest.raises(door.RouteError):
        flags.door_route(dict(body, line=""), _App())


# --- the review's cases (register rows 1-12) ----------------------------------------------------------------------- #
@pytest.mark.parametrize("given, kept", [(float("inf"), None), (float("nan"), None), (10 ** 400, None), (-1, None),
                                         (True, None), ("12", None), (4.567, 4.57)])
def test_a_time_that_isnt_a_finite_number_is_none(given, kept):
    flags.add("ja", JA[0], "文化祭", "journey", key="k", at=given)
    assert flags.read("ja")[0]["at"] == kept
    json.loads(open(os.path.join(path_utils.get_user_files_path("ja"), flags.FILE), encoding="utf-8").read(),
               parse_constant=lambda c: pytest.fail(f"{c} written into the list"))


@pytest.mark.parametrize("given, kept", [("parsing", ["parsing"]), (5, []), (None, []), ({"other": 1}, []),
                                         (("bad_audio", 3), ["bad_audio"])])
def test_reasons_given_as_one_word_or_not_a_list(given, kept):
    flags.add("ja", JA[0], "文化祭", "journey", key="k", reasons=given)
    assert flags.read("ja")[0]["reasons"] == kept


def test_a_change_in_the_same_clock_tick_still_moves_its_time(monkeypatch):
    """Windows' clock may not move between two presses: clear_sent must still tell the versions apart."""
    monkeypatch.setattr(flags.time, "time_ns", lambda: 1_763_700_000_000_000_000)
    first = flags.add("ja", JA[1], "授業", "journey", key="k")
    again = flags.add("ja", JA[1], "授業", "journey", key="k", note="同じ瞬間のメモ")
    assert again["changed_ns"] > first["changed_ns"]
    assert flags.clear_sent("ja", {first["id"]: first["changed_ns"]}) == 0        # the newer note stays


def test_an_entry_written_without_an_id_is_kept_on_the_next_write():
    folder = path_utils.get_user_files_path("zh")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, flags.FILE), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "lines": [{"line": ZH[0], "word": "大家", "source": "journey", "key": "k0"}]}, f,
                  ensure_ascii=False)
    flags.add("zh", ZH[1], "夜市", "journey", key="k1")
    lines = _file("zh")["lines"]
    assert [x["word"] for x in lines] == ["大家", "夜市"] and all(x.get("id") for x in lines)


def test_a_list_that_cant_be_read_is_said_to_send_report_never_as_none():
    folder = path_utils.get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, flags.FILE), "w", encoding="utf-8") as f:
        f.write('{"format": 1, "lines": [')
    with pytest.raises(ValueError):
        flags.for_report("ja")
    assert flags.read("ja") == []


def test_the_door_route_refuses_no_line_id_and_a_list_it_cant_write(monkeypatch):
    door = pytest.importorskip("app.door")
    body = {"line_id": "", "word": "看板", "line": JA[7], "on": True}
    with pytest.raises(door.RouteError):
        flags.door_route(body, _App())
    assert flags.count("ja") == 0

    def full_disk(language, lines):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(flags, "_write", full_disk)
    with pytest.raises(door.RouteError) as got:
        flags.door_route(dict(body, line_id="e3:21.0"), _App())
    assert "couldn't be saved" in got.value.message
