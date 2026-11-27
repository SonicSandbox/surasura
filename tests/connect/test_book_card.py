"""BOOK-CARD (3.0.19; the lead's lean (a), PROVISIONAL until Sonic's § 96): a mine whose source has no sound — a book or a
text with no audiobook lined up — never makes an audio card. Connect sends Anki Miner no card type of its own; the
learner's profile names one for every mine, so under the audio card a book's card was marked as one with nothing to
play (27 of the learner's 1,005 Connect audio cards). Now that mine alone makes the sentence card: `card_type` in the
run file's `config` (Anki Miner applies it "for this run only, never saved"), the learner's setting unchanged.

What a wrong answer would cost: an audio card with no sound is a card the learner can't answer (the flagged card); a
video's or an audiobook's card turned into a sentence card loses the listening practice the learner chose; a card type
whose mark the note type has no field for makes Anki Miner refuse the whole run (no card at all); and a write to the
learner's settings would change every later mine.

Real data: the suite's texts (`ja/context_test.txt`, `zh/chinese_text_1.txt`) and episodes (`ja/library_episode.ass`,
`zh/night_market.srt`), picked by Connect's own pick; Anki Miner is the suite's fake (`fake_anki_miner.py`), which
keeps every run file it is given.
"""
import json
import os

import pytest

from app import cues, path_utils
from app.connect import anki_miner, fields, pick, runfile, runner
from app.connect.ledger import Ledger
from tests.connect.fake_anki_miner import LAPIS_EXPORT

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
TEXT = {"ja": os.path.join(RESOURCES, "ja", "context_test.txt"), "zh": os.path.join(RESOURCES, "zh", "chinese_text_1.txt")}
EPISODE = {"ja": os.path.join(RESOURCES, "ja", "library_episode.ass"),
           "zh": os.path.join(RESOURCES, "zh", "night_market.srt")}
# Anki Miner's own presets (its `services/note_presets.py`): Lapis' four marks (Kiku and Anki Miner Note share them),
# and Senren's, which has no click or word-and-sentence card
JPMN_MARKS = {"word_and_sentence": "IsWordAndSentenceCard", "click": "IsClickCard", "sentence": "IsSentenceCard",
              "audio": "IsAudioCard"}
SENREN_MARKS = {"word_and_sentence": "", "click": "", "sentence": "sentenceCard", "audio": "audioCard"}
NOTE = {"ja": "Lapis", "zh": "Anki Miner Note"}
APP = {"ja": "3.11.0", "zh": "3.12.0"}          # Chinese cards only with 3.12 or newer (anki_miner.ZH_FROM)


def _export(lang, card_type="audio", marks=JPMN_MARKS):
    """The learner's profile as Anki Miner's settings export writes it: the suite's Lapis mapping, with the card type
    and its marks (a language's own since Anki Miner 3.x: `languages/switching.py`)."""
    settings = dict(json.loads(json.dumps(LAPIS_EXPORT["settings"])), anki_note_type=NOTE[lang], card_type=card_type)
    if marks is not None:
        settings["card_type_marker_fields"] = dict(marks)
    return dict(LAPIS_EXPORT, settings=settings)


def _words(lang, source, reading):
    """Connect's own pick of the source's first three words, each carrying the name it is sent as."""
    if reading:
        read, tokens = cues.reading(source, lang)
    else:
        read = cues.read(source, lang)
        tokens = cues.tokens(read, lang)
    words = pick.pick(read, tokens, lang, lambda key: False, mode="unknown")["words"][:3]
    assert words, "the suite's text gives words"
    for w in words:
        w["sent"] = [w["word"]]
    return words


def _mine(fake_miner, tmp_path, lang, export, kind="book", **kw):
    """One `mine_batch` of `kind` ("book": the text as its reading file · "video" · "audio": an audiobook's file, as a
    lined-up book's part goes, `runner.Steps.mine`) -> the `config` of the run file Anki Miner was given."""
    features = ["word-from-line", "reading", "audio-episodes"]
    fake_miner.plan(app=APP[lang], features=features)
    mapping = fields.from_export(export, lang)
    if kind == "book":
        words, video, subtitle, reading = _words(lang, TEXT[lang], True), None, None, TEXT[lang]
    else:
        video = tmp_path / ("episode.mkv" if kind == "video" else "chapter 01.mp3")
        video.write_bytes(b"\x1aE\xdf\xa3")         # the fake never opens it
        words, video, subtitle, reading = _words(lang, EPISODE[lang], False), str(video), EPISODE[lang], None
    anki_miner.mine_batch(fake_miner.path, lang, "job-1", video, subtitle, words, mapping, "Surasura",
                          str(tmp_path / "runs" / "job-1"), "http://127.0.0.1:9", reading=reading, **kw)
    run = fake_miner.run_files()[-1]
    episode = run["episodes"][0]
    assert ("reading_file" in episode) is (kind == "book")
    assert ("audio_file" in episode) is (kind == "audio") and ("video_file" in episode) is (kind == "video")
    return run["config"]


