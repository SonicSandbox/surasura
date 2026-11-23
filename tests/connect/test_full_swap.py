"""FS-1, the full Swap (Connect; SCOPE.md § 8 — Sonic's decisions 1–15, 2026-11-23): a flagged card gets its new
sentence IN PLACE — the same note and cards, so its reviews, interval and due date stay — behind `swap_in_place`
(default on: *Same card, new sentence*).

What each test holds still:
- **the kind** (decided when the swap's job is made, decision 10): in place only for the loop's flag or the journey's
  ⇄, on a card Connect made (decision 6) whose sentence still holds Connect's line (decision 5); a *Bad card*
  (decision 11), the setting off, a card made by hand or changed by hand → a new card, said once;
- **the write** (the one field writer's replace mode): only the sentence side — the sentence, its audio and picture,
  the furigana emptied, the translation the new line's or the old one marked *（前の文）* (decision 2), the source
  field only while it holds Anki Miner's line (decision 4) — never the word, pitch, パターン / 例文, a ヒント, tags;
  the card's schedule untouched; back in reviews after a flag (decision 8), never taken out by a journey ⇄;
- **Undo:** every old value and the old media back, the card left in reviews; refused after a hand edit; twice:
  nothing more; the ledger's line of the card back to the old one (decision 15: *sentence from now*);
- **decision 15:** the card keeps its first job's tag and show tag (*first learned from*), and the ledger's newest
  made outcome of the note is its line now.
What a wrong answer costs: a card that loses its reviews (the reason to swap), a learner's edit overwritten, a word's
side rewritten, an old clip lost for good, or an Undo that writes over the learner's own work.
Real Japanese and Chinese lines from tests/Test Resources (the simple Swap's CASES); the ledger is real; Anki is the
simple Swap's fake plus the field writer's calls; Anki Miner's `render` answers as its source writes it.
"""
import base64
import json
import os

import pytest

from app.connect import anki_miner, deleted, fields, runner, sentence_audio, swap, swap_queue, tidy
from app.connect.ledger import SWAP
from tests.connect.test_kantan_sl_swap import CASES, Anki as SwapAnki, Steps, _lists, _queued, _row, ledger  # noqa: F401

FIRST_TAG = "surasura::connect::x-1"
SHOW_TAG = "Surasura::from::Toshokan"
MAPPING = fields.Mapping("日本語::Mining", "Lapis", {
    "word": "Word", "sentence": "Sentence", "audio": "SentenceAudio", "picture": "Picture",
    "sentence_furigana": "SentenceFurigana", "source": "MiscInfo", "pitch_position": "PitchPosition"},
    "Word", "Sentence", "MiscInfo", None, None)


class Anki(SwapAnki):
    """The simple Swap's fake, plus the one field writer's calls on the same notes (store, update, tag, read)."""

    def __init__(self):
        super().__init__()
        self.editor_open = set()

    def field_writer(self):
        return self

    def store(self, name, data):
        self.log.append(("store", name))
        self.media.setdefault(name, base64.b64decode(data))
        return name

    def update(self, nid, values):
        self.log.append(("update", int(nid), tuple(sorted(values))))
        if int(nid) in self.editor_open:
            return
        for k, v in values.items():
            self.notes_[int(nid)]["fields"][k]["value"] = v

    def tag(self, ids, tag, on=True):
        (self.add_tags if on else self.remove_tags)(ids, tag)

    def read_media(self, name):
        return self.media.get(name)

    def delete_media(self, name):
        self.log.append(("delete_media", name))
        self.media.pop(name, None)


def _card(anki, lang, note=900, reps=5, misc="Toshokan - 02 @ 00:17:27"):
    """A Connect card as Anki Miner + Backfill fill it (Lapis), studied `reps` times, suspended + green (the loop's
    move), its old clip and picture in Anki's media."""
    word, old, _other = CASES[lang]
    anki.add(note, FIRST_TAG, word, 1, cards=[{"reps": reps, "type": 2, "queue": -1, "flags": 3, "ivl": 21,
                                               "due": 830, "lapses": 1}])
    values = {"Word": word, "Sentence": old.replace(word, f"<b>{word}</b>"), "SentenceAudio": "[sound:sl-old.mp3]",
              "Picture": '<img src="sl-old.webp">', "SentenceFurigana": "AJTの色[いろ]", "Hint": "the old line's",
              "MiscInfo": misc, "PitchPosition": "2", "Patterns": "〜てもいい", "ExampleSentences": "例文",
              "IsSentenceCard": ""}
    anki.notes_[note]["fields"] = {k: {"value": v, "order": i} for i, (k, v) in enumerate(values.items())}
    anki.notes_[note]["tags"] = [FIRST_TAG, SHOW_TAG]
    anki.media["sl-old.mp3"], anki.media["sl-old.webp"] = b"ID3 old clip", b"RIFF old picture"
    return anki


