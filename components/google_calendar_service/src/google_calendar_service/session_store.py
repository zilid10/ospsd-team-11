"""Session and OAuth utilities for the Google Calendar service.

Uses fastapi-sessions for in-memory session storage. OAuth handshake data
and tokens are stored within the session. Defines cookie, backend, and
verifier used by FastAPI routes.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi_sessions.backends.implementations import InMemoryBackend  # type: ignore[import-untyped]
from fastapi_sessions.frontends.implementations import CookieParameters, SessionCookie  # type: ignore[import-untyped]
from fastapi_sessions.session_verifier import SessionVerifier  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict


class OAuthStateRecord(BaseModel):
    """Temporary OAuth handshake payload."""

    model_config = ConfigDict(frozen=True)

    state: str
    code_verifier: str
    expires_at: datetime


class OAuthTokenRecord(BaseModel):
    """OAuth token data stored in the current session."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    expires_at: datetime
    refresh_token: str | None = None


class SessionData(BaseModel):
    """Session payload stored by fastapi-sessions."""

    oauth_state: str | None = None
    oauth_code_verifier: str | None = None
    oauth_state_expires_at: datetime | None = None

    oauth_access_token: str | None = None
    oauth_refresh_token: str | None = None
    oauth_token_expires_at: datetime | None = None

    def with_oauth_handshake(self, *, state: str, code_verifier: str, ttl_seconds: int) -> SessionData:
        """Return a copy with OAuth handshake values set."""
        if ttl_seconds <= 0:
            err_msg = f"invalid ttl_seconds: {ttl_seconds} (must be > 0)"
            raise ValueError(err_msg)

        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "oauth_state": state,
                "oauth_code_verifier": code_verifier,
                "oauth_state_expires_at": now + timedelta(seconds=ttl_seconds),
            },
        )

    def get_oauth_handshake(self, *, state: str, now: datetime | None = None) -> OAuthStateRecord | None:
        """Get handshake data if valid; returns record or None."""
        current_time = now or datetime.now(UTC)

        if self.oauth_state is None or self.oauth_code_verifier is None or self.oauth_state_expires_at is None:
            return None
        if state != self.oauth_state:
            return None
        if self.oauth_state_expires_at <= current_time:
            return None

        return OAuthStateRecord(
            state=self.oauth_state,
            code_verifier=self.oauth_code_verifier,
            expires_at=self.oauth_state_expires_at,
        )

    def clear_oauth_handshake(self) -> SessionData:
        """Return a copy with OAuth handshake values cleared."""
        return self.model_copy(
            update={
                "oauth_state": None,
                "oauth_code_verifier": None,
                "oauth_state_expires_at": None,
            },
        )

    def with_oauth_tokens(self, *, access_token: str, refresh_token: str | None = None, expires_at: datetime) -> SessionData:
        """Return a copy with OAuth token values set/updated."""
        expires_at_utc = _to_utc(expires_at)
        persisted_refresh = refresh_token if refresh_token is not None else self.oauth_refresh_token

        return self.clear_oauth_handshake().model_copy(
            update={
                "oauth_access_token": access_token,
                "oauth_token_expires_at": expires_at_utc,
                "oauth_refresh_token": persisted_refresh,
            },
        )

    def get_oauth_tokens(self) -> OAuthTokenRecord | None:
        """Return OAuth token record from session fields, if complete."""
        if self.oauth_access_token is None or self.oauth_token_expires_at is None:
            return None

        return OAuthTokenRecord(
            access_token=self.oauth_access_token,
            expires_at=self.oauth_token_expires_at,
            refresh_token=self.oauth_refresh_token,
        )

    def clear_oauth_tokens(self) -> SessionData:
        """Return a copy with OAuth token fields cleared."""
        return self.model_copy(
            update={
                "oauth_access_token": None,
                "oauth_refresh_token": None,
                "oauth_token_expires_at": None,
            },
        )


