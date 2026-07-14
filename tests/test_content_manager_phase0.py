"""Phase 0 of the Content Manager redesign (see docs/Content_Manager_Redesign_Spec.md).

Covers the two behavior changes that de-risk the later phases:
  1. Samples are ON-DEMAND: ensure_data_setup no longer auto-seeds; seed_samples() does it explicitly.
  2. The splicer can also drop its output into a chosen tier (in addition to Processed).

Dest paths (data / User Files) are redirected to a temp dir; the SOURCE samples stay the real
bundled `samples/` (via the un-patched get_resource), so seeding is exercised against real files.
"""

import os
from types import SimpleNamespace

from app import path_utils


def _isolate_dest(monkeypatch, root):
    """Point get_data_path / get_user_files_path at a temp root (leaves get_resource = real samples)."""
    monkeypatch.setattr("app.path_utils.get_data_path",
                        lambda language=None: os.path.join(str(root), "data", language) if language
                        else os.path.join(str(root), "data"))
    monkeypatch.setattr("app.path_utils.get_user_files_path",
                        lambda language=None: os.path.join(str(root), "User Files", language) if language
                        else os.path.join(str(root), "User Files"))


def test_ensure_data_setup_creates_empty_folders_without_seeding(tmp_path, monkeypatch):
    """ensure_data_setup makes the tier folders but must NOT auto-copy samples anymore, so a new
    user starts with a genuinely empty library (and the empty-state onboarding can appear)."""
    _isolate_dest(monkeypatch, tmp_path)
    path_utils.ensure_data_setup("ja")
    data = tmp_path / "data" / "ja"
    for tier in ("HighPriority", "LowPriority", "GoalContent"):
        assert (data / tier).is_dir(), f"{tier} folder should be created"
        assert list((data / tier).iterdir()) == [], f"{tier} must NOT be auto-seeded with samples"


def test_seed_samples_copies_bundled_samples_into_empty_tiers(tmp_path, monkeypatch):
    """The explicit 'Test with samples' path: seed_samples copies the real bundled ja samples in."""
    _isolate_dest(monkeypatch, tmp_path)
    path_utils.ensure_data_setup("ja")
    copied = path_utils.seed_samples("ja")
    high = tmp_path / "data" / "ja" / "HighPriority"
    assert copied > 0, "should copy the bundled ja samples"
    assert any(high.iterdir()), "HighPriority should now contain sample files"


def test_seed_samples_does_not_clobber_existing_content(tmp_path, monkeypatch):
    """Belt-and-suspenders: a tier that already has content is left untouched (only empty tiers seed)."""
    _isolate_dest(monkeypatch, tmp_path)
    path_utils.ensure_data_setup("ja")
    high = tmp_path / "data" / "ja" / "HighPriority"
    (high / "mine.txt").write_text("私の内容。", encoding="utf-8")
    path_utils.seed_samples("ja")
    assert {p.name for p in high.iterdir()} == {"mine.txt"}, "a non-empty tier must not be seeded"


def test_splicer_copies_output_into_target_tier(tmp_path, monkeypatch):
    """--tier: after writing to Processed/<base>, the splicer also drops the output into the tier
    (both), so spliced content becomes part of the library, not just staged."""
    from app import epub_importer
    monkeypatch.setattr("app.epub_importer.get_data_path",
                        lambda language=None: os.path.join(str(tmp_path), "data", language))
    processed = tmp_path / "data" / "ja" / "Processed" / "MyBook"
    processed.mkdir(parents=True)
    (processed / "MyBook_01.txt").write_text("冒険する。", encoding="utf-8")
    fake = SimpleNamespace(target_tier="HighPriority",
                           processed_dir=str(tmp_path / "data" / "ja" / "Processed"), language="ja")
    assert epub_importer.FileImporterApp._copy_output_to_tier(fake, "MyBook") is True
    assert (tmp_path / "data" / "ja" / "HighPriority" / "MyBook" / "MyBook_01.txt").is_file()
    assert (processed / "MyBook_01.txt").is_file(), "the Processed copy must remain (both)"


def test_splicer_no_tier_is_a_noop(tmp_path):
    """Standalone use (no --tier) leaves Processed as the only output."""
    from app import epub_importer
    fake = SimpleNamespace(target_tier=None, processed_dir=str(tmp_path), language="ja")
    assert epub_importer.FileImporterApp._copy_output_to_tier(fake, "X") is False