# --------------------------------------------------------------------------- #
# The mine with no sound
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_book_with_no_audiobook_under_the_audio_card_makes_a_sentence_card(fake_miner, tmp_path, lang):
    """The flagged card: a book's mine (no audiobook lined up, so no clip is cut) under the learner's audio card goes
    with `card_type` "sentence" — Anki Miner marks the note type's sentence card (`IsSentenceCard`), never its audio
    card. The mark map stays the profile's (none sent): the overlay is the one value."""
    config = _mine(fake_miner, tmp_path, lang, _export(lang))
    assert config["card_type"] == "sentence"
    assert "card_type_marker_fields" not in config


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("kind", ["video", "audio"])
def test_a_video_and_a_books_audiobook_keep_the_learners_audio_card(fake_miner, tmp_path, lang, kind):
    """A video's mine, and a lined-up book's mine from its audiobook's file (an audio episode, its clip cut from the
    audiobook), have sound: no card type is sent, so the learner's audio card stays as it is."""
    config = _mine(fake_miner, tmp_path, lang, _export(lang), kind=kind)
    assert "card_type" not in config


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_learners_settings_are_unchanged_after_a_book_is_mined(fake_miner, tmp_path, lang):
    """Only that mine's card type differs: nothing is written to Anki Miner's profile (no `settings-import`) or to
    Surasura's settings.json, and the next video's mine is the audio card again."""
    settings = path_utils.get_settings_path()
    os.makedirs(os.path.dirname(settings), exist_ok=True)
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"language": lang, "connect_anki_miner_profile": "Surasura"}, f, ensure_ascii=False)
    before = open(settings, "rb").read()
    export = _export(lang)
    held = json.dumps(export, sort_keys=True)
    assert _mine(fake_miner, tmp_path, lang, export)["card_type"] == "sentence"
    assert "card_type" not in _mine(fake_miner, tmp_path, lang, export, kind="video")
    assert "settings-import" not in fake_miner.commands()
    assert open(settings, "rb").read() == before
    assert json.dumps(export, sort_keys=True) == held, "the learner's export as read, untouched"


# --------------------------------------------------------------------------- #
# The card types it never changes, and the note types with no sentence card
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("card_type", ["", "sentence", "click", "word_and_sentence"])
def test_a_card_type_other_than_the_audio_card_is_the_learners_for_a_book_too(fake_miner, tmp_path, lang, card_type):
    """The rule is about the audio card only: a learner's plain word card ("" — no mark), sentence, click or
    word-and-sentence card has nothing to play on its front, so a book's mine keeps it (nothing sent)."""
    config = _mine(fake_miner, tmp_path, lang, _export(lang, card_type))
    assert "card_type" not in config


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("marks", [dict(SENREN_MARKS, sentence=""), dict(JPMN_MARKS, sentence="  "),
                                   {"audio": "IsAudioCard"}, None])
def test_a_note_type_with_no_sentence_card_mark_gets_no_card_type(fake_miner, tmp_path, lang, marks):
    """A note type with no sentence card (its mark empty or blank, missing, or no mark map at all): the book's mine sends the
    card type empty — no mark is written, so the card is the note type's plain word card, never its audio card."""
    config = _mine(fake_miner, tmp_path, lang, _export(lang, marks=marks))
    assert config["card_type"] == ""


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_senrens_sentence_card_is_its_own_mark(fake_miner, tmp_path, lang):
    """Senren's marks are its own field names (`sentenceCard`): the value sent is still "sentence" — Anki Miner finds
    the mark in the profile's map."""
    assert _mine(fake_miner, tmp_path, lang, _export(lang, marks=SENREN_MARKS))["card_type"] == "sentence"


