"""Strava API v3 client.

Thin HTTP wrapper around Strava's REST endpoints. Returns raw JSON —
data cleaning, unit conversion, and feature extraction belong to
Layer 2 (`paced_mcp.processing`), not here.

Responsibilities:
- Inject Bearer token from OAuthManager on every request.
- Refresh and retry once on 401 (token revoked or stale-cached).
- Surface and react to Strava's rate limits (see _check_rate_limits).
- Raise typed exceptions so callers can distinguish auth / rate-limit
  / network / API errors.

Usage:
    from paced_mcp.auth.oauth_manager import OAuthManager
    from paced_mcp.strava.client import StravaClient

    manager = OAuthManager.from_env()
    with StravaClient(manager) as client:
        athlete = client.get_athlete()
        recent = client.list_activities(after=int(time.time()) - 14*86400)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ..auth.oauth_manager import OAuthManager

logger = logging.getLogger("paced.strava")

STRAVA_API_BASE = "https://www.strava.com/api/v3"

# Strava enforces two independent quotas. Both must hold.
#   short:  100 requests per 15-minute window (resets at :00, :15, :30, :45 UTC)
#   daily:  1000 requests per calendar day    (resets at 00:00 UTC)
# When either is exceeded, Strava returns HTTP 429.
RATE_LIMIT_SHORT_WINDOW_SEC = 15 * 60
RATE_LIMIT_WARN_THRESHOLD = 0.8  # log.warning when usage >= 80% of quota

# Cap matched to the get_recent_training_summary contract in
# docs/contracts/tools.yaml. Anything outside this range either has
# no value (days < 1) or risks exhausting the daily quota (days > 90
# might require many pages × many activities).
DAYS_MIN = 1
DAYS_MAX = 90


class StravaError(Exception):
    """Base class for any Strava client failure."""


class StravaAuthError(StravaError):
    """Raised when the access token is rejected and refresh did not help.

    Typically means the user revoked the app's authorization on
    https://www.strava.com/settings/apps and needs to re-authorize.
    """


class StravaRateLimitError(StravaError):
    """Raised when a Strava rate limit is exceeded.

    Attributes:
        scope: Which limit tripped — "short" (15-min) or "daily".
        retry_after_sec: Estimated seconds until the limit resets.
        usage: Current usage tuple (short_used, daily_used).
        limit: Quota tuple (short_limit, daily_limit).
    """

    def __init__(
        self,
        scope: str,
        retry_after_sec: int,
        usage: tuple[int, int],
        limit: tuple[int, int],
    ) -> None:
        self.scope = scope
        self.retry_after_sec = retry_after_sec
        self.usage = usage
        self.limit = limit
        super().__init__(
            f"Strava rate limit hit (scope={scope}, "
            f"usage={usage[0]}/{limit[0]} short, {usage[1]}/{limit[1]} daily); "
            f"retry after ~{retry_after_sec}s"
        )


class StravaClient:
    """Authenticated client for Strava API v3."""

    def __init__(
        self,
        oauth_manager: OAuthManager,
        base_url: str = STRAVA_API_BASE,
        timeout: float = 30.0,
    ) -> None:
        self.oauth = oauth_manager
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------
    # High-level endpoints
    # ------------------------------------------------------------------

    def get_athlete(self) -> dict[str, Any]:
        """Return the authenticated athlete's profile.

        Strava endpoint: GET /athlete
        Useful as a connectivity check (the /athlete endpoint is cheap
        and unambiguously requires `read` scope).
        """
        return self._request("GET", "/athlete")

    def list_activities(
        self,
        after: int | None = None,
        before: int | None = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List the authenticated athlete's activities, newest-first.

        Args:
            after:     Unix timestamp (seconds). Only activities started
                       AFTER this time are returned.
            before:    Unix timestamp (seconds). Only activities started
                       BEFORE this time are returned.
            page:      1-indexed page number.
            per_page:  Items per page. Strava cap is 200.

        Strava endpoint: GET /athlete/activities

        Note: Strava paginates. For >per_page activities, the caller
        iterates `page` until an empty list is returned. Auto-pagination
        is intentionally NOT done here — Layer 2 may want to bail early
        once it has enough activities for the requested window.
        """
        if per_page > 200:
            raise ValueError("per_page must be <= 200 (Strava API limit)")

        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before

        return self._request("GET", "/athlete/activities", params=params)

    def list_recent_activities(
        self,
        days: int = 14,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch every activity started in the last `days` days.

        This is the convenience method that maps onto the MCP tool
        `get_recent_training_summary` (see docs/contracts/tools.yaml).
        It auto-paginates through Strava until an empty page comes back.

        Args:
            days:     Look-back window in days. Constrained to
                      [DAYS_MIN, DAYS_MAX] to match the tool contract.
            per_page: Page size for the underlying Strava call. 100 is a
                      good balance — large enough that 14 days of an
                      active athlete fits in 1 request, small enough
                      that a single request stays well under timeout.

        Returns:
            A flat list of activity summary dicts (newest first), exactly
            as Strava returns them. No filtering, no unit conversion —
            Layer 2 turns these into the contract's `activities` array.
        """
        if not DAYS_MIN <= days <= DAYS_MAX:
            raise ValueError(
                f"days must be in [{DAYS_MIN}, {DAYS_MAX}] "
                f"(matches get_recent_training_summary contract); got {days}"
            )

        after = int(time.time()) - days * 86400
        all_activities: list[dict[str, Any]] = []
        page = 1

        while True:
            batch = self.list_activities(after=after, page=page, per_page=per_page)
            all_activities.extend(batch)
            # A short page (or empty one) means we've reached the end.
            if len(batch) < per_page:
                break
            page += 1

        logger.info(
            "Fetched %d activities from the last %d days (across %d page(s))",
            len(all_activities),
            days,
            page,
        )
        return all_activities

    def get_activity(
        self,
        activity_id: int,
        include_all_efforts: bool = False,
    ) -> dict[str, Any]:
        """Return full detail for a single activity.

        Strava endpoint: GET /activities/{id}

        Args:
            include_all_efforts: If True, include all segment efforts.
                                 Off by default — they balloon response size
                                 and Layer 2 doesn't need them for Phase 1.
        """
        params = {"include_all_efforts": str(include_all_efforts).lower()}
        return self._request("GET", f"/activities/{activity_id}", params=params)

    def get_activity_streams(
        self,
        activity_id: int,
        keys: list[str],
        resolution: str = "high",
    ) -> dict[str, Any]:
        """Return time-series streams for an activity, keyed by stream type.

        Strava endpoint: GET /activities/{id}/streams

        Args:
            keys: Stream types to fetch. Common values:
                  time, distance, latlng, altitude, velocity_smooth,
                  heartrate, cadence, watts, temp, moving, grade_smooth.
            resolution: "low" | "medium" | "high". High is per-second-ish;
                        Layer 2 downsamples as needed.

        Returns:
            A dict like {"heartrate": {"data": [...], "series_type": "time", ...}}
            because we always pass key_by_type=true.
        """
        if not keys:
            raise ValueError("keys must contain at least one stream type")

        params = {
            "keys": ",".join(keys),
            "key_by_type": "true",
            "series_type": "time",
            "resolution": resolution,
        }
        return self._request(
            "GET", f"/activities/{activity_id}/streams", params=params
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> "StravaClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal request plumbing
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Execute an authenticated request with auth-retry and rate-limit checks.

        On 401, fetches a fresh token and retries ONCE. If the second
        attempt also returns 401, raises StravaAuthError — the refresh
        token itself is likely revoked.
        """
        url = f"{self.base_url}{path}"
        token = self.oauth.get_valid_token()
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}"}

        try:
            response = self._client.request(method, url, headers=headers, **kwargs)
        except httpx.RequestError as e:
            raise StravaError(f"Network error calling {method} {path}: {e}") from e

        if response.status_code == 401:
            logger.info("Got 401 from %s; forcing token refresh and retrying once.", path)
            # OAuthManager will refresh if the stored token is past expiry.
            # If our cached `token` was already valid-by-clock but Strava
            # rejected it (e.g. user revoked the app), get_valid_token()
            # will return the same token and we bail.
            new_token = self.oauth.get_valid_token()
            if new_token == token:
                raise StravaAuthError(
                    f"Strava returned 401 on {method} {path} with a locally-valid "
                    "token. Likely causes: (1) insufficient scope — the token from "
                    "Strava's settings page only grants 'read'; activity endpoints "
                    "need 'activity:read_all'. (2) the user revoked the app at "
                    "https://www.strava.com/settings/apps. Re-run the OAuth "
                    "authorization flow with scope=activity:read_all to fix (1)."
                )
            headers["Authorization"] = f"Bearer {new_token}"
            try:
                response = self._client.request(method, url, headers=headers, **kwargs)
            except httpx.RequestError as e:
                raise StravaError(f"Network error on retry of {method} {path}: {e}") from e

        # Inspect rate-limit headers and decide what to do BEFORE checking
        # the status code — a 429 IS a rate-limit signal, but we may also
        # want to react proactively when usage approaches the limit.
        self._check_rate_limits(response)

        if not response.is_success:
            raise StravaError(
                f"Strava API error {response.status_code} on {method} {path}: "
                f"{response.text[:500]}"
            )

        return response.json()

    def _check_rate_limits(self, response: httpx.Response) -> None:
        """Inspect Strava rate-limit headers and react to them.

        Policy: raise on 429 (let the caller decide how to back off);
        log.warning when usage crosses 80% so operators get a heads-up
        before quotas trip. We never sleep — this is a long-running
        MCP server and blocking the thread would hide caller bugs.

        Strava headers (sent on every response):
            X-RateLimit-Limit:  "<short>,<daily>"   e.g. "100,1000"
            X-RateLimit-Usage:  "<short>,<daily>"   e.g. "23,150"
        """
        limit_header = response.headers.get("X-RateLimit-Limit")
        usage_header = response.headers.get("X-RateLimit-Usage")

        # Some error responses (e.g. 401 from a malformed request) skip
        # the headers. Still need to surface 429 even without headers.
        if not limit_header or not usage_header:
            if response.status_code == 429:
                raise StravaRateLimitError(
                    scope="unknown",
                    retry_after_sec=_seconds_until_short_window_reset(),
                    usage=(0, 0),
                    limit=(0, 0),
                )
            return

        try:
            limit = _parse_rate_pair(limit_header)
            usage = _parse_rate_pair(usage_header)
        except ValueError:
            logger.warning(
                "Could not parse Strava rate-limit headers: limit=%r usage=%r",
                limit_header,
                usage_header,
            )
            return

        # Either quota tripping → 429. If both tripped, prefer the daily
        # error since waiting out the short window won't help the caller.
        if response.status_code == 429:
            if usage[1] >= limit[1]:
                scope = "daily"
                retry_after = _seconds_until_utc_midnight()
            else:
                scope = "short"
                retry_after = _seconds_until_short_window_reset()
            raise StravaRateLimitError(
                scope=scope,
                retry_after_sec=retry_after,
                usage=usage,
                limit=limit,
            )

        # Normal path: log debug always, warn when getting close.
        logger.debug(
            "Strava quota: short=%d/%d, daily=%d/%d",
            usage[0], limit[0], usage[1], limit[1],
        )
        for scope_name, used, cap in (
            ("short", usage[0], limit[0]),
            ("daily", usage[1], limit[1]),
        ):
            if cap > 0 and used / cap >= RATE_LIMIT_WARN_THRESHOLD:
                logger.warning(
                    "Strava %s quota at %d/%d (%.0f%%) — back off soon",
                    scope_name, used, cap, 100 * used / cap,
                )


def _parse_rate_pair(header_value: str) -> tuple[int, int]:
    """Parse a 'short,daily' header into (short, daily) ints."""
    parts = header_value.split(",")
    if len(parts) != 2:
        raise ValueError(f"expected 'short,daily', got {header_value!r}")
    return int(parts[0].strip()), int(parts[1].strip())


def _seconds_until_short_window_reset() -> int:
    """Seconds until the next 15-minute Strava window boundary (UTC)."""
    now = int(time.time())
    return RATE_LIMIT_SHORT_WINDOW_SEC - (now % RATE_LIMIT_SHORT_WINDOW_SEC)


def _seconds_until_utc_midnight() -> int:
    """Seconds until 00:00 UTC tomorrow."""
    now = datetime.now(timezone.utc)
    seconds_into_day = now.hour * 3600 + now.minute * 60 + now.second
    return 86400 - seconds_into_day
