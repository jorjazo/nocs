"""Find the Sun or the Moon by its brightness, and centre it (ADR 0049)."""

from nocs.finder.service import FinderError, FinderOptions, FinderService
from nocs.sky.bodies import Body

__all__ = ["Body", "FinderError", "FinderOptions", "FinderService"]
