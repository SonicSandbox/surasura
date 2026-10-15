"""Row 4's doors on the Settings tab's list (W3.4; `app/qt/windows.py` `OPENERS`): Speech (Koe), Video transcripts and
Preview a video — shown by the Tk dashboard's rules, each opening its module's window lazily.

What a wrong answer would cost: Speech advertised to every user before they revealed it (the reveal gate: the line in
settings.json), or a dead door when its switch is off; the downloader or the preview shown with its switch off, or
hidden with it on; a door shown for a module the build doesn't have (a dead button); a door that reads a file on the
window's thread to decide.
"""
import pytest

pytest.importorskip("PyQt6")

from app.qt import windows  # noqa: E402

ROW4 = ("youtube-downloader", "youtube-preview", "koe")
# The modules live in the private repo, laid over this tree: a public checkout has none, and every door hides (the
# last test's case). The rules themselves are proven where the modules are.
needs = {m: pytest.mark.skipif(not windows.module_present(m), reason=f"modules/{m} is not in this checkout")
         for m in ("koe", "youtube_downloader")}


def _door(name):
    return next(op for op in windows.OPENERS if op.name == name)


def test_row_4s_doors_are_registered_with_their_modules():
    assert [op.name for op in windows.OPENERS if op.name in ROW4] == list(ROW4)
    assert {_door(n).module for n in ROW4} == {"youtube_downloader", "koe"}
    assert all(_door(n).label and _door(n).tip for n in ROW4)


@needs["koe"]
@pytest.mark.parametrize("settings, shown", [
    ({}, False),                                     # not revealed: no door, whatever else is set
    ({"enable_koe": False}, False),                  # revealed, switched off
    ({"enable_koe": True}, True),
])
def test_speech_shows_only_once_revealed_and_switched_on(settings, shown):
    assert windows.available(_door("koe"), settings, "ja") is shown


@needs["youtube_downloader"]
@pytest.mark.parametrize("name, key", [("youtube-downloader", "enable_youtube_transcripts"),
                                       ("youtube-preview", "enable_youtube_preview")])
def test_the_youtube_doors_follow_their_switches(name, key):
    assert windows.available(_door(name), {key: True}, "zh") is True
    assert windows.available(_door(name), {key: False}, "ja") is False
    assert windows.available(_door(name), {}, "ja") is False


@pytest.mark.parametrize("name", ROW4)
def test_a_door_hides_when_its_module_is_absent(name, monkeypatch):
    monkeypatch.setattr(windows, "module_present", lambda module: False)
    everything = {"enable_koe": True, "enable_youtube_transcripts": True, "enable_youtube_preview": True}
    assert windows.available(_door(name), everything, "ja") is False


@needs["koe"]
def test_deciding_speechs_door_reads_no_file(monkeypatch):
    # The reveal rule is read off the settings service's copy (the reveal key has no default), never settings.json.
    import builtins
    import modules.koe.koe_view  # noqa: F401  (imported first: only the decision is watched)
    real_open = builtins.open

    def no_file(*a, **k):
        raise AssertionError(f"a file was read: {a[0]}")
    monkeypatch.setattr(builtins, "open", no_file)
    try:
        assert windows.available(_door("koe"), {"enable_koe": True}, "ja") is True
    finally:
        monkeypatch.setattr(builtins, "open", real_open)
