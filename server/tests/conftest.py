import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest


@pytest.fixture
def indi_address() -> tuple[str, int]:
    """Address of an indiserver running the simulators, from NOCS_TEST_INDI=host:port.

    Integration tests are skipped when it is not set. Start one locally with
    ``docker compose -f dev/compose.yaml up -d`` and ``NOCS_TEST_INDI=localhost:7624``.
    """
    value = os.environ.get("NOCS_TEST_INDI")
    if not value:
        pytest.skip("NOCS_TEST_INDI not set")
    host, _, port = value.rpartition(":")
    return host, int(port)


@pytest.fixture(autouse=True, scope="session")
def test_hostname() -> Iterator[None]:
    """Let TestClient's ``Host: testserver`` in, as NOCS_HOSTNAMES would (ADR 0014).

    Session-scoped so that module-scoped apps get it too; not a default of nocsd.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("NOCS_HOSTNAMES", "testserver")
        yield


@pytest.fixture(autouse=True)
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every Settings() of a test away from the user's real configuration and data."""
    path = tmp_path / "config"
    monkeypatch.setenv("NOCS_CONFIG_DIR", str(path))
    monkeypatch.setenv("NOCS_DATA_DIR", str(tmp_path / "data"))
    return path


@pytest.fixture
def indi_fifo(indi_address: tuple[str, int]) -> Path:
    """indiserver's driver FIFO, from NOCS_TEST_INDI_FIFO (``../dev/.run/fifo`` with compose)."""
    value = os.environ.get("NOCS_TEST_INDI_FIFO")
    if not value:
        pytest.skip("NOCS_TEST_INDI_FIFO not set")
    return Path(value)


@dataclass(frozen=True)
class Phd2Setup:
    host: str
    port: int
    settings: Path
    """Where nocsd writes PHD2's settings, which PHD2's service imports."""
    indi_host: str
    """indiserver as PHD2 reaches it."""


@pytest.fixture
def phd2(indi_address: tuple[str, int]) -> Phd2Setup:
    """A headless PHD2 next to the INDI simulators, from NOCS_TEST_PHD2=host:port.

    With compose: ``NOCS_TEST_PHD2=localhost:4400 NOCS_TEST_PHD2_SETTINGS=../dev/.run/phd2.phd``;
    PHD2 reaches indiserver as ``indi`` (NOCS_TEST_PHD2_INDI_HOST to change it).
    """
    value = os.environ.get("NOCS_TEST_PHD2")
    settings = os.environ.get("NOCS_TEST_PHD2_SETTINGS")
    if not value or not settings:
        pytest.skip("NOCS_TEST_PHD2 and NOCS_TEST_PHD2_SETTINGS not set")
    host, _, port = value.rpartition(":")
    indi_host = os.environ.get("NOCS_TEST_PHD2_INDI_HOST", "indi")
    return Phd2Setup(host, int(port), Path(settings), indi_host)


@pytest.fixture(autouse=True)
def cheap_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hash test passphrases in a millisecond instead of a fifth of a second."""
    monkeypatch.setattr("nocs.auth.store.SCRYPT_N", 2**10)


@pytest.fixture
def astap_paths() -> tuple[Path, Path | None]:
    """The ASTAP solver from NOCS_TEST_ASTAP, and its databases from NOCS_TEST_ASTAP_DB
    (default: next to it). ``dev/astap/install.sh`` installs both in ``dev/.astap``."""
    value = os.environ.get("NOCS_TEST_ASTAP")
    if not value:
        pytest.skip("NOCS_TEST_ASTAP not set (e.g. ../dev/.astap/astap_cli)")
    database = os.environ.get("NOCS_TEST_ASTAP_DB")
    return Path(value), Path(database) if database else None
