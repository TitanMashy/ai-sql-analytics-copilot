"""Issue a signed access token for local testing of AUTH_MODE=jwt.

This is a development helper, not an identity provider. It signs with the same HS256 secret the
backend validates with, so it only works when JWT_ALGORITHM=HS256. Production deployments obtain
tokens from their identity provider.

    python scripts/issue_token.py --customer-id 7
    python scripts/issue_token.py --admin

Reads JWT_SECRET, JWT_ISSUER and JWT_AUDIENCE from the environment (or backend/.env).
"""

import argparse
import sys
import time

import jwt

from app.core.auth import ANALYTICS_ADMIN_ROLE
from app.core.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subject", default="local-user", help="token subject (user id)")
    parser.add_argument("--customer-id", type=int, help="tenant the token is limited to")
    parser.add_argument("--admin", action="store_true", help="grant the all-customers role")
    parser.add_argument("--minutes", type=int, default=60, help="token lifetime")
    arguments = parser.parse_args()

    settings = get_settings()
    if settings.jwt_algorithm != "HS256" or not settings.jwt_secret:
        print("Set JWT_ALGORITHM=HS256 and JWT_SECRET (32+ characters) first.", file=sys.stderr)
        return 1
    if not settings.jwt_issuer or not settings.jwt_audience:
        print("Set JWT_ISSUER and JWT_AUDIENCE first.", file=sys.stderr)
        return 1
    if not arguments.admin and arguments.customer_id is None:
        print("Pass --customer-id N for a tenant token, or --admin.", file=sys.stderr)
        return 1

    claims = {
        "sub": arguments.subject,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": int(time.time()) + arguments.minutes * 60,
        "roles": [ANALYTICS_ADMIN_ROLE] if arguments.admin else ["analyst"],
    }
    if arguments.customer_id is not None:
        claims["customer_id"] = arguments.customer_id
    print(jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
