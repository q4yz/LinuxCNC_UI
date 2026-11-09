"""Windows has no ``fcntl``: camera detection must still import (the
machine backend failed to start there) and simply find no V4L2 nodes."""
from __future__ import annotations

import builtins
import importlib
import sys


def test_imports_and_degrades_without_fcntl(monkeypatch):
    real = builtins.__import__

    def no_fcntl(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("No module named 'fcntl'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_fcntl)
    monkeypatch.delitem(sys.modules, "fcntl", raising=False)
    import services.camera.camera_detection as detection

    try:
        reloaded = importlib.reload(detection)
        assert reloaded.fcntl is None
        assert reloaded._query_capabilities("/dev/video0") is None
    finally:
        monkeypatch.undo()
        importlib.reload(detection)
