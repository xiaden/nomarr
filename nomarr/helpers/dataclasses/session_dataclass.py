"""Domain model for authenticated application sessions.

The session token is the natural identity of a session.  Persistence-specific
column names and timestamp units stay behind the ``AppDb`` intent facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AuthSession:
    """An authenticated application session.

    ``expires_at`` is an epoch timestamp in seconds, matching the domain time
    helpers used by the authentication service.  The persistence facade maps
    it to the database's millisecond representation.
    """

    token: str
    expires_at: float
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("AuthSession.token must not be blank")
        if self.expires_at < 0:
            raise ValueError("AuthSession.expires_at must not be negative")


__all__ = ["AuthSession"]
