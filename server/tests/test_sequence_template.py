# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Templates: this target, these filters, tonight (phase 5.10)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner
from test_sequence import DIAGUITAS, NGC_253, Rig, frames

from nocs.api.app import create_app
from nocs.config import Settings
from nocs.sequence import Container, Event, ExposurePlan, Outcome, PlanRow, Runner
from nocs.sequence import sky as night_sky
from nocs.sequence.model import (
    Autofocus,
    AutofocusTrigger,
    Center,
    Cool,
    DitherTrigger,
    FlipTrigger,
    FocusPlan,
    Guide,
    RecenterTrigger,
    Slew,
    Template,
    Unpark,
    UntilDawn,
    Wait,
    WhileAbove,
)
from nocs.sequence.template import estimate, expand

LRGB = [
    PlanRow(filter="L", exposure=120, count=40),
    PlanRow(filter="R", exposure=180, count=10),
    PlanRow(filter="G", exposure=180, count=10),
    PlanRow(filter="B", exposure=180, count=10),
]


def ngc253(**fields: object) -> Template:
    return Template.model_validate(
        {"name": "NGC 253 LRGB", "target": NGC_253, "rows": LRGB, **fields}
    )


def test_a_template_makes_the_night_s_tree() -> None:
    sequence = expand(ngc253())
    assert sequence.template == ngc253()
    assert [c.kind for c in sequence.start.children] == ["unpark", "wait"]
    assert sequence.start.children[1] == Wait(dusk="astronomical")
    [target] = sequence.targets.children
    assert isinstance(target, Container)
    assert target.target == NGC_253
    assert target.conditions == [UntilDawn()]
    wait, imaging = target.children
    assert wait == Wait(altitude=30)
    assert isinstance(imaging, Container)
    assert imaging.conditions == [WhileAbove(altitude=30)]
    assert imaging.triggers == [AutofocusTrigger(temperature_change=1.0), FlipTrigger()]
    slew, focus, plan = imaging.children
    assert (slew, focus) == (Slew(), Autofocus())
    assert isinstance(plan, ExposurePlan)
    assert (plan.rows, plan.batch) == (LRGB, 5)
    assert [c.kind for c in sequence.end.children] == ["park", "warm"]


