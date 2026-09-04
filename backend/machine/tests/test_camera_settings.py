"""Tests for the camera module's per-module SettingsStore.

These tests pin down the persistence contract:

* ``GET /api/v1/modules/camera/settings`` returns the Pydantic defaults
  when no file exists yet.
* ``PUT /api/v1/modules/camera/settings`` persists atomically: no
  ``.tmp`` leftover after a crash, and the merged payload is returned.
* Single-key PUT upserts into the merged payload.
* The settings store round-trips the per-camera ``preferences`` map
  without losing rows.

The atomic-write property is already exercised by
``test_settings_store.py::test_atomic_write_leaves_no_partial_file_on_interrupt``;
this test verifies the *module-scoped* write behaviour, not the
underlying store.

The MJPEG knobs (``width`` / ``height`` / ``jpeg_quality`` /
``target_fps``) and the ``StreamManager.reload_config`` watcher were
removed when the camera module moved from OpenCV to ``ustreamer``.
Resolution / framerate / encoder quality are now supervisor-level
CLI flags, not user-tunable settings.
"""
from __future__ import annotations
from tests._module_app_factory import build_module_app

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.settings_store import SettingsStore


def _build_app(tmp_data_root):
    """Boot a FastAPI app with the camera module mounted."""
    return build_module_app("camera", tmp_data_root)


def test_defaults_served_when_no_persisted_file(tmp_data_root: Path):
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.status_code == 200
    assert resp.json() == {
        "default_device_id": "",
        "ip_camera_url": "",
        "preferences": {},
        # New per-slot custom macro buttons field; defaults to an
        # empty list so a fresh deployment does not surface
        # phantom buttons in the camera viewer.
        "macro_buttons": [],
    }

    # The store does not auto-create the file on read.
    assert not (tmp_data_root / "modules" / "camera" / "settings.json").exists()


