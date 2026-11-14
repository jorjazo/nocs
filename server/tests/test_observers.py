import copy

import pytest

from nocs.api.observers import observer_patch, observer_state
from nocs.api.schemas import AppState
from nocs.state import Json, Op, Patch, StateStore

SITE: dict[str, Json] = {"latitude": -30.03, "longitude": -70.67, "elevation": 700.0}
COORD: dict[str, Json] = {"type": "number", "elements": {"LAT": {"value": -30.03}}}


def full_state() -> dict[str, Json]:
    return {
        "mount": {"device": "AM5", "ra": 1.0, "site": SITE, "site_check": "same"},
        "sites": {"active": "lab", "saved": {"lab": {"name": "Lab", **SITE}}},
        "gps": {
            "connected": True,
            "fix": "3d",
            "latitude": -30.03,
            "longitude": -70.67,
            "elevation": 700,
            "time": "2026-11-14T03:00:00Z",
            "site": "lab",
        },
        "network": {
            "mode": "station",
            "ssid": "Home",
            "ap_ssid": "NOCS-1234",
            "known": ["Home", "Office"],
            "joining": "Office",
            "last_join": {"ssid": "Home", "ok": True, "error": None, "at": None},
        },
        "indi": {
            "devices": {
                "AM5": {"properties": {"GEOGRAPHIC_COORD": COORD, "EQUATORIAL_EOD_COORD": {}}},
                "GPSD": {"properties": {"GEOGRAPHIC_COORD": COORD}},
            },
            "messages": [
                {"device": "AM5", "timestamp": None, "text": "Slew complete"},
                {
                    "device": "AM5",
                    "timestamp": None,
                    "text": "Observer location updated: Latitude 30:01:48 (-30.03) Longitude …",
                },
            ],
        },
    }


def test_observers_get_no_location_or_networks() -> None:
    state = full_state()
    before = copy.deepcopy(state)
    view = observer_state(state)
    assert state == before  # the owner's snapshot is left alone
    assert "sites" not in view
    assert view["mount"] == {"device": "AM5", "ra": 1.0, "site": None, "site_check": "same"}
    assert view["gps"] == {
        "connected": True,
        "fix": "3d",
        "latitude": None,
        "longitude": None,
        "elevation": None,
        "time": "2026-11-14T03:00:00Z",
        "site": None,
    }
    assert view["network"] == {
        "mode": "station",
        "ssid": None,
        "ap_ssid": "NOCS-1234",  # the box's own access point, on the air anyway
        "known": [],
        "joining": None,
        "last_join": None,
    }
    assert view["indi"] == {
        "devices": {
            "AM5": {"properties": {"EQUATORIAL_EOD_COORD": {}}},
            "GPSD": {"properties": {}},
        },
        "messages": [{"device": "AM5", "timestamp": None, "text": "Slew complete"}],
    }
    assert "-30.03" not in repr(view)
    assert "Home" not in repr(view)


def test_missing_parts_stay_missing() -> None:
    assert observer_state({}) == {}
    assert observer_state({"mount": None, "gps": None}) == {"mount": None, "gps": None}


def test_redacted_state_is_still_valid() -> None:
    """What the server publishes still matches the schema once redacted."""
    store = StateStore()
    store.set(
        ("gps",),
        {
            "connected": True,
            "fix": "3d",
            "latitude": 1.0,
            "longitude": 2.0,
            "elevation": 3,
            "time": None,
            "site": "x",
        },
    )
    AppState.model_validate(observer_state(store.snapshot()))


@pytest.mark.parametrize(
    "ops",
    [
        # inside a hidden node
        [Op("set", ("mount", "site", "latitude"), 1.0)],
        [Op("set", ("sites", "saved", "lab", "name"), "Home")],
        [Op("delete", ("sites", "saved", "lab"))],
        [Op("set", ("indi", "devices", "AM5", "properties", "GEOGRAPHIC_COORD", "state"), "Ok")],
        # at a hidden node
        [Op("set", ("mount", "site"), SITE)],
        [Op("set", ("sites",), {"active": None, "saved": {}})],
        [Op("delete", ("sites",))],
        [Op("set", ("network", "known"), ["Neighbour"])],
        [Op("set", ("indi", "devices", "GPSD", "properties", "GEOGRAPHIC_COORD"), COORD)],
        [Op("delete", ("indi", "devices", "GPSD", "properties", "GEOGRAPHIC_COORD"))],
        [
            Op(
                "set",
                ("indi", "messages"),
                [{"device": None, "timestamp": None, "text": "GPS fix acquired"}],
            )
        ],
        # above hidden nodes
        [Op("set", ("mount",), {"device": "AM7", "site": SITE})],
        [Op("set", ("gps",), {"latitude": 5.0, "longitude": 6.0, "fix": "2d"})],
        [Op("set", ("network",), {"ssid": "Cafe", "known": ["Cafe"]})],
        [Op("set", ("indi", "devices", "AM7"), {"properties": {"GEOGRAPHIC_COORD": COORD}})],
        [Op("set", ("indi",), {"devices": {}, "messages": []})],
        [Op("delete", ("mount",))],
        [Op("delete", ("indi", "devices", "AM5"))],
        # elsewhere
        [Op("set", ("mount", "ra"), 2.0), Op("set", ("gps", "fix"), "none")],
    ],
)
def test_patches_keep_observers_in_step(ops: list[Op]) -> None:
    """Observers applying their patches to their snapshot hold what they would get as a
    new snapshot: a patch never brings back what the snapshot left out."""
    owner = StateStore()
    with owner.transaction():
        for key, value in full_state().items():
            owner.set((key,), value)
    observer = StateStore()
    with observer.transaction():
        for key, value in observer_state(owner.snapshot()).items():
            observer.set((key,), value)

    with owner.transaction():
        for op in ops:
            owner.set(op.path, op.value) if op.op == "set" else owner.delete(op.path)
    seen = observer_patch(Patch(owner.version, tuple(ops)))
    assert seen.version == owner.version
    for op in seen.ops:
        observer.set(op.path, op.value) if op.op == "set" else observer.delete(op.path)
    assert observer.snapshot() == observer_state(owner.snapshot())


def test_a_patch_of_hidden_changes_only_keeps_its_version() -> None:
    patch = Patch(7, (Op("set", ("network", "ssid"), "Home"), Op("delete", ("sites",))))
    assert observer_patch(patch) == Patch(7, (Op("set", ("network", "ssid"), None),))
    assert observer_patch(Patch(8, (Op("delete", ("sites",)),))) == Patch(8, ())
