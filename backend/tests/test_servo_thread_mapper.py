"""Tests for ``ServoThreadStateMapper``.

Pins the contract the WebSocket layer depends on:

* ``from_stat`` returns a complete ``ServoThreadStateDTO`` with
  every field populated even when ``machine_stat`` is ``None``
  (offline snapshot),
* the bounded ``errors`` history is normalised into
  :class:`LinuxCNCError` rows regardless of whether the upstream
  source shipped dicts (mock) or plain strings (real LinuxCNC's
  ``stat.errors``),
* ``get_diff_response`` only surfaces fields that actually
  changed so a single ``current_line`` update never ships the
  entire ``position`` array again.
"""

from __future__ import annotations

from types import SimpleNamespace

from mappers.ServoThreadStateMapper import ServoThreadStateMapper


class TestNormalizeErrors:
    """``ServoThreadStateMapper.normalize_errors`` must coerce every
    upstream shape into ``List[LinuxCNCError]``.

    The mock stores ``{kind, text, time}`` dicts; real LinuxCNC's
    ``stat.errors`` is a list of plain strings; a defensive path
    guards against malformed dicts. The mapper is the single
    boundary that decides what the UI sees, so the contract is
    pinned here.
    """

    def test_empty_inputs_return_empty_list(self):
        assert ServoThreadStateMapper.normalize_errors(None) == []
        assert ServoThreadStateMapper.normalize_errors([]) == []

    def test_dict_passes_through(self):
        """Mock-shaped dicts survive normalisation verbatim so the
        ``kind`` / ``time`` fields round-trip to the UI.
        """
        out = ServoThreadStateMapper.normalize_errors(
            [
                {"kind": 11, "text": "limit-switch", "time": "2026-08-12T10:00:00"},
            ]
        )
        assert len(out) == 1
        assert out[0].kind == 11
        assert out[0].text == "limit-switch"
        assert out[0].time == "2026-08-12T10:00:00"

    def test_real_linuxcnc_strings_get_wrapped(self):
        """Real LinuxCNC's ``stat.errors`` is a list of strings —
        we wrap each entry with ``kind=0`` so the UI keeps a
        consistent ``{kind, text, time}`` shape and the
        translation table's "kind=0 → unspecified" branch fires.
        """
        out = ServoThreadStateMapper.normalize_errors(
            ["joint 2 on limit switch error", "soft limit on Y"]
        )
        assert len(out) == 2
        assert out[0].kind == 0
        assert out[0].text == "joint 2 on limit switch error"
        assert out[0].time is None
        assert out[1].kind == 0
        assert out[1].text == "soft limit on Y"

    def test_malformed_dicts_fall_through_to_string_wrapper(self):
        """A dict missing required keys must not crash the
        normaliser — fall back to the string wrapper so the
        bounded history still surfaces the row.
        """
        out = ServoThreadStateMapper.normalize_errors(
            [{"unexpected": "shape"}, "real-string"]
        )
        assert len(out) == 2
        assert out[0].kind == 0
        # The wrapper coerces the dict via ``str(...)`` so the row
        # keeps a non-empty text representation regardless of the
        # exact contents.
        assert out[0].text, "malformed dict must produce non-empty text"
        assert out[1].text == "real-string"


class TestFromStat:
    """``from_stat`` builds the DTO the WebSocket layer ships."""

    def test_offline_returns_safe_defaults(self):
        """When ``machine_stat`` is ``None`` the mapper must not
        crash and must still include the supplied ``errors`` so a
        reconnect re-hydrates the operator's last session.
        """
        dto = ServoThreadStateMapper.from_stat(None, [])
        assert dto.task_state == 0
        assert dto.estop == 1
        assert dto.errors == []

    def test_offline_preserves_supplied_errors(self):
        """A reconnect-after-offline must surface the bounded
        history even when ``machine_stat`` is never reachable.
        """
        dto = ServoThreadStateMapper.from_stat(
            None,
            [{"kind": 11, "text": "soft-limit", "time": "2026-08-12T10:00:00"}],
        )
        assert len(dto.errors) == 1
        assert dto.errors[0].kind == 11

    def test_normalises_string_errors(self):
        """Real-LinuxCNC-shaped string errors flow through the
        mapper and arrive at the DTO as typed rows.
        """
        fake_stat = SimpleNamespace(actual_position=(0,) * 9)
        dto = ServoThreadStateMapper.from_stat(
            fake_stat,
            ["joint 2 on limit switch error"],
        )
        assert len(dto.errors) == 1
        assert dto.errors[0].kind == 0
        assert dto.errors[0].text == "joint 2 on limit switch error"


class TestGetDiffResponse:
    """``get_diff_response`` must surface only the fields that
    actually changed.
    """

    def test_first_call_returns_full_payload(self):
        """A ``None`` baseline means this is the first poll after a
        reconnect — ship the full snapshot so the UI re-hydrates.
        """
        stat = SimpleNamespace(
            task_state=4,
            estop=0,
            task_mode=2,
            actual_position=(1.0,) * 9,
            g5x_offset=(0,) * 9,
            g92_offset=(0,) * 9,
            tool_offset=(0,) * 9,
        )
        full = ServoThreadStateMapper.from_stat(stat, [])
        diff = ServoThreadStateMapper.get_diff_response(full, None)
        assert diff.task_state == 4
        assert diff.estop == 0

    def test_identical_states_produce_empty_diff(self):
        """Two consecutive snapshots that match field-for-field must
        produce a diff with every field ``None`` so the WS layer
        can skip the broadcast.
        """
        stat = SimpleNamespace(
            task_state=4,
            estop=0,
            task_mode=2,
            actual_position=(1.0,) * 9,
            g5x_offset=(0,) * 9,
            g92_offset=(0,) * 9,
            tool_offset=(0,) * 9,
        )
        full = ServoThreadStateMapper.from_stat(stat, [])
        diff = ServoThreadStateMapper.get_diff_response(full, full)
        assert diff.model_dump(exclude_none=True) == {}

    def test_single_field_change_only_ships_changed_field(self):
        """A single ``current_line`` increment must NOT re-ship the
        full ``position`` array — that is the silent-bug the diff
        path was introduced to fix.
        """
        stat_a = SimpleNamespace(
            task_state=4,
            estop=0,
            task_mode=2,
            actual_position=(1.0,) * 9,
            g5x_offset=(0,) * 9,
            g92_offset=(0,) * 9,
            tool_offset=(0,) * 9,
            current_line=10,
            total_lines=100,
        )
        stat_b = SimpleNamespace(**stat_a.__dict__)
        stat_b.current_line = 11

        full_a = ServoThreadStateMapper.from_stat(stat_a, [])
        full_b = ServoThreadStateMapper.from_stat(stat_b, [])
        diff = ServoThreadStateMapper.get_diff_response(full_b, full_a)

        assert diff.current_line == 11
        # ``actual_position`` is identical and must be dropped from
        # the diff payload.
        assert diff.actual_position is None
