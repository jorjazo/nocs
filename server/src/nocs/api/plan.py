"""The plan: its targets and lines, and starting it (``plan`` in the state shows it).

Pausing, resuming and stopping a plan that runs go through ``/api/sequence``: the
plan runs as the sequence ``plan``.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import JobStarted
from nocs.api.sequences import sequence_errors
from nocs.plan import NightPlan, PlanBusyError, PlanService, expand
from nocs.sequence.service import SequenceService


def plan_router(
    plan: Callable[[], PlanService], sequences: Callable[[], SequenceService]
) -> APIRouter:
    router = APIRouter(prefix="/api/plan")

    @router.get("")
    async def get() -> NightPlan:  # pyright: ignore[reportUnusedFunction]
        return plan().plan

    @router.put("", status_code=status.HTTP_204_NO_CONTENT)
    async def put(body: NightPlan) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Keep the plan; each line keeps the frames it has (``done`` is the server's).
        While it runs, what it does around its targets cannot change."""
        try:
            await plan().put(body, running=sequences().running_plan)
        except PlanBusyError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/targets/{target_id}/reset", status_code=status.HTTP_204_NO_CONTENT)
    async def reset(target_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Forget the frames a target's lines have."""
        try:
            await plan().reset(target_id)
        except KeyError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no target {target_id!r}") from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/start", status_code=status.HTTP_202_ACCEPTED)
    async def start() -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """Run the plan; guiding started by hand is stopped first (the plan guides under
        its own job when it is asked to)."""
        current = plan().plan
        if current.left == 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "no target of the plan has frames left"
            )
        with sequence_errors():
            await sequences().take_over_guiding()
            return JobStarted(job=sequences().start_plan(expand(current)))

    return router
