"""Smoke test for StravaClient.

Hits the real Strava API. Requires .env with valid OAuth credentials
(reuses the same .env as test_oauth_live.py).

Run from repo root:
    python mcp-server/tests/test_client_live.py
"""

import logging
import sys
from pathlib import Path

# Make `paced_mcp` importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paced_mcp.auth.oauth_manager import OAuthError, OAuthManager
from paced_mcp.strava.client import (
    StravaAuthError,
    StravaClient,
    StravaError,
    StravaRateLimitError,
)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    print(f"Loading credentials from: {env_path}\n")

    try:
        manager = OAuthManager.from_env(env_path=env_path)
    except OAuthError as e:
        print(f"[FAIL] OAuth config error: {e}")
        sys.exit(1)

    with StravaClient(manager) as client:
        # 1. Connectivity check via /athlete
        try:
            athlete = client.get_athlete()
        except StravaAuthError as e:
            print(f"[FAIL] Auth error — re-authorize: {e}")
            sys.exit(1)
        except StravaRateLimitError as e:
            print(f"[FAIL] Rate limited on /athlete (scope={e.scope}, "
                  f"retry in {e.retry_after_sec}s)")
            sys.exit(1)
        except StravaError as e:
            print(f"[FAIL] /athlete error: {e}")
            sys.exit(1)

        print(f"[OK] Authenticated as: {athlete.get('firstname')} "
              f"{athlete.get('lastname')} (id={athlete.get('id')})")
        print()

        # 2. Recent activities — the main contract method
        days = 14
        try:
            activities = client.list_recent_activities(days=days)
        except StravaRateLimitError as e:
            print(f"[FAIL] Rate limited (scope={e.scope}, "
                  f"retry in {e.retry_after_sec}s, "
                  f"usage {e.usage[0]}/{e.limit[0]} short, "
                  f"{e.usage[1]}/{e.limit[1]} daily)")
            sys.exit(1)
        except StravaError as e:
            print(f"[FAIL] list_recent_activities error: {e}")
            sys.exit(1)

        print(f"[OK] Got {len(activities)} activities in the last {days} days")

        # Spot-check shape: each activity must have the fields Layer 2
        # depends on for get_recent_training_summary.
        expected_keys = {
            "id", "name", "sport_type", "start_date_local",
            "distance", "moving_time", "elapsed_time", "total_elevation_gain",
        }
        if activities:
            sample = activities[0]
            missing = expected_keys - sample.keys()
            if missing:
                print(f"[FAIL] First activity missing keys: {missing}")
                print(f"       Got keys: {sorted(sample.keys())}")
                sys.exit(1)
            print(f"[OK] Activity shape looks right (sample keys checked: "
                  f"{sorted(expected_keys)})")
            print()
            print("Most recent activity:")
            print(f"  {sample['start_date_local']}  "
                  f"{sample['sport_type']:<10}  "
                  f"{sample['distance']/1000:.2f} km  "
                  f"{sample['moving_time']/60:.1f} min  "
                  f"({sample['name']!r})")
        else:
            print("[INFO] No activities in window — shape check skipped.")

        print()
        print("Phase 1 client: PASS")


if __name__ == "__main__":
    main()