def _to_utc(value: datetime) -> datetime:
    """Convert datetime to UTC timezone."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def generate_oauth_state(num_bytes: int = 32) -> str:
    """Generate a cryptographically-random OAuth state."""
    return secrets.token_urlsafe(num_bytes)


def generate_pkce_pair(verifier_bytes: int = 64) -> tuple[str, str]:
    """Generate PKCE (code_verifier, code_challenge) using S256."""
    code_verifier = secrets.token_urlsafe(verifier_bytes)
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


cookie = SessionCookie(
    cookie_name="google_calendar_session_id",
    identifier="google_calendar_service_verifier",
    auto_error=True,
    secret_key=os.getenv("GOOGLE_CALENDAR_SESSION_SECRET", "dev-only-change-me"),
    cookie_params=CookieParameters(),
)

backend = InMemoryBackend[UUID, SessionData]()


class BasicSessionVerifier(SessionVerifier[UUID, SessionData]):  # type: ignore[misc]
    """Session verifier used by fastapi dependency injection."""

    def __init__(
        self,
        *,
        identifier: str,
        auto_error: bool,
        backend: InMemoryBackend[UUID, SessionData],
        auth_http_exception: HTTPException,
    ) -> None:
        """Initialize the verifier."""
        self._identifier = identifier
        self._auto_error = auto_error
        self._backend = backend
        self._auth_http_exception = auth_http_exception

    @property
    def identifier(self) -> str:
        """Return the unique identifier for this verifier."""
        return self._identifier

    @property
    def backend(self) -> InMemoryBackend[UUID, SessionData]:
        """Return the session backend instance."""
        return self._backend

    @property
    def auto_error(self) -> bool:
        """Return whether to raise HTTPException on auth failure."""
        return self._auto_error

    @property
    def auth_http_exception(self) -> HTTPException:
        """Return the HTTPException to raise for auth errors."""
        return self._auth_http_exception

    def verify_session(self, model: SessionData) -> bool:
        """If the session exists, it is valid."""
        assert model
        return True


verifier = BasicSessionVerifier(
    identifier="google_calendar_service_verifier",
    auto_error=True,
    backend=backend,
    auth_http_exception=HTTPException(status_code=403, detail="invalid session"),
)


# async helpers for routes/services
async def create_session() -> UUID:
    """Create a new session and persist it in session backend."""
    session_id = uuid4()
    await backend.create(session_id, SessionData())
    return session_id


async def read_session(*, session_id: UUID) -> SessionData | None:
    """Read session payload by session id."""
    return cast("SessionData | None", await backend.read(session_id))


async def delete_session(*, session_id: UUID) -> None:
    """Delete session by session id."""
    await backend.delete(session_id)


async def set_oauth_handshake_in_session(*, session_id: UUID, state: str, code_verifier: str, ttl_seconds: int) -> SessionData:
    """Set OAuth handshake values into existing session data."""
    current = cast("SessionData | None", await backend.read(session_id))
    if current is None:
        err_msg = f"cannot set OAuth handshake: session {session_id} not found"
        raise KeyError(err_msg)

    updated = current.with_oauth_handshake(
        state=state,
        code_verifier=code_verifier,
        ttl_seconds=ttl_seconds,
    )
    await backend.create(session_id, updated)
    return updated


async def consume_oauth_handshake_from_session(*, session_id: UUID, state: str) -> OAuthStateRecord | None:
    """Consume OAuth handshake values from session if valid."""
    current = cast("SessionData | None", await backend.read(session_id))
    if current is None:
        return None

    record = current.get_oauth_handshake(state=state)
    await backend.create(session_id, current.clear_oauth_handshake())
    return record


async def set_oauth_tokens_in_session(
    *,
    session_id: UUID,
    access_token: str,
    expires_at: datetime,
    refresh_token: str | None = None,
) -> SessionData:
    """Set OAuth tokens in session data."""
    current = cast("SessionData | None", await backend.read(session_id))
    if current is None:
        err_msg = f"cannot set OAuth tokens: session {session_id} not found"
        raise KeyError(err_msg)

    updated = current.with_oauth_tokens(
        access_token=access_token,
        expires_at=expires_at,
        refresh_token=refresh_token,
    )
    await backend.create(session_id, updated)
    return updated


async def get_oauth_tokens_from_session(*, session_id: UUID) -> OAuthTokenRecord | None:
    """Read OAuth token record from session data."""
    current = cast("SessionData | None", await backend.read(session_id))
    if current is None:
        return None
    return current.get_oauth_tokens()


async def clear_oauth_tokens_in_session(*, session_id: UUID) -> SessionData | None:
    """Clear OAuth token fields from session data."""
    current = cast("SessionData | None", await backend.read(session_id))
    if current is None:
        return None

    updated = current.clear_oauth_tokens()
    await backend.create(session_id, updated)
    return updated
