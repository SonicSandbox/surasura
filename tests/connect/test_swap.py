"""⇄ Swap's backend (app/connect/swap.py; the 3.0 plan's tracks/pipeline/work/swap/SWAP-PROTO.md) on a real library:
RP-2's Japanese one (`plan_file_cases`: a sample's subtitles split in three episodes, two novels, the phrases sample), one
real Generate a module, its plan file read by the real engine. Anki is a fake AnkiConnect on a loopback port, spoken to
by the real adapter; Anki Miner's `render` and `media` answers are handed in (never the real Anki Miner, K91).

What a wrong answer would cost: a swap that writes the card's Hint (his translation, K18) or MiscInfo (his ヒント),
or a card left with the old line's furigana over a new sentence; an Undo that can't, because the snapshot was written
after Anki; a write while he reviews (K88); a preview that made a card."""
import json
import os
import shutil

import pytest

from app.connect import fields, fit_check, swap
from tests import plan_file_cases as cases
from tests.connect.fake_ankiconnect import FakeAnkiConnect

NOTE = 1_731_000_000_000
LAPIS = fields.from_export({"configured": True, "settings": {
    "anki_deck_name": "DevTest", "anki_note_type": "Lapis",
    "anki_fields": {"word": "Expression", "sentence": "Sentence", "picture": "Picture", "audio": "SentenceAudio",
                    "source": "MiscInfo", "sentence_translation": "Hint", "definition": "MainDefinition"}}})
INFO = {"app": "3.11.0", "features": ["render", "media", "word-from-line", "bold-target", "sentence-rules-off"]}


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("swap_library"))
    cases.build(root, "rp2-ja")
    cases.generate(root, "rp2-ja")
    return root


