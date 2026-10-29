"""Settings export and import (alpha 6, Mattias's note 8; `app/services/settings_io.py`; leans SI-1…SI-5, PROVISIONAL).

What a wrong answer would cost: a learner's settings lost on a new PC or at the next alpha — or worse, mixed with the
old ones (an import that merges leaves keys he never chose), written over without a copy, half written, or carried in
from a newer Surasura whose keys mean what this one can't read. A secret in the file, his known words or library in it.
A folder from the old PC that isn't here breaking Connect quietly instead of asking. And a needless full Generate after
importing the same settings (a moved run signature), or a stale list after importing different ones.

Real settings: a Japanese learner's 3.0 file and a Chinese profile (`tests/Test Resources/settings/`), the app's own
reads and writes (`settings_manager`, `path_utils.backup_to_trash`), the test root's settings.json.
"""
import json
import os
import shutil

import pytest

from app import analyzer, locks, path_utils, settings_manager
from app.services import needs, settings_io
from app.services.settings import SettingsService

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "settings")


def _fixture(name):
    with open(os.path.join(RESOURCES, name), encoding="utf-8") as f:
        return json.load(f)


def _install(settings):
    """`settings` as the test root's settings.json, written as the app writes it."""
    path = path_utils.get_settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    return path


def _file():
    with open(path_utils.get_settings_path(), encoding="utf-8") as f:
        return json.load(f)


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _trash():
    trash = os.path.join(os.path.dirname(path_utils.get_settings_path()), ".trash")
    return sorted(os.listdir(trash)) if os.path.isdir(trash) else []


def _signatures(language):
    """(the run signature's settings part, the render signature) as the analyzer reads settings.json now."""
    from tests.test_settings_signatures import _signatures as signatures
    return analyzer.settings_signature(settings_manager.load_settings(), language), signatures(language)


@pytest.fixture
def ja():
    return _fixture("settings_ja_learner.json")


@pytest.fixture
def zh():
    return _fixture("settings_zh_profile.json")


@pytest.fixture
def export_dir(tmp_path):
    d = tmp_path / "設定 バックアップ"                # a non-ASCII folder, a space in it
    d.mkdir()
    return d


# --- the round trip ----------------------------------------------------------------------------------------------- #
def test_round_trip_puts_back_every_known_setting_and_the_signatures_as_they_were(ja, export_dir):
    """Exported, changed, imported: the file holds what was exported (less only what this version doesn't know), and
    the run and render signatures are the exported settings' again — no needless Generate, none skipped."""
    _install(ja)
    before = _signatures("ja")
    out = str(export_dir / settings_io.default_name())
    assert settings_io.export(out).ok
    settings_manager.save_keys({"words_per_day": 3, "logic": dict(ja["logic"], ignore_names=False)})
    assert _signatures("ja") != before                          # an analysis setting moved: the list is stale
    plan = settings_io.read(out, isdir=lambda p: True)
    assert plan.refused is None
    outcome = settings_io.apply(plan)
    assert outcome.ok, outcome.message
    written = _file()
    expected = {k: v for k, v in ja.items() if k not in ("reinforce_segmentation", "hide_satoru")}
    expected["logic"] = json.loads(json.dumps(ja["logic"]))
    del expected["logic"]["weights"]["_comment"], expected["logic"]["context"]["min_words"]
    assert written == expected
    assert set(plan.dropped) == {"reinforce_segmentation", "hide_satoru", "logic.context.min_words"}
    assert _signatures("ja") == before


def test_the_export_is_the_file_as_it_holds_it_stamped_with_the_version_and_language(export_dir):
    """Only the choices the file holds go out (a default left unsaved follows the next version's default)."""
    _install({"target_language": "zh", "words_per_day": 9})
    out = str(export_dir / "s.json")
    settings_io.export(out)
    with open(out, encoding="utf-8") as f:
        data = json.load(f)
    assert data[settings_io.MARK] == settings_io.FORMAT
    assert data["version"] == settings_io.app_version() and data["language"] == "zh" and data["exported"]
    assert data["settings"] == {"target_language": "zh", "words_per_day": 9}


