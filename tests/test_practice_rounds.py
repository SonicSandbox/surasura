"""Saved practice rounds (app/practice_rounds.py, H9; Sonic 2026-10-28: past rounds kept as an option, to do again, and
replies kept as context for later): one file per round in User Files/<lang>/practice/, written whole and atomically
under the `practice` lock; a crash mid-save or an unreadable file never costs an earlier round; what a later round
reads back stays short. Real Japanese and Chinese rounds (words and lines from the test resources' kind of content).
"""
import json
import os
import threading
import time

import pytest

from app import practice_rounds as pr

JA_START = {"round": {"words": 2, "role": "senpai", "kind": "chat", "source": "soon"},
            "words": [{"word": "冒険", "orth": "冒険", "reading": "ボウケン", "lines": [
                          {"line": "冒険は危険だが、価値がある。", "from": "ep01.srt"}]},
                      {"word": "議事録", "orth": "議事録", "reading": "ギジロク", "lines": [
                          {"line": "会議の議事録を確認してください。", "from": "ep01.srt"}]}]}
ZH_START = {"round": {"words": 1, "role": "shopkeeper", "kind": "quiz", "source": "latest"},
            "words": [{"word": "夜市", "orth": "夜市", "reading": "ye4 shi4", "lines": [
                          {"line": "我们明天去夜市吧。", "from": "night_market.srt"}]}]}


def _round_file(language, round_id):
    return os.path.join(pr.folder(language), round_id + ".json")


def _saved(language, start, lines=(), notes=(), when=None):
    """A round kept with `lines` and `notes`; `when` (seconds ago) dates its file so the newest-first order is known."""
    round_id = pr.new_id()
    pr.save(language, round_id, start=start)
    if lines or notes:
        pr.save(language, round_id, lines=list(lines), notes=list(notes))
    if when is not None:
        stamp = time.time() - when
        os.utime(_round_file(language, round_id), (stamp, stamp))
    return round_id


@pytest.mark.parametrize("language,start,line,note", [
    ("ja", JA_START, "【senpai】おう、冒険の話でもするか？", "冒険と危険をよく間違える"),
    ("zh", ZH_START, "【shopkeeper】欢迎光临！今天夜市人很多。", "总是把夜市说成早市"),
])
def test_a_round_is_kept_at_its_start_then_its_lines_and_notes_are_added(language, start, line, note):
    """The first save writes the round's choices and words (so it can be done again exactly); later saves add only
    what the learner asked to keep, each with when, and mark the round saved again."""
    round_id = pr.new_id()
    first = pr.save(language, round_id, start=start)
    assert first["round"] == start["round"] and first["words"] == start["words"]
    assert first["lines"] == [] and first["notes"] == [] and first["language"] == language
    pr.save(language, round_id, lines=[line, "  "], notes=note)          # blank lines are not kept; a note may be one text
    data = json.loads(open(_round_file(language, round_id), encoding="utf-8").read())
    assert [x["text"] for x in data["lines"]] == [line] and [x["text"] for x in data["notes"]] == [note]
    assert data["round"] == start["round"] and data["started"] <= data["saved"]
    (listed,) = pr.rounds(language)
    assert listed["round_id"] == round_id and listed["role"] == start["round"]["role"]
    assert listed["round_words"] == [w["orth"] for w in start["words"]]
    assert listed["lines_kept"] == 1 and listed["notes_kept"] == 1
    assert pr.load(language, round_id)["words"] == start["words"]


