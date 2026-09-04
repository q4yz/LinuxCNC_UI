"""Nullable-module guarantee for the camera module.

Boot the registry with an empty candidate list (no camera, no anything)
and verify:

* The boot summary log line reads ``mounted=[] skipped=0 missing=0``.
* No errors leak into the log.
* The FastAPI app still starts cleanly — the ``/api/v1/modules/camera``
  prefix returns ``404`` because no router is mounted there, but no
  module code is imported at all.

This is the most important acceptance criterion from Issue #2: the
camera module is *removable* without breaking the rest of the app.
"""
from __future__ import annotations
from tests._module_app_factory import build_module_app

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus

