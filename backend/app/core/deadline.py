from __future__ import annotations

from time import monotonic


class RequestDeadlineExceeded(Exception):
    """Raised when the overall request time budget is spent."""


class Deadline:
    """A monotonic time budget shared by every step of one request.

    ``None`` means unbounded, which keeps direct service construction (tests, scripts) simple.
    """

    def __init__(self, seconds: float | None) -> None:
        self._expires_at = None if seconds is None else monotonic() + seconds

    def remaining(self) -> float | None:
        if self._expires_at is None:
            return None
        return max(0.0, self._expires_at - monotonic())

    def expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0

    def check(self) -> None:
        if self.expired():
            raise RequestDeadlineExceeded
