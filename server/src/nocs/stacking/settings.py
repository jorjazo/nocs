"""Live stacking's settings, kept in ``<config dir>/stacking.json`` (ADR 0039).

Pydantic models only, so the API schemas can use them without importing the
stacking code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StackLook(BaseModel):
    """How the stack is shown (``nocs.stacking.stack.Look``)."""

    model_config = ConfigDict(extra="forbid")

    background: float = Field(default=0.25, ge=0.02, le=0.6, description="Sky level, 0..1.")
    shadows: float = Field(
        default=-2.8, ge=-8.0, le=0.0, description="Black point, MADs from the median."
    )
    saturation: float = Field(default=1.0, ge=0.0, le=3.0, description="Colour gain.")
    linked: bool = Field(default=False, description="One stretch for every channel.")


class StackSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool = False
    look: StackLook = Field(default_factory=StackLook)
