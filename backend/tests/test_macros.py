"""Tests for :class:`backend.macros.service.MacroFileService`.

Covers the full CRUD lifecycle plus the small set of edge cases the
issue calls out: name/suffix validation, lazy directory creation,
and list ordering. Atomic writes are exercised through the public
``write_macro`` API; the underlying ``tempfile`` + ``fsync`` +
``os.replace`` machinery is the same pattern as
``core.settings_store`` (``LESSONS_LEARNED §3.4``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.macros import MacroFileService, MacroNotFoundError
from backend.macros.service import MACRO_SUFFIX


@pytest.fixture()
def macro_service(tmp_path: Path) -> MacroFileService:
    """A fresh ``MacroFileService`` rooted at a per-test temp directory."""
    return MacroFileService(storage_dir=tmp_path)


# ---------------------------------------------------------------------- #
# Lifecycle                                                              #
# ---------------------------------------------------------------------- #


def test_full_crud_lifecycle(macro_service: MacroFileService, tmp_path: Path) -> None:
    """write → list → read → overwrite → delete → delete-again."""
    macro_service.write_macro("hello", "G0 X0\n")
    macro_service.write_macro("world", "G0 X10\n")

    listed = macro_service.list_macros()
    # Names come back without the suffix and sorted.
    assert listed == ["hello", "world"]

    assert macro_service.read_macro("hello") == "G0 X0\n"
    assert macro_service.read_macro("world") == "G0 X10\n"

    # Overwrite the first macro and confirm the new content sticks.
    macro_service.write_macro("hello", "G0 X99\n")
    assert macro_service.read_macro("hello") == "G0 X99\n"
    assert macro_service.list_macros() == ["hello", "world"]

    # Delete one macro; the other survives.
    macro_service.delete_macro("hello")
    assert macro_service.list_macros() == ["world"]

    # Deleting a second time raises ``MacroNotFoundError`` (and still
    # surfaces as ``FileNotFoundError`` so generic handlers work).
    with pytest.raises(MacroNotFoundError):
        macro_service.delete_macro("hello")
    with pytest.raises(FileNotFoundError):
        macro_service.delete_macro("hello")


def test_on_disk_files_keep_macro_suffix(
    macro_service: MacroFileService, tmp_path: Path
) -> None:
    """The filesystem layer always sees the ``.macro`` extension."""
    macro_service.write_macro("alpha", "G0 X1\n")
    macro_service.write_macro("beta", "G0 X2\n")

    on_disk = sorted(p.name for p in tmp_path.iterdir())
    assert on_disk == ["alpha.macro", "beta.macro"]


def test_write_macro_suffix_is_idempotent(
    macro_service: MacroFileService,
) -> None:
    """Passing ``"foo.macro"`` normalises to ``"foo"`` (no double suffix)."""
    macro_service.write_macro("foo.macro", "G0 X0\n")
    assert macro_service.list_macros() == ["foo"]
    assert macro_service.read_macro("foo") == "G0 X0\n"


# ---------------------------------------------------------------------- #
# Listing                                                                #
# ---------------------------------------------------------------------- #


def test_list_returns_empty_when_directory_is_missing(tmp_path: Path) -> None:
    """``list_macros`` does not crash when the directory does not exist yet."""
    nested = tmp_path / "does" / "not" / "exist"
    service = MacroFileService(storage_dir=nested)

    assert service.list_macros() == []


def test_list_orders_names_alphabetically(
    macro_service: MacroFileService,
) -> None:
    """Insertion order does not matter; output is always sorted."""
    for name in ["charlie", "alpha", "bravo"]:
        macro_service.write_macro(name, f"payload-{name}\n")

    assert macro_service.list_macros() == ["alpha", "bravo", "charlie"]


def test_list_ignores_non_macro_files(
    macro_service: MacroFileService, tmp_path: Path
) -> None:
    """Stray files without the ``.macro`` suffix never appear in the list."""
    macro_service.write_macro("real", "G0 X0\n")

    # Drop a few neighbours directly on disk to mimic editor backups
    # or accidental drops. They must not show up in the listing.
    (tmp_path / "README").write_text("notes")
    (tmp_path / "real.macro.bak").write_text("backup")
    (tmp_path / ".hidden.macro").write_text("hidden")

    assert macro_service.list_macros() == ["real"]


# ---------------------------------------------------------------------- #
# Read                                                                   #
# ---------------------------------------------------------------------- #


def test_read_missing_macro_raises(macro_service: MacroFileService) -> None:
    with pytest.raises(MacroNotFoundError):
        macro_service.read_macro("ghost")


def test_read_handles_unicode_payload(
    macro_service: MacroFileService,
) -> None:
    """UTF-8 round-trip preserves non-ASCII content."""
    payload = "G0 X0 ; привет 🔧\n"
    macro_service.write_macro("unicode", payload)

    assert macro_service.read_macro("unicode") == payload


# ---------------------------------------------------------------------- #
# Write                                                                  #
# ---------------------------------------------------------------------- #


def test_write_creates_storage_directory_lazily(
    tmp_path: Path,
) -> None:
    """The storage directory is created on first write, not at construction."""
    nested = tmp_path / "deep" / "nested" / "macros"
    assert not nested.exists()

    service = MacroFileService(storage_dir=nested)
    service.write_macro("first", "G0 X0\n")

    assert nested.is_dir()
    assert (nested / f"first{MACRO_SUFFIX}").read_text(encoding="utf-8") == "G0 X0\n"


def test_write_is_atomic_when_replace_fails(
    macro_service: MacroFileService, monkeypatch
) -> None:
    """A failing ``os.replace`` leaves the previous file intact and no temp."""
    macro_service.write_macro("durable", "original\n")
    target = macro_service.storage_dir / f"durable{MACRO_SUFFIX}"
    original_bytes = target.read_bytes()

    # Patch ``os.replace`` so the first call raises. Mirrors the
    # ``SettingsStore`` atomic-write tripwire (``LESSONS_LEARNED §3.4``).
    import backend.macros.service as svc

    real_replace = svc.os.replace
    calls = {"count": 0}

    def boom(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated crash")
        return real_replace(src, dst)

    monkeypatch.setattr(svc.os, "replace", boom)

    with pytest.raises(RuntimeError, match="simulated crash"):
        macro_service.write_macro("durable", "new\n")

    # The original file is still intact (no half-written content).
    assert target.read_bytes() == original_bytes
    # No leftover temp file in the storage directory.
    leftovers = [
        p
        for p in macro_service.storage_dir.iterdir()
        if p.name.startswith(".macro-") and p.name.endswith(".tmp")
    ]
    assert leftovers == []

    # Subsequent writes still succeed.
    macro_service.write_macro("durable", "next\n")
    assert target.read_text(encoding="utf-8") == "next\n"


# ---------------------------------------------------------------------- #
# Delete                                                                 #
# ---------------------------------------------------------------------- #


def test_delete_missing_macro_raises(macro_service: MacroFileService) -> None:
    with pytest.raises(MacroNotFoundError):
        macro_service.delete_macro("never-written")


# ---------------------------------------------------------------------- #
# Validation                                                             #
# ---------------------------------------------------------------------- #


def test_write_rejects_empty_name(macro_service: MacroFileService) -> None:
    with pytest.raises(ValueError):
        macro_service.write_macro("", "G0 X0\n")


def test_read_rejects_empty_name(macro_service: MacroFileService) -> None:
    with pytest.raises(ValueError):
        macro_service.read_macro("")


def test_delete_rejects_empty_name(macro_service: MacroFileService) -> None:
    with pytest.raises(ValueError):
        macro_service.delete_macro("")


def test_write_rejects_non_string_content(macro_service: MacroFileService) -> None:
    with pytest.raises(TypeError):
        macro_service.write_macro("ok", b"G0 X0\n")  # type: ignore[arg-type]


def test_resolve_rejects_non_string_name(macro_service: MacroFileService) -> None:
    with pytest.raises(ValueError):
        macro_service.read_macro(None)  # type: ignore[arg-type]


def test_write_rejects_non_macro_suffix(macro_service: MacroFileService) -> None:
    """Names carrying a non-``.macro`` suffix are rejected so the on-disk
    extension stays strictly ``.macro``."""
    with pytest.raises(ValueError):
        macro_service.write_macro("foo.txt", "G0 X0\n")
    with pytest.raises(ValueError):
        macro_service.write_macro("foo.py", "G0 X0\n")


def test_read_rejects_non_macro_suffix(macro_service: MacroFileService) -> None:
    with pytest.raises(ValueError):
        macro_service.read_macro("foo.txt")


def test_delete_rejects_non_macro_suffix(macro_service: MacroFileService) -> None:
    with pytest.raises(ValueError):
        macro_service.delete_macro("foo.txt")


def test_service_defaults_storage_dir_to_package_directory() -> None:
    """Without arguments, the service points at ``backend/macros/``."""
    service = MacroFileService()
    assert service.storage_dir.name == "macros"
    assert service.storage_dir.is_dir()