def test_options_change_the_tree() -> None:
    sequence = expand(
        ngc253(
            cooling=-10,
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
    [target] = sequence.targets.children
    assert isinstance(target, Container)
    assert target.conditions == []
    [imaging] = target.children
    assert isinstance(imaging, Container)
    assert imaging.conditions == []
    assert imaging.triggers[0] == AutofocusTrigger(filter_change=True, temperature_change=None)
    # The filter trigger focuses before the first frame: no autofocus of its own.
    assert [c.kind for c in imaging.children] == ["slew", "guide", "expose"]
    assert sequence.end.children[0] == Guide(on=False)
    assert [c.kind for c in sequence.end.children] == ["guide", "warm", "outputs"]
    assert expand(ngc253(focus=None)).targets != sequence.targets


def test_a_guided_template_dithers_every_n_frames() -> None:
    def triggers(template: Template) -> list[str]:
        [target] = expand(template).targets.children
        assert isinstance(target, Container)
        imaging = target.children[-1]
        assert isinstance(imaging, Container)
        return [t.kind for t in imaging.triggers]

    assert triggers(ngc253(guide=True, dither_every=3)) == ["autofocus", "flip", "dither"]
    # Without guiding there is nothing to dither.
    assert triggers(ngc253(dither_every=3, flip=False)) == ["autofocus"]
    [target] = expand(ngc253(guide=True, dither_every=3, dither_pixels=8)).targets.children
    assert isinstance(target, Container)
    imaging = target.children[-1]
    assert isinstance(imaging, Container)
    dither = imaging.triggers[-1]
    assert isinstance(dither, DitherTrigger)
    assert (dither.every, dither.dither.pixels) == (3, 8)


async def test_a_night_from_a_template_on_a_fake_rig() -> None:
    rig = Rig()
    begin = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)  # 17:00 at the site: daylight
    rig.time = begin
    events: list[Event] = []
    runner = Runner(
        expand(ngc253()),
        rig,
        now=rig.now,
        sleep=rig.sleep,
        place=lambda: DIAGUITAS,
        on_event=events.append,
    )
    assert await runner.run() is Outcome.COMPLETED
    taken = frames(rig)
    assert len(taken) == 70  # 2.8 h: the plan ends before NGC 253 sets
    assert taken[:5] == ["L 120"] * 5
    assert rig.calls[:3] == ["unpark", "slew NGC 253", "autofocus"]
    assert rig.calls[-2:] == ["park", "warm"]
    # It waited for the dark, within a look at the sky (30 s) of astronomical dusk.
    [dusk] = [e for e in events if e.message == "wait"][:1]
    waited = dusk.data["waited"]
    assert isinstance(waited, int)
    dark = begin + timedelta(seconds=waited)
    assert night_sky.dark(DIAGUITAS, dark, "astronomical")
    assert not night_sky.dark(DIAGUITAS, dark - timedelta(seconds=35), "astronomical")


def test_an_estimate_of_the_plan() -> None:
    template = ngc253()
    found = estimate(
        template, sensor=(6248, 4176), place=DIAGUITAS, now=datetime(2026, 11, 1, 1, tzinfo=UTC)
    )
    assert found.frames == 70
    assert found.integration == 40 * 120 + 30 * 180
    assert found.duration == found.integration + 70 * 3
    assert found.bytes is not None
    assert 3.6e9 < found.bytes < 3.7e9  # 70 frames of 52 MB
    assert found.window is not None
    assert 3 * 3600 < found.window < 7 * 3600
    # At 22:00 local NGC 253 is up in the dark: imaging starts now and the plan (2.9 h)
    # ends before the window closes.
    assert found.starts == datetime(2026, 11, 1, 1, tzinfo=UTC)
    assert found.ends == datetime(2026, 11, 1, 1, tzinfo=UTC) + timedelta(seconds=found.duration)
    # In the afternoon it starts when the window opens, and a long plan ends when it closes.
    afternoon = datetime(2026, 11, 1, 18, tzinfo=UTC)
    long = template.model_copy(update={"rows": [PlanRow(exposure=300, count=200)]})
    later = estimate(long, place=DIAGUITAS, now=afternoon)
    assert later.starts is not None
    assert later.ends is not None
    assert later.starts > afternoon
    assert (later.ends - later.starts).total_seconds() == pytest.approx(later.window, abs=1)
    blind = estimate(template)
    assert (blind.bytes, blind.window, blind.starts, blind.ends) == (None, None, None, None)


def test_the_api_builds_a_sequence_from_a_template(tmp_path: Path) -> None:
    settings = Settings(
        indi_host="127.0.0.1",
        indi_port=1,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        body = ngc253().model_dump(mode="json")
        assert client.put("/api/sequences/ngc253/template", json=body).status_code == 204
        stored = client.get("/api/sequences/ngc253").json()
        assert stored["template"] == body
        assert stored["targets"]["children"][0]["target"]["name"] == "NGC 253"
        response = client.post("/api/sequences/estimate", json=body)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "frames": 70,
            "integration": 10200.0,
            "duration": 10410.0,
            "bytes": None,
            "window": None,
            "starts": None,
            "ends": None,
        }
        expanded = client.post("/api/sequences/expand", json=body)
        assert expanded.status_code == 200, expanded.text
        assert expanded.json()["end"]["children"][0] == {"kind": "park"}
        bad = {**body, "target": {"name": "somewhere"}}
        assert client.put("/api/sequences/x/template", json=bad).status_code == 422


def test_a_template_centres_and_checks_the_pointing() -> None:
    [target] = expand(ngc253(center=True, recenter_every=10, recenter_drift=3)).targets.children
    assert isinstance(target, Container)
    imaging = target.children[-1]
    assert isinstance(imaging, Container)
    assert imaging.children[0] == Center()
    recenter = imaging.triggers[-1]
    assert isinstance(recenter, RecenterTrigger)
    assert (recenter.every, recenter.recenter.drift) == (10, 3)
    flip = imaging.triggers[-2]
    assert isinstance(flip, FlipTrigger)
    assert flip.flip.center == Center()  # a flip centres again