def test_a_chinese_profile_round_trips_and_its_question_names_chinese(zh, export_dir):
    _install(zh)
    before = _signatures("zh")
    out = str(export_dir / "中文 设置.json")
    settings_io.export(out)
    _install({"target_language": "ja", "zh_script": "s"})
    plan = settings_io.read(out, isdir=lambda p: True)
    assert plan.language == "zh" and plan.dropped == ()
    title, body, yes = settings_io.question(plan)
    assert "for Chinese" in body and yes == "Import and restart" and title == "Replace your settings?"
    assert settings_io.apply(plan).ok
    assert _file() == zh
    assert settings_manager.load_settings()["anki_sync_decks"] == {"zh": ["中文::挖词", "中文::台剧"]}
    assert _signatures("zh") == before


def test_an_export_to_a_non_ascii_path_keeps_its_words_readable(ja, export_dir):
    _install(ja)
    out = str(export_dir / "スラスラ 設定.json")
    assert settings_io.export(out).ok
    text = _bytes(out).decode("utf-8")
    assert "日本語::採掘" in text and "\\u" not in text      # the decks as written, not escaped
    assert settings_io.read(out, isdir=lambda p: True).settings["anki_sync_decks"] == ja["anki_sync_decks"]


# --- an import replaces whole, a dated copy first ----------------------------------------------------------------- #
def test_an_import_replaces_the_settings_whole_never_merged_and_a_missing_key_takes_its_default(ja, export_dir):
    """A key the imported file lacks isn't kept from the settings now: it reads as its default."""
    out = str(export_dir / "s.json")
    _install({"target_language": "ja", "text_size": "S"})
    settings_io.export(out)
    _install(ja)
    assert settings_io.apply(settings_io.read(out)).ok
    assert _file() == {"target_language": "ja", "text_size": "S"}
    loaded = settings_manager.load_settings()
    assert loaded["words_per_day"] == settings_manager.DEFAULT_SETTINGS["words_per_day"]       # ja's 12 is gone
    assert loaded["logic"]["selection"]["band"] == settings_manager.DEFAULT_SETTINGS["logic"]["selection"]["band"]


def test_the_settings_before_are_kept_whole_in_a_dated_copy(ja, export_dir):
    out = str(export_dir / "s.json")
    _install({"target_language": "ja"})
    settings_io.export(out)
    path = _install(ja)
    old = _bytes(path)
    outcome = settings_io.apply(settings_io.read(out))
    assert outcome.ok and outcome.path and _bytes(outcome.path) == old
    assert _trash() == [os.path.basename(outcome.path)] and outcome.path in outcome.message


def test_with_no_settings_yet_the_import_writes_them_and_says_so(export_dir):
    out = str(export_dir / "s.json")
    _install({"target_language": "ja", "words_per_day": 7})
    settings_io.export(out)
    os.remove(path_utils.get_settings_path())
    outcome = settings_io.apply(settings_io.read(out))
    assert outcome.ok and outcome.path is None and outcome.message == "Settings imported."
    assert _file() == {"target_language": "ja", "words_per_day": 7}


def test_no_copy_no_import_the_file_untouched(ja, export_dir, monkeypatch):
    out = str(export_dir / "s.json")
    _install({"target_language": "ja"})
    settings_io.export(out)
    path = _install(ja)
    old = _bytes(path)

    def refuse(_path, move=False):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(path_utils, "backup_to_trash", refuse)
    outcome = settings_io.apply(settings_io.read(out))
    assert not outcome.ok and "nothing was changed" in outcome.message and "No space" in outcome.message
    assert _bytes(path) == old


def test_a_write_that_fails_leaves_the_file_as_it_was(ja, export_dir, monkeypatch):
    out = str(export_dir / "s.json")
    _install({"target_language": "ja"})
    settings_io.export(out)
    path = _install(ja)
    old = _bytes(path)

    def broken(_path, _data):
        raise PermissionError(13, "held open")
    monkeypatch.setattr(settings_manager, "_write_atomically", broken)
    outcome = settings_io.apply(settings_io.read(out))
    assert not outcome.ok and outcome.message == settings_io.STRINGS["write_failed"]
    assert _bytes(path) == old


