"""Live stacking (ADR 0039): the switch, a new stack, the look; ``stack`` shows it."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Response, status

from nocs.api.schemas import StackSwitchRequest
from nocs.stacking.service import LiveStackService
from nocs.stacking.settings import StackLook


def stacking_router(stacking: Callable[[], LiveStackService]) -> APIRouter:
    router = APIRouter(prefix="/api/stack")

    @router.put("", status_code=status.HTTP_204_NO_CONTENT)
    async def switch(body: StackSwitchRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Stack the main camera's lights as they arrive, or stop (ends every stack)."""
        await stacking().set_on(body.on)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
    async def reset() -> Response:  # pyright: ignore[reportUnusedFunction]
        """End the stack: the next frame starts a new one."""
        await stacking().reset()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/look", status_code=status.HTTP_204_NO_CONTENT)
    async def look(body: StackLook) -> Response:  # pyright: ignore[reportUnusedFunction]
        """How the stack is shown; the current stack is shown with it at once."""
        await stacking().set_look(body)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
