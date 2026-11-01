"""Tonight's target: choose it and forget it (stage 3.6); ``plan.target`` shows it."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Response, status

from nocs.targets.plan import PlannedTarget, PlanService


def plan_router(plan: Callable[[], PlanService]) -> APIRouter:
    router = APIRouter(prefix="/api/plan")

    @router.put("/target", status_code=status.HTTP_204_NO_CONTENT)
    async def choose(target: PlannedTarget) -> Response:  # pyright: ignore[reportUnusedFunction]
        plan().set(target)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/target", status_code=status.HTTP_204_NO_CONTENT)
    async def forget() -> Response:  # pyright: ignore[reportUnusedFunction]
        plan().set(None)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
