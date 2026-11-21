# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Templates: groups of frames of what the camera has framed."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient
from owner import pair_owner
from test_sequence import DIAGUITAS, M42, Rig, frames

from nocs.api.app import create_app
from nocs.config import Settings
from nocs.sequence import (
    Checkpoint,
    Container,
    Event,
    EventKind,
    ExposurePlan,
    Outcome,
    Runner,
    RunState,
    Sequence,
    SequenceStore,
)
from nocs.sequence import sky as night_sky
from nocs.sequence.model import (
    Aim,
    Autofocus,
    AutofocusTrigger,
    Center,
    Cool,
    DitherTrigger,
    Flats,
    FlipTrigger,
    FocusPlan,
    Group,
    Guide,
    Prompt,
    RecenterTrigger,
    Slew,
    Template,
    Unpark,
    UntilDawn,
    Wait,
    WhileAbove,
)
from nocs.sequence.template import estimate, expand, segments

LRGB = [
    Group(filter="L", exposure=120, count=40),
    Group(filter="R", exposure=180, count=10),
    Group(filter="G", exposure=180, count=10),
    Group(filter="B", exposure=180, count=10),
]


def lrgb(*extra: Group, **fields: object) -> Template:
    return Template.model_validate({"name": "LRGB", "groups": [*LRGB, *extra], **fields})


def lights_of(template: Template, index: int = 0) -> Container:
    segment = expand(template).targets.children[index]
    assert isinstance(segment, Container)
    return segment


def imaging_of(template: Template, index: int = 0) -> Container:
    imaging = lights_of(template, index).children[-1]
    assert isinstance(imaging, Container)
    return imaging


def test_lights_in_a_row_are_one_plan_each_to_its_end() -> None:
    sequence = expand(lrgb())
    assert sequence.template == lrgb()
    assert sequence.start.children == [Unpark()]
    [lights] = sequence.targets.children
    assert isinstance(lights, Container)
    assert lights.conditions == [UntilDawn()]
    dusk, aim, high, imaging = lights.children
    assert (dusk, aim, high) == (Wait(dusk="astronomical"), Aim(), Wait(altitude=30))
    assert isinstance(imaging, Container)
    assert imaging.conditions == [WhileAbove(altitude=30)]
    assert imaging.triggers == [AutofocusTrigger(temperature_change=1.0), FlipTrigger()]
    focus, plan = imaging.children
    assert focus == Autofocus()
    assert isinstance(plan, ExposurePlan)
    assert [(r.filter, r.exposure, r.count) for r in plan.rows] == [
        ("L", 120, 40),
        ("R", 180, 10),
        ("G", 180, 10),
        ("B", 180, 10),
    ]
    assert (plan.order, plan.frame_type) == ("in_turn", "light")
    assert [c.kind for c in sequence.end.children] == ["park", "warm"]


def test_options_change_the_tree() -> None:
    sequence = expand(
        lrgb(
            cooling="global",
            temperature=-10,
            cooling_ramp=3,
            guide=True,
            start_at_dusk=False,
            until_dawn=False,
            min_altitude=None,
            focus=FocusPlan(filter_change=True, temperature_change=None),
            end={"park": False, "outputs": ["dc:1", "dew:1"]},
        )
    )
    assert sequence.start.children == [Cool(temperature=-10, ramp=3), Unpark()]
    [lights] = sequence.targets.children
    assert isinstance(lights, Container)
    assert lights.conditions == []
    aim, imaging = lights.children
    assert aim == Aim()
    assert isinstance(imaging, Container)
    assert imaging.conditions == []
    assert imaging.triggers[0] == AutofocusTrigger(filter_change=True, temperature_change=None)
    # The filter trigger focuses before the first frame anyway: no autofocus of its own.
    assert [c.kind for c in imaging.children] == ["guide", "expose"]
    assert [c.kind for c in sequence.end.children] == ["guide", "warm", "outputs"]
    assert sequence.end.children[0] == Guide(on=False)


def test_a_guided_template_dithers_every_n_frames() -> None:
    def triggers(template: Template) -> list[str]:
        return [t.kind for t in imaging_of(template).triggers]

    assert triggers(lrgb(guide=True, dither_every=3)) == ["autofocus", "flip", "dither"]
    # Without guiding there is nothing to dither.
    assert triggers(lrgb(dither_every=3, flip=False)) == ["autofocus"]
    dither = imaging_of(lrgb(guide=True, dither_every=3, dither_pixels=8)).triggers[-1]
    assert isinstance(dither, DitherTrigger)
    assert (dither.every, dither.dither.pixels) == (3, 8)


