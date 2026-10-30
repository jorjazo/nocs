"""Equipment profiles on disk."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from nocs.equipment import DeviceConfig, Optics, Profile, ProfileError, ProfileStore, Role


def rig() -> Profile:
    return Profile(
        name="AM5 + 2600MC",
        devices={
            Role.MAIN_CAMERA: DeviceConfig(driver="indi_asi_ccd", device="ZWO CCD ASI2600MC Pro"),
            Role.MOUNT: DeviceConfig(driver="indi_lx200am5", port="/dev/serial/by-id/usb-am5"),
        },
        imaging=Optics(focal_length=250, aperture=50),
    )


def test_put_get_list_delete(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    assert store.load_all() == {}
    store.put("am5", rig())
    assert store.get("am5") == rig()
    assert store.load_all() == {"am5": rig()}
    assert store.delete("am5")
    assert not store.delete("am5")
    assert store.get("am5") is None


def test_files_are_readable_json_without_nulls(tmp_path: Path) -> None:
    ProfileStore(tmp_path).put("am5", rig())
    text = (tmp_path / "profiles" / "am5.json").read_text()
    assert '"driver": "indi_asi_ccd"' in text
    assert "null" not in text


def test_unreadable_files_are_skipped(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.put("good", rig())
    (tmp_path / "profiles" / "broken.json").write_text("{")
    (tmp_path / "profiles" / "Not An Id.json").write_text(rig().model_dump_json())
    assert list(store.load_all()) == ["good"]


@pytest.mark.parametrize("profile_id", ["", "UPPER", "../escape", "a/b", "-dash-first", "x" * 65])
def test_invalid_ids_are_rejected(tmp_path: Path, profile_id: str) -> None:
    with pytest.raises(ProfileError):
        ProfileStore(tmp_path).put(profile_id, rig())


def test_active_profile_persists(tmp_path: Path) -> None:
    ProfileStore(tmp_path).active = "am5"
    assert ProfileStore(tmp_path).active == "am5"
    ProfileStore(tmp_path).active = None
    assert ProfileStore(tmp_path).active is None


@pytest.mark.parametrize("driver", ["", "indi asi", "indi_asi\nstop indi_x", "../bin/sh"])
def test_driver_names_cannot_inject_fifo_commands(driver: str) -> None:
    with pytest.raises(ValidationError):
        DeviceConfig(driver=driver)


def test_unknown_roles_and_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate({"name": "x", "devices": {"telescope": {"driver": "indi_x"}}})
    with pytest.raises(ValidationError):
        Profile.model_validate({"name": "x", "colour": "red"})