@pytest.fixture
def root(generated, monkeypatch):
    """The generated library (its store's database is named by its data folder's path, so it isn't copied); Swap's
    own folder — the undo file, the previews, the run folders — fresh for each test."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", generated)
    shutil.rmtree(swap.folder(), ignore_errors=True)
    yield generated
    shutil.rmtree(swap.folder(), ignore_errors=True)


def a_card(**fields_):
    values = {"Expression": "家庭教師", "Sentence": "<b>家庭教師</b>するんでしょ？", "SentenceFurigana": "AJT's old line",
              "SentenceAudio": "[sound:家庭教師_1000_1_abc.mp3]", "Picture": '<img src="家庭教師_1000_1_abc.webp">',
              "MiscInfo": "家で勉強を教える先生のこと。", "Hint": "You're going to tutor, right?",
              "MainDefinition": "home tutor"}
    values.update(fields_)
    return {NOTE: {"deck": "DevTest", "fields": values, "tags": ["surasura::connect::x-1"]}}


@pytest.fixture
def anki(root):
    seen = {}

    def on_write(action):
        # the snapshot-first rule: Swap's undo file is on disk before Anki's first write
        seen.setdefault(action, os.path.exists(swap.undo_path("ja")))
    fake = FakeAnkiConnect(a_card(), on_write=on_write)
    fake.snapshot_before = seen
    yield fake
    fake.stop()


class Steps:
    """Connect's steps for one line's episode: the real store, a video beside it, the fit verdict asked."""

    def __init__(self, verdict=fit_check.TIMED):
        self.verdict, self.asked = verdict, []

    def _open(self, lang):
        from app.connect import library
        return library.open_store(lang)

    def video(self, lang, job):
        return os.path.join(os.environ["SURASURA_TEST_ROOT"], "videos", f"ep-{job['item_id']}.mkv")

    def pairing(self, lang, job):
        return {"content_key": "hato-key-1"}

    def fit(self, lang, job, pairing, video, subtitle):
        self.asked.append(subtitle)
        return self.verdict, "hato", None, 0.25


class Miner:
    """Anki Miner's `render` and `media` answers, written where the real one writes them (API.md)."""

    def __init__(self, sentence="<b>家庭教師</b>ができなくなる。"):
        self.calls, self.sentence = [], sentence

    def __call__(self, path, args, timeout=None, look_up=None, **_kw):
        command, run_file = args
        with open(run_file, encoding="utf-8") as f:
            data = json.load(f)
        self.calls.append((command, data))
        episode = data["episodes"][0]
        folder = os.path.join(data["run_dir"], episode["run_id"])
        os.makedirs(folder, exist_ok=True)
        if command == "media":
            os.makedirs(os.path.join(folder, "media-1"), exist_ok=True)
            for name in ("1.mp3", "1.webp"):
                with open(os.path.join(folder, "media-1", name), "wb") as f:
                    f.write(b"cut " + name.encode())
            line = episode["lines"][0]
            with open(os.path.join(folder, "media-1.json"), "w", encoding="utf-8") as f:
                json.dump({"schema": 1, "run_id": episode["run_id"], "lines": [
                    {"line_start": line["line_start"], "start": line["line_start"], "end": line["line_start"] + 2,
                     "text": "このままじゃ家庭教師ができなくなる。", "audio": "media-1/1.mp3",
                     "picture": "media-1/1.webp"}]}, f, ensure_ascii=False)
            return {"ok": True, "runs": [{"run_id": episode["run_id"], "ok": True, "file": "media-1.json"}]}
        assert command == "render"
        out = os.path.join(folder, "render-1")
        os.makedirs(out, exist_ok=True)
        for name in ("家庭教師_2000_1_def.mp3", "家庭教師_2000_1_def.webp"):
            with open(os.path.join(out, name), "wb") as f:
                f.write(name.encode("utf-8"))
        word = episode["words"][0]["word"]
        row = {"word": word, "status": "rendered", "files": ["家庭教師_2000_1_def.mp3", "家庭教師_2000_1_def.webp"],
               "fields": {"Expression": word, "Sentence": self.sentence, "SentenceAudio": "[sound:家庭教師_2000_1_def.mp3]",
                          "Picture": '<img src="家庭教師_2000_1_def.webp">', "MiscInfo": "Yomi ep03 01:02",
                          "Hint": "", "MainDefinition": "a NEW definition"}}
        with open(os.path.join(folder, "render-1.json"), "w", encoding="utf-8") as f:
            json.dump({"words": [row]}, f, ensure_ascii=False)
        return {"ok": True, "runs": [{"run_id": episode["run_id"], "ok": True, "file": "render-1.json"}]}


def session(anki, steps=None, miner=None):
    return swap.Session({}, steps=steps or Steps(), miner="AnkiMiner.exe", setup=lambda lang: (INFO, "p-surasura",
                                                                                              LAPIS),
                        url=anki.url, api=miner or Miner())


def test_candidates_are_the_words_own_sentences_easiest_first_each_subtitle_line_timed(root, anki):
    got = session(anki).candidates("ja", "家庭教師", "カテイキョウシ")
    lines = got["candidates"]
    assert got["note"] == NOTE and got["now"] == "家庭教師するんでしょ？" and got["hint"] is True
    texts = [line["text"] for line in lines]
    assert "このままじゃ家庭教師ができなくなる。" in texts and "30階の中野さんの家庭教師をしている。" in texts
    # easiest first: every 0-unknown sentence before the one with an unknown
    assert [line["unknown"] for line in lines] == sorted(line["unknown"] for line in lines)
    # a subtitle's line carries its times (Connect's line reader); the card's own sentence is marked
    assert all(line["timed"] and line["start"] is not None and line["end"] >= line["start"] for line in lines)
    assert [line["now"] for line in lines].count(True) == 1 and lines[texts.index("家庭教師するんでしょ？")]["now"]
    assert {line["episode"] for line in lines} >= {"gotoubun_ep01", "gotoubun_ep03"}
    # the show is the store's title, never a tier's own folder (the learner sees NOW / Soon / 6+ Months, CLAUDE.md §6)
    assert not {"HighPriority", "LowPriority", "GoalContent", "Library"} & {line["show"] for line in lines}


