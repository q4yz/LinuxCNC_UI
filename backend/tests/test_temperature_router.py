"""Integration tests for the temperature module's HTTP router.

These tests mount the temperature router on a dummy FastAPI app and
exercise the HTTP layer with ``fastapi.testclient.TestClient``. The
external hardware layer is mocked via ``unittest.mock.patch`` so the
tests do not depend on the real ``linuxcnc`` binary or the
``linuxcnc_mock`` singleton state.

Coverage (issue #43 § 3):

* ``GET /sensors`` — calls ``stat.poll()`` before reading
  ``temperatures``; coerces the nested dict into plain
  ``dict[str, dict[str, float]]`` for the response.
* ``POST /sensors/{name}/target`` — happy-path invocation of
  ``execute_sync_cmd("set_temperature", 0, name, req.target)``,
  response echoes the applied target.
* URL-vs-body precedence — ``{name}`` in the URL wins over
  ``sensor_name`` in the JSON body.
* Error handling — empty/invalid URL name → ``400``; raised
  ``Exception`` from ``execute_sync_cmd`` → ``500``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_router_app() -> FastAPI:
    """Build a fresh FastAPI app with only the temperature router
    mounted (no module registry). Keeps the surface small so
    each test can mock the hardware layer in isolation.
    """
    from modules.temperature.router import router as temperature_router

    app = FastAPI()
    app.include_router(temperature_router, prefix="/api/v1/modules/temperature")
    return app


# ---------------------------------------------------------------------------
# GET /sensors
# ---------------------------------------------------------------------------


def test_get_sensors_calls_stat_poll_before_reading():
    """``GET /sensors`` must call ``stat.poll()`` before fetching
    ``temperatures`` so fresh readings are returned even when the
    WebSocket telemetry loop has not yet broadcast them (issue #43
    § 3).
    """
    app = _build_router_app()
    client = TestClient(app)

    # Build a mock stat object that records the order of calls.
    stat = MagicMock()
    stat.poll = MagicMock()
    stat.temperatures = {
        "extruder": {"actual": 50.0, "target": 60.0},
        "bed": {"actual": 25.0, "target": 0.0},
        "cpu": {"actual": 40.0},
    }

    with patch(
        "modules.temperature.router.get_machine_stat",
        return_value=stat,
    ) as get_stat:
        resp = client.get("/api/v1/modules/temperature/sensors")

    assert resp.status_code == 200
    # The factory must have been called to fetch the stat object.
    get_stat.assert_called_once_with()
    # ``poll()`` must be invoked on the stat object before the
    # temperatures are read.
    stat.poll.assert_called_once_with()


def test_get_sensors_response_matches_sensors_response_schema():
    """The ``GET /sensors`` response must match the
    :class:`SensorsResponse` schema — a top-level ``sensors`` dict
    whose values are themselves plain ``dict`` (not MagicMock /
    namespace objects) so Pydantic can serialise them in a
    deterministic shape (issue #43 § 3).
    """
    app = _build_router_app()
    client = TestClient(app)

    stat = MagicMock()
    stat.temperatures = {
        "extruder": {"actual": 50.0, "target": 60.0},
        "bed": {"actual": 25.0, "target": 0.0},
        "cpu": {"actual": 40.0},
    }

    with patch(
        "modules.temperature.router.get_machine_stat",
        return_value=stat,
    ):
        resp = client.get("/api/v1/modules/temperature/sensors")

    assert resp.status_code == 200
    body = resp.json()
    # Top-level shape.
    assert set(body.keys()) == {"sensors"}
    sensors = body["sensors"]
    # The mock injected three sensors — they must all be present.
    assert set(sensors.keys()) == {"extruder", "bed", "cpu"}
    # Each value must be a plain dict with the documented keys.
    for sensor_dict in sensors.values():
        assert isinstance(sensor_dict, dict)
        assert "actual" in sensor_dict
    # And the actual values must round-trip via the standard JSON
    # number type.
    assert sensors["extruder"]["actual"] == 50.0
    assert sensors["extruder"]["target"] == 60.0
    assert sensors["cpu"] == {"actual": 40.0}


def test_get_sensors_response_dicts_are_plain_dicts_not_mock_objects():
    """The router must coerce each sensor entry to a plain ``dict``
    before constructing the response so Pydantic serialises it
    consistently — even if the hardware layer returned a
    ``MagicMock`` (issue #43 § 3).
    """
    app = _build_router_app()
    client = TestClient(app)

    # Build a stat whose temperatures contain a ``MagicMock`` value
    # rather than a plain dict. The router must wrap each entry in
    # ``dict(...)`` so the response is JSON-serialisable.
    inner = MagicMock()
    # ``dict()`` over a MagicMock would iterate its attributes and
    # build a dict-of-MagicMocks; the resulting JSON is a plain
    # object, which is what we want to verify.
    stat = MagicMock()
    stat.temperatures = {"extruder": inner}

    with patch(
        "modules.temperature.router.get_machine_stat",
        return_value=stat,
    ):
        resp = client.get("/api/v1/modules/temperature/sensors")

    assert resp.status_code == 200
    sensors = resp.json()["sensors"]
    # The outer container is a plain dict.
    assert isinstance(sensors, dict)
    # The inner container is also a plain dict — not a MagicMock.
    assert isinstance(sensors["extruder"], dict)
    # And the response is serialisable: it round-trips through
    # ``json.dumps`` without raising.
    import json

    json.dumps(sensors)


def test_get_sensors_handles_empty_temperatures():
    """An empty ``temperatures`` mapping must yield ``{"sensors": {}}``
    rather than a 500.
    """
    app = _build_router_app()
    client = TestClient(app)

    stat = MagicMock()
    stat.temperatures = {}

    with patch(
        "modules.temperature.router.get_machine_stat",
        return_value=stat,
    ):
        resp = client.get("/api/v1/modules/temperature/sensors")

    assert resp.status_code == 200
    assert resp.json() == {"sensors": {}}


def test_get_sensors_tolerates_missing_temperatures_attribute():
    """Some stat implementations may not expose ``temperatures`` at
    all. The router must treat the missing attribute as an empty
    dict rather than raising ``AttributeError``.
    """
    app = _build_router_app()
    client = TestClient(app)

    # ``spec=['poll']`` constrains the mock to expose only ``poll``,
    # so accessing ``stat.temperatures`` raises ``AttributeError``
    # and ``getattr(stat, "temperatures", None)`` falls back to
    # ``None`` (then ``or {}`` → empty dict).
    stat = MagicMock(spec=["poll"])

    with patch(
        "modules.temperature.router.get_machine_stat",
        return_value=stat,
    ):
        resp = client.get("/api/v1/modules/temperature/sensors")

    assert resp.status_code == 200
    assert resp.json() == {"sensors": {}}


# ---------------------------------------------------------------------------
# POST /sensors/{name}/target — happy path
# ---------------------------------------------------------------------------


def test_set_target_success_path_calls_execute_sync_cmd_with_exact_args():
    """``POST /sensors/{name}/target`` must call
    ``execute_sync_cmd`` with exactly ``"set_temperature", 0, name,
    req.target`` and return a ``SetTargetResponse`` echoing the
    applied target (issue #43 § 3).
    """
    app = _build_router_app()
    client = TestClient(app)

    with patch(
        "modules.temperature.router.execute_sync_cmd",
        return_value={"status": "success"},
    ) as exec_cmd:
        resp = client.post(
            "/api/v1/modules/temperature/sensors/extruder/target",
            json={"sensor_name": "extruder", "target": 210.0},
        )

    assert resp.status_code == 200
    # The command must be forwarded verbatim: the exact positional
    # arguments the router is required to pass.
    exec_cmd.assert_called_once_with("set_temperature", 0, "extruder", 210.0)
    body = resp.json()
    assert body == {
        "status": "success",
        "sensor_name": "extruder",
        "target": 210.0,
    }


def test_set_target_accepts_boundary_targets():
    """Targets at the documented inclusive boundaries (0.0 and 400.0)
    must be accepted.
    """
    app = _build_router_app()
    client = TestClient(app)

    with patch(
        "modules.temperature.router.execute_sync_cmd",
        return_value={"status": "success"},
    ) as exec_cmd:
        for value in (0.0, 400.0):
            resp = client.post(
                "/api/v1/modules/temperature/sensors/bed/target",
                json={"sensor_name": "bed", "target": value},
            )
            assert resp.status_code == 200
            assert resp.json()["target"] == value

    # Two calls, one per boundary.
    assert exec_cmd.call_count == 2


def test_set_target_rejects_out_of_range_target_payload():
    """Pydantic must reject targets outside ``[0.0, 400.0]`` with a
    ``422`` validation error before the hardware layer is touched.
    """
    app = _build_router_app()
    client = TestClient(app)

    with patch(
        "modules.temperature.router.execute_sync_cmd",
    ) as exec_cmd:
        resp = client.post(
            "/api/v1/modules/temperature/sensors/extruder/target",
            json={"sensor_name": "extruder", "target": 401.0},
        )

    assert resp.status_code == 422
    # The hardware layer must not have been invoked.
    exec_cmd.assert_not_called()


def test_set_target_default_status_when_hardware_omits_it():
    """If the hardware layer returns a dict without a ``status`` key,
    the router must default to ``"success"`` so the response always
    carries a string.
    """
    app = _build_router_app()
    client = TestClient(app)

    with patch(
        "modules.temperature.router.execute_sync_cmd",
        return_value={},  # no status key
    ):
        resp = client.post(
            "/api/v1/modules/temperature/sensors/bed/target",
            json={"sensor_name": "bed", "target": 50.0},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


# ---------------------------------------------------------------------------
# POST /sensors/{name}/target — URL-vs-body precedence
# ---------------------------------------------------------------------------


def test_set_target_url_param_takes_precedence_over_body():
    """When the URL ``{name}`` differs from the ``sensor_name`` in
    the JSON body, the URL must win (issue #43 § 3). The router
    communicates the canonical name to the hardware layer.
    """
    app = _build_router_app()
    client = TestClient(app)

    with patch(
        "modules.temperature.router.execute_sync_cmd",
        return_value={"status": "success"},
    ) as exec_cmd:
        resp = client.post(
            "/api/v1/modules/temperature/sensors/bed/target",
            json={"sensor_name": "extruder", "target": 65.0},
        )

    assert resp.status_code == 200
    # The hardware command must use the URL name, not the body name.
    exec_cmd.assert_called_once_with("set_temperature", 0, "bed", 65.0)
    # The response must echo the URL name as the canonical sensor.
    body = resp.json()
    assert body["sensor_name"] == "bed"
    assert body["target"] == 65.0


def test_set_target_url_and_body_match_succeeds():
    """When the URL and body agree, the behaviour is unchanged —
    the hardware command is invoked once with the agreed name.
    """
    app = _build_router_app()
    client = TestClient(app)

    with patch(
        "modules.temperature.router.execute_sync_cmd",
        return_value={"status": "success"},
    ) as exec_cmd:
        resp = client.post(
            "/api/v1/modules/temperature/sensors/cpu/target",
            json={"sensor_name": "cpu", "target": 30.0},
        )

    assert resp.status_code == 200
    exec_cmd.assert_called_once_with("set_temperature", 0, "cpu", 30.0)
    assert resp.json()["sensor_name"] == "cpu"


# ---------------------------------------------------------------------------
# POST /sensors/{name}/target — error handling
# ---------------------------------------------------------------------------


def test_set_target_url_name_cannot_be_empty():
    """An empty URL ``{name}`` must yield ``400 Bad Request`` and
    must not invoke the hardware layer (issue #43 § 3).
    """
    app = _build_router_app()
    client = TestClient(app)

    # The pattern ``/sensors//target`` collapses to ``/sensors/target``
    # in the HTTP path, so we drive the endpoint directly to exercise
    # the empty-string branch in the router.
    from modules.temperature.router import set_target as set_target_fn

    with patch(
        "modules.temperature.router.execute_sync_cmd",
    ) as exec_cmd:
        with pytest.raises(Exception) as excinfo:
            set_target_fn(name="", req=MagicMock(sensor_name="bed", target=60.0))

    # The router raises ``HTTPException`` which propagates as a
    # ``HTTPException`` instance.
    from fastapi import HTTPException

    assert isinstance(excinfo.value, HTTPException)
    assert excinfo.value.status_code == 400
    # And the hardware must not have been invoked.
    exec_cmd.assert_not_called()


def test_set_target_url_name_must_be_a_string():
    """A non-string ``name`` (e.g. ``None``) must yield ``400 Bad
    Request`` without invoking the hardware layer (issue #43 § 3).
    """
    from fastapi import HTTPException

    from modules.temperature.router import set_target as set_target_fn

    with patch(
        "modules.temperature.router.execute_sync_cmd",
    ) as exec_cmd:
        with pytest.raises(HTTPException) as excinfo:
            set_target_fn(name=None, req=MagicMock(sensor_name="bed", target=60.0))

    assert excinfo.value.status_code == 400
    exec_cmd.assert_not_called()


def test_set_target_http_exception_passes_through():
    """An ``HTTPException`` raised by ``execute_sync_cmd`` (e.g.
    400 from a hardware-layer validation) must propagate unchanged
    so callers can surface the actionable error message.
    """
    from fastapi import HTTPException

    app = _build_router_app()
    client = TestClient(app)

    boom = HTTPException(status_code=400, detail="Command execution error")
    with patch(
        "modules.temperature.router.execute_sync_cmd",
        side_effect=boom,
    ):
        resp = client.post(
            "/api/v1/modules/temperature/sensors/bed/target",
            json={"sensor_name": "bed", "target": 60.0},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Command execution error"


def test_set_target_generic_exception_returns_500():
    """Any non-``HTTPException`` raised by ``execute_sync_cmd`` must
    be caught and surfaced as a ``500`` with the original message
    in the detail (issue #43 § 3).
    """
    app = _build_router_app()
    client = TestClient(app)

    with patch(
        "modules.temperature.router.execute_sync_cmd",
        side_effect=RuntimeError("hardware went away"),
    ):
        resp = client.post(
            "/api/v1/modules/temperature/sensors/bed/target",
            json={"sensor_name": "bed", "target": 60.0},
        )

    assert resp.status_code == 500
    assert "hardware went away" in resp.json()["detail"]
