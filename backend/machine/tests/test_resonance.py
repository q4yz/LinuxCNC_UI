"""Resonance measurement: the shaper math, the spectrum, the fit, a sweep
with a synthetic accelerometer, and the ADXL345 data decoding."""
from __future__ import annotations

import math

import numpy as np
import pytest

import services.ResonanceService as module
from services.Adxl345 import decode, parse_axes_map


def test_a_shaper_cancels_its_own_frequency():
    for kind in module.SHAPERS:
        amps, times = module.shaper_impulses(kind, 50.0)
        left = module.residual_vibration(amps, times, np.array([50.0, 150.0]), 0.1)
        assert left[0] < 0.05, kind


def test_impulses_match_the_hal_component():
    amps, times = module.shaper_impulses("mzv", 50.0)
    norm = [a / sum(amps) for a in amps]
    assert norm == pytest.approx([0.365, 0.407, 0.227], abs=0.002)
    assert times[-1] * 1000 == pytest.approx(15.1, abs=0.1)


def _psd_with_peak(peak_hz):
    freqs = np.arange(0, 200, 0.5)
    psd = 1.0 / (1.0 + ((freqs - peak_hz) / 2.0) ** 2) + 0.001
    return freqs, psd


def test_fit_recommends_near_the_resonance():
    freqs, psd = _psd_with_peak(45.0)
    fits, best = module.fit_shapers(freqs, psd, 5.0, 133.0)
    assert {fit.kind for fit in fits} == set(module.SHAPERS)
    assert best.vibrations < 0.1
    assert 35.0 <= best.freq <= 60.0


def test_power_spectrum_finds_a_sine():
    rate = 3200.0
    t = np.arange(0, 4, 1 / rate)
    freqs, psd = module.power_spectrum(np.sin(2 * math.pi * 62.0 * t), rate)
    assert abs(freqs[int(np.argmax(psd))] - 62.0) < 2.0


def test_measure_with_a_synthetic_accelerometer(monkeypatch):
    import services.ShaperService as shaper_module

    calls = []

    class Shaper:
        def test_signal(self, axis, amp, freq):
            calls.append((axis, amp, freq))

        def stop_test(self):
            calls.append("stop")

    monkeypatch.setattr(shaper_module, "get_shaper_service", lambda: Shaper())
    rate, clock = 3200.0, {"t": 0.0}

    def source():  # 2 kHz worth of a 48 Hz ringing on X since the last call
        samples = []
        for _ in range(64):
            clock["t"] += 1 / rate
            t = clock["t"]
            samples.append((t, 500 * math.sin(2 * math.pi * 48 * t), 5 * math.sin(2 * math.pi * 7 * t), 0.0))
        return samples

    logs = []
    config = {"min_freq": 20, "max_freq": 80, "hz_per_sec": 120, "accel_per_hz": 75}
    best = module.ResonanceService().measure(config, "x", lambda m, **k: logs.append(m), source=source)
    assert calls[-1] == "stop" and calls[0][0] == "x"
    assert calls[0][1] == pytest.approx(75 / (4 * math.pi ** 2 * 20), rel=0.2)  # a / (2πf)², per Hz
    assert 40 <= best.freq <= 60
    assert any("Recommended for X: [input_shaper] shaper_type_x:" in m for m in logs)


def test_adxl_decoding_and_axes_map():
    axes = parse_axes_map("-y,x,z")
    raw = [0x00, 0x01, 0xFF, 0xFF, 0x02, 0x00]   # chip x = 256, y = -1, z = 2 LSB
    x, y, z = decode(raw, axes)
    lsb = 0.0039 * 9806.65
    assert x == pytest.approx(1 * lsb) and y == pytest.approx(256 * lsb) and z == pytest.approx(2 * lsb)


def test_sampler_lines():
    from services.Adxl345 import parse_sampler_line

    assert parse_sampler_line("17 12.5 -3\n") == (17, 12.5, -3.0)
    assert parse_sampler_line("garbage") is None and parse_sampler_line("1 x 2") is None


def test_node_accelerometer_reads_halsampler(monkeypatch, tmp_path):
    """A fake halsampler: 250 samples of a 40 Hz sine on X, 1 kHz."""
    import os
    import time as _time

    from services.Adxl345 import NodeAdxl345

    script = tmp_path / "halsampler"
    # waits first: open() drops what is in the FIFO before recording starts
    script.write_text("#!/usr/bin/env python3\nimport math, sys, time\ntime.sleep(0.5)\n"
                      "for n in range(250):\n"
                      "    print(n, 1000 * math.sin(2 * math.pi * 40 * n / 1000), 5.0, flush=True)\n"
                      "import time; time.sleep(30)\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    record = []
    chip = NodeAdxl345({"cs_pin": "ebb:PB12"}, record.append, period_s=0.001)
    monkeypatch.setattr(_time, "sleep", lambda s: None)  # open() would drop the fake's samples
    chip.open()
    deadline = _time.monotonic() + 5
    samples: list = []
    while len(samples) < 250 and _time.monotonic() < deadline:
        samples.extend(chip.read_fifo())
    chip.close()
    assert record == [False, True, False]  # recording only between open and close
    assert len(samples) == 250 and chip.rate == 1000.0
    assert samples[1][0] - samples[0][0] == pytest.approx(0.001)
    assert samples[0][2] == 5.0 and samples[0][3] == 0.0


def test_measure_picks_the_node_accelerometer(monkeypatch):
    service = module.ResonanceService()
    from services.Adxl345 import Adxl345, NodeAdxl345

    assert isinstance(service.accelerometer({"cs_pin": "ebb:PB12"}), NodeAdxl345)
    assert isinstance(service.accelerometer({"spi_device": "/dev/spidev1.1"}), Adxl345)
