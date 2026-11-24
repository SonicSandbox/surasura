"""AM-FIX (2026-11-23, release-blocking for 3.0.18): two findings of FS-R's drill through a real Anki Miner.

1. **The simple Swap's new card was refused as its old card's duplicate.** Anki Miner's `mine` checks every note before
   adding it (3.13 `services/anki_service.py` `_probe_duplicates`: AnkiConnect `canAddNotesWithErrorDetail`, duplicates
   off) — a note whose first field another note of its note type holds is refused, and `allow_duplicate_cards` only
   narrows that check to the deck (`anki_note_builder.build_note`: `duplicateScope: deck`), where the old card is. So a
   swap whose old card is of Connect's note type never got its card (3.13 and the installed 3.5.0, drilled). Swap now
   makes that card beside the old one (`swap.add_new_card`: the old card's word side, the new line's sentence side from
   `render`, AnkiConnect `addNote` with the duplicate allowed); any other swap is mined as before.
2. **A word on a caption's second line came back `not_found`.** A two-line caption written as two Dialogue events with
   one start is one cue to Surasura and two lines to Anki Miner, whose `line_start` names the earlier of a tie. Such a
   word is named by its event's own text (`runfile.named_by_text`: `line_text`, no `line_start`).
3. `render` for a swap asks for no word audio (the card keeps its own).

What a wrong answer costs: a learner's ⇄ that never makes its card (the ask waits forever), a card whose word side is
render's instead of the learner's, an old card changed, a clip left in Anki's media for a card Anki refused, or a word
named by a line it isn't on. Real lines: the simple Swap's CASES (tests/Test Resources) and `ja/tv_captions.ass`.
"""
import os
import shutil

import pytest

from app import anki_connect, path_utils
from app.connect import anki_miner, media_names, runfile, runner, sentence_audio, swap
from app.connect.ledger import SWAP
from tests.connect.test_full_swap import (MAPPING, Anki as FullAnki, _card, _made_by_connect, _rendered, _to_job,
                                          _value)
from tests.connect.test_kantan_sl_swap import CASES, ledger  # noqa: F401

TV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources", "ja",
                  "tv_captions.ass")
FROM_LINE = (runfile.WORD_FROM_LINE,)


class Anki(FullAnki):
    """The full Swap's fake, plus AnkiConnect's `addNote` (Anki's own: it refuses what it's told to)."""

    def __init__(self):
        super().__init__()
        self.refuse = None

    def add_note(self, note):
        self.log.append(("add_note", note["deckName"], note["modelName"], tuple(sorted(note["fields"])),
                         dict(note.get("options") or {})))
        if self.refuse:
            raise anki_connect.AnkiError(self.refuse)
        nid = 951 + sum(1 for op in self.log if op[0] == "add_note") - 1
        self.notes_[nid] = {"noteId": nid, "modelName": note["modelName"], "tags": list(note["tags"]), "mod": 1,
                            "fields": {k: {"value": v, "order": i} for i, (k, v) in enumerate(note["fields"].items())},
                            "deck": note["deckName"]}
        return nid


def _steps(tmp_path, monkeypatch, anki, rendered, renders=None):
    """Connect's real step with Anki Miner's look-ups and `render` answered as its source writes them."""
    from app.cli import verbs
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "am.exe")

    def render(*a, **k):
        if renders is not None:
            renders.append(k)
        return {(a[5][0]["word"], ""): rendered} if rendered is not None else {}
    monkeypatch.setattr(anki_miner, "render_line", render)
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda *a, **k: ({}, "p1", MAPPING))
    monkeypatch.setattr(swap, "AnkiSwap", lambda url: anki)
    steps = runner.Steps({"connect_enabled": True})
    monkeypatch.setattr(steps, "run_dir", lambda job: str(tmp_path / "run"))
    monkeypatch.setattr(steps, "_anki_miner_held", lambda lang: {})
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    monkeypatch.setattr(steps, "show", lambda lang, job: "Toshokan")
    monkeypatch.setattr(steps, "_media_key", lambda lang, job: "toshokan-05")
    return steps


