"""FastAPI service endpoints for the Google Calendar service component."""

from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID  # noqa: TC003 - required at runtime for FastAPI/Pydantic annotation resolution

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from fastapi_sessions.frontends.session_frontend import FrontendError  # type: ignore[import-untyped]
from google_calendar_client_impl import CredentialsToken, GoogleCalendarClient, get_calendar_client_with_credentials

from google_calendar_service.models import (
    EventCreateRequest,
    EventEnvelope,
    EventsEnvelope,
    EventUpdateRequest,
    StatusResponse,
    to_event_response,
)
from google_calendar_service.session_store import (
    SessionData,
    clear_oauth_tokens_in_session,
    consume_oauth_handshake_from_session,
    cookie,
    create_session,
    delete_session,
    generate_oauth_state,
    generate_pkce_pair,
    optional_cookie,
    set_oauth_handshake_in_session,
    set_oauth_tokens_in_session,
    verifier,
)
from google_calendar_service.settings import get_settings

app = FastAPI(
    title="Google Calendar Service",
    version="0.1.0",
)


def _build_google_authorization_url(*, state: str, code_challenge: str) -> str:
    """Build Google OAuth authorization URL."""
    try:
        service_settings = get_settings()
        client_id = service_settings.oauth.require_client_id()
        redirect_uri = service_settings.oauth.require_redirect_uri()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": service_settings.oauth.scopes,
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": service_settings.oauth.prompt,
    }
    return f"{service_settings.oauth.auth_url}?{urllib.parse.urlencode(params)}"


def _exchange_code_for_tokens(*, code: str, code_verifier: str) -> tuple[str, str | None, datetime]:
    """Exchange auth code for OAuth tokens with Google."""
    try:
        service_settings = get_settings()
        client_id, client_secret, redirect_uri = service_settings.oauth.require_web_credentials()
        token_url = service_settings.oauth.token_url
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    form_data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }

    try:
        response = httpx.post(
            token_url,
            data=form_data,
            timeout=service_settings.oauth.token_request_timeout_seconds,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach token endpoint: {exc}",
        ) from exc

    if response.is_error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Token exchange failed with provider: {response.text}",
        )

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Provider returned a non-JSON token response",
        ) from exc

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Provider token response missing access_token",
        )

    refresh_token = payload.get("refresh_token")
    refresh_token_value = refresh_token if isinstance(refresh_token, str) and refresh_token else None

    raw_expires_in = payload.get("expires_in", 3600)
    try:
        expires_in = int(raw_expires_in)
    except (TypeError, ValueError):
        expires_in = 3600

    expires_at = datetime.now(UTC) + timedelta(seconds=max(expires_in, 1))
    return access_token, refresh_token_value, expires_at


def get_client(
    _session_id: Annotated[UUID, Depends(cookie)],
    session_data: Annotated[SessionData, Depends(verifier)],
) -> GoogleCalendarClient:
    """Get a GoogleCalendarClient instance with tokens from the current session."""
    tokens = session_data.get_oauth_tokens()
    if tokens is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No valid OAuth tokens found in session",
        )

    services_settings = get_settings()
    creds_token = CredentialsToken(
        client_id=services_settings.oauth.require_client_id(),
        client_secret=services_settings.oauth.require_client_secret(),
        token_uri=services_settings.oauth.token_url,
        scopes=services_settings.oauth.scopes.split(),
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )

    return get_calendar_client_with_credentials(creds_token=creds_token)


@app.get("/health")
def health() -> StatusResponse:
    """Return service health status."""
    return StatusResponse(status="ok")


@app.get("/auth/login")
async def login(previous_session_id: Annotated[UUID | FrontendError, Depends(optional_cookie)]) -> RedirectResponse:
    """Start OAuth login flow and redirect to Google consent screen."""
    if not isinstance(previous_session_id, FrontendError):
        await delete_session(session_id=previous_session_id)

    session_id = await create_session()
    state = generate_oauth_state()
    code_verifier, code_challenge = generate_pkce_pair()

    await set_oauth_handshake_in_session(
        session_id=session_id,
        state=state,
        code_verifier=code_verifier,
        ttl_seconds=get_settings().oauth.state_ttl_seconds,
    )

    authorization_url = _build_google_authorization_url(state=state, code_challenge=code_challenge)
    response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
    cookie.attach_to_response(response, session_id)
    return response


@app.post("/auth/logout")
async def logout(session_id: Annotated[UUID, Depends(cookie)], response: Response) -> StatusResponse:
    """Log out by clearing OAuth token/session state and removing session cookie."""
    if session_id is not None:
        await clear_oauth_tokens_in_session(session_id=session_id)
        await delete_session(session_id=session_id)

    cookie.delete_from_response(response)
    return StatusResponse(status="logged out")


@app.get("/auth/callback")
async def callback(
    session_id: Annotated[UUID, Depends(cookie)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> StatusResponse:
    """Handle OAuth callback, validate state, exchange code, and persist session tokens."""
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth provider returned error: {error}",
        )

    if code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )

    if state is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth state",
        )

    handshake = await consume_oauth_handshake_from_session(session_id=session_id, state=state)
    if handshake is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

    access_token, refresh_token, expires_at = _exchange_code_for_tokens(
        code=code,
        code_verifier=handshake.code_verifier,
    )

    await set_oauth_tokens_in_session(
        session_id=session_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )

    return StatusResponse(status="authenticated")


@app.get("/events")
def list_events(
    client: Annotated[GoogleCalendarClient, Depends(get_client)], max_results: Annotated[int, Query(ge=1)] = 10
) -> EventsEnvelope:
    """List calendar events."""
    events = client.list_events(max_results=max_results)
    return EventsEnvelope(events=[to_event_response(event) for event in events])


@app.get("/events/{event_id}")
def get_event(client: Annotated[GoogleCalendarClient, Depends(get_client)], event_id: str) -> EventEnvelope:
    """Get a single calendar event by ID."""
    event = client.get_event(event_id)
    return EventEnvelope(event=to_event_response(event))


@app.post("/events")
def create_event(client: Annotated[GoogleCalendarClient, Depends(get_client)], event: EventCreateRequest) -> EventEnvelope:
    """Create a calendar event."""
    created_event = client.create_event(event.to_event_create())
    return EventEnvelope(event=to_event_response(created_event))


@app.patch("/events/{event_id}")
def update_event(
    client: Annotated[GoogleCalendarClient, Depends(get_client)], event_id: str, event: EventUpdateRequest
) -> EventEnvelope:
    """Update a calendar event."""
    updated_event = client.update_event(event_id, event.to_event_update())
    return EventEnvelope(event=to_event_response(updated_event))


@app.delete("/events/{event_id}")
def delete_event(client: Annotated[GoogleCalendarClient, Depends(get_client)], event_id: str) -> StatusResponse:
    """Delete a calendar event."""
    client.delete_event(event_id)
    return StatusResponse(status="deleted")