def test_a_crash_mid_save_leaves_the_round_and_every_other_round_as_they_were(monkeypatch):
    """The write is temp file + replace: a crash before the replace leaves the round's old bytes, no stray file, and
    the other rounds untouched."""
    from app import anki_sync
    kept = _saved("ja", JA_START, lines=["【senpai】冒険に行こうぜ。"])
    other = _saved("ja", JA_START, notes=["議事録はまだ早い"])
    before = {rid: open(_round_file("ja", rid), "rb").read() for rid in (kept, other)}

    def crash(*_args):
        raise OSError("the power went")
    with monkeypatch.context() as patched:
        patched.setattr(anki_sync.os, "replace", crash)
        with pytest.raises(OSError):
            pr.save("ja", kept, lines=["【senpai】次は議事録の話だ。"])
    assert {rid: open(_round_file("ja", rid), "rb").read() for rid in (kept, other)} == before
    assert sorted(os.listdir(pr.folder("ja"))) == sorted([kept + ".json", other + ".json"])
    pr.save("ja", kept, lines=["【senpai】次は議事録の話だ。"])                # and the next save goes on from it
    assert len(pr.load("ja", kept)["lines"]) == 2


def test_an_unreadable_round_is_left_alone_never_listed_and_never_written_over():
    good = _saved("ja", JA_START, lines=["【senpai】冒険だな。"], when=100)
    broken = pr.new_id()
    os.makedirs(pr.folder("ja"), exist_ok=True)
    raw = '{"round": {"role": "senpai"'.encode("utf-8")                 # half a file, as an editor might leave it
    with open(_round_file("ja", broken), "wb") as f:
        f.write(raw)
    assert [r["round_id"] for r in pr.rounds("ja")] == [good]
    with pytest.raises(ValueError, match="left as it is"):
        pr.save("ja", broken, start=JA_START, lines=["【senpai】上書きするな。"])
    with pytest.raises(ValueError, match="left as it is"):
        pr.load("ja", broken)
    assert open(_round_file("ja", broken), "rb").read() == raw
    assert [c["round_id"] for c in pr.context("ja")] == [good]


@pytest.mark.parametrize("bad", ["../../KnownWord", "..\\settings", "20261029-120000-zzzzzzzz", "20261029-120000-abcd", "",
                                 None, "20261029-120000-abcdef01/../../x"])
def test_a_round_id_that_is_not_one_is_refused_and_nothing_is_written(bad):
    """The AI passes the id: anything but Surasura's own id shape is refused, so no file outside practice/ is touched."""
    with pytest.raises(ValueError, match="No saved round"):
        pr.save("ja", bad, start=JA_START, lines=["冒険"])
    assert not os.path.exists(pr.folder("ja")) or os.listdir(pr.folder("ja")) == []


def test_a_round_never_started_can_not_be_saved():
    with pytest.raises(ValueError, match="Start a round"):
        pr.save("ja", pr.new_id(), lines=["【senpai】冒険だ。"])


