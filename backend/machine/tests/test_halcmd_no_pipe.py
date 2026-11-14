"""``halcmd show`` never writes into a pipe (2026-11-12 hang).

halcmd holds the HAL mutex while it prints; into a full pipe (> 64 KiB)
it blocks holding it, while ``hal.get_value()`` spins on that mutex
holding the GIL, so the thread that would drain the pipe never runs and
the whole backend hangs. ``HalPinSignalService.halcmd_show`` gives
halcmd a regular file instead."""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

import services.HalPinSignalService as module

BACKEND = Path(__file__).resolve().parents[2]

# A fake halcmd: refuses to print into anything but a regular file, then
# prints far more than a pipe buffer holds.
FAKE_HALCMD = r"""#!/usr/bin/env python3
import os, stat, sys
if not stat.S_ISREG(os.fstat(1).st_mode):
    sys.stderr.write("stdout is not a regular file\n")
    sys.exit(3)
what = sys.argv[2]
for k in range(4000):  # ~200 KiB
    if what == "pin":
        print(f"    5  float IN          {k}.0  comp-{k:05d}.some-long-pin-name-in")
    else:
        print(f"float  {k}.0  sig-{k:05d}")
"""


@pytest.fixture
def fake_halcmd(tmp_path, monkeypatch):
    path = tmp_path / "halcmd"
    path.write_text(FAKE_HALCMD)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return path


def test_halcmd_show_reads_a_listing_bigger_than_a_pipe(fake_halcmd):
    out = module.halcmd_show("pin", timeout_s=20)
    lines = out.splitlines()
    assert len(out) > 64 * 1024 and len(lines) == 4000
    assert lines[-1].endswith("comp-03999.some-long-pin-name-in")


def test_pins_come_from_the_file_listing(fake_halcmd):
    pins = module.HalPinSignalService()._read_pins_from_linuxcnc()
    assert len(pins) == 4000


def test_stdout_is_never_a_pipe(monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append(kwargs)
        kwargs["stdout"].write("")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(module.subprocess, "run", run)
    module.halcmd_show("sig")
    assert calls and calls[0]["stdout"] not in (subprocess.PIPE, None)
    assert calls[0].get("timeout")


def test_no_failure_falls_back_to_the_mock(monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.HalPinSignalService()._read_pins_from_linuxcnc() == module._mock_pins()


def test_no_halcmd_show_through_a_pipe_anywhere():
    """check_output / capture_output / stdout=PIPE with ``halcmd show``."""
    piped = re.compile(r"check_output|capture_output|stdout\s*=\s*subprocess\.PIPE|Popen")
    offenders = []
    for path in BACKEND.rglob("*.py"):
        if "tests" in path.parts or "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"[^\n]*\n?[^\n]*halcmd[^\n]*\n?[^\n]*", text):
            if '"show"' in match.group(0) and piped.search(match.group(0)):
                offenders.append(f"{path.relative_to(BACKEND)}: {match.group(0).strip()[:80]}")
    assert offenders == []
