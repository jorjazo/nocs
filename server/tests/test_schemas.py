# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The state the server builds must match the documented (and exported) schema."""

import time

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schema import build
from nocs.api.schemas import AppState, IndiProperty
from nocs.config import Settings
from nocs.indi.properties import (
    BlobElement,
    LightElement,
    NumberElement,
    Permission,
    Property,
    PropertyState,
    PropertyType,
    SwitchElement,
    SwitchRule,
    TextElement,
)
from nocs.services.indi_bridge import property_to_json


def make(prop_type: PropertyType, *elements: object) -> Property:
    prop = Property("Dev", "PROP", prop_type, perm=Permission.READ_WRITE)
    for element in elements:
        assert isinstance(
            element, TextElement | NumberElement | SwitchElement | LightElement | BlobElement
        )
        prop.elements[element.name] = element
    return prop


@pytest.mark.parametrize(
    "prop",
    [
        make(PropertyType.TEXT, TextElement("T", "Text", "hello")),
        make(PropertyType.NUMBER, NumberElement("N", "Number", 1.5, "%g", 0, 10, 0.5)),
        make(PropertyType.SWITCH, SwitchElement("S", "Switch", True)),
        make(PropertyType.LIGHT, LightElement("L", "Light", PropertyState.ALERT)),
        make(PropertyType.BLOB, BlobElement("B", "Blob", ".fits", 2880, b"SIMPLE")),
    ],
    ids=lambda p: p.type.value,
)
def test_property_json_round_trips_through_schema(prop: Property) -> None:
    data = property_to_json(prop)
    assert IndiProperty.model_validate(data).model_dump(mode="json") == data


def test_switch_property_with_rule() -> None:
    prop = make(PropertyType.SWITCH, SwitchElement("A", "A", False))
    prop.rule = SwitchRule.ONE_OF_MANY
    assert IndiProperty.model_validate(property_to_json(prop)).rule == "OneOfMany"


def test_schema_export_has_every_wire_type() -> None:
    names = set(build()["$defs"])
    assert {"AppState", "Hello", "SnapshotMessage", "PatchMessage", "IndiProperty"} <= names


@pytest.mark.indi
def test_live_state_matches_schema(indi_address: tuple[str, int]) -> None:
    host, port = indi_address
    with TestClient(create_app(Settings(indi_host=host, indi_port=port))) as client:
        pair_owner(client)
        deadline = time.monotonic() + 10
        while True:
            state = client.get("/api/state").json()["state"]
            devices = state["indi"]["devices"]
            if len(devices) >= 5 and all("interfaces" in d for d in devices.values()):
                break
            assert time.monotonic() < deadline
            time.sleep(0.1)
        AppState.model_validate(state)
