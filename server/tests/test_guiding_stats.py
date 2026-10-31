"""Guide steps and RMS, on synthetic steps and on a session PHD2 recorded."""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from nocs.guiding.stats import GuideEntry, GuideHistory, rms

RECORDING = Path(__file__).parents[2] / "dev" / "recordings" / "phd2-simulators-2026-10-31.jsonl"


def step(ra: float, dec: float, **fields: Any) -> dict[str, Any]:
    return {"Timestamp": 1000.0, "RADistanceRaw": ra, "DECDistanceRaw": dec, **fields}


def test_rms_is_the_deviation_as_phd2_shows_it() -> None:
    history = GuideHistory()
    for ra, dec in [(1, 2), (-1, -2), (1, 2), (-1, -2)]:
        history.add("GuideStep", step(ra, dec), settling=False)
    result = history.recent_rms()
    assert result is not None
    assert (result.count, result.ra, result.dec) == (4, 1.0, 2.0)
    assert result.total == pytest.approx(math.sqrt(5))
    assert (result.peak_ra, result.peak_dec) == (1.0, 2.0)
    # A constant offset is not a guiding error.
    offset = rms(GuideEntry(seq=i, kind="step", time=0, ra=3.0, dec=-1.0) for i in range(1, 4))
    assert offset is not None
    assert (offset.ra, offset.dec) == (0.0, 0.0)


def test_steps_keep_pulses_signed_and_star_figures() -> None:
    history = GuideHistory()
    entry = history.add(
        "GuideStep",
        step(
            0.8,
            1.3,
            RADuration=292,
            RADirection="West",
            DECDuration=710,
            DECDirection="South",
            SNR=134.4,
            HFD=3.12,
            StarMass=36299,
        ),
        settling=True,
    )
    assert entry is not None
    assert (entry.kind, entry.ra_pulse, entry.dec_pulse) == ("step", 292, -710)
    assert (entry.snr, entry.hfd, entry.mass, entry.settling) == (134.4, 3.12, 36299, True)
    east = history.add("GuideStep", step(0, 0, RADuration=100, RADirection="East"), settling=False)
    assert east is not None
    assert east.ra_pulse == -100
    assert history.add("Calibrating", {"step": 1}, settling=False) is None


def test_settling_steps_are_left_out_of_the_rms() -> None:
    history = GuideHistory()
    history.add("GuideStep", step(5, 5), settling=True)
    assert history.recent_rms() is None
    history.add("GuideStep", step(0.5, 0.1), settling=False)
    history.add("GuideStep", step(-0.5, -0.1), settling=False)
    result = history.recent_rms()
    assert result is not None
    assert (result.count, result.ra) == (2, 0.5)


def test_window_lost_frames_and_dithers() -> None:
    history = GuideHistory()
    for i in range(150):
        history.add("GuideStep", step(i, 0), settling=False)
    window = history.recent_rms(window=100)
    assert window is not None
    assert window.count == 100
    assert window.peak_ra == 149
    history.add("StarLost", {"Timestamp": 2000.0, "SNR": 0, "StarMass": 0}, settling=False)
    dither = history.add(
        "GuidingDithered", {"Timestamp": 2001.0, "dx": -1.1, "dy": 2.8}, settling=True
    )
    assert dither is not None
    assert (dither.kind, dither.ra, dither.dec) == ("dither", -1.1, 2.8)
    assert history.lost_count() == 1


def test_entries_are_numbered_across_runs() -> None:
    history = GuideHistory(limit=3)
    for i in range(5):
        history.add("GuideStep", step(i, 0), settling=False)
    assert [e.seq for e in history.after(0)] == [3, 4, 5]  # the oldest dropped
    assert [e.seq for e in history.after(3)] == [4, 5]
    assert [e.seq for e in history.after(0, limit=1)] == [3]
    history.reset()
    assert history.after(0) == []
    entry = history.add("GuideStep", step(0, 0), settling=False)
    assert entry is not None
    assert entry.seq == 6  # a client that saw 5 asks for what follows


def test_a_recorded_session() -> None:
    """Calibration, guiding with settling, a dither and its settling, as PHD2 sent them."""
    history = GuideHistory()
    settling = False
    for line in RECORDING.read_text().splitlines():
        event = json.loads(line)
        name = event["Event"]
        if name == "StartGuiding":
            history.reset()
        elif name == "SettleBegin":
            settling = True
        elif name == "SettleDone":
            settling = False
        history.add(name, event, settling=settling)
    entries = history.after(0)
    kinds = [e.kind for e in entries]
    assert kinds.count("step") == 58
    assert kinds.count("dither") == 1
    times = [e.time for e in entries]
    assert times == sorted(times)
    steady = [e for e in entries if e.kind == "step" and not e.settling]
    result = history.recent_rms()
    assert result is not None
    assert result.count == len(steady)
    # The simulators guide well: well under a pixel either way.
    assert 0 < result.ra < 0.5
    assert 0 < result.dec < 0.5
    assert history.between(times[0], times[0] + 10)