def test_a_text_sentence_is_listed_but_not_timed(root, anki):
    # このまま's pool holds a novel's sentence: listed (the learner can read it) with no times, so no ▶ and no Swap
    s = session(anki)
    lines = s.candidates("ja", "此の侭", "コノママ")["candidates"]
    novel = [line for line in lines if line["episode"] == "novel_school_part1"]
    assert novel and not novel[0]["timed"] and novel[0]["start"] is None
    with pytest.raises(swap.SwapError) as e:
        s.line(novel[0]["id"])
    assert e.value.kind == "text"


def test_anki_closed_still_lists_the_sentences_and_says_why(root, anki):
    anki.closed = True
    got = session(anki).candidates("ja", "家庭教師", "カテイキョウシ")
    assert got["note"] is None and got["anki"] == swap.ANKI_CLOSED and len(got["candidates"]) == 5


def test_no_card_and_several_cards_are_said(root, anki):
    s = session(anki)
    assert s.candidates("ja", "誠実", "セイジツ")["anki"] == "No card for 誠実 yet."
    anki.notes[NOTE + 7] = {"deck": "DevTest", "fields": dict(anki.notes[NOTE]["fields"])}
    assert "Several cards" in s.candidates("ja", "家庭教師", "カテイキョウシ")["anki"]


def test_a_word_not_on_the_list_is_refused(root, anki):
    with pytest.raises(swap.SwapError) as e:
        session(anki).candidates("ja", "存在しない語", "")
    assert e.value.kind == "not-listed"


def _line(s, text, word="家庭教師", reading="カテイキョウシ"):
    lines = s.candidates("ja", word, reading)["candidates"]
    return next(line for line in lines if line["text"] == text)


def test_swap_replaces_the_sentence_side_and_keeps_hint_miscinfo_and_the_word_side(root, anki):
    miner = Miner()
    s = session(anki, miner=miner)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    answer = s.swap(NOTE, line["id"])
    note = anki.notes[NOTE]["fields"]
    assert note["Sentence"] == "<b>家庭教師</b>ができなくなる。"
    assert note["SentenceAudio"].startswith("[sound:sl-") and note["SentenceAudio"].endswith(".mp3]")
    assert note["Picture"].startswith('<img src="sl-') and ".webp" in note["Picture"]
    # kept: the translation (K18), the ヒント band (the Lapis preset maps `source` there), the word side
    assert note["Hint"] == "You're going to tutor, right?"
    assert note["MiscInfo"] == "家で勉強を教える先生のこと。"
    assert note["MainDefinition"] == "home tutor" and note["Expression"] == "家庭教師"
    # AJT's furigana of the OLD line is blanked (the card shows SentenceFurigana before Sentence)
    assert note["SentenceFurigana"] == ""
    assert swap.TAG in anki.notes[NOTE]["tags"] and "surasura::connect::x-1" in anki.notes[NOTE]["tags"]
    assert answer["now"] == "家庭教師ができなくなる。"
    # the media stored under the line's names, the snapshot on disk before Anki's first write
    assert sorted(n[-4:] for n in anki.media) == [".mp3", "webp"]
    assert anki.snapshot_before == {"storeMediaFile": True, "updateNoteFields": True, "addTags": True}
    # render was asked for the card's word on that line, at the fit check's offset; the line's expansion sent
    command, data = miner.calls[-1]
    episode = data["episodes"][0]
    assert command == "render" and episode["words"][0]["word"] == "家庭教師"
    assert episode["subtitle_offset"] == 0.25 and episode["subtitle_file"].endswith("gotoubun_ep03.srt")
    assert abs(episode["words"][0]["line_start"] - line["start"]) < 0.001


