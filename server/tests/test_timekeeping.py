"""What keeps the system clock, and setting it from a client (ADR 0029), with fake
chronyc, timedatectl, date and hwclock on the PATH."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nocs.clock import Clock
from nocs.jobs import JobManager
from nocs.services.timekeeping import TimeKeeper, clock_source
from nocs.state import StateStore
from nocs.system.operations import Context, set_time
from nocs.system.protocol import HelperError

SYSTEM = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
TRACKING_UNSYNCED = "00000000,,0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.0,1.0,0.0,Not synchronised\n"
TRACKING_SYNCED = (
    "C0A80101,192.168.1.1,2,1793000000.0,0.0,0.0,0.0,1.0,0.0,0.1,0.01,0.01,64.0,Normal\n"
)


class Tools:
    """Fake tools: each prints the answer written for its first argument that is not an
    option, if any; every call is logged."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dir = tmp_path / "tools"
        self.dir.mkdir()
        self.log = tmp_path / "calls.log"
        monkeypatch.setenv("PATH", str(self.dir))

    def add(self, tool: str) -> None:
        script = self.dir / tool
        script.write_text(
            f'#!/bin/sh\necho "{tool} $*" >> "{self.log}"\n'
            # Answers are named after the first argument that is not an option.
            'for arg; do case "$arg" in -*) ;; *) break ;; esac; done\n'
            f'answer="{self.dir}/{tool}-$arg.out"\n'
            '[ -f "$answer" ] || exit 0\n/bin/cat "$answer"\n'
        )
        script.chmod(0o755)

    def answer(self, tool: str, argument: str, output: str) -> None:
        self.add(tool)
        (self.dir / f"{tool}-{argument}.out").write_text(output)

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tools:
    return Tools(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ("#,*,GPS,0,4,377,10,0.01,0.01,0.2\n^,-,ntp.example,2,6,377,12,0.0,0.0,0.02\n", "gps"),
        ("#,x,GPS,0,4,0,0,0,0,0\n^,*,ntp.example,2,6,377,12,0.0,0.0,0.02\n", "ntp"),
        ("^,?,ntp.example,0,6,0,0,0,0,0\n", "none"),
        ("", "none"),
    ],
)
async def test_chrony_names_the_source(tools: Tools, sources: str, expected: str) -> None:
    tools.answer("chronyc", "sources", sources)
    assert await clock_source() == expected


async def test_without_chrony_timesyncd_says(tools: Tools) -> None:
    tools.answer("timedatectl", "show", "yes\n")
    assert await clock_source() == "ntp"
    tools.answer("timedatectl", "show", "no\n")
    assert await clock_source() == "none"


async def test_with_neither_nothing_keeps_it(tools: Tools) -> None:
    assert await clock_source() == "none"


# -- nocs-system's time.set -------------------------------------------------------


async def test_set_time_steps_the_clock_and_the_rtc(tools: Tools) -> None:
    tools.answer("chronyc", "tracking", TRACKING_UNSYNCED)
    tools.add("date")
    tools.add("hwclock")
    assert await set_time(Context(), {"utc": 1793502000.25}) == {}
    assert tools.calls() == [
        "chronyc -c tracking",
        "date --utc --set=@1793502000.250",
        "hwclock --systohc --utc",
    ]


async def test_a_synchronised_clock_is_left_alone(tools: Tools) -> None:
    tools.answer("chronyc", "tracking", TRACKING_SYNCED)
    tools.add("date")
    with pytest.raises(HelperError, match="kept by chrony"):
        await set_time(Context(), {"utc": 1793502000})
    assert not any(call.startswith("date") for call in tools.calls())


async def test_without_an_rtc_the_clock_is_set_anyway(tools: Tools) -> None:
    tools.answer("timedatectl", "show", "no\n")
    tools.add("date")
    assert await set_time(Context(), {"utc": 1793502000}) == {}
    assert "date --utc --set=@1793502000.000" in tools.calls()


@pytest.mark.parametrize("args", [{}, {"utc": "now"}, {"utc": True}, {"utc": 0}, {"utc": 1e12}])
async def test_unbelievable_times_are_refused(tools: Tools, args: dict[str, object]) -> None:
    with pytest.raises(HelperError) as refused:
        await set_time(Context(), args)
    assert refused.value.code == "invalid"
    assert tools.calls() == []


