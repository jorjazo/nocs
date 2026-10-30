import os
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


@pytest.fixture(autouse=True)
def cheap_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hash test passphrases in a millisecond instead of a fifth of a second."""
    monkeypatch.setattr("nocs.auth.store.SCRYPT_N", 2**10)