def test_too_many_or_too_long_texts_are_refused_with_what_to_do_and_nothing_is_saved():
    round_id = _saved("zh", ZH_START)
    before = open(_round_file("zh", round_id), "rb").read()
    with pytest.raises(ValueError, match="shorten"):
        pr.save("zh", round_id, lines=["夜市" * (pr.TEXT_CHARS // 2 + 1)])
    with pytest.raises(ValueError, match="another call"):
        pr.save("zh", round_id, notes=["夜市很热闹"] * (pr.PER_SAVE + 1))
    assert open(_round_file("zh", round_id), "rb").read() == before


def test_what_a_new_round_reads_back_is_short_and_newest_first():
    """Only the newest CONTEXT_ROUNDS rounds with something kept, each its newest items, CONTEXT_CHARS in all; a round
    kept with nothing added is passed over; the round done again comes first."""
    oldest = _saved("ja", JA_START, lines=["【senpai】一番古い冒険の話。"], when=500)
    rounds = [_saved("ja", JA_START, lines=[f"【senpai】冒険の話、その{n}。"], notes=[f"メモ{n}"], when=400 - n * 50)
              for n in range(4)]
    _saved("ja", JA_START, when=10)                                      # the newest: nothing kept in it
    got = pr.context("ja")
    assert [c["round_id"] for c in got] == rounds[::-1][:pr.CONTEXT_ROUNDS]
    assert got[0]["notes"] == ["メモ3"] and got[0]["lines"] == ["【senpai】冒険の話、その3。"]
    assert got[0]["role"] == "senpai" and got[0]["kind"] == "chat"
    again = pr.context("ja", first=oldest)
    assert again[0]["round_id"] == oldest and len(again) == pr.CONTEXT_ROUNDS + 1

    many = _saved("ja", JA_START, lines=["冒" * (pr.TEXT_CHARS - 1)] * pr.PER_SAVE, when=0)
    got = pr.context("ja")
    assert got[0]["round_id"] == many and len(got[0]["lines"]) <= pr.CONTEXT_ITEMS
    assert sum(len(t) for c in got for t in c["lines"] + c["notes"]) <= pr.CONTEXT_CHARS


def test_no_rounds_yet_lists_nothing_and_reads_nothing_back():
    assert pr.rounds("ja") == [] and pr.context("zh") == []
    with pytest.raises(ValueError, match="No saved round"):
        pr.load("ja", pr.new_id())


def test_two_saves_at_once_keep_both_lines():
    """Two AI sessions saving to one round at once: the `practice` lock makes one wait, so neither line is lost."""
    round_id = _saved("ja", JA_START)
    errors = []

    def add(text):
        try:
            pr.save("ja", round_id, lines=[text])
        except Exception as e:          # pragma: no cover - reported below
            errors.append(e)
    threads = [threading.Thread(target=add, args=(f"【senpai】冒険{n}。",)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    assert sorted(x["text"] for x in pr.load("ja", round_id)["lines"]) == sorted(f"【senpai】冒険{n}。" for n in range(6))


def test_rounds_are_never_trimmed_however_many_there_are():
    ids = [_saved("zh", ZH_START, when=n) for n in range(pr.LIST_LIMIT + 3)]
    assert len(pr.rounds("zh", limit=1000)) == pr.LIST_LIMIT                     # a listing is capped …
    assert sorted(os.listdir(pr.folder("zh"))) == sorted(i + ".json" for i in ids)   # … the files never are


def test_the_switch_is_on_unless_it_is_set_to_false():
    assert pr.keeps({}) and pr.keeps(None) and pr.keeps({"practice_keep_rounds": True})
    assert not pr.keeps({"practice_keep_rounds": False})


@pytest.mark.parametrize("hand_edited", [{}, {"lines": []}, {"round": "senpai", "lines": []}, {"round": {}, "lines": 5},
                                         {"round": {}, "words": 3}, {"round": {}, "notes": "メモ"}, ["not", "a", "round"]])
def test_a_hand_edited_round_of_the_wrong_shape_is_passed_over_and_never_written_over(hand_edited):
    """Valid JSON of the wrong shape (round not an object, lines not a list...) is "not a round": the listing and the
    read-back pass it over (the other rounds still come), a save refuses it and leaves its bytes as they were."""
    good = _saved("ja", JA_START, notes=["冒険が好き"], when=100)
    odd = pr.new_id()
    raw = json.dumps(hand_edited, ensure_ascii=False).encode("utf-8")
    with open(_round_file("ja", odd), "wb") as f:
        f.write(raw)
    assert [r["round_id"] for r in pr.rounds("ja")] == [good]
    assert [c["round_id"] for c in pr.context("ja")] == [good]
    with pytest.raises(ValueError, match="isn't a round"):
        pr.save("ja", odd, lines=["【senpai】冒険だ。"])
    assert open(_round_file("ja", odd), "rb").read() == raw


def test_a_saved_rounds_words_come_back_clean_whatever_a_hand_edit_left():
    data = {"words": [{"word": "冒険"}, {"word": "夜市", "orth": 5, "lines": ["我们明天去夜市吧。", {"line": "夜市很热闹。"}]},
                      "散歩", {"orth": "議事録"}, {"word": ""}]}
    assert pr.words(data) == [{"word": "冒険", "orth": "冒険", "reading": "", "lines": []},
                              {"word": "夜市", "orth": "夜市", "reading": "", "lines": [{"line": "夜市很热闹。", "from": ""}]}]


def test_a_round_done_again_with_nothing_kept_still_reads_back_only_the_usual_three():
    plain = _saved("zh", ZH_START, when=500)                              # kept, nothing added
    rounds = [_saved("zh", ZH_START, notes=[f"笔记{n}"], when=400 - n * 50) for n in range(4)]
    got = pr.context("zh", first=plain)
    assert [c["round_id"] for c in got] == rounds[::-1][:pr.CONTEXT_ROUNDS]
    again = pr.context("zh", first=rounds[0])                              # the oldest of them, done again: first, once
    assert [c["round_id"] for c in again] == [rounds[0]] + rounds[::-1][:pr.CONTEXT_ROUNDS]
    newest = pr.context("zh", first=rounds[-1])                            # the newest, done again: still once
    assert [c["round_id"] for c in newest] == [rounds[-1]] + rounds[::-1][1:pr.CONTEXT_ROUNDS + 1]


def test_a_round_reads_back_its_newest_items_first_and_only_a_few_of_them():
    """Short lines, many of them: a round gives back its newest CONTEXT_ITEMS lines, newest first (the char cap isn't
    what stops it)."""
    texts = [f"夜市{n}" for n in range(pr.CONTEXT_ITEMS + 4)]
    _saved("zh", ZH_START, lines=texts)
    (got,) = pr.context("zh")
    assert got["lines"] == texts[::-1][:pr.CONTEXT_ITEMS]


def test_only_surasuras_own_round_files_are_listed():
    """A file the learner (or another program) put in practice/ — a copy, notes of their own — is never taken for a
    round: listed, read back or written."""
    good = _saved("ja", JA_START, notes=["冒険が好き"], when=100)
    for name in ("notes.json", good + " (copy).json", "20261029-010000-abcdef01.json.bak"):
        with open(os.path.join(pr.folder("ja"), name), "w", encoding="utf-8") as f:
            json.dump({"round": {"role": "friend"}, "notes": [{"text": "ほかのファイル"}]}, f, ensure_ascii=False)
    assert [r["round_id"] for r in pr.rounds("ja")] == [good]
    assert [c["round_id"] for c in pr.context("ja")] == [good]


def test_a_hand_edited_choice_never_floods_the_ai_and_a_round_is_known_by_its_file_name():
    """A role a hand edit made huge is left out of the listing and the read-back; a body naming another id (or none) is
    still the round its file name says."""
    good = _saved("ja", JA_START, notes=["冒険が好き"])
    path = _round_file("ja", good)
    data = json.loads(open(path, encoding="utf-8").read())
    data["round"]["role"] = "先輩" * 5000
    data["round_id"] = "20200101-000000-00000000"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    (listed,) = pr.rounds("ja")
    assert "role" not in listed and listed["kind"] == "chat"
    (back,) = pr.context("ja")
    assert back["round_id"] == good and back["role"] is None and back["notes"] == ["冒険が好き"]


def test_a_text_too_long_for_what_is_left_is_passed_and_an_older_short_one_still_comes():
    """The read-back's 1,500 characters: the newest round takes nearly all; in the next, its newest text no longer fits
    and is passed, and its older, short one still comes."""
    older = _saved("zh", ZH_START, notes=["早市", "夜" * (pr.TEXT_CHARS - 1)], when=100)
    full = pr.CONTEXT_CHARS // (pr.TEXT_CHARS - 1)
    newest = _saved("zh", ZH_START, notes=["市" * (pr.TEXT_CHARS - 1)] * full, when=0)
    got = pr.context("zh")
    assert [c["round_id"] for c in got] == [newest, older] and got[1]["notes"] == ["早市"]
    assert sum(len(t) for c in got for t in c["notes"] + c["lines"]) <= pr.CONTEXT_CHARS


def test_a_null_among_the_lines_is_not_kept_as_text():
    round_id = _saved("ja", JA_START)
    pr.save("ja", round_id, lines=[None, "【senpai】冒険だ。"])
    assert [x["text"] for x in pr.load("ja", round_id)["lines"]] == ["【senpai】冒険だ。"]
