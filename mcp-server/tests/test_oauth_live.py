"""Quick smoke test for OAuth token refresh.

Run from repo root:
    python -m mcp-server.tests.test_oauth_live

Requires .env with valid STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET,
and STRAVA_REFRESH_TOKEN.
"""

import sys
from pathlib import Path

# Add parent to path so we can import paced_mcp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paced_mcp.auth.oauth_manager import OAuthManager, OAuthError


def main() -> None:
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"

    print(f"Loading credentials from: {env_path}")
    print()

    try:
        manager = OAuthManager.from_env(env_path=env_path)
    except OAuthError as e:
        print(f"[FAIL] Configuration error: {e}")
        sys.exit(1)

    print(f"Client ID: {manager.client_id}")
    print()

    try:
        token = manager.get_valid_token()
    except OAuthError as e:
        print(f"[FAIL] Token refresh failed: {e}")
        sys.exit(1)

    print(f"[OK] Got valid access token: {token[:8]}...")
    print()

    # Quick API test: fetch athlete profile
    import httpx

    response = httpx.get(
        "https://www.strava.com/api/v3/athlete",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    if response.status_code == 200:
        athlete = response.json()
        print(f"[OK] Authenticated as: {athlete.get('firstname')} {athlete.get('lastname')}")
        print(f"     City: {athlete.get('city')}, {athlete.get('country')}")
        print()
        print("Phase 1 OAuth: PASS")
    else:
        print(f"[FAIL] API returned {response.status_code}: {response.text}")
        sys.exit(1)


if __name__ == "__main__":
    main()