def test_the_settings_lock_held_elsewhere_refuses_and_writes_nothing(ja, export_dir, monkeypatch):
    out = str(export_dir / "s.json")
    _install({"target_language": "ja"})
    settings_io.export(out)
    path = _install(ja)
    old = _bytes(path)

    def busy(_wait):
        raise locks.Busy("settings", None)
    monkeypatch.setattr(settings_manager, "_settings_lock", busy)
    outcome = settings_io.apply(settings_io.read(out))
    assert not outcome.ok and outcome.message == settings_io.STRINGS["busy"]
    assert _bytes(path) == old and _trash() == []


def test_a_change_still_queued_lands_before_the_import_never_after_it(ja, export_dir):
    """A setting pressed just before the import is replaced too: the window's queued change can't land on top."""
    out = str(export_dir / "s.json")
    _install({"target_language": "ja", "words_per_day": 7})
    settings_io.export(out)
    _install(ja)
    service = SettingsService(delay=0.5)
    service.set({"words_per_day": 99})
    assert settings_io.apply(settings_io.read(out), service=service).ok
    service.flush(5)
    assert _file()["words_per_day"] == 7
    assert service.get()["words_per_day"] == 7               # the window's copy read again


# --- refused, in plain words -------------------------------------------------------------------------------------- #
def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _stamped(version, settings=None, mark=settings_io.FORMAT):
    return json.dumps({settings_io.MARK: mark, "version": version, "language": "ja", "exported": "2026-10-29T10:00:00",
                       "settings": settings if settings is not None else {"words_per_day": 4}})


def test_a_file_from_a_newer_surasura_is_refused_in_plain_words_and_nothing_changes(ja, export_dir, monkeypatch):
    monkeypatch.setattr(settings_io, "app_version", lambda: "2.9.0.6")
    path = _install(ja)
    old = _bytes(path)
    plan = settings_io.read(_write(export_dir / "s.json", _stamped("2.9.0.7")))
    assert plan.refused == ("These settings come from Surasura 2.9.0.7, newer than this one (2.9.0.6). Update "
                            "Surasura first, then import them.")
    assert not settings_io.apply(plan).ok
    assert _bytes(path) == old and _trash() == []


@pytest.mark.parametrize("theirs, ours, newer", [
    ("2.9.0.7", "2.9.0.6", True), ("2.9.0.6", "2.9.0.6", False), ("2.9.0.5", "2.9.0.6", False),
    ("3.0.0", "2.9.0.6", True), ("2.9", "2.9.0", False), ("2.9.0", "2.9", False), ("v3.0.1-beta", "3.0", True),
    ("2.10.0", "2.9.0.6", True), ("", "2.9.0.6", False)])
def test_newer_compares_versions_by_their_numbers(theirs, ours, newer):
    assert settings_io.newer(theirs, ours) is newer


def test_the_same_or_an_older_version_imports(export_dir, monkeypatch):
    monkeypatch.setattr(settings_io, "app_version", lambda: "2.9.0.7")
    _install({"target_language": "ja"})
    for version in ("2.9.0.7", "2.9.0.6", "2.5.0"):
        assert settings_io.read(_write(export_dir / "s.json", _stamped(version))).refused is None


def test_a_newer_shape_of_file_is_refused(export_dir):
    plan = settings_io.read(_write(export_dir / "s.json", _stamped(settings_io.app_version(), mark=2)))
    assert plan.refused == settings_io.STRINGS["newer_format"]


@pytest.mark.parametrize("text, why", [
    ("", "empty"), ("  \r\n\t", "empty"), ("{not json", "not_ours"), ("[1, 2]", "not_ours"),
    ('{"words_per_day": 5, "logic": {}}', "not_ours"),            # a bare settings.json: no version to judge it by
    ('{"surasura_settings": 1, "version": "2.5.0", "settings": [1]}', "not_ours"),
    ('{"surasura_settings": 1, "settings": {"words_per_day": 5}}', "no_version"),
    ('{"surasura_settings": 1, "version": "latest", "settings": {}}', "no_version")])
def test_a_file_that_isnt_a_settings_export_is_refused(text, why, export_dir):
    plan = settings_io.read(_write(export_dir / "s.json", text))
    assert plan.refused == settings_io.STRINGS[why] and plan.settings is None