def _simple_swap(ledger, lang, anki, monkeypatch):
    """A flagged card Connect made, its swap's job made as the shipped default makes it: a new card."""
    monkeypatch.setattr(swap, "_swap_flag", lambda: 3)
    monkeypatch.setattr(swap, "in_place_on", lambda settings=None: False)
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    assert (row["kind"], row["state"]) == (swap.NEW_CARD, swap.QUEUED)
    return row


def _words(lang):
    word, _old, other = CASES[lang]
    return [{"word": word, "reading": "", "line_start": 190.0, "line_end": 193.5, "line_text": other}]


# --------------------------------------------------------------------------- #
# 1. The simple Swap's new card, beside its old card
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_simple_swaps_new_card_beside_an_old_card_of_connects_note_type_is_added_with_the_duplicate_allowed(
        ledger, lang, tmp_path, monkeypatch):
    """The card Anki Miner's `mine` refuses (its old card holds the word in the same note type): made here — a new note
    in Connect's deck, the duplicate allowed; its word side the old card's (never render's: here render's word reads
    `（別）`), its sentence, clip and picture the new line's (named by the line, stored first), the old line's
    translation never carried over, the source the new line's, the job's tags; the old card untouched; render asked
    for no word audio. The batch's answer is the new note made, as a mined card's."""
    word, old, other = CASES[lang]
    anki = _card(Anki(), lang)
    before = {k: dict(v) for k, v in anki.notes_[900]["fields"].items()}
    row = _simple_swap(ledger, lang, anki, monkeypatch)
    job = ledger.job_by_id(row["job_id"])
    renders = []
    steps = _steps(tmp_path, monkeypatch, anki, _rendered(tmp_path, lang), renders)
    assert swap.new_card_row(ledger, row["job_id"])["id"] == row["id"]
    done = steps.swap_new_card(lang, job, {"video": "Toshokan - 05.mkv", "subtitle": "Toshokan - 05.ass"},
                               _words(lang), 1, ledger, swap.new_card_row(ledger, row["job_id"]))
    new = done["outcomes"][0]["note_id"]
    assert (done["outcomes"][0]["outcome"], done.get("in_place"), done["deck"]) == ("made", None, MAPPING.deck)
    add = [op for op in anki.log if op[0] == "add_note"]
    assert add == [("add_note", MAPPING.deck, "Lapis", tuple(sorted(before)), {"allowDuplicate": True})]
    clip = media_names.line_name("toshokan-05", 190.0, 193.5, media_names.fingerprint(other), ".mp3")
    assert _value(anki, "Sentence", new) == other.replace(word, f"<b>{word}</b>")
    assert _value(anki, "SentenceAudio", new) == f"[sound:{clip}]" and anki.media[clip].startswith(b"ID3 ")
    assert _value(anki, "Picture", new).startswith('<img src="sl-') and "am-clip.mp3" not in anki.media
    for field in ("Word", "PitchPosition", "Patterns", "ExampleSentences", "IsSentenceCard"):
        assert _value(anki, field, new) == before[field]["value"]          # the old card's word side
    assert _value(anki, "Hint", new) == "" and _value(anki, "SentenceFurigana", new) == ""  # Backfill's after
    assert _value(anki, "MiscInfo", new) == "Toshokan - 05 @ 00:03:10"   # the new line's episode
    assert anki.notes_[new]["tags"] == [f"surasura::connect::{runner._tag(job)}", "Surasura::from::Toshokan"]
    assert anki.notes_[900]["fields"] == before                           # the old card: nothing written
    assert [k.get("word_audio") for k in renders] == [False]


def test_a_rendered_translation_is_the_new_cards_own(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    row = _simple_swap(ledger, "ja", anki, monkeypatch)
    steps = _steps(tmp_path, monkeypatch, anki, _rendered(tmp_path, "ja", translation="May I borrow a pen?"))
    done = steps.swap_new_card("ja", ledger.job_by_id(row["job_id"]), {"video": "a.mkv", "subtitle": "a.ass"},
                               _words("ja"), 1, ledger, row)
    assert _value(anki, "Hint", done["outcomes"][0]["note_id"]) == "May I borrow a pen?"


@pytest.mark.parametrize("why", ["another note type", "deleted", "no render", "not on its line"])
def test_a_swap_anki_would_take_or_render_cant_make_is_mined_as_before(ledger, why, tmp_path, monkeypatch):
    """Only the old card of Connect's own note type is the duplicate: a card of the learner's own note type, or one
    deleted since (a *Bad card*'s), is mined — Anki takes it — and so is the word when render can't make it (an Anki
    Miner without `render`, 3.5–3.10; the word not on that line). Nothing is added, stored or written; for another note
    type nothing is even rendered."""
    anki = _card(Anki(), "ja")
    row = _simple_swap(ledger, "ja", anki, monkeypatch)
    renders = []
    steps = _steps(tmp_path, monkeypatch, anki, None if why == "not on its line" else _rendered(tmp_path, "ja"),
                   renders)
    if why == "another note type":
        anki.notes_[900]["modelName"] = "Japanese (recognition)"
    elif why == "deleted":
        del anki.notes_[900]
    elif why == "no render":
        def none(*a, **k):
            raise anki_miner.AnkiMinerError("no-render", "This Anki Miner can't render a line (3.11 or later can).")
        monkeypatch.setattr(anki_miner, "render_line", none)
    assert steps.swap_new_card("ja", ledger.job_by_id(row["job_id"]), {"video": "a.mkv", "subtitle": "a.ass"},
                               _words("ja"), 1, ledger, row) is None
    assert not any(op[0] in ("add_note", "store", "update", "delete_media") for op in anki.log)
    assert len(renders) == {"another note type": 0, "deleted": 0, "no render": 0, "not on its line": 1}[why]


def test_a_new_card_anki_refuses_leaves_no_clip_behind_and_asks_you_as_a_refused_mine_does(ledger, tmp_path, monkeypatch):
    """Anki refusing the note (a field it won't take, a deck gone mid-way): the line's clip and picture stored for it
    are taken out again — unless another note names them — and the refusal is *Needs you*, as a refused mine's."""
    anki = _card(Anki(), "ja")
    anki.refuse = "cannot create note because it is empty"
    row = _simple_swap(ledger, "ja", anki, monkeypatch)
    steps = _steps(tmp_path, monkeypatch, anki, _rendered(tmp_path, "ja"))
    with pytest.raises(runner.Needs):
        steps.swap_new_card("ja", ledger.job_by_id(row["job_id"]), {"video": "a.mkv", "subtitle": "a.ass"},
                            _words("ja"), 1, ledger, row)
    stored = [op[1] for op in anki.log if op[0] == "store"]
    assert len(stored) == 2 and all(name not in anki.media for name in stored)
    assert {"sl-old.mp3", "sl-old.webp"} <= set(anki.media)                # the old card's media stay


def test_while_you_review_nothing_is_stored_or_added(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    row = _simple_swap(ledger, "ja", anki, monkeypatch)
    monkeypatch.setattr(anki, "reviewing", lambda: True)
    steps = _steps(tmp_path, monkeypatch, anki, _rendered(tmp_path, "ja"))
    with pytest.raises(runner.Wait) as e:
        steps.swap_new_card("ja", ledger.job_by_id(row["job_id"]), {"video": "a.mkv", "subtitle": "a.ass"},
                            _words("ja"), 1, ledger, row)
    assert e.value.reason == runner.REVIEWING
    assert not any(op[0] in ("add_note", "store") for op in anki.log)


def test_render_without_a_sentence_or_its_files_is_mined_never_half_written(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    row = _simple_swap(ledger, "ja", anki, monkeypatch)
    rendered = _rendered(tmp_path, "ja")
    os.remove(rendered["files"][0])                                         # the clip render named isn't there
    steps = _steps(tmp_path, monkeypatch, anki, rendered)
    monkeypatch.setattr(steps, "_media_key", lambda lang, job: None)        # render's own names kept
    assert steps.swap_new_card("ja", ledger.job_by_id(row["job_id"]), {"video": "a.mkv", "subtitle": "a.ass"},
                               _words("ja"), 1, ledger, row) is None
    assert not any(op[0] in ("add_note", "store") for op in anki.log)
    with pytest.raises(ValueError):
        swap.add_new_card(anki, anki.notes_[900], {"fields": {"Sentence": ""}, "files": []}, MAPPING, ())


def test_new_card_row_is_a_queued_swap_with_an_old_card_never_an_in_place_one(ledger, monkeypatch):
    anki = _card(Anki(), "ja")
    row = _simple_swap(ledger, "ja", anki, monkeypatch)
    assert swap.new_card_row(ledger, row["job_id"])["id"] == row["id"]
    swap._set(ledger, row["id"], kind=swap.IN_PLACE)
    assert swap.new_card_row(ledger, row["job_id"]) is None
    swap._set(ledger, row["id"], kind=swap.NEW_CARD, old_note=None)          # *Add now*: no old card
    assert swap.new_card_row(ledger, row["job_id"]) is None
    swap._set(ledger, row["id"], old_note=900, state=swap.MADE)
    assert swap.new_card_row(ledger, row["job_id"]) is None
    assert swap.new_card_row(ledger, 12345) is None


def test_the_swap_jobs_batch_tries_in_place_then_beside_the_old_card_then_mines(ledger, monkeypatch):
    """The batch's order for a swap job: in place (FS-1), else the new card beside the old one, else Anki Miner's
    `mine` as for any card; a job of another kind always mines."""
    calls = []

    class S:
        def swap_in_place(self, lang, job, picked, words, attempt, ledger_, row):
            calls.append("in place")

        def swap_new_card(self, lang, job, picked, words, attempt, ledger_, row):
            calls.append(("beside", row["id"]))
            return self.answer

        def mine(self, lang, job, picked, words, attempt):
            calls.append("mine")
            return {"outcomes": []}
    steps = S()
    monkeypatch.setattr(runner, "_part_read", lambda *a: {})
    monkeypatch.setattr(swap, "in_place_row", lambda l, j: {"id": 4})
    monkeypatch.setattr(swap, "new_card_row", lambda l, j: {"id": 4} if j == 1 else None)
    steps.answer = {"outcomes": ["made"]}
    assert runner._mine_batch(steps, ledger, "ja", {"id": 1, "kind": SWAP}, {}, [], 1) == {"outcomes": ["made"]}
    steps.answer = None
    assert runner._mine_batch(steps, ledger, "ja", {"id": 1, "kind": SWAP}, {}, [], 1) == {"outcomes": []}
    runner._mine_batch(steps, ledger, "ja", {"id": 3, "kind": SWAP}, {}, [], 1)       # no old card on record
    runner._mine_batch(steps, ledger, "ja", {"id": 1, "kind": "level"}, {}, [], 1)
    assert calls == ["in place", ("beside", 4), "in place", ("beside", 4), "mine", "in place", "mine", "mine"]


def test_the_adapter_adds_through_ankiconnect_with_the_note_as_given(monkeypatch):
    sent = []
    monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **k: sent.append((action, url, k)) or 77)
    note = {"deckName": "D", "modelName": "Lapis", "fields": {"Word": "借りる"}, "tags": [],
            "options": {"allowDuplicate": True}}
    assert swap.AnkiSwap("http://127.0.0.1:8765").add_note(note) == 77
    assert sent == [("addNote", "http://127.0.0.1:8765", {"note": note})]


# --------------------------------------------------------------------------- #
# 2. A word on a caption's later event of one start: named by that event's text
# --------------------------------------------------------------------------- #
def _entry(word, at, surface=None):
    out = {"word": word, "line_start": at, "line_expansion": [0, 0]}
    if surface:
        out["surface"] = surface
    return out


def test_a_word_on_a_captions_later_event_is_named_by_its_text_and_one_on_the_first_keeps_its_start():
    """tv_captions.ass, a real broadcast's: at 0:00:05.10 three events (a ruby line, then 《門番は城への侵入者を, then
    厳しく取り調べた》) are one cue to Surasura; Anki Miner's `line_start` would name the first. A word on a later one
    goes by that event's text as the file writes it; a word on the line `line_start` names keeps its start; times not
    shared are left alone."""
    out = runfile.named_by_text(TV, [_entry("厳しい", 5.1, surface="厳しく"), _entry("侵入者", 5.1),
                                     _entry("父", 9.0, surface="父"), _entry("伝え", 14.0)], FROM_LINE, "ja")
    assert out[0] == {"word": "厳しい", "surface": "厳しく", "line_expansion": [0, 0], "line_text": "厳しく取り調べた》"}
    assert out[1] == {"word": "侵入者", "line_expansion": [0, 0], "line_text": "《門番は城への侵入者を"}
    assert out[2] == _entry("父", 9.0, surface="父") and out[3] == _entry("伝え", 14.0)
    episode = runfile.episode("x-1", "/v/a.mkv", TV, [_entry("長老", 11.5)], features=FROM_LINE, language="ja")
    assert episode["words"] == [{"word": "長老", "line_expansion": [0, 0], "line_text": "長老の話によれば➡"}]
    runfile.check(runfile.build("/run", "ja", [episode]))                  # a run file Anki Miner takes


def test_named_by_text_never_picks_a_text_an_earlier_line_holds_too(tmp_path):
    """Anki Miner's `line_text` names the FIRST line holding it: a later event whose text an earlier line holds too
    (a line said twice) keeps its start — never a card cut from the earlier time."""
    text = path_utils.read_text(TV, "ja")
    early = "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,厳しく取り調べた》"
    copy = tmp_path / "tv_captions.ass"
    copy.write_text(text.replace("[Events]\n", "[Events]\n", 1).replace(
        "Dialogue: 0,0:00:05.10", early + "\nDialogue: 0,0:00:05.10", 1), encoding="utf-8")
    assert runfile.named_by_text(str(copy), [_entry("厳しい", 5.1, surface="厳しく")], FROM_LINE, "ja") == \
        [_entry("厳しい", 5.1, surface="厳しく")]


def test_named_by_text_reads_a_chinese_caption_and_a_crlf_file(tmp_path):
    zh_a, zh_b = CASES["zh"][1], CASES["zh"][2]
    lines = ["[Script Info]", "ScriptType: v4.00+", "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
             f"Dialogue: 0,0:01:02.50,0:01:05.00,Default,,0,0,0,,{{\\pos(380,900)}}{zh_a}\\N",
             f"Dialogue: 0,0:01:02.50,0:01:05.00,Default,,0,0,0,,{{\\pos(380,1020)}}{zh_b}\\N"]
    path = tmp_path / "zh.ass"
    path.write_bytes("\r\n".join(lines).encode("utf-8-sig"))
    assert runfile.named_by_text(str(path), [_entry("牛肉面", 62.5)], FROM_LINE, "zh") == \
        [{"word": "牛肉面", "line_expansion": [0, 0], "line_text": f"{{\\pos(380,1020)}}{zh_b}\\N"}]


@pytest.mark.parametrize("case", ["no word-from-line", "srt", "missing file", "no line start", "word nowhere"])
def test_named_by_text_changes_nothing_it_cant_be_sure_of(tmp_path, case):
    """An Anki Miner that may not take `line_text` on a subtitle's word (no `word-from-line`: 3.5, 3.6), an .srt (one
    cue a caption), a file that can't be read, a book's entry (no start), a word no tied event holds: as they are."""
    words = [{"word": "長老", "line_text": "長老の話によれば➡"}] if case == "no line start" else \
        [_entry("村長" if case == "word nowhere" else "長老", 11.5)]
    path = TV
    if case == "srt":
        path = str(tmp_path / "a.srt")
        shutil.copy(TV, path)
    elif case == "missing file":
        path = str(tmp_path / "gone.ass")
    features = () if case == "no word-from-line" else FROM_LINE
    assert runfile.named_by_text(path, words, features, "ja") == words


def test_every_run_file_episode_carries_the_tie_rule(tmp_path, monkeypatch):
    """`mine_batch` and `render_line` build their episodes through `runfile.episode` with the version's features and
    the language — so a swap's render, Connect's mine and a Best sentence's other episodes all name such a word by
    its text."""
    import inspect
    src = inspect.getsource(anki_miner._mine_held) + inspect.getsource(anki_miner.render_line)
    assert src.count("features=named") == 3 and "".join(src.split()).count("features=named,language=language") == 3
    from app.cli import verbs
    assert "features=named, language=lang" in inspect.getsource(verbs)
