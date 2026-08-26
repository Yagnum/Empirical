"""Mint a Clerk session token so you can call the API by hand.

WHY THIS EXISTS
    Every route except /health wants `Authorization: Bearer <Clerk session
    token>`. In the browser Clerk mints that token for you. In Swagger, curl
    or Postman there is no browser, so this script asks Clerk's Backend API
    for one directly, using the same CLERK_SECRET_KEY the server verifies
    against.

HOW IT WORKS (two calls, because Clerk separates the two ideas)
    1. POST /v1/sessions          create a session *for* a user - the
                                  server-side equivalent of signing in.
    2. POST /v1/sessions/{id}/tokens
                                  mint a short-lived JWT for that session.
                                  `expires_in_seconds` may be raised to at
                                  most 3600 (one hour); the default is 60,
                                  which is fine for a browser that refreshes
                                  silently and useless for poking at /docs.

    Docs: https://clerk.com/docs/reference/backend-api/tag/Sessions
          https://github.com/clerk/clerk-sdk-python/blob/main/docs/sdks/sessions/README.md

USAGE (from app/api)
    uv run python scripts/dev_token.py                 # the E2E test user
    uv run python scripts/dev_token.py user_ABC123     # some other user

    # Swagger: open http://localhost:8000/docs, click Authorize, paste it.
    # curl:
    TOKEN=$(uv run python scripts/dev_token.py)
    curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/accounts/me

The script prints the token and nothing else, so it can be captured in a
shell variable. It never prints CLERK_SECRET_KEY. The token is a bearer
credential for a real user: treat it like a password and let it expire.

DEVELOPMENT ONLY. Sessions created this way are real sessions; they show up
in the Clerk dashboard and can be revoked there.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clerk_backend_api import Clerk  # noqa: E402

from config import settings  # noqa: E402

# The user the end-to-end tests sign in as. Overridable on the command line.
DEFAULT_USER_ID = "user_3INlz3murnCCQRMRamt6STBHIBJ"

# Clerk's ceiling for a session token. Anything larger is rejected.
MAX_EXPIRES_IN_SECONDS = 3600


def mint(user_id: str) -> str:
    if not settings.clerk_secret_key:
        raise SystemExit("CLERK_SECRET_KEY is not set (see .env at the repo root)")

    with Clerk(bearer_auth=settings.clerk_secret_key) as clerk:
        session = clerk.sessions.create(request={"user_id": user_id})
        if session is None or not getattr(session, "id", None):
            raise SystemExit(f"Clerk did not create a session for {user_id}")

        token = clerk.sessions.create_token(
            session_id=session.id,
            expires_in_seconds=MAX_EXPIRES_IN_SECONDS,
        )
        jwt = getattr(token, "jwt", None)
        if not jwt:
            raise SystemExit("Clerk returned a session token with no jwt field")
        return jwt


if __name__ == "__main__":
    print(mint(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_USER_ID))
