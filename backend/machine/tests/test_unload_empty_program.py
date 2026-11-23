"""Unloading loads nc_files/EmptyProgram.ngc: it must be a program LinuxCNC
accepts — an empty file fails with "File ended with no percent sign (%)"
and "can't open"."""
from __future__ import annotations

from pathlib import Path

from domain_file_services.ProgramFileService import ProgramFileService


def test_a_missing_empty_program_is_written(tmp_path: Path):
    service = ProgramFileService(root=tmp_path)
    path = service.ensure_empty_program()
    assert path == tmp_path / "EmptyProgram.ngc"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("%\n") and text.rstrip().endswith("%"), "%-delimited"


def test_an_empty_or_edited_one_is_repaired(tmp_path: Path):
    service = ProgramFileService(root=tmp_path)
    (tmp_path / "EmptyProgram.ngc").write_text("", encoding="utf-8")
    assert service.ensure_empty_program().read_text(encoding="utf-8") == ProgramFileService.EMPTY_PROGRAM_TEXT
    (tmp_path / "EmptyProgram.ngc").write_text("G0 X100\n", encoding="utf-8")
    assert service.ensure_empty_program().read_text(encoding="utf-8") == ProgramFileService.EMPTY_PROGRAM_TEXT


def test_the_shipped_one_is_valid():
    shipped = Path(__file__).resolve().parents[3] / "nc_files" / "EmptyProgram.ngc"
    assert shipped.read_text(encoding="utf-8") == ProgramFileService.EMPTY_PROGRAM_TEXT


def test_unload_uses_it():
    import inspect

    from routers import program

    assert "get_program_service().ensure_empty_program()" in inspect.getsource(program.unload_program)
