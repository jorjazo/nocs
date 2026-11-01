"""Sequences: their definitions, and starting, pausing and stopping one (ADR 0031)."""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Callable, Generator

import anyio
from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import (
    JobStarted,
    SequenceEstimate,
    SequencePauseRequest,
    SequenceStopRequest,
)
from nocs.devices import DeviceError
from nocs.imaging import CameraNotReadyError
from nocs.jobs import ResourceBusyError
from nocs.sequence import Sequence, SequenceError
from nocs.sequence.model import Template
from nocs.sequence.service import SequenceBusyError, SequenceService


def sequences_router(sequences: Callable[[], SequenceService]) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/sequences")
    async def all() -> dict[str, Sequence]:  # pyright: ignore[reportUnusedFunction]
        return sequences().all()

    @router.get("/sequences/{sequence_id}")
    async def get(sequence_id: str) -> Sequence:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            sequence = sequences().get(sequence_id)
        if sequence is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no sequence {sequence_id!r}")
        return sequence

    @router.put("/sequences/{sequence_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def put(sequence_id: str, sequence: Sequence) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            sequences().put(sequence_id, sequence)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/sequences/{sequence_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete(sequence_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            if not sequences().delete(sequence_id):
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no sequence {sequence_id!r}")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/sequences/{sequence_id}/template", status_code=status.HTTP_204_NO_CONTENT)
    async def put_template(sequence_id: str, template: Template) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Build the sequence from a template and keep it (with the template)."""
        with _errors():
            sequences().put_template(sequence_id, template)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/sequences/estimate")
    async def estimate(template: Template) -> SequenceEstimate:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            found = await anyio.to_thread.run_sync(sequences().estimate, template)
        return SequenceEstimate(**dataclasses.asdict(found))

    @router.post("/sequences/{sequence_id}/start", status_code=status.HTTP_202_ACCEPTED)
    async def start(sequence_id: str) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            return JobStarted(job=sequences().start(sequence_id))

    @router.post("/sequence/pause", status_code=status.HTTP_204_NO_CONTENT)
    async def pause(request: SequencePauseRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            sequences().pause(now=request.now)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/sequence/resume", status_code=status.HTTP_204_NO_CONTENT)
    async def resume() -> Response:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            sequences().resume()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/sequence/stop", status_code=status.HTTP_204_NO_CONTENT)
    async def stop(request: SequenceStopRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            sequences().stop(run_end=request.run_end, now=request.now)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


@contextlib.contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no sequence {e.args[0]!r}") from e
    except (ResourceBusyError, SequenceBusyError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except CameraNotReadyError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except (SequenceError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (DeviceError, ConnectionError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