def test_a_file_that_isnt_text_is_refused(export_dir):
    path = export_dir / "s.json"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe\x80")
    assert settings_io.read(str(path)).refused == settings_io.STRINGS["not_ours"]


def test_a_file_gone_before_it_is_read_says_why(export_dir):
    plan = settings_io.read(str(export_dir / "gone.json"))
    assert plan.refused.startswith("Couldn't read that file: ")


def test_a_bom_from_notepad_is_read(export_dir):
    path = export_dir / "s.json"
    path.write_bytes(b"\xef\xbb\xbf" + _stamped(settings_io.app_version()).encode("utf-8"))
    assert settings_io.read(str(path)).refused is None


# --- what is left out --------------------------------------------------------------------------------------------- #
def test_keys_this_version_doesnt_know_are_left_out_and_counted(export_dir):
    settings = {"words_per_day": 4, "future_switch": True, "hide_satoru": True, "junban_url": "http://x",
                "logic": {"ignore_names": True, "future_rule": 3, "_comment": "x",
                          "selection": {"band": "rare", "future_band": 1}, "weights": {"high": 9, "future": 1}}}
    plan = settings_io.read(_write(export_dir / "s.json", _stamped(settings_io.app_version(), settings)))
    assert plan.settings == {"words_per_day": 4, "logic": {"ignore_names": True, "selection": {"band": "rare"},
                                                           "weights": {"high": 9}}}
    assert set(plan.dropped) == {"future_switch", "hide_satoru", "junban_url", "logic.future_rule",
                                 "logic.selection.future_band", "logic.weights.future"}
    assert "6 settings this version doesn't use are left out." in settings_io.question(plan)[1]


def test_a_module_not_installed_leaves_its_settings_out(export_dir, monkeypatch):
    from app import settings_placement
    monkeypatch.setattr(settings_placement, "_installed", lambda path: not path.startswith("koe_"))
    settings = {"koe_voice": "Kore", "words_per_day": 4}
    plan = settings_io.read(_write(export_dir / "s.json", _stamped(settings_io.app_version(), settings)))
    assert plan.settings == {"words_per_day": 4} and plan.dropped == ("koe_voice",)


def test_a_key_named_like_a_secret_never_leaves_or_comes_in(export_dir):
    _install({"words_per_day": 4, "jiten_api_key": "sk-123", "anki_token": "t"})
    out = str(export_dir / "s.json")
    settings_io.export(out)
    assert "sk-123" not in _bytes(out).decode("utf-8") and '"t"' not in _bytes(out).decode("utf-8")
    plan = settings_io.read(_write(export_dir / "in.json", _stamped(settings_io.app_version(),
                                                                    {"koe_api_key": "k", "words_per_day": 4,
                                                                     "logic": {"password": "p"}})))
    assert plan.settings == {"words_per_day": 4, "logic": {}}


def test_no_placed_setting_is_named_like_a_secret():
    """The secret rule never drops a real setting (a new key named so would vanish from every export)."""
    from app.settings_placement import PLACED
    assert [k for k in PLACED if not settings_io.known(k) and settings_io.SECRET.search(k.rsplit(".", 1)[-1])] == []


# --- this PC's places --------------------------------------------------------------------------------------------- #
def test_anki_miners_place_not_on_this_pc_goes_back_to_finding_it(export_dir, tmp_path):
    here = tmp_path / "Anki Miner" / "anki_miner.exe"
    here.parent.mkdir()
    here.write_bytes(b"MZ")
    for place, kept in ((str(here), True), ("C:\\Program Files\\Gone\\anki_miner.exe", False), ("", True)):
        settings = {"connect_anki_miner_path": place, "words_per_day": 4}
        plan = settings_io.read(_write(export_dir / "s.json", _stamped(settings_io.app_version(), settings)))
        assert ("connect_anki_miner_path" in plan.settings) is kept
        assert plan.miner_reset is (not kept)
        assert ("Surasura finds it by itself" in settings_io.question(plan)[1]) is (not kept)