# -- nocsd's side -----------------------------------------------------------------


class FakeHelper:
    def __init__(self, *ops: str) -> None:
        self.ops = set(ops)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def offers(self, op: str) -> bool:
        return op in self.ops

    async def perform(self, op: str, args: dict[str, object]) -> dict[str, object]:
        self.calls.append((op, args))
        return {}


def wrong_clock(store: StateStore) -> Clock:
    """A Pi that booted an hour behind, and a client that knows better."""
    clock = Clock(store, system=lambda: SYSTEM, monotonic=lambda: 100.0)
    clock.report(SYSTEM + timedelta(hours=1))
    return clock


async def test_the_clock_is_set_from_the_client_when_nothing_keeps_it(tools: Tools) -> None:
    tools.answer("chronyc", "sources", "")
    store = StateStore()
    helper = FakeHelper("time.set")
    keeper = TimeKeeper(wrong_clock(store), JobManager(store), helper)
    await keeper.check()
    assert helper.calls == [("time.set", {"utc": (SYSTEM + timedelta(hours=1)).timestamp()})]
    assert store.get(("clock", "source")) == "client"


async def test_a_clock_set_this_boot_stays_known_after_a_restart(
    tools: Tools, tmp_path: Path
) -> None:
    tools.answer("chronyc", "sources", "")
    boot_id = tmp_path / "boot_id"
    boot_id.write_text("boot-1\n")
    memory = tmp_path / "data/clock-set-from-client"
    store = StateStore()
    keeper = TimeKeeper(
        wrong_clock(store),
        JobManager(store),
        FakeHelper("time.set"),
        memory=memory,
        boot_id=boot_id,
    )
    await keeper.check()
    # nocsd restarts: no client yet, and the clock is right now.
    store = StateStore()
    clock = Clock(store)
    helper = FakeHelper("time.set")
    await TimeKeeper(clock, JobManager(store), helper, memory=memory, boot_id=boot_id).check()
    assert helper.calls == []
    assert store.get(("clock", "source")) == "client"
    assert clock.known
    # After a reboot it is not known until something sets it again.
    boot_id.write_text("boot-2\n")
    store = StateStore()
    clock = Clock(store)
    await TimeKeeper(clock, JobManager(store), helper, memory=memory, boot_id=boot_id).check()
    assert store.get(("clock", "source")) == "none"
    assert not clock.known


async def test_never_during_a_job(tools: Tools) -> None:
    tools.answer("chronyc", "sources", "")
    store = StateStore()
    jobs = JobManager(store)
    jobs.reserve("slew pad", ["mount"])
    helper = FakeHelper("time.set")
    await TimeKeeper(wrong_clock(store), jobs, helper).check()
    assert helper.calls == []
    assert store.get(("clock", "source")) == "none"


async def test_never_over_gps_or_ntp(tools: Tools) -> None:
    tools.answer("chronyc", "sources", "#,*,GPS,0,4,377,10,0.01,0.01,0.2\n")
    store = StateStore()
    helper = FakeHelper("time.set")
    await TimeKeeper(wrong_clock(store), JobManager(store), helper).check()
    assert helper.calls == []
    assert store.get(("clock", "source")) == "gps"


async def test_a_pc_only_corrects_timestamps(tools: Tools) -> None:
    tools.answer("chronyc", "sources", "")
    store = StateStore()
    clock = wrong_clock(store)
    await TimeKeeper(clock, JobManager(store), FakeHelper()).check()
    assert clock.corrected is True
    assert os.environ["PATH"] == str(tools.dir)


def test_a_clock_kept_by_ntp_or_a_gps_is_known_without_a_client() -> None:
    clock = Clock(StateStore())
    told: list[bool] = []
    clock.add_listener(lambda: told.append(clock.known))
    assert not clock.known
    clock.set_source("none")
    assert not clock.known
    assert told == []
    clock.set_source("ntp")
    assert clock.known
    assert told == [True]  # the mount gets the time at once
    clock.set_source("gps")
    assert told == [True]
    clock.set_source("none")
    assert not clock.known