def test_undo_puts_the_old_line_back_and_takes_the_tag_off(root, anki):
    s = session(anki)
    before = dict(anki.notes[NOTE]["fields"])
    undo = s.swap(NOTE, _line(s, "このままじゃ家庭教師ができなくなる。")["id"])["undo"]
    assert s.undo("ja", undo)["now"]
    assert anki.notes[NOTE]["fields"] == before
    assert swap.TAG not in anki.notes[NOTE]["tags"]
    with pytest.raises(swap.SwapError):
        s.undo("ja", undo)                  # once only


def test_undo_refuses_when_the_card_changed_since(root, anki):
    s = session(anki)
    undo = s.swap(NOTE, _line(s, "このままじゃ家庭教師ができなくなる。")["id"])["undo"]
    anki.notes[NOTE]["fields"]["Sentence"] = "his own edit"
    with pytest.raises(swap.SwapError) as e:
        s.undo("ja", undo)
    assert e.value.message == swap.CHANGED and anki.notes[NOTE]["fields"]["Sentence"] == "his own edit"


def test_nothing_is_written_while_he_reviews(root, anki):
    s = session(anki)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    anki.reviewing = True
    with pytest.raises(swap.SwapError) as e:
        s.swap(NOTE, line["id"])
    assert e.value.kind == "reviewing"
    assert not {"storeMediaFile", "updateNoteFields", "addTags"} & set(anki.names())
    assert anki.notes[NOTE]["fields"]["Sentence"] == "<b>家庭教師</b>するんでしょ？"


def test_the_same_line_swapped_in_twice_uploads_its_files_once(root, anki):
    s = session(anki)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    undo = s.swap(NOTE, line["id"])["undo"]
    s.undo("ja", undo)
    s.swap(NOTE, line["id"])
    assert anki.names().count("storeMediaFile") == 2      # the clip and the picture, once each


def test_a_line_not_timed_to_its_video_is_neither_cut_nor_swapped(root, anki):
    miner = Miner()
    s = session(anki, steps=Steps(verdict=fit_check.NOT_TIMED), miner=miner)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    for call in (lambda: s.preview(line["id"]), lambda: s.swap(NOTE, line["id"])):
        with pytest.raises(swap.SwapError) as e:
            call()
        assert e.value.kind == "not-timed"
    assert miner.calls == [] and "updateNoteFields" not in anki.names()


def test_preview_cuts_once_with_media_and_never_touches_anki(root, anki):
    miner = Miner()
    s = session(anki, miner=miner)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    before = list(anki.names())
    got = s.preview(line["id"])
    assert got == {"clip": f"{line['id']}.mp3", "picture": f"{line['id']}.webp"}
    with open(os.path.join(swap.preview_folder(), got["clip"]), "rb") as f:
        assert f.read() == b"cut 1.mp3"
    assert s.preview(line["id"]) == got and [c[0] for c in miner.calls] == ["media"]   # the second plays at once
    assert anki.names() == before          # no card made for a preview, nothing asked of Anki


def test_render_not_finding_the_word_writes_nothing(root, anki):
    class NotFound(Miner):
        def __call__(self, path, args, **kw):
            answer = super().__call__(path, args, **kw)
            run_dir = json.load(open(args[1], encoding="utf-8"))["run_dir"]
            run_id = answer["runs"][0]["run_id"]
            with open(os.path.join(run_dir, run_id, "render-1.json"), "w", encoding="utf-8") as f:
                json.dump({"words": [{"word": "家庭教師", "status": "not_found", "fields": None, "files": []}]}, f)
            return answer
    s = session(anki, miner=NotFound())
    with pytest.raises(swap.SwapError) as e:
        s.swap(NOTE, _line(s, "このままじゃ家庭教師ができなくなる。")["id"])
    assert e.value.kind == "not-found" and not os.path.exists(swap.undo_path("ja"))
    assert "updateNoteFields" not in anki.names()