def test_a_video_folder_not_on_this_pc_is_kept_and_becomes_a_needs_you_card(ja, export_dir, tmp_path):
    """Not an error: the import goes on, the folder stays in the settings, and *Needs you* asks for it — until it is
    found (*Find it…* puts the folder picked in its place) or taken out, or the folder appears."""
    here = tmp_path / "動画 フォルダ"
    here.mkdir()
    gone = "Z:\\アニメ\\字幕と動画"
    ja["connect_video_folders"] = {"ja": [str(here), gone], "zh": [gone]}
    _install(ja)
    out = str(export_dir / "s.json")
    settings_io.export(out)
    plan = settings_io.read(out)
    assert plan.missing == (gone,) and plan.refused is None
    assert "1 video folder in them isn't on this computer" in settings_io.question(plan)[1]
    assert settings_io.apply(plan).ok
    loaded = settings_manager.load_settings()
    assert settings_io.missing_folders(loaded, "ja") == [gone] == settings_io.missing_folders(loaded, "zh")
    cards = needs.entries(None, settings_folders=settings_io.missing_folders(loaded, "ja"))
    assert [(c.kind, c.actions, c.data["path"]) for c in cards] == [
        (needs.SETTINGS_FOLDER, ("find_settings_folder", "drop_settings_folder"), gone)]
    assert gone in cards[0].title and cards[0].unseen
    assert needs.entries(None, seen={cards[0].key}, settings_folders=[gone])[0].unseen is False
    found = tmp_path / "新しい 場所"
    found.mkdir()
    change = settings_io.folder_change(loaded, gone, str(found))
    assert change == {"connect_video_folders": {"ja": [str(here), str(found)], "zh": [str(found)]}}
    settings_manager.save_keys(change)
    assert settings_io.missing_folders(settings_manager.load_settings(), "ja") == []


def test_stop_looking_there_takes_the_folder_out_of_every_language(tmp_path):
    for value, left in (({"ja": ["A", "Z:\\x"], "zh": ["Z:\\x"]}, {"ja": ["A"], "zh": []}),
                        (["A", "Z:\\x", "B"], ["A", "B"]), ("Z:\\x", [])):
        assert settings_io.folder_change({"connect_video_folders": value}, "Z:\\x") == {"connect_video_folders": left}


def test_a_folder_found_already_in_the_list_is_not_listed_twice():
    value = {"connect_video_folders": ["A", "Z:\\x"]}
    assert settings_io.folder_change(value, "Z:\\x", "A") == {"connect_video_folders": ["A"]}


def test_only_the_imports_own_folders_ask_never_one_added_by_hand(tmp_path):
    """An unplugged drive's folder the learner added himself is Connect's to wait for, never a card of the import's."""
    settings = {"connect_video_folders": ["Z:\\mine", "Z:\\imported"]}
    with open(settings_io.record_path(), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "folders": ["Z:\\imported"]}, f)
    assert settings_io.missing_folders(settings, "ja") == ["Z:\\imported"]
    assert settings_io.missing_folders(settings, "ja", isdir=lambda p: True) == []      # it came back
    assert settings_io.missing_folders({"connect_video_folders": ["Z:\\mine"]}, "ja") == []   # taken out


def test_the_windows_frozen_settings_are_read_as_the_files(tmp_path):
    """The window hands its settings frozen (`SettingsService.get`: mappings and tuples): the same answers."""
    from app.services.settings import freeze
    settings = {"connect_video_folders": {"ja": ["A", "Z:/imported"], "zh": ["Z:/imported"]}}
    with open(settings_io.record_path(), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "folders": ["Z:/imported"]}, f)
    assert settings_io.missing_folders(freeze(settings), "ja") == ["Z:/imported"]
    assert settings_io.folder_change(freeze(settings), "Z:/imported") == {"connect_video_folders": {"ja": ["A"],
                                                                                                    "zh": []}}


def test_an_unreadable_record_means_no_card():
    with open(settings_io.record_path(), "w", encoding="utf-8") as f:
        f.write("{broken")
    assert settings_io.missing_folders({"connect_video_folders": ["Z:\\x"]}, "ja") == []
    assert settings_io.missing_folders(None, "ja") == []


def test_the_needs_card_key_is_one_for_a_case_or_slash_apart():
    a = needs.entries(None, settings_folders=["Z:\\Anime\\Videos"])[0]
    b = needs.entries(None, settings_folders=["z:/anime/videos"])[0]
    assert a.key == b.key