def test_a_template_centres_and_checks_the_pointing() -> None:
    imaging = imaging_of(lrgb(center=True, recenter_every=10, recenter_drift=3))
    assert imaging.children[0] == Center()
    recenter = imaging.triggers[-1]
    assert isinstance(recenter, RecenterTrigger)
    assert (recenter.every, recenter.recenter.drift) == (10, 3)
    flip = imaging.triggers[-2]
    assert isinstance(flip, FlipTrigger)
    assert flip.flip.center == Center()  # a flip centres again
    # Checking the pointing needs centring.
    assert [t.kind for t in imaging_of(lrgb(recenter_every=10)).triggers] == [
        "autofocus",
        "flip",
    ]


def test_each_kind_of_frames_asks_for_the_rig_and_guiding_stops_for_it() -> None:
    template = lrgb(
        Group(frame_type="flat", filter="L", count=20),
        Group(frame_type="flat", filter="R", exposure=0.5, count=20),
        Group(frame_type="bias", filter="L", exposure=3, count=50),
        Group(frame_type="dark", exposure=120, count=20),
        guide=True,
    )
    assert [s.frame_class for s in segments(template)] == ["light", "flat", "flat", "dark", "dark"]
    sequence = expand(template)
    steps = [
        [n.kind for n in c.children] for c in sequence.targets.children if isinstance(c, Container)
    ]
    assert steps == [
        ["wait", "aim", "wait", "container"],
        ["guide", "prompt", "flats"],
        ["expose"],
        ["prompt", "expose"],
        ["expose"],
    ]
    flats, fixed, bias, dark = sequence.targets.children[1:]
    assert isinstance(flats, Container)
    assert flats.children[0] == Guide(on=False)
    assert flats.children[1] == Prompt(frame_type="flat")
    assert flats.children[2] == Flats(filter="L", count=20)
    assert isinstance(fixed, Container)
    [plan] = fixed.children
    assert isinstance(plan, ExposurePlan)
    assert (plan.frame_type, plan.rows[0].exposure) == ("flat", 0.5)
    # Bias take the camera's shortest exposure and no filter; darks no filter.
    assert isinstance(bias, Container)
    plan = bias.children[1]
    assert isinstance(plan, ExposurePlan)
    assert (plan.frame_type, plan.rows[0].filter, plan.rows[0].exposure) == ("bias", None, None)
    assert isinstance(dark, Container)
    # Lights after darks ask to uncover the telescope.
    again = expand(
        Template(
            name="x",
            groups=[Group(frame_type="dark", exposure=60, count=5), LRGB[0]],
        )
    )
    first, lights = again.targets.children
    assert isinstance(first, Container)
    assert isinstance(lights, Container)
    assert first.children[0] == Prompt(frame_type="dark")
    assert lights.children[0] == Prompt(frame_type="light")


def test_cooling_per_group_cools_before_each_and_splits_lights() -> None:
    template = Template(
        name="x",
        cooling="group",
        groups=[
            Group(filter="L", exposure=60, count=5, temperature=-10),
            Group(filter="R", exposure=60, count=5, temperature=-10),
            Group(filter="B", exposure=60, count=5, temperature=-5),
            Group(frame_type="dark", exposure=60, count=5),
        ],
    )
    assert [len(s.groups) for s in segments(template)] == [2, 1, 1]
    sequence = expand(template)
    first, second, dark = sequence.targets.children
    assert isinstance(first, Container)
    assert isinstance(second, Container)
    assert isinstance(dark, Container)
    assert first.children[0] == Cool(temperature=-10)
    assert second.children[0] == Cool(temperature=-5)
    assert [c.kind for c in dark.children] == ["prompt", "expose"]  # no temperature: as is
    with pytest.raises(ValueError, match="global cooling needs a temperature"):
        Template(name="x", cooling="global", groups=LRGB)


def test_groups_fit_their_kind() -> None:
    with pytest.raises(ValueError, match="light frames need an exposure"):
        Group(count=1)
    with pytest.raises(ValueError, match="dark frames need an exposure"):
        Group(frame_type="dark", count=1)
    assert Group(frame_type="dark", filter="L", exposure=60, count=1).filter is None
    flat = Group(frame_type="flat", filter="L", count=10)
    assert (flat.filter, flat.exposure) == ("L", None)