def _made_by_connect(ledger, lang, note=900):
    word, old, _other = CASES[lang]
    job = ledger.queue(lang, 3, "user", None, store_id="s1")
    ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made", "note_id": note,
                                       "sentence": old}], deck=MAPPING.deck)
    ledger.set_state(job, "done")
    return job


def _rendered(tmp_path, lang, translation=""):
    """Anki Miner's `render` of the word on the other line: the whole note (the word's side too — never taken)."""
    word, _old, other = CASES[lang]
    clip, picture = tmp_path / "am-clip.mp3", tmp_path / "am-pic.webp"
    clip.write_bytes(b"ID3 " + other.encode("utf-8"))
    picture.write_bytes(b"RIFF new picture")
    values = {"Word": word + "（別）", "Sentence": other.replace(word, f"<b>{word}</b>"),
              "SentenceAudio": "[sound:am-clip.mp3]", "Picture": '<img src="am-pic.webp">',
              "SentenceFurigana": "", "MiscInfo": "Toshokan - 05 @ 00:03:10", "PitchPosition": "0",
              "Patterns": "", "Hint": translation}
    return {"fields": values, "files": [str(clip), str(picture)]}


def _to_job(ledger, lang, anki, monkeypatch):
    """The loop's green read into an ask, then the look that makes its job (the line picked: the other one)."""
    word, _old, other = CASES[lang]
    _lists(lang)
    entry = _queued(lang, word, card=9000, note=900)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    swap.look(Steps(), ledger, lang, store_id="s1", anki=anki, files=5)
    return entry, swap._rows(ledger, "language = ? AND ref = ?", (lang, entry["id"]))[-1]


def _job_made(ledger, row, note):
    """The swap job's batch ends as `runner._mine` ends it: its made outcome (the old note, for an in-place swap)."""
    word, _old, other = CASES[row["language"]]
    ledger.end_batch(row["job_id"], 1, "done", [{"word": row["word"], "reading": "", "outcome": "made",
                                                 "note_id": note, "sentence": other}], deck=MAPPING.deck)
    ledger.set_state(row["job_id"], "done")


def _value(anki, field, note=900):
    return anki.notes_[note]["fields"][field]["value"]


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setattr(swap, "_swap_flag", lambda: 3)       # the learner's Swap flag: green (the default)