def test_a_sentence_mark_the_note_type_has_no_field_for_is_dropped_before_the_run():
    """Anki Miner refuses a run whose card type's mark the note type lacks (its preflight requires the field): read
    against Anki's note type (`fields.with_note_fields`, at the note type's check), such a mark is none — the book's
    mine then sends the card type empty. A note type Anki didn't answer for (None) is left as it is."""
    mapping = fields.from_export(_export("ja"))
    assert mapping.quiet_mark == "IsSentenceCard"
    lapis = ["Expression", "Sentence", "MainDefinition", "Picture", "SentenceAudio", "MiscInfo", "IsSentenceCard",
             "IsAudioCard"]
    assert fields.with_note_fields(mapping, lapis).quiet_mark == "IsSentenceCard"
    lacking = fields.with_note_fields(mapping, [f for f in lapis if f != "IsSentenceCard"])
    assert lacking.quiet_mark == ""
    assert runfile.config(lacking, "3.11.0", quiet=True)["card_type"] == ""
    assert fields.with_note_fields(mapping, None) is mapping
    plain = fields.from_export(_export("ja", ""))
    assert plain.quiet_mark is None and fields.with_note_fields(plain, lapis[:6]) is plain


@pytest.mark.parametrize("mark", [" IsSentenceCard", "Sentence"])
def test_a_mark_anki_miner_would_refuse_is_no_card_type(mark):
    """Anki Miner reads the mark as written and refuses a run whose mark field the note type lacks (a padded name is
    another name) or one the mapping already fills (`Sentence`: written twice): the mark kept as written, so Anki's
    note type check drops the padded one; the mapped one is none at once."""
    mapping = fields.from_export(_export("ja", marks=dict(JPMN_MARKS, sentence=mark)))
    lapis = ["Expression", "Sentence", "MainDefinition", "Picture", "SentenceAudio", "MiscInfo", "IsSentenceCard"]
    assert fields.with_note_fields(mapping, lapis).quiet_mark == ""


def test_the_run_files_card_type_is_one_anki_miner_takes(tmp_path):
    """`card_type` is a key Anki Miner's overlay allows (its `ALLOWED_OVERLAY_KEYS`), with one of its values: the run
    file passes Connect's own check and the fake's."""
    for export, want in ((_export("ja"), "sentence"), (_export("ja", marks=None), "")):
        config = runfile.config(fields.from_export(export), "3.11.0", ["bold-target"], quiet=True)
        assert config["card_type"] == want
        data = runfile.build(str(tmp_path / "runs"), "ja", [runfile.reading_episode(
            "job-1-1", TEXT["ja"], [{"word": "冒険", "line_text": "冒険だ。"}])],
                             run_config=config)
        runfile.check(data)
    assert "card_type" not in runfile.config(fields.from_export(_export("ja")), "3.11.0")


# --------------------------------------------------------------------------- #
# The AI voice's book (AUDIO-FILL, Sonic § 106 decision 4): always the sentence card first, Card sound flips it
# --------------------------------------------------------------------------- #
def test_a_job_an_older_connect_marked_for_the_ai_voice_is_mined_as_any_book(tmp_path):
    """`runner._mine_batch`: a ledger from before 3.0.21 still holding a job's AI mark (`ai_audio_job:<id>`) never
    reaches `Steps.mine` as anything else — the book's cards are the sentence card, and Card sound makes each the
    learner's audio card once it has sound (`card_sound.flip_of`)."""
    seen = []

    class Steps:
        def mine(self, lang, job, picked, words, attempt):
            seen.append(dict(picked))
            return {"outcomes": [], "app": None, "doubt": False}

    picked = {"reading": TEXT["ja"], "words": []}
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("ai_audio_job:7", "1"))
        runner._mine_batch(Steps(), ledger, "ja", {"id": 7}, picked, [], 1)
    assert seen == [picked]


