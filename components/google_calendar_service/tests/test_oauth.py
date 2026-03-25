"""Tests for OAuth helpers and auth endpoints in Google Calendar Service."""

import json
import urllib.parse
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import google_calendar_service.main as main_module
import google_calendar_service.settings as settings_module
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google_calendar_service.main import app
from google_calendar_service.session_store import OAuthStateRecord, optional_cookie
from google_calendar_service.session_store import cookie as session_cookie

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_FORBIDDEN = 403
HTTP_FOUND = 302
HTTP_BAD_GATEWAY = 502
OAUTH_STATE_TTL_SECONDS = 900

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Clear cached settings so env monkeypatching is applied per test."""
    settings_module.get_settings.cache_clear()


class TestAuthHelperFunctions:
    """Tests for centralized settings and OAuth helper behavior."""

    def test_get_settings_reads_required_oauth_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Load OAuth values from environment into settings."""
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "id-1")
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("GOOGLE_CALENDAR_REDIRECT_URI", "http://localhost:8000/auth/callback")
        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_STATE_TTL_SECONDS", str(OAUTH_STATE_TTL_SECONDS))

        settings = settings_module.get_settings()

        assert settings.oauth.require_client_id() == "id-1"
        assert settings.oauth.require_client_secret() == "secret-1"
        assert settings.oauth.require_redirect_uri() == "http://localhost:8000/auth/callback"
        assert settings.oauth.state_ttl_seconds == OAUTH_STATE_TTL_SECONDS

    def test_get_settings_raises_for_invalid_state_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reject invalid OAuth state TTL values through centralized settings."""
        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_STATE_TTL_SECONDS", "abc")
        with pytest.raises(ValueError, match="invalid literal for int"):
            settings_module.get_settings()

        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_STATE_TTL_SECONDS", "0")
        with pytest.raises(ValueError, match="GOOGLE_CALENDAR_OAUTH_STATE_TTL_SECONDS must be >= 1"):
            settings_module.get_settings()

    def test_build_google_authorization_url_contains_expected_params(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Build provider URL with expected OAuth parameters."""
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "id-1")
        monkeypatch.setenv("GOOGLE_CALENDAR_REDIRECT_URI", "http://localhost:8000/auth/callback")
        monkeypatch.setenv("GOOGLE_CALENDAR_SCOPES", "scope.a scope.b")
        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_PROMPT", "select_account")
        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")

        url = main_module._build_google_authorization_url(
            state="state-1",
            code_challenge="challenge-1",
        )
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert params["client_id"] == ["id-1"]
        assert params["redirect_uri"] == ["http://localhost:8000/auth/callback"]
        assert params["response_type"] == ["code"]
        assert params["scope"] == ["scope.a scope.b"]
        assert params["state"] == ["state-1"]
        assert params["code_challenge"] == ["challenge-1"]
        assert params["code_challenge_method"] == ["S256"]
        assert params["access_type"] == ["offline"]

    def test_get_settings_rejects_invalid_token_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reject non-https and non-whitelisted token endpoint hosts."""
        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_TOKEN_URL", "http://oauth2.googleapis.com/token")
        with pytest.raises(ValueError, match="must be a valid https URL"):
            settings_module.get_settings()

        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_TOKEN_URL", "https://evil.example.com/token")
        with pytest.raises(ValueError, match="host is not allowed"):
            settings_module.get_settings()

    def test_exchange_code_for_tokens_success_and_fallback_expiry(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Return tokens and use fallback expiry when provider value is invalid."""
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "id-1")
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("GOOGLE_CALENDAR_REDIRECT_URI", "http://localhost:8000/auth/callback")
        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token")

        class FakeResponse:
            is_error = False
            text = "ok"

            def json(self) -> dict[str, object]:
                return {
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": "not-an-int",
                }

        def fake_post_success(
            url: str,
            *,
            data: dict[str, str],
            timeout: int,
            headers: dict[str, str],
        ) -> FakeResponse:
            del url, data, timeout, headers
            return FakeResponse()

        monkeypatch.setattr(httpx, "post", fake_post_success)

        before = datetime.now(UTC)
        access_token, refresh_token, expires_at = main_module._exchange_code_for_tokens(
            code="code-1",
            code_verifier="verifier-1",
        )
        after = datetime.now(UTC)

        assert access_token == "access-1"
        assert refresh_token == "refresh-1"
        assert before + timedelta(seconds=3590) <= expires_at <= after + timedelta(seconds=3610)

    def test_exchange_code_for_tokens_handles_provider_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handle request/network error, HTTP error response, bad JSON, and missing token."""
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "id-1")
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("GOOGLE_CALENDAR_REDIRECT_URI", "http://localhost:8000/auth/callback")
        monkeypatch.setenv("GOOGLE_CALENDAR_OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token")

        request = httpx.Request("POST", "https://oauth2.googleapis.com/token")

        def raise_request_error(
            url: str,
            *,
            data: dict[str, str],
            timeout: int,
            headers: dict[str, str],
        ) -> None:
            del url, data, timeout, headers
            msg = "boom"
            raise httpx.RequestError(msg, request=request)

        monkeypatch.setattr(httpx, "post", raise_request_error)
        with pytest.raises(HTTPException) as exc_request_error:
            main_module._exchange_code_for_tokens(code="code-1", code_verifier="verifier-1")
        assert exc_request_error.value.status_code == HTTP_BAD_GATEWAY

        class ErrorResponse:
            is_error = True
            text = "bad request"

            def json(self) -> dict[str, object]:
                return {}

        def fake_post_error_response(
            url: str,
            *,
            data: dict[str, str],
            timeout: int,
            headers: dict[str, str],
        ) -> ErrorResponse:
            del url, data, timeout, headers
            return ErrorResponse()

        monkeypatch.setattr(httpx, "post", fake_post_error_response)
        with pytest.raises(HTTPException) as exc_http_error:
            main_module._exchange_code_for_tokens(code="code-1", code_verifier="verifier-1")
        assert exc_http_error.value.status_code == HTTP_BAD_GATEWAY

        class NonJsonResponse:
            is_error = False
            text = "not-json"

            def json(self) -> dict[str, object]:
                msg = "bad json"
                raise json.JSONDecodeError(msg, doc="not-json", pos=0)

        def fake_post_non_json(
            url: str,
            *,
            data: dict[str, str],
            timeout: int,
            headers: dict[str, str],
        ) -> NonJsonResponse:
            del url, data, timeout, headers
            return NonJsonResponse()

        monkeypatch.setattr(httpx, "post", fake_post_non_json)
        with pytest.raises(HTTPException) as exc_bad_json:
            main_module._exchange_code_for_tokens(code="code-1", code_verifier="verifier-1")
        assert exc_bad_json.value.status_code == HTTP_BAD_GATEWAY

        class MissingTokenResponse:
            is_error = False
            text = "ok"

            def json(self) -> dict[str, object]:
                return {"refresh_token": "refresh-1", "expires_in": 1200}

        def fake_post_missing_token(
            url: str,
            *,
            data: dict[str, str],
            timeout: int,
            headers: dict[str, str],
        ) -> MissingTokenResponse:
            del url, data, timeout, headers
            return MissingTokenResponse()

        monkeypatch.setattr(httpx, "post", fake_post_missing_token)
        with pytest.raises(HTTPException) as exc_missing_access:
            main_module._exchange_code_for_tokens(code="code-1", code_verifier="verifier-1")
        assert exc_missing_access.value.status_code == HTTP_BAD_GATEWAY


class TestAuthEndpoints:
    """Tests for auth/login, auth/callback, and auth/logout endpoints."""

    def test_login_redirects_and_clears_previous_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Delete previous session, create new one, and redirect to provider."""
        previous_session_id = UUID("00000000-0000-0000-0000-000000000111")
        new_session_id = UUID("00000000-0000-0000-0000-000000000222")
        observed: dict[str, object] = {}

        async def fake_delete_session(*, session_id: UUID) -> None:
            observed["deleted_session_id"] = session_id

        async def fake_create_session() -> UUID:
            return new_session_id

        async def fake_set_oauth_handshake_in_session(
            *,
            session_id: UUID,
            state: str,
            code_verifier: str,
            ttl_seconds: int,
        ) -> None:
            observed["set_session_id"] = session_id
            observed["set_state"] = state
            observed["set_code_verifier"] = code_verifier
            observed["set_ttl"] = ttl_seconds

        app.dependency_overrides[optional_cookie] = lambda: previous_session_id
        monkeypatch.setattr(main_module, "delete_session", fake_delete_session)
        monkeypatch.setattr(main_module, "create_session", fake_create_session)
        monkeypatch.setattr(main_module, "generate_oauth_state", lambda: "state-1")
        monkeypatch.setattr(main_module, "generate_pkce_pair", lambda: ("verifier-1", "challenge-1"))
        fake_settings = SimpleNamespace(
            oauth=SimpleNamespace(state_ttl_seconds=123),
            session=SimpleNamespace(cookie_name="google_calendar_session_id"),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: fake_settings)
        monkeypatch.setattr(main_module, "set_oauth_handshake_in_session", fake_set_oauth_handshake_in_session)
        monkeypatch.setattr(
            main_module,
            "_build_google_authorization_url",
            lambda *, state, code_challenge: f"https://example.com/oauth?state={state}&cc={code_challenge}",
        )

        try:
            response = client.get("/auth/login", follow_redirects=False)
        finally:
            app.dependency_overrides.pop(optional_cookie, None)

        assert response.status_code == HTTP_FOUND
        assert response.headers["location"] == "https://example.com/oauth?state=state-1&cc=challenge-1"
        assert observed["deleted_session_id"] == previous_session_id
        assert observed["set_session_id"] == new_session_id
        assert observed["set_state"] == "state-1"
        assert observed["set_code_verifier"] == "verifier-1"

    def test_logout_without_session_returns_403(self) -> None:
        """Return 403 when no session cookie is present."""
        client.cookies.clear()
        response = client.post("/auth/logout")

        assert response.status_code == HTTP_FORBIDDEN

    def test_callback_error_branches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return 400 for provider error, missing code, missing state, and invalid handshake."""
        session_id = UUID("00000000-0000-0000-0000-000000000333")
        app.dependency_overrides[session_cookie] = lambda: session_id

        async def fake_consume_none(*, session_id: UUID, state: str) -> None:
            del session_id
            del state

        monkeypatch.setattr(main_module, "consume_oauth_handshake_from_session", fake_consume_none)

        try:
            provider_error = client.get("/auth/callback", params={"error": "access_denied"})
            assert provider_error.status_code == HTTP_BAD_REQUEST

            missing_code = client.get("/auth/callback", params={"state": "state-1"})
            assert missing_code.status_code == HTTP_BAD_REQUEST

            missing_state = client.get("/auth/callback", params={"code": "code-1"})
            assert missing_state.status_code == HTTP_BAD_REQUEST

            invalid_state = client.get("/auth/callback", params={"code": "code-1", "state": "state-1"})
            assert invalid_state.status_code == HTTP_BAD_REQUEST
        finally:
            app.dependency_overrides.pop(session_cookie, None)

    def test_callback_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exchange code and persist tokens when callback is valid."""
        session_id = UUID("00000000-0000-0000-0000-000000000444")
        expires_at = datetime.now(UTC) + timedelta(seconds=3600)
        observed: dict[str, object] = {}

        async def fake_consume(
            *,
            session_id: UUID,
            state: str,
        ) -> OAuthStateRecord:
            observed["consume_session_id"] = session_id
            observed["consume_state"] = state
            return OAuthStateRecord(
                state=state,
                code_verifier="verifier-1",
                expires_at=expires_at,
            )

        def fake_exchange(*, code: str, code_verifier: str) -> tuple[str, str | None, datetime]:
            observed["exchange_code"] = code
            observed["exchange_verifier"] = code_verifier
            return ("access-1", "refresh-1", expires_at)

        async def fake_set_tokens(
            *,
            session_id: UUID,
            access_token: str,
            expires_at: datetime,
            refresh_token: str | None = None,
        ) -> None:
            observed["set_session_id"] = session_id
            observed["set_access_token"] = access_token
            observed["set_refresh_token"] = refresh_token
            observed["set_expires_at"] = expires_at

        app.dependency_overrides[session_cookie] = lambda: session_id
        monkeypatch.setattr(main_module, "consume_oauth_handshake_from_session", fake_consume)
        monkeypatch.setattr(main_module, "_exchange_code_for_tokens", fake_exchange)
        monkeypatch.setattr(main_module, "set_oauth_tokens_in_session", fake_set_tokens)

        try:
            response = client.get(
                "/auth/callback",
                params={
                    "code": "code-1",
                    "state": "state-1",
                },
            )
        finally:
            app.dependency_overrides.pop(session_cookie, None)

        assert response.status_code == HTTP_OK
        assert response.json() == {"status": "authenticated"}
        assert observed["consume_session_id"] == session_id
        assert observed["consume_state"] == "state-1"
        assert observed["exchange_code"] == "code-1"
        assert observed["exchange_verifier"] == "verifier-1"
        assert observed["set_session_id"] == session_id
        assert observed["set_access_token"] == "access-1"
        assert observed["set_refresh_token"] == "refresh-1"