# --------------------------------------------------------------------------- #
# The whole round: in place, back in reviews, Undo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_flagged_connect_card_gets_its_new_sentence_in_place_keeps_its_reviews_and_undo_puts_it_back(
        ledger, lang, tmp_path, monkeypatch):
    word, old, other = CASES[lang]
    anki = _card(Anki(), lang)
    first_job = _made_by_connect(ledger, lang)
    entry, row = _to_job(ledger, lang, anki, monkeypatch)
    assert (row["state"], row["kind"]) == (swap.QUEUED, swap.IN_PLACE)
    assert ledger.job_by_id(row["job_id"])["kind"] == SWAP
    assert swap.in_place_row(ledger, row["job_id"])["id"] == row["id"]
    before = dict(anki.cards_[9000])
    kind, note = swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, str(tmp_path / "kept"))
    assert (kind, note) == (swap.IN_PLACE, 900)
    _job_made(ledger, swap.in_place_row(ledger, row["job_id"]), 900)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = _row(ledger, row["id"])
    assert (row["state"], row["new_note"], row["kind"], row["tagged"]) == (swap.MADE, 900, swap.IN_PLACE, 1)
    assert [e for e in swap_queue.load(lang) if e["id"] == entry["id"]][0]["state"] == "made"
    # the sentence side is the new line's
    assert _value(anki, "Sentence") == other.replace(word, f"<b>{word}</b>")
    assert _value(anki, "SentenceAudio") == "[sound:am-clip.mp3]" and _value(anki, "Picture") == '<img src="am-pic.webp">'
    assert _value(anki, "SentenceFurigana") == ""                                  # AJT's colours of the old line
    assert _value(anki, "Hint") == swap.MARK + "the old line's"                    # decision 2: kept, marked
    assert _value(anki, "MiscInfo") == "Toshokan - 05 @ 00:03:10"                  # decision 4/15: from now
    # the word's side, pitch, パターン / 例文 and the card type: never written
    for name, value in (("Word", word), ("PitchPosition", "2"), ("Patterns", "〜てもいい"),
                        ("ExampleSentences", "例文"), ("IsSentenceCard", "")):
        assert _value(anki, name) == value
    # the card: its reviews, interval, due and lapses kept; back in your reviews, its green flag off (decision 8)
    card = anki.cards_[9000]
    assert {k: card[k] for k in ("reps", "ivl", "due", "lapses")} == {k: before[k] for k in ("reps", "ivl", "due",
                                                                                              "lapses")}
    assert (card["queue"], card["flags"]) == (0, 0)
    # decision 15: first learned from — the first job's tag and the show's stay; the line now — the ledger's newest
    assert {FIRST_TAG, SHOW_TAG, swap.SWAP_TAG} <= set(anki.notes_[900]["tags"])
    assert deleted._made(ledger.conn, lang, 900)[2] == other
    assert ledger.outcomes(first_job)[0]["outcome"] == "made"                       # never overwritten
    # the old clip and picture: kept on disk first, then gone from Anki (no other note names them)
    assert "sl-old.mp3" not in anki.media and "sl-old.webp" not in anki.media
    assert swap.status_of(ledger.conn, lang)["made"][0]["kind"] == swap.IN_PLACE
    # Undo: the old sentence side back, the old media stored again, the card left in reviews
    got = swap.undo(anki, ledger, lang, row["id"])
    assert got == {"undone": True, "word": word, "kind": swap.IN_PLACE}
    assert _value(anki, "Sentence") == old.replace(word, f"<b>{word}</b>")
    assert _value(anki, "SentenceFurigana") == "AJTの色[いろ]" and _value(anki, "Hint") == "the old line's"
    assert _value(anki, "MiscInfo") == "Toshokan - 02 @ 00:17:27"
    assert anki.media["sl-old.mp3"] == b"ID3 old clip" and "am-clip.mp3" not in anki.media
    assert swap.SWAP_TAG not in anki.notes_[900]["tags"] and anki.cards_[9000]["queue"] == 0
    assert deleted._made(ledger.conn, lang, 900)[2] == old                         # the card's line is its old one
    assert [e for e in swap_queue.load(lang) if e["id"] == entry["id"]][0]["state"] == "undone"
    with pytest.raises(tidy.Refused) as twice:
        swap.undo(anki, ledger, lang, row["id"])
    assert twice.value.say == swap.ALREADY


def test_a_journey_swap_in_place_never_takes_the_card_out_of_reviews(ledger, tmp_path, monkeypatch):
    lang = "ja"
    anki = _card(Anki(), lang)
    anki.cards_[9000].update(queue=2, flags=0)                       # in reviews, unflagged: the page's ⇄
    _made_by_connect(ledger, lang)
    got = swap.make_card(lang, CASES[lang][0], old_note=900, old_card=9000, by=swap.BY_JOURNEY, ledger=ledger,
                         wake=False, state_of=lambda w, r: None)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, CASES[lang][2]))
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = _row(ledger, got["id"])
    assert row["kind"] == swap.IN_PLACE
    swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, str(tmp_path / "kept"))
    _job_made(ledger, _row(ledger, got["id"]), 900)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert _row(ledger, got["id"])["state"] == swap.MADE
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (2, 0)
    assert not [e for e in anki.log if e[0] in ("suspend", "unsuspend", "set_flag")]


# --------------------------------------------------------------------------- #
# The kind: who gets a new card instead
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_whose_sentence_was_changed_by_hand_gets_a_new_card_said_once(ledger, lang, monkeypatch):
    anki = _card(Anki(), lang)
    anki.notes_[900]["fields"]["Sentence"]["value"] = "自分で書き直した文です。"
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    assert (row["kind"], row["kind_why"], row["why"]) == (swap.NEW_CARD, swap.HAND_EDITED, None)


