# SPDX-License-Identifier: GPL-3.0-or-later
"""The public surface `app/main.py` is allowed to depend on.

The core reaches this module through exactly two names — `SETTINGS_DEFAULTS` and `open_junban`.
Changing either silently breaks a caller that cannot import this package to check.

The behavioural clauses matter more than the shapes. `SETTINGS_DEFAULTS` is read by
`settings_manager` on EVERY settings load (feature on or off, module bundled or not), so importing
this package must stay cheap; and `open_junban` is a button callback, so it must fail into a
messagebox rather than up into the dashboard's event loop.
"""
import os
import sys
import types
from unittest import mock

import modules.junban as junban

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# --- settings ------------------------------------------------------------------------------------- #
def test_settings_defaults_shape():
    assert isinstance(junban.SETTINGS_DEFAULTS, dict)
    expected = {
        "enable_junban": True,
        "junban_scope": "deck",
        "junban_deck": "",
        "junban_word_fields": {},
        "junban_chunk_size": 150,
        # Junban_Backlog_Spec §11 / §12 — the list's words first, the rest after ("List first").
        "junban_unlisted": "list_first",
        # The panel's "Phrases": a frequent phrase card placed as the list's words are.
        "junban_phrases": True,
        # §17 — "i+1 first": a list card whose own sentence waits for a later list word. Off.
        "junban_ready_first": False,
        # WP-M — which of Surasura's two orders to follow.
        "junban_order": "content",
        # WP-N — the report's own markers, as tags and as a filter.
        "junban_tag_markers": False,
        "junban_only_markers": [],
        # WP-L — the optional card touch-ups.
        "junban_tag": "Surasura",
        "junban_write_frequency": False,
        "junban_frequency_field": "Frequency",
        "junban_write_freqsort": False,
        # Junban_Backlog_Spec §13 — the cards not on the list; none ticked is "No action".
        "junban_later_tag": False,
        "junban_later_flag": False,
        "junban_later_suspend": False,
        "junban_show_tags": True,
        # The automatic reorder, a test option switched on by hand.
        "junban_auto_reorder": False,
        "junban_auto_actions": False,
        # The fast re-plan's preview (E1.1 04 §1): off.
        "junban_replan_preview": False,
        "junban_replan_language": "",
        "junban_replan_deck": "",
        # P1.4-1 — your own cards, with Connect's preview on: a tag of your own, and "order all".
        "junban_own_tag": "",
        "junban_order_all": False,
        # Anki Backfill (Patterns_Spec §17): its window's choices, and its automatic step.
        "junban_backfill_deck": "",
        "junban_backfill_cards": "all",
        "junban_backfill_replace": False,
        "junban_backfill_fills": ["patterns"],
        "junban_backfill_fields": {},
        # Patterns_Chinese_Spec S3: each note type's language, set in the Fields window.
        "junban_backfill_note_languages": {},
        "junban_auto_backfill": False,
    }
    assert junban.SETTINGS_DEFAULTS == expected


def test_backfill_overwrites_nothing_and_runs_nothing_by_default():
    """Replace is off (a filled field stays as the user left it) and the automatic step is off: the
    window writes only after a preview, and only what that preview showed."""
    assert junban.SETTINGS_DEFAULTS["junban_backfill_replace"] is False
    assert junban.SETTINGS_DEFAULTS["junban_auto_backfill"] is False


def test_nothing_that_overwrites_a_note_field_is_on_by_default():
    """WP-L's whole safety argument, pinned.

    A wrong `due` is annoying and comes straight back out of the snapshot. A clobbered note field
    has destroyed something the user wrote, and the snapshot is the only copy — so every touch-up
    that OVERWRITES arrives off. (The extra example sentence, which had no default field, moved to
    Anki Backfill's 例文 on 2026-09-24 — its settings are gone from here.)
    """
    assert junban.SETTINGS_DEFAULTS["junban_write_frequency"] is False
    assert junban.SETTINGS_DEFAULTS["junban_write_freqsort"] is False, \
        "FreqSort is the browser's sort key — it can never default to being overwritten"
    assert not [key for key in junban.SETTINGS_DEFAULTS if key.startswith("junban_sentence")], \
        "the example sentence is Backfill's now"


def test_nothing_happens_to_the_cards_not_on_the_list_by_default():
    """The user's choice (2026-09-23): "No Action" is the default — nothing is tagged, flagged
    or suspended until they tick it. And there is no delete setting at all, by design."""
    assert junban.SETTINGS_DEFAULTS["junban_later_tag"] is False
    assert junban.SETTINGS_DEFAULTS["junban_later_flag"] is False
    assert junban.SETTINGS_DEFAULTS["junban_later_suspend"] is False
    assert not any("delete" in key for key in junban.SETTINGS_DEFAULTS)


def test_the_tag_is_the_only_touch_up_that_starts_on():
    """And it is allowed to, because it is the one that destroys nothing: it ADDS a tag, only to
    notes whose card actually moved, and `Undo the last reorder` takes that exact tag back off
    again — and only from the notes Junban put it on."""
    assert junban.SETTINGS_DEFAULTS["junban_tag"] == "Surasura"


def test_the_feature_is_on_when_the_module_is_bundled():
    """Deliberately NOT opt-in, and safe because the same key gates the build: a build that has
    this module at all is one whose developer switched it on, so the default only ever applies to
    someone who already asked for the feature. Mirrors `enable_youtube_transcripts`.

    Being on still writes nothing by itself — see the test below: the default scope names no deck,
    and every write is behind a preview the user has to look at."""
    assert junban.SETTINGS_DEFAULTS["enable_junban"] is True


def test_nothing_reaches_the_collection_by_default():
    """The defaults must describe a module that, if launched untouched, would write nothing anywhere
    surprising: one nominated deck (empty, so nothing is selected) rather than every deck at once.

    This matters more here than in any other module — a `due` write syncs to AnkiWeb and mobile, and
    AnkiConnect's `setSpecificValueOfCard` hardcodes `skip_undo_entry=True`, so Anki itself offers no
    way back."""
    assert junban.SETTINGS_DEFAULTS["junban_scope"] == "deck", "never default to touching every deck"
    assert junban.SETTINGS_DEFAULTS["junban_deck"] == "", "no deck is nominated until the user picks one"


def test_the_endpoint_is_loopback_only():
    """Invariant I7: Surasura is offline by contract. AnkiConnect is reached on 127.0.0.1 and nowhere
    else — a default pointing off-box would ship a network call in a privacy-respecting app. Junban reads
    the one address every Anki caller reads (`anki_connect.address`, E1.4); its own 2.x key is retired."""
    from app import anki_connect
    from modules.junban import reposition
    assert "junban_url" not in junban.SETTINGS_DEFAULTS
    assert anki_connect.DEFAULT_URL.startswith("http://127.0.0.1:")
    assert reposition._url({}) == anki_connect.DEFAULT_URL


def test_every_setting_is_either_honoured_or_declared_inert():
    """A setting that silently does nothing is worse than a missing one — settings.json says
    otherwise, so the user believes it works.

    At the skeleton stage (WP-B) the package has no transport, planner or panel and the core does not
    know this module exists, so ALL of them are inert and declared. That is the point: each later
    package has to remove its own keys from `NOT_YET_IMPLEMENTED` as it wires them up, and a newly
    added setting has to be either honoured or deliberately declared.
    """
    package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body = []
    for root, dirs, files in os.walk(package):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "vendor", "tests")]
        for name in sorted(files):
            # __init__.py is excluded because it DEFINES the keys — including it would make every
            # setting look honoured.
            if name.endswith(".py") and name != "__init__.py":
                with open(os.path.join(root, name), encoding="utf-8") as handle:
                    body.append(handle.read())
    with open(os.path.join(_ROOT, "app", "main.py"), encoding="utf-8") as handle:
        body.append(handle.read())
    blob = "\n".join(body)

    inert = {key for key in junban.SETTINGS_DEFAULTS if key not in blob}
    assert inert == set(junban.NOT_YET_IMPLEMENTED), (
        f"settings that nothing reads: {sorted(inert)}; "
        f"declared inert: {sorted(junban.NOT_YET_IMPLEMENTED)}")


