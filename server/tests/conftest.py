import os

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
