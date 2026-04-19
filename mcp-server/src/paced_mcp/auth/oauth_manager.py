"""Strava OAuth 2.0 token management.

Handles:
- Initial token bootstrap from .env refresh_token
- Automatic token refresh when expired
- Persistent storage via TokenStore

Usage:
    manager = OAuthManager.from_env()
    token = manager.get_valid_token()  # Always returns a non-expired token
"""

import logging
import os
import time
from pathlib import Path

import httpx

from .token_store import TokenData, TokenStore

logger = logging.getLogger("paced.auth")

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


class OAuthError(Exception):
    """Raised when OAuth operations fail."""


class OAuthManager:
    """Manages Strava OAuth tokens with automatic refresh.

    The manager ensures you always get a valid access token:
    1. Check SQLite store for existing token
    2. If expired (or within 5-min buffer), refresh it
    3. Save the new token back to store
    4. Return valid access token
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        store: TokenStore,
        initial_refresh_token: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.store = store
        self._initial_refresh_token = initial_refresh_token

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "OAuthManager":
        """Create OAuthManager from environment variables.

        Reads: STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, PACED_DB_PATH
        Optionally loads from a .env file if env_path is provided.

        Args:
            env_path: Optional path to .env file. If provided, loads
                      variables from it (does not override existing env vars).
        """
        if env_path:
            _load_dotenv(Path(env_path))

        client_id = os.environ.get("STRAVA_CLIENT_ID")
        client_secret = os.environ.get("STRAVA_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise OAuthError(
                "STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set. "
                "Copy .env.example to .env and fill in your Strava API credentials."
            )

        db_path = os.environ.get("PACED_DB_PATH", "~/.paced/paced.db")
        store = TokenStore(db_path)

        # The refresh token from Strava's API settings page, used for
        # first-time bootstrap only. After first refresh, the store
        # holds the latest refresh_token.
        initial_refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            store=store,
            initial_refresh_token=initial_refresh_token,
        )

    def get_valid_token(self) -> str:
        """Return a valid (non-expired) access token.

        Refreshes automatically if the stored token is expired.

        Returns:
            A valid Strava access token string.

        Raises:
            OAuthError: If no token is available and no refresh token
                        is configured, or if the refresh request fails.
        """
        token = self.store.load()

        # First-time bootstrap: no token in store yet
        if token is None:
            if not self._initial_refresh_token:
                raise OAuthError(
                    "No stored token found and STRAVA_REFRESH_TOKEN is not set. "
                    "Add your refresh token from https://www.strava.com/settings/api "
                    "to .env as STRAVA_REFRESH_TOKEN for first-time setup."
                )
            logger.info("No stored token found. Bootstrapping from initial refresh token.")
            token = self._refresh(self._initial_refresh_token)
            self.store.save(token)
            return token.access_token

        # Token still valid
        if not token.is_expired:
            logger.debug("Token valid until %s", token.expires_at)
            return token.access_token

        # Token expired — refresh it
        logger.info("Token expired. Refreshing...")
        new_token = self._refresh(token.refresh_token)
        self.store.save(new_token)
        return new_token.access_token

    def _refresh(self, refresh_token: str) -> TokenData:
        """Exchange a refresh token for a new token set.

        Args:
            refresh_token: The refresh token to exchange.

        Returns:
            A new TokenData with fresh access_token, refresh_token, and expiry.

        Raises:
            OAuthError: If the Strava API returns an error.
        """
        try:
            response = httpx.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise OAuthError(
                f"Strava token refresh failed ({e.response.status_code}): "
                f"{e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise OAuthError(f"Network error during token refresh: {e}") from e

        data = response.json()

        new_token = TokenData(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            scope=data.get("scope", "read"),
        )

        logger.info(
            "Token refreshed successfully. New expiry: %s",
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(new_token.expires_at)),
        )
        return new_token


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader. Does not override existing env vars."""
    path = path.expanduser()
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")

        if key not in os.environ:
            os.environ[key] = value