async def test_a_night_from_a_template_on_a_fake_rig() -> None:
    rig = Rig()
    begin = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)  # 17:00 at the site: daylight
    rig.time = begin
    rig.aim = {"name": "M 42", "ra": M42.ra, "dec": M42.dec}
    events: list[Event] = []
    template = Template(
        name="M 42",
        groups=[
            Group(filter="L", exposure=120, count=10),
            Group(frame_type="dark", exposure=120, count=3),
        ],
        min_altitude=None,
    )
    runner = Runner(
        expand(template),
        rig,
        now=rig.now,
        sleep=rig.sleep,
        place=lambda: DIAGUITAS,
        on_event=events.append,
    )
    async with anyio.create_task_group() as group:

        async def answer() -> None:
            # Polled: the runner has no event to wait on.
            for _ in range(1000):
                if runner.state is RunState.PAUSED:
                    break
                await anyio.sleep(0.01)
            assert runner.status()["prompt"] == "dark"
            runner.resume()

        group.start_soon(answer)
        assert await runner.run() is Outcome.COMPLETED
    assert frames(rig) == ["L 120"] * 10 + ["- 120"] * 3
    assert rig.calls[:3] == ["unpark", "aim", "autofocus"]
    assert "paused" in rig.calls  # the rig is lent back while the user covers it
    assert rig.calls[-2:] == ["park", "warm"]
    assert [kind for kind, _ in rig.ended] == ["light", "dark"]
    assert rig.ended[1][1] == [11, 12, 13]  # the darks' frames, for their master
    assert [e.kind for e in events].count(EventKind.PROMPT) == 1
    status = runner.status()
    assert [p["frame_type"] for p in status["plans"].values()] == ["light", "dark"]  # type: ignore[index]
    assert runner.checkpoint.aimed is not None
    assert runner.checkpoint.aimed.name == "M 42"
    # It waited for the dark, within a look at the sky (30 s) of astronomical dusk.
    [dusk] = [e for e in events if e.message == "wait"][:1]
    waited = dusk.data["waited"]
    assert isinstance(waited, int)
    dark = begin + timedelta(seconds=waited)
    assert night_sky.dark(DIAGUITAS, dark, "astronomical")
    assert not night_sky.dark(DIAGUITAS, dark - timedelta(seconds=35), "astronomical")


async def test_an_aim_without_coordinates_skips_the_altitude() -> None:
    rig = Rig()
    rig.time = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)  # night at the site
    rig.aim = {"name": None, "ra": None, "dec": None}
    template = Template(name="x", groups=[Group(exposure=60, count=2)], flip=False)
    runner = Runner(expand(template), rig, now=rig.now, sleep=rig.sleep, place=lambda: DIAGUITAS)
    assert await runner.run() is Outcome.COMPLETED
    assert frames(rig) == ["- 60"] * 2
    assert runner.checkpoint.aimed is not None
    assert runner.checkpoint.aimed.name == "Untitled"


def test_an_estimate_of_the_groups() -> None:
    template = lrgb(Group(frame_type="bias", count=50), Group(frame_type="flat", count=20))
    now = datetime(2026, 11, 1, 1, tzinfo=UTC)  # 22:00 at the site: dark
    found = estimate(template, sensor=(6248, 4176), place=DIAGUITAS, now=now)
    assert found.frames == 140
    assert found.integration == pytest.approx(40 * 120 + 30 * 180 + 50 * 0.001 + 20 * 2)
    assert found.duration == pytest.approx(found.integration + 140 * 3)
    assert found.bytes is not None
    assert 7.2e9 < found.bytes < 7.4e9  # 140 frames of 52 MB
    assert found.starts == now
    assert found.ends == now + timedelta(seconds=found.duration)
    # In the afternoon lights wait for dusk; darks first start at once.
    afternoon = datetime(2026, 11, 1, 18, tzinfo=UTC)
    later = estimate(template, place=DIAGUITAS, now=afternoon)
    assert later.starts is not None
    assert later.starts > afternoon
    darks = Template(name="d", groups=[Group(frame_type="dark", exposure=60, count=5)])
    assert estimate(darks, place=DIAGUITAS, now=afternoon).starts == afternoon
    assert estimate(template).bytes is None


