"""SQLite-based token persistence for Strava OAuth tokens.

Stores access_token, refresh_token, and expiry so that tokens
survive process restarts. Single-file, zero-config.
"""

import sqlite3
import time
from pathlib import Path
from dataclasses import dataclass


@dataclass
class TokenData:
    """Represents a stored OAuth token set."""
    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp
    scope: str = "read"

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 5-minute buffer)."""
        return time.time() >= (self.expires_at - 300)


class TokenStore:
    """SQLite store for OAuth tokens.

    Usage:
        store = TokenStore("~/.paced/paced.db")
        store.save(token_data)
        token = store.load()
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tokens table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'read',
                    updated_at INTEGER NOT NULL
                )
            """)

    def save(self, token: TokenData) -> None:
        """Save or update the token. Only one token set is stored (id=1)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO tokens (id, access_token, refresh_token, expires_at, scope, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    scope = excluded.scope,
                    updated_at = excluded.updated_at
            """, (
                token.access_token,
                token.refresh_token,
                token.expires_at,
                token.scope,
                int(time.time()),
            ))

    def load(self) -> TokenData | None:
        """Load the stored token, or None if no token exists."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT access_token, refresh_token, expires_at, scope FROM tokens WHERE id = 1"
            ).fetchone()

        if row is None:
            return None

        return TokenData(
            access_token=row[0],
            refresh_token=row[1],
            expires_at=row[2],
            scope=row[3],
        )

    def clear(self) -> None:
        """Delete stored tokens (for logout / re-auth)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM tokens")