def test_a_card_connect_did_not_make_is_never_rewritten(ledger, monkeypatch):
    anki = _card(Anki(), "ja")                                       # flagged green, but mined by hand
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    assert (row["kind"], row["kind_why"]) == (swap.NEW_CARD, swap.NOT_CONNECTS)


def test_the_setting_off_and_a_bad_card_make_a_new_card(ledger, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    with monkeypatch.context() as patched:
        patched.setattr(swap, "in_place_on", lambda settings=None: False)
        _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    assert row["kind"] == swap.NEW_CARD
    bad = {"by": swap.BY_BAD_CARD, "old_note": 900}
    assert swap._kind_of(ledger, bad, anki) == (swap.NEW_CARD, None)


def test_a_swap_waiting_when_the_setting_is_switched_follows_it_when_its_job_is_made(ledger, monkeypatch):
    """Decision 10: the ask was made while *Same card* was on; switched to *A new card* before Connect's look: the job
    made then is a new card's (nothing redone for swaps already made)."""
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    swap.make_card("ja", CASES["ja"][0], old_note=900, old_card=9000, ledger=ledger, wake=False,
                   state_of=lambda w, r: None)
    assert swap.in_place_on({"swap_in_place": True}) and not swap.in_place_on({"swap_in_place": False})
    assert swap.in_place_on({}) and swap.in_place_on({"swap_in_place": "no"})      # anything else: the default
    monkeypatch.setattr(swap, "in_place_on", lambda settings=None: False)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, CASES["ja"][2]))
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    assert swap._rows(ledger, "language = ?", ("ja",))[-1]["kind"] == swap.NEW_CARD


def test_anki_unreadable_at_the_look_decides_nothing(ledger, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")

    def gone(ids):
        raise OSError("Anki stopped answering")
    anki.notes = gone
    assert swap._kind_of(ledger, {"by": swap.BY_SWAP, "old_note": 900}, anki) == (None, None)


# --------------------------------------------------------------------------- #
# The write's own rules
# --------------------------------------------------------------------------- #
def test_a_hand_edit_between_the_look_and_the_write_falls_back_to_a_new_card(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    anki.notes_[900]["fields"]["Sentence"]["value"] = "電話で直した。"
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja"), MAPPING, str(tmp_path / "k")) == (
        swap.NEW_CARD, swap.HAND_EDITED)
    assert not [e for e in anki.log if e[0] == "update"]


def test_a_source_field_holding_a_hint_and_a_rendered_translation(ledger, tmp_path, monkeypatch):
    """The source field holds the learner's ヒント, not Anki Miner's line: kept (decision 4). The new line comes with
    its own translation (a second subtitle track): it replaces the old one, no mark."""
    anki = _card(Anki(), "ja", misc="借りる＝to borrow（自分のメモ）")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja", translation="May I borrow a pen?"), MAPPING,
                        str(tmp_path / "k"))
    assert _value(anki, "MiscInfo") == "借りる＝to borrow（自分のメモ）"
    assert _value(anki, "Hint") == "May I borrow a pen?"


def test_a_book_line_with_no_audio_or_picture_empties_them(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    book = _rendered(tmp_path, "ja")
    book["fields"].update(SentenceAudio="", Picture="")
    book["files"] = []
    swap.write_in_place(anki, ledger, row, book, MAPPING, str(tmp_path / "k"))
    assert _value(anki, "SentenceAudio") == "" and _value(anki, "Picture") == ""


def test_a_card_open_in_ankis_editor_is_asked_again_never_a_new_card(ledger, tmp_path, monkeypatch):
    """The write read back unchanged (Anki's editor keeps its own copy): no card made, the swap still in place and
    queued — the runner's batch waits (`Wait`) and renders the same line again at the next look."""
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    anki.editor_open.add(900)
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja"), MAPPING, str(tmp_path / "k")) == (
        None, swap.NOT_APPLIED)
    row = _row(ledger, row["id"])
    assert (row["state"], row["kind"], row["wrote"]) == (swap.QUEUED, swap.IN_PLACE, None)
    assert "sl-old.mp3" in anki.media