def test_the_api_builds_a_sequence_from_a_template(tmp_path: Path) -> None:
    settings = Settings(
        indi_host="127.0.0.1",
        indi_port=1,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        body = lrgb().model_dump(mode="json")
        assert client.put("/api/sequences/lrgb/template", json=body).status_code == 204
        stored = client.get("/api/sequences/lrgb").json()
        assert stored["template"] == body
        assert stored["targets"]["children"][0]["children"][1] == {"kind": "aim"}
        response = client.post("/api/sequences/estimate", json=body)
        assert response.status_code == 200, response.text
        found = response.json()
        assert (found["frames"], found["integration"], found["duration"]) == (70, 10200.0, 10410.0)
        assert found["bytes"] is None
        expanded = client.post("/api/sequences/expand", json=body)
        assert expanded.status_code == 200, expanded.text
        assert expanded.json()["end"]["children"][0] == {"kind": "park"}
        bad = {**body, "groups": [{"frame_type": "light", "count": 3}]}
        assert client.put("/api/sequences/x/template", json=bad).status_code == 422


def test_a_template_s_offs_survive_the_store(tmp_path: Path) -> None:
    template = lrgb(focus=None, min_altitude=None)
    store = SequenceStore(tmp_path)
    store.put("lrgb", expand(template))
    stored = store.get("lrgb")
    assert stored is not None
    assert stored.template == template
    assert stored.digest() == expand(template).digest()


def test_lights_after_other_frames_go_back_to_what_was_framed() -> None:
    template = Template(
        name="x",
        groups=[LRGB[0], Group(frame_type="flat", filter="L", count=5), LRGB[1]],
        start_at_dusk=False,
        min_altitude=None,
    )
    first, _, again = expand(template).targets.children
    assert isinstance(first, Container)
    assert isinstance(again, Container)
    assert Slew() not in first.children
    assert again.children[:3] == [Prompt(frame_type="light"), Aim(), Slew()]
    # Centring goes back by itself.
    centred = expand(template.model_copy(update={"center": True})).targets.children[2]
    assert isinstance(centred, Container)
    assert Slew() not in centred.children


async def test_a_plan_done_before_a_restart_is_not_kept_again() -> None:
    rig = Rig()
    rig.time = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
    template = Template(
        name="x",
        groups=[Group(frame_type="dark", exposure=60, count=2), Group(frame_type="bias", count=2)],
    )
    sequence = expand(template)
    saved: list[Checkpoint] = []

    async def save(checkpoint: Checkpoint) -> None:
        saved.append(checkpoint.model_copy(deep=True))

    runner = Runner(sequence, rig, now=rig.now, sleep=rig.sleep, save=save)
    async with anyio.create_task_group() as group:

        async def answer() -> None:
            for _ in range(1000):
                if runner.state is RunState.PAUSED:
                    runner.resume()
                    return
                await anyio.sleep(0.01)

        group.start_soon(answer)
        assert await runner.run() is Outcome.COMPLETED
    assert [kind for kind, _ in rig.ended] == ["dark", "bias"]
    # Resumed from a checkpoint taken after the darks' plan was done, but before its
    # container was marked finished: the darks' master is not made again.
    after = next(
        c for c in saved if c.plans.get("targets.0.1") and c.plans["targets.0.1"].done == [2]
    )
    assert "targets.0" not in after.finished
    rig.ended.clear()
    rig.calls.clear()
    resumed = Runner(sequence, rig, now=rig.now, sleep=rig.sleep, checkpoint=after)
    async with anyio.create_task_group() as group:

        async def answer_again() -> None:
            for _ in range(1000):
                if resumed.state is RunState.PAUSED:
                    resumed.resume()
                    return
                await anyio.sleep(0.01)

        group.start_soon(answer_again)
        assert await resumed.run() is Outcome.COMPLETED
    assert [kind for kind, _ in rig.ended] == ["bias"]
    assert resumed.status()["prompt"] is None


def test_a_prompt_for_bias_asks_for_the_dark() -> None:
    sequence = Sequence(name="x", targets=Container(children=[Prompt(frame_type="bias")]))
    runner = Runner(sequence, Rig(), now=Rig().now)
    runner._prompt = Prompt(frame_type="bias")  # pyright: ignore[reportPrivateUsage]
    assert runner.status()["prompt"] == "dark"