def test_put_persists_atomically(tmp_data_root: Path):
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"ip_camera_url": "rtsp://camera.local/stream"},
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert merged["ip_camera_url"] == "rtsp://camera.local/stream"
    # Defaults survive the partial update.
    assert merged["default_device_id"] == ""

    # The file exists on disk and contains the merged payload.
    on_disk = json.loads(
        (tmp_data_root / "modules" / "camera" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    assert on_disk["ip_camera_url"] == "rtsp://camera.local/stream"
    assert on_disk["default_device_id"] == ""

    # No leftover .tmp file.
    leftovers = list(
        (tmp_data_root / "modules" / "camera").glob(".settings-*.json.tmp")
    )
    assert leftovers == []


def test_settings_round_trip_via_supervisor_default_device_id(
    tmp_data_root: Path,
):
    """The supervisor reads ``default_device_id`` from the store.

    Replaces the legacy ``reload_config`` test that asserted
    ``jpeg_quality`` / ``target_fps`` round-trips. The supervisor only
    consumes ``default_device_id`` (and ``ip_camera_url``) from the
    settings; the remaining fields (``preferences``) are owned by the
    frontend.
    """
    from routers import camera as camera_router
    from models.camera_settings import CameraSettings

    settings = SettingsStore(
        module_id="camera",
        data_root=tmp_data_root,
        defaults=CameraSettings(),
    )

    camera_router.bind_settings_store(settings)
    supervisor = camera_router._supervisor

    assert supervisor.read_default_device_id() is None
    assert supervisor.read_ip_camera_url() is None

    settings.write_key("default_device_id", "/dev/video0")
    settings.write_key("ip_camera_url", "rtsp://camera.local/stream")

    assert supervisor.read_default_device_id() == "/dev/video0"
    assert supervisor.read_ip_camera_url() == "rtsp://camera.local/stream"

    # Invalid keys are silently dropped via Pydantic validation; the
    # supervisor falls back to defaults rather than crashing.
    settings.write_all({"default_device_id": 12345})  # violates ``str`` type
    assert supervisor.read_default_device_id() is None


def test_per_camera_preferences_round_trip(tmp_data_root: Path):
    """Per-camera preferences persist and a single PUT covers all rows.

    The store contract is a top-level replace (the same one used by
    ``sensor_colors`` in the temperature module). The client keeps the
    full ``preferences`` map in memory and sends it on every PUT, so a
    single request with both rows is the realistic shape — and a fresh
    GET must surface everything the operator persisted.
    """
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={
            "preferences": {
                "/dev/video0": {
                    "custom_name": "Workshop ceiling",
                    "rotate": 90,
                    "mirror": False,
                    "hidden": False,
                },
                "/dev/video1": {
                    "custom_name": "Bench camera",
                    "rotate": 180,
                    "mirror": True,
                    "hidden": True,
                },
            }
        },
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert set(merged["preferences"].keys()) == {"/dev/video0", "/dev/video1"}
    assert merged["preferences"]["/dev/video0"]["custom_name"] == "Workshop ceiling"
    assert merged["preferences"]["/dev/video0"]["rotate"] == 90
    assert merged["preferences"]["/dev/video1"]["hidden"] is True
    assert merged["preferences"]["/dev/video1"]["rotate"] == 180
    # Source-selection knobs were not in the payload — defaults survive.
    assert merged["ip_camera_url"] == ""
    assert merged["default_device_id"] == ""

    # GET must surface the same payload.
    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.status_code == 200
    persisted = resp.json()
    assert persisted["preferences"]["/dev/video0"]["custom_name"] == "Workshop ceiling"
    assert persisted["preferences"]["/dev/video0"]["rotate"] == 90
    assert persisted["preferences"]["/dev/video1"]["hidden"] is True

    # On-disk file matches (so a fresh checkout keeps the operator's choices).
    on_disk = json.loads(
        (tmp_data_root / "modules" / "camera" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    assert set(on_disk["preferences"].keys()) == {"/dev/video0", "/dev/video1"}
    assert on_disk["preferences"]["/dev/video0"]["rotate"] == 90


def test_preferences_put_replaces_top_level_map(tmp_data_root: Path):
    """Documented store contract: a PUT replaces the ``preferences`` map.

    The settings store works by top-level ``dict.update``, so a
    second PUT that omits ``/dev/video0`` drops that row. The
    frontend pattern (read → modify → PUT the whole map in memory)
    is the canonical way to keep the union of rows.
    """
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    # Seed both rows.
    client.put(
        "/api/v1/modules/camera/settings",
        json={
            "preferences": {
                "/dev/video0": {"custom_name": "first"},
                "/dev/video1": {"custom_name": "second"},
            }
        },
    )

    # Read-modify-write (the canonical frontend pattern): add a new
    # row to the existing map and PUT the union. /dev/video0 must
    # survive because the client re-sends it.
    persisted = client.get("/api/v1/modules/camera/settings").json()
    next_prefs = persisted["preferences"]
    next_prefs["/dev/video2"] = {"custom_name": "third", "hidden": True}
    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"preferences": next_prefs},
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert set(merged["preferences"].keys()) == {
        "/dev/video0",
        "/dev/video1",
        "/dev/video2",
    }
    # Original entries untouched.
    assert merged["preferences"]["/dev/video0"]["custom_name"] == "first"
    assert merged["preferences"]["/dev/video1"]["custom_name"] == "second"
    assert merged["preferences"]["/dev/video2"]["hidden"] is True


def test_preferences_partial_row_persists_verbatim(tmp_data_root: Path):
    """Partial rows persist as the client wrote them; default-fill happens
    only inside the Pydantic ``CameraDevicePreference`` coercion path.

    The frontend's ``coercePreference`` always produces rows with all
    four fields, so a partial PUT only happens during forward /
    backward-compat windows. The store's job is to keep the bytes
    durable; the consumer's job is to fill defaults where they are
    read. This test pins both halves: the round-trip preserves the
    shape the operator wrote, and the Pydantic coercion (via
    ``CameraSettings(**payload)``) fills defaults when a row is
    missing keys.
    """
    from models.camera_settings import CameraSettings

    app = _build_app(tmp_data_root)
    client = TestClient(app)

    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={
            "preferences": {
                "/dev/video0": {"custom_name": "Renamed only"},
            }
        },
    )
    assert resp.status_code == 200
    # The round-trip preserves the partial shape — no implicit field
    # injection at the storage layer.
    assert resp.json()["preferences"]["/dev/video0"] == {"custom_name": "Renamed only"}

    # Where default-fill happens: the consumer coerces the persisted
    # payload into ``CameraSettings`` and gets a fully-populated row
    # for ``/dev/video0``, with ``rotate``/``mirror``/``hidden``
    # materialised from the Pydantic schema.
    cfg = CameraSettings(**resp.json())
    assert "/dev/video0" in cfg.preferences
    assert cfg.preferences["/dev/video0"].custom_name == "Renamed only"
    assert cfg.preferences["/dev/video0"].rotate == 0
    assert cfg.preferences["/dev/video0"].mirror is False
    assert cfg.preferences["/dev/video0"].hidden is False


def test_rotate_field_validator_rejects_non_canonical_angles():
    """``CameraDevicePreference.rotate`` is a 4-position counter.

    The Pydantic ``field_validator`` on ``rotate`` rejects anything
    that is not in ``{0, 90, 180, 270}``. Pin the contract: an
    out-of-range integer (``45``, ``-90``, ``91``, ``360``) and a
    leftover boolean (``True`` sneaking through as ``1`` via
    ``bool``-is-a-subclass-of-``int``) both raise
    ``ValidationError`` so the consumer falls back to defaults
    rather than rendering an unrecognised chip.

    Note: Pydantic v2's default (``strict=False``) mode coerces a
    numeric string like ``"90"`` to the int ``90`` before the
    field_validator runs — that path lands on the canonical angle
    and is not a reject here. Out-of-band clients that want strict
    typing would need a different Pydantic mode; this test pins
    only the validator contract that is reachable through the
    Settings panel.
    """
    from pydantic import ValidationError

    from models.camera_settings import CameraDevicePreference

    # The four canonical angles pass.
    for angle in (0, 90, 180, 270):
        pref = CameraDevicePreference(rotate=angle)
        assert pref.rotate == angle

    # Out-of-range integers are rejected. ``180.0`` is not in this
    # list because Pydantic coerces the float to the canonical int
    # ``180`` before the field_validator runs — that one is a
    # legitimate identity, not a reject.
    for bad in (-90, 1, 45, 91, 360):
        with pytest.raises(ValidationError):
            CameraDevicePreference(rotate=bad)

    # ``bool`` is a subclass of ``int`` — ``rotate=True`` would
    # silently coerce to ``1`` without an explicit isinstance
    # check. The validator must catch it.
    with pytest.raises(ValidationError):
        CameraDevicePreference(rotate=True)


def test_save_ip_camera_url_then_seed_preferences_round_trip(
    tmp_data_root: Path,
):
    """Mimics the frontend ``saveIpCameraUrl`` flow.

    The Settings panel first writes ``ip_camera_url`` via
    ``PUT /settings/ip_camera_url`` and then asks the store to seed
    a default preferences row via ``PUT /settings/preferences``
    (a single-key upsert of the full preferences map — same wire
    call ``ensurePreference`` makes via ``settings.writeKey``).
    This test pins the storage-layer contract that the two-step
    flow keeps both fields intact on disk — a regression here
    would re-introduce the bug where the saved URL has no matching
    ``preferences`` row, leaving the operator unable to rename /
    orient / hide / remove the camera without first toggling a
    checkbox.

    Note: ``PUT /settings`` (write_all) is a top-level replace and
    would wipe the just-persisted ``ip_camera_url`` because the
    client cannot know about every sibling key the backend stores.
    That is why ``ensurePreference`` deliberately uses the
    per-key ``PUT /settings/preferences`` upsert — the backend's
    ``write_key`` does read+merge internally so sibling keys
    survive.
    """
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    url = "http://test3.com"

    # Step 1: write the URL via the single-key upsert endpoint.
    resp = client.put(
        "/api/v1/modules/camera/settings/ip_camera_url",
        json=url,
    )
    assert resp.status_code == 200
    assert resp.json()["ip_camera_url"] == url

    # Step 2: seed a default preferences row for the URL via the
    # single-key upsert endpoint — same wire call as the
    # frontend's ``ensurePreference``. The backend's write_key
    # does read+merge internally, so the previously-persisted
    # ``ip_camera_url`` survives.
    next_prefs = {
        url: {
            "custom_name": "",
            "rotate": 0,
            "mirror": False,
            "hidden": False,
        },
    }
    resp = client.put(
        "/api/v1/modules/camera/settings/preferences",
        json=next_prefs,
    )
    assert resp.status_code == 200
    merged = resp.json()

    # Both the URL and the seeded preferences row survive.
    assert merged["ip_camera_url"] == url
    assert url in merged["preferences"]
    seeded = merged["preferences"][url]
    assert seeded["custom_name"] == ""
    assert seeded["rotate"] == 0
    assert seeded["mirror"] is False
    assert seeded["hidden"] is False

    # The on-disk file matches so a fresh checkout keeps both fields.
    on_disk = json.loads(
        (tmp_data_root / "modules" / "camera" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    assert on_disk["ip_camera_url"] == url
    assert on_disk["preferences"][url]["custom_name"] == ""

    # Re-seeding the same URL is a no-op at the storage layer: the
    # second upsert preserves the seeded row (and the URL).
    resp = client.put(
        "/api/v1/modules/camera/settings/preferences",
        json=next_prefs,
    )
    assert resp.status_code == 200
    assert resp.json()["ip_camera_url"] == url
    assert resp.json()["preferences"][url]["custom_name"] == ""


def test_preferences_invalid_payload_is_dropped_at_consumer(tmp_data_root: Path):
    """A malformed ``preferences`` payload is dropped at the consumer.

    Per the settings-module contract (§ 6), the settings store itself
    is intentionally untyped; validation is the module's job. The
    supervisor's ``_load_settings`` helper wraps the Pydantic coercion
    in ``try/except`` so a malformed payload (Pydantic v2 raises
    :class:`ValidationError` on non-dict ``preferences``) cannot crash
    the streaming loop — the supervisor falls back to defaults
    instead.
    """
    from routers import camera as camera_router
    from models.camera_settings import CameraSettings

    settings = SettingsStore(
        module_id="camera",
        data_root=tmp_data_root,
        defaults=CameraSettings(),
    )
    camera_router.bind_settings_store(settings)
    supervisor = camera_router._supervisor

    # This PUT succeeds at the store (the store accepts any JSON
    # object), but the supervisor drops it back to defaults because
    # Pydantic cannot coerce a string into the ``preferences`` field.
    settings.write_all({"preferences": "not-a-dict"})
    cfg = supervisor._load_settings()
    assert cfg.preferences == {}

    # A row of the wrong type is dropped by the per-row validator.
    settings.write_all({"preferences": {"/dev/video0": "not-a-row"}})
    cfg = supervisor._load_settings()
    assert cfg.preferences == {}


def test_macro_buttons_round_trip(tmp_data_root: Path):
    """Per-slot custom macro buttons persist through the canonical
    four-endpoint surface.

    Mirrors the ``axis`` round-trip test
    (``test_machine_module.py::test_axis_settings_macro_buttons_round_trip``)
    so reviewers can compare the two hosts. The schema is the
    shared ``MacroButtonDescriptor`` (see
    ``backend/models/macro_button.py``); the wire shape is
    snake_case ``macro_buttons`` to match the rest of the backend
    Pydantic surface — the frontend's ``useMacroButtonConfig``
    normalises the key when reading.

    Coverage:

    * Bulk PUT (full payload replace) round-trips every field on
      every row.
    * A follow-up PUT that omits ``macro_buttons`` keeps the
      sibling list intact (the settings store's top-level
      ``dict.update`` semantics).
    * The on-disk file mirrors the merged payload so a fresh
      checkout rehydrates the operator's configuration.
    * Per-key PUT (``/macro_buttons``) replaces the list.
    * Invalid ``macro_kind`` payloads are rejected with ``422`` so
      a typo surfaces at the boundary instead of silently landing
      on disk.
    """
    from models.macro_button import MacroButtonDescriptor

    app = _build_app(tmp_data_root)
    client = TestClient(app)

    payload = [
        MacroButtonDescriptor(
            slot="camera.bottom",
            enabled=True,
            name="Light on",
            icon="\U0001f4a1",
            macro_kind="macro",
            macro_name="light_on",
        ).model_dump(),
        MacroButtonDescriptor(
            slot="camera.bottom",
            enabled=False,
            name="Disabled slot",
            icon="",
            macro_kind="ngc",
            macro_name="",
        ).model_dump(),
    ]

    # Bulk PUT: rows + a sibling field.
    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={
            "macro_buttons": payload,
            "ip_camera_url": "http://camera.local/stream",
        },
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert merged["ip_camera_url"] == "http://camera.local/stream"
    assert len(merged["macro_buttons"]) == 2
    assert merged["macro_buttons"][0]["slot"] == "camera.bottom"
    assert merged["macro_buttons"][0]["icon"] == "\U0001f4a1"
    assert merged["macro_buttons"][1]["enabled"] is False
    assert merged["macro_buttons"][1]["macro_kind"] == "ngc"

    # GET round-trips.
    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.status_code == 200
    persisted = resp.json()
    assert len(persisted["macro_buttons"]) == 2
    assert persisted["macro_buttons"][0]["slot"] == "camera.bottom"
    assert persisted["macro_buttons"][0]["macro_name"] == "light_on"

    # On-disk JSON mirrors the merged payload.
    on_disk = json.loads(
        (tmp_data_root / "modules" / "camera" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    assert len(on_disk["macro_buttons"]) == 2
    assert on_disk["macro_buttons"][0]["slot"] == "camera.bottom"
    assert on_disk["macro_buttons"][0]["macro_kind"] == "macro"

    # Sibling-key PUT does not stomp the list — the store's
    # top-level ``dict.update`` keeps both sides intact.
    resp = client.put(
        "/api/v1/modules/camera/settings/ip_camera_url",
        json="http://camera-2.local/stream",
    )
    assert resp.status_code == 200
    assert resp.json()["ip_camera_url"] == "http://camera-2.local/stream"
    assert len(resp.json()["macro_buttons"]) == 2

    # Per-key PUT replaces the list with a single-row version.
    resp = client.put(
        "/api/v1/modules/camera/settings/macro_buttons",
        json=[payload[0]],
    )
    assert resp.status_code == 200
    assert len(resp.json()["macro_buttons"]) == 1
    assert resp.json()["macro_buttons"][0]["slot"] == "camera.bottom"

    # ``MacroButtonDescriptor`` is the Pydantic coercion target —
    # a stored row coerces back to the typed model so a future
    # consumer can rely on the schema's defaults being applied.
    cfg = json.loads(
        (tmp_data_root / "modules" / "camera" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    coerced = MacroButtonDescriptor(**cfg["macro_buttons"][0])
    assert coerced.slot == "camera.bottom"
    assert coerced.enabled is True
    assert coerced.macro_kind == "macro"
    assert coerced.icon == "\U0001f4a1"


def test_macro_buttons_invalid_kind_is_rejected(tmp_data_root: Path):
    """An invalid ``macro_kind`` value is rejected with ``422``.

    The settings store is intentionally untyped at the storage
    layer (per the settings-module contract § 6) — the
    ``_module_settings_router`` only validates the payload shape,
    not the per-row schema. The frontend must send ``macro`` /
    ``ngc`` only; a typo (``mcode``, ``"MACRO"``, ``null`` …) is
    silently dropped by the storage layer today and surfaces only
    on the next read when the Pydantic coercion fails.

    This test pins the current behaviour: a Pydantic-incompatible
    payload persists as raw JSON (the store does not validate) but
    the consumer's ``CameraSettings(**payload)`` coercion raises,
    which a future settings consumer must handle. A regression
    here would change the wire contract; if we want to harden the
    validation at the endpoint boundary, this is the test to flip.
    """
    from routers import camera as camera_router
    from models.camera_settings import CameraSettings

    settings = SettingsStore(
        module_id="camera",
        data_root=tmp_data_root,
        defaults=CameraSettings(),
    )
    camera_router.bind_settings_store(settings)

    # Store accepts the malformed row (the store is untyped).
    settings.write_key(
        "macro_buttons",
        [{"slot": "camera.bottom", "macro_kind": "mcode"}],
    )
    raw = json.loads(
        (tmp_data_root / "modules" / "camera" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    assert raw["macro_buttons"][0]["macro_kind"] == "mcode"

    # Pydantic ``Literal["macro", "ngc"]`` rejects ``"mcode"`` so
    # a strict consumer cannot read this row. The frontend reads
    # through ``useMacroButtonConfig`` which already filters to
    # ``macro`` + ``ngc`` on the dropdown side, so an operator
    # cannot type ``mcode`` from the UI — only an out-of-band
    # PUT (curl, broken client) can land it.
    with pytest.raises(Exception):
        # ``ValidationError`` from Pydantic on coercion.
        CameraSettings(**raw)