def test_undo_after_a_hand_edit_is_refused_and_changes_nothing(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja"), MAPPING, str(tmp_path / "k"))
    _job_made(ledger, _row(ledger, row["id"]), 900)
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    anki.notes_[900]["fields"]["Sentence"]["value"] = "直した。"
    with pytest.raises(tidy.Refused) as e:
        swap.undo(anki, ledger, "ja", row["id"])
    assert e.value.say == swap.CHANGED
    assert _value(anki, "Sentence") == "直した。" and _row(ledger, row["id"])["state"] == swap.MADE


# --------------------------------------------------------------------------- #
# The runner and Anki Miner's render
# --------------------------------------------------------------------------- #
def test_the_swap_jobs_batch_renders_in_place_and_falls_back_to_mining_when_it_cant(ledger, monkeypatch):
    calls = []

    class S:
        def swap_in_place(self, lang, job, picked, words, attempt, ledger_, row):
            calls.append(("in place", row["id"]))
            return self.answer

        def mine(self, lang, job, picked, words, attempt):
            calls.append(("mine",))
            return {"outcomes": []}
    steps = S()
    monkeypatch.setattr(runner, "_part_read", lambda *a: {})
    monkeypatch.setattr(swap, "in_place_row", lambda l, j: {"id": 4})
    steps.answer = {"outcomes": ["made"]}
    assert runner._mine_batch(steps, ledger, "ja", {"id": 1, "kind": SWAP}, {}, [], 1) == {"outcomes": ["made"]}
    steps.answer = None                                              # it can't be rewritten: a new card
    assert runner._mine_batch(steps, ledger, "ja", {"id": 1, "kind": SWAP}, {}, [], 1) == {"outcomes": []}
    runner._mine_batch(steps, ledger, "ja", {"id": 2, "kind": "level"}, {}, [], 1)
    assert calls == [("in place", 4), ("in place", 4), ("mine",), ("mine",)]


def test_render_line_reads_render_rows_and_needs_render(tmp_path, monkeypatch):
    """Anki Miner's `render` (its source: `runs.py` writes `render-NNN.json`, rows with `fields` and `files` inside the
    run folder): the word's note read back; an Anki Miner without `render` (Z-10) → `no-render` (a new card)."""
    word, _old, other = CASES["ja"]
    run_dir = tmp_path / "run"
    sent = []

    def api(path, args, timeout=None, **_k):
        sent.append(args[0])
        run_id = "j7-1"
        folder = run_dir / run_id
        (folder / "render-001").mkdir(parents=True)
        (folder / "render-001" / "am-clip.mp3").write_bytes(b"ID3")
        (folder / "render-001.json").write_text(json.dumps({"words": [
            {"word": word, "mined_form": word, "status": "rendered", "line_start": 12.5,
             "fields": {"Sentence": other, "SentenceAudio": "[sound:am-clip.mp3]"},
             "files": ["render-001/am-clip.mp3"]}]}, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "runs": [{"run_id": run_id, "ok": True, "file": "render-001.json"}]}
    info = {"app": "3.12.0", "features": ["render", "media"]}
    monkeypatch.setattr(anki_miner, "preflight", lambda *a, **k: (info, "p1"))
    monkeypatch.setattr(anki_miner, "api", api)
    words = [{"word": word, "reading": "", "line_start": 12.5, "line_expansion": [0, 0], "sent": [word]}]
    got = anki_miner.render_line("am.exe", "ja", "j7", "ep.mkv", "ep.ass", words, MAPPING, "Surasura", str(run_dir))
    assert sent == ["render"]
    assert got[(word, "")]["fields"]["Sentence"] == other
    assert got[(word, "")]["files"] == [os.path.join(str(run_dir), "j7-1", "render-001", "am-clip.mp3")]
    info["features"] = ["media"]
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.render_line("am.exe", "ja", "j7", "ep.mkv", "ep.ass", words, MAPPING, "Surasura", str(run_dir))
    assert e.value.kind == "no-render"


def test_the_field_writers_adapter_is_swaps_for_its_in_place_write():
    assert isinstance(swap.AnkiSwap("http://127.0.0.1:8765").field_writer(), sentence_audio.AnkiConnectNotes)
