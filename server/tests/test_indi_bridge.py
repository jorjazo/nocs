"""The INDI mirror publishes a property's updates at most once a second (ADR 0037)."""

import asyncio

import pytest

from nocs.indi import (
    NumberElement,
    Property,
    PropertyDefined,
    PropertyDeleted,
    PropertyUpdated,
)
from nocs.indi.properties import PropertyState, PropertyType
from nocs.services import indi_bridge
from nocs.services.indi_bridge import IndiBridge
from nocs.state import StateStore

PATH = ("indi", "devices", "Telescope Simulator", "properties", "EQUATORIAL_EOD_COORD")


@pytest.fixture(autouse=True)
def coalesce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indi_bridge, "COALESCE", 0.2)


def coordinates() -> Property:
    prop = Property("Telescope Simulator", "EQUATORIAL_EOD_COORD", PropertyType.NUMBER)
    prop.elements = {"RA": NumberElement("RA", "RA"), "DEC": NumberElement("DEC", "Dec")}
    return prop


def move(bridge: IndiBridge, prop: Property, **values: float) -> None:
    for name, value in values.items():
        element = prop.elements[name]
        assert isinstance(element, NumberElement)
        element.value = value
    bridge._mirror(PropertyUpdated(prop, tuple(values)))  # pyright: ignore[reportPrivateUsage]


def value(store: StateStore, name: str) -> object:
    return store.get((*PATH, "elements", name, "value"))


async def test_updates_are_held_and_the_latest_values_published() -> None:
    store = StateStore()
    bridge = IndiBridge(store, "localhost", 7624)
    prop = coordinates()
    bridge._mirror(PropertyDefined(prop))  # pyright: ignore[reportPrivateUsage]
    move(bridge, prop, RA=1.0)
    assert value(store, "RA") == 1.0  # the first one at once
    version = store.version
    move(bridge, prop, RA=2.0)
    move(bridge, prop, DEC=-30.0)
    move(bridge, prop, RA=3.0)
    assert store.version == version
    assert value(store, "RA") == 1.0
    await asyncio.sleep(0.3)
    assert store.version == version + 1  # one patch for the three
    assert value(store, "RA") == 3.0
    assert value(store, "DEC") == -30.0


async def test_a_state_change_is_published_at_once() -> None:
    store = StateStore()
    bridge = IndiBridge(store, "localhost", 7624)
    prop = coordinates()
    bridge._mirror(PropertyDefined(prop))  # pyright: ignore[reportPrivateUsage]
    move(bridge, prop, RA=1.0)
    move(bridge, prop, DEC=-30.0)
    prop.state = PropertyState.ALERT
    move(bridge, prop, RA=2.0)
    assert store.get((*PATH, "state")) == "Alert"
    assert value(store, "RA") == 2.0
    assert value(store, "DEC") == -30.0  # held until then, published with it


async def test_a_deleted_property_does_not_come_back() -> None:
    store = StateStore()
    bridge = IndiBridge(store, "localhost", 7624)
    prop = coordinates()
    bridge._mirror(PropertyDefined(prop))  # pyright: ignore[reportPrivateUsage]
    move(bridge, prop, RA=1.0)
    move(bridge, prop, RA=2.0)
    bridge._mirror(PropertyDeleted(prop.device, prop.name))  # pyright: ignore[reportPrivateUsage]
    await asyncio.sleep(0.3)
    assert store.get(PATH) is None


async def test_only_what_changed_is_sent() -> None:
    store = StateStore()
    bridge = IndiBridge(store, "localhost", 7624)
    prop = coordinates()
    bridge._mirror(PropertyDefined(prop))  # pyright: ignore[reportPrivateUsage]
    version = store.version
    move(bridge, prop, RA=1.0, DEC=0.0)  # DEC as defined
    [patch] = store.patches_since(version) or []
    assert [op.path[len(PATH) :] for op in patch.ops] == [("elements", "RA", "value")]

    await asyncio.sleep(0.25)
    dec = prop.elements["DEC"]
    assert isinstance(dec, NumberElement)
    dec.max = 90.0  # a limit changed: the whole element
    version = store.version
    move(bridge, prop, RA=1.0, DEC=-30.0)
    [patch] = store.patches_since(version) or []
    assert [op.path[len(PATH) :] for op in patch.ops] == [("elements", "DEC")]
    assert store.get((*PATH, "elements", "DEC")) == {
        "label": "Dec",
        "value": -30.0,
        "format": "%g",
        "min": 0.0,
        "max": 90.0,
        "step": 0.0,
    }