# --------------------------------------------------------------------------- #
# The wiring: the setup Connect mines with, and the runner's own call
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_setup_connect_mines_with_carries_the_mark_and_drops_one_the_note_type_lacks(fake_miner, tmp_path,
                                                                                         monkeypatch, lang):
    """`verbs._anki_miner_setup` (every Connect batch, and the command line's pick): the mapping read from the
    profile's export carries the sentence card's mark; Anki's note type is asked for its fields, and one with no field
    for the mark gives a mapping with none. Kept set: the export's own mapping, asked again at the next call."""
    from app import anki_connect
    from app.cli import verbs
    fake_miner.plan(app=APP[lang], features=["word-from-line", "reading"], export=_export(lang))
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_connect, "probe", lambda url, timeout=2: {"ok": True})
    note = ["Expression", "Sentence", "MainDefinition", "Picture", "SentenceAudio", "MiscInfo", "IsSentenceCard",
            "IsAudioCard"]
    asked = []

    def invoke(action, url, **params):
        asked.append(action)
        return list(note) if action == "modelFieldNames" else []
    monkeypatch.setattr(anki_connect, "invoke", invoke)
    loaded, held = {"connect_anki_miner_path": fake_miner.path}, {}
    run_dir = str(tmp_path / "runs" / "job-1")
    assert verbs._anki_miner_setup(loaded, lang, run_dir, held=held)[2].quiet_mark == "IsSentenceCard"
    note.remove("IsSentenceCard")
    assert verbs._anki_miner_setup(loaded, lang, run_dir, held=held)[2].quiet_mark == ""
    assert held["set"][2].quiet_mark == "IsSentenceCard", "the kept set is the export's, checked at every call"
    assert asked.count("modelFieldNames") == 2
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")     # Anki not asked: as read (Anki Miner's own check asks)
    assert verbs._anki_miner_setup(loaded, lang, run_dir)[2].quiet_mark == "IsSentenceCard"


def test_the_runners_mine_hands_anki_miner_the_books_reading_and_no_voice_mark(tmp_path, monkeypatch):
    """`Steps._mine_one` (the runner's one call of `mine_batch`): the book's reading file, and no AI-voice mark (a
    pick still carrying one from before 3.0.21 too): the run is quiet, so the card is the sentence card."""
    from types import SimpleNamespace
    from app.cli import verbs
    mapping = fields.from_export(_export("ja"))
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "AnkiMiner.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir, held=None: ({}, "p", mapping))
    sent = {}

    def mine_batch(*args, **kw):
        sent.update(kw)
        return {"outcomes": []}
    monkeypatch.setattr(anki_miner, "mine_batch", mine_batch)
    steps = SimpleNamespace(loaded={}, url="http://127.0.0.1:9", run_dir=lambda job: str(tmp_path / "runs"),
                            _anki_miner_held=lambda lang: {}, _settings=lambda lang: {}, show=lambda lang, job: None,
                            _reviewing=lambda: False, _place=lambda *a: None)
    picked = {"reading": TEXT["ja"], "video": None, "subtitle": None, "words": []}
    picked["voiced"] = True                                     # (an older pick's)
    runner.Steps._mine_one(steps, "ja", {"id": 7}, picked, [], 1)
    assert "voiced" not in sent and sent["reading"] == TEXT["ja"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("kind", ["book", "video"])
def test_the_command_lines_pick_writes_the_same_card_type_rule(fake_miner, tmp_path, monkeypatch, lang, kind):
    """`surasura-cli pick` writes the run file a learner's own script may mine (`verbs.pick`): a book's (`reading`)
    under the audio card names the sentence card, a video's names none — the runner's rule (no AI voice here)."""
    from types import SimpleNamespace
    from app.cli import verbs
    from app.connect import pick as picking
    from tests import cli_helpers as h
    fake_miner.plan(app=APP[lang], features=["word-from-line", "reading"], export=_export(lang))
    from app.path_utils import get_user_files_path
    os.makedirs(get_user_files_path(lang), exist_ok=True)        # (the language set up: its folders made)
    h.write_settings(connect_anki_miner_path=fake_miner.path, language=lang)
    monkeypatch.setattr(picking, "carded", lambda lang, settings, decks=(): (set(), "backlog"))
    if kind == "book":
        source, video, reading = TEXT[lang], None, TEXT[lang]
    else:
        video = str(tmp_path / "episode.mkv")
        with open(video, "wb") as f:
            f.write(b"\x1aE\xdf\xa3")
        source, reading = EPISODE[lang], None
    ns = SimpleNamespace(lang=lang, file=source, video=video, reading=reading, words="unknown", job="job-9", wait=30,
                         made=(), listed=None, held=None, unsure=())
    out = verbs.pick(ns)
    assert out["run_file"], out
    with open(out["run_file"], encoding="utf-8") as f:
        config = json.load(f)["config"]
    assert config.get("card_type") == ("sentence" if kind == "book" else None)