def test_another_notes_id_is_never_rewritten(root, anki):
    # an id from an old page, or from anything else that read the door's file: another deck's card, or a card of
    # another word, is refused inside the lock, before any write
    s = session(anki)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    other = dict(anki.notes[NOTE], deck="Kaishi 1.5k", fields=dict(anki.notes[NOTE]["fields"]))
    anki.notes[NOTE + 50] = other
    with pytest.raises(swap.SwapError) as e:
        s.swap(NOTE + 50, line["id"])
    assert e.value.kind == "not-the-card"
    assert not {"storeMediaFile", "updateNoteFields"} & set(anki.names()) and not os.path.exists(swap.undo_path("ja"))


def test_the_line_already_on_the_card_is_refused_not_recorded(root, anki):
    s = session(anki, miner=Miner(sentence=anki.notes[NOTE]["fields"]["Sentence"]))
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    s.swap(NOTE, line["id"])
    with pytest.raises(swap.SwapError) as e:
        s.swap(NOTE, line["id"])            # the same line again: old == new, nothing to undo to
    assert e.value.message == swap.SAME
    assert len(swap._records("ja")) == 1


def test_a_refused_write_leaves_the_card_and_offers_no_undo(root, anki):
    s = session(anki)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    before = dict(anki.notes[NOTE]["fields"])
    anki.refuse_update = "collection is busy"
    with pytest.raises(Exception):
        s.swap(NOTE, line["id"])
    (record,) = swap._records("ja")
    assert record["failed"] and anki.notes[NOTE]["fields"] == before
    with pytest.raises(swap.SwapError):
        s.undo("ja", record["id"])


def test_a_write_anki_didnt_take_is_said_and_offers_no_undo(root, anki):
    s = session(anki)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    anki.ignore_update = True
    with pytest.raises(swap.SwapError) as e:
        s.swap(NOTE, line["id"])
    assert e.value.kind == "not-applied" and swap._records("ja")[0]["failed"]
    assert swap.TAG not in anki.notes[NOTE]["tags"]


def test_two_cards_swapped_then_one_undone_keeps_the_others_record(root, anki):
    s = session(anki)
    second = NOTE + 100
    anki.notes[second] = {"deck": "DevTest", "fields": dict(anki.notes[NOTE]["fields"]), "tags": []}
    anki.notes[NOTE]["fields"]["Expression"] = "家庭教師"
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    first = s.swap(NOTE, line["id"])["undo"]
    del anki.notes[NOTE]                    # (the word has one card again for the second's swap)
    other = s.swap(second, line["id"])["undo"]
    anki.notes[NOTE] = a_card()[NOTE]
    anki.notes[NOTE]["fields"].update(swap._records("ja")[0]["new"])
    s.undo("ja", first)
    ids = {r["id"]: r for r in swap._records("ja")}
    assert ids[first]["undone"] and not ids[other]["undone"]
    s.undo("ja", other)


def test_no_run_folder_or_file_is_left_behind(root, anki):
    s = session(anki)
    line = _line(s, "このままじゃ家庭教師ができなくなる。")
    s.preview(line["id"])
    s.swap(NOTE, line["id"])
    for kind in ("media", "render"):
        assert os.listdir(os.path.join(swap.folder(), kind)) == []


def test_an_old_list_id_is_refused(root, anki):
    with pytest.raises(swap.SwapError) as e:
        session(anki).swap(NOTE, "0123456789abcdef")
    assert e.value.kind == "stale"


def test_the_routes_answer_through_the_door(root, anki):
    from app import door
    routes = swap.routes(session(anki))
    got = routes["swap/candidates"]({"lang": "ja", "word": "家庭教師", "reading": "カテイキョウシ"})
    assert got["note"] == NOTE
    for body in ({"lang": "xx", "word": "家庭教師"}, {"lang": "ja"}, {"lang": "ja", "word": "  "}):
        with pytest.raises(door.RouteError):
            routes["swap/candidates"](body)
    with pytest.raises(door.RouteError):
        routes["swap/do"]({"note": True, "id": "x"})       # a bool is never a note id
