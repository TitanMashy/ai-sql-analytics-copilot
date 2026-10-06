import os

import pytest


def require_integration_or_skip(reason: str) -> None:
    """Skip an integration test locally, but fail it in CI.

    CI sets ``REQUIRE_INTEGRATION=1`` so a missing database or Redis can never turn the
    permission, tenant-isolation, and shared-state tests into silent skips.
    """
    if os.environ.get("REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"Integration prerequisites are missing: {reason}")
    pytest.skip(reason)