def test_the_inert_list_only_names_real_settings():
    """A stale entry here would hide a setting that genuinely stopped being read."""
    assert set(junban.NOT_YET_IMPLEMENTED) <= set(junban.SETTINGS_DEFAULTS)


def test_no_key_or_value_looks_like_a_credential():
    """settings.json is read by `packaging/Surasura.spec` at build time and SHIPS with the app, so a
    credential here would be published. AnkiConnect's optional `apiKey` is specifically the one this
    module must never accept as a setting — it belongs in `get_persistent_user_data_path()`, the way
    `modules/koe/keystore.py` holds its own."""
    for key, value in junban.SETTINGS_DEFAULTS.items():
        lowered = key.lower()
        for shape in ("key", "token", "secret"):
            assert shape not in lowered, f"{key} looks like it would hold a credential"
        assert not (isinstance(value, str) and value.startswith("AQ.")), "an API key leaked in"


# --- entry points --------------------------------------------------------------------------------- #
def test_launch_entry_point_is_callable():
    """The core dashboard calls this; it must exist and be callable."""
    assert callable(junban.open_junban)


def test_open_junban_never_raises_past_a_messagebox():
    """A button callback that raises lands as an unhandled traceback in the dashboard's event loop.
    Right now the panel itself does not exist (`gui.py` arrives with WP-H), which is exactly the kind
    of missing piece this has to absorb and report rather than propagate."""
    junban.open_junban(object())        # modals are neutered by conftest's autouse `_no_real_modals`


def test_open_junban_survives_a_panel_that_blows_up():
    """The generic failure path: anything the panel throws on construction (a dead AnkiConnect, a
    missing results CSV, a theme error) becomes a messagebox, never an exception past this function."""
    fake = types.ModuleType("modules.junban.gui")
    fake.JunbanGui = mock.Mock(side_effect=RuntimeError("panel exploded"))
    with mock.patch.dict(sys.modules, {"modules.junban.gui": fake}):
        junban.open_junban(object())    # must not raise


def test_open_junban_caches_the_window_and_focuses_it_the_second_time():
    """Pressing the button twice must focus the open panel, not build a second one over it — two
    panels over one collection is two independent snapshots and two views of the same queue."""
    fake = types.ModuleType("modules.junban.gui")
    window = mock.Mock()
    window.winfo_exists.return_value = True
    fake.JunbanGui = mock.Mock(return_value=window)
    host = types.SimpleNamespace(root="a-tk-root")

    with mock.patch.dict(sys.modules, {"modules.junban.gui": fake}):
        junban.open_junban(host)
        assert host.junban_window is window
        fake.JunbanGui.assert_called_once_with("a-tk-root", app=host)

        junban.open_junban(host)
        fake.JunbanGui.assert_called_once()     # still once — not rebuilt
        window.lift.assert_called_once()


def test_importing_the_package_is_cheap():
    """`settings_manager` imports this package on every settings load just to read
    SETTINGS_DEFAULTS — feature on or off, module bundled or not. If a heavy import escaped to
    module scope, every launch would pay for it. `urllib.request` is on the watch list because this
    module's transport is built on it: it is cheap-ish, but it must still be imported inside the
    functions that talk to AnkiConnect, not at package scope.

    Run in a CLEAN subprocess, mirroring `tests/test_lazy_imports.py`: checking `sys.modules` in this
    process would prove nothing, because pytest and its plugins have already imported half of these
    for their own reasons.
    """
    import subprocess

    watch = ("tkinter", "pandas", "fugashi", "jieba", "urllib.request", "sqlite3",
             "modules.junban.gui", "modules.junban.ankiconnect")
    code = ("import modules.junban; import sys; "
            "print(','.join(m for m in %r if m in sys.modules))" % (watch,))
    env = {**os.environ, "PYTHONPATH": _ROOT, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)

    assert result.returncode == 0, f"importing modules.junban failed:\n{result.stderr}"
    loaded = [m for m in result.stdout.strip().split(",") if m]
    assert loaded == [], f"`import modules.junban` eagerly loaded: {loaded}"
