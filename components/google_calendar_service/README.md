# Google Calendar Service

## Purpose
This component is a FastAPI service that wraps the Google Calendar client and exposes it through HTTP endpoints. It serves as the deployment layer so the client can be used remotely instead of just locally.

## Current Status
- Initial FastAPI application scaffold created
- `/health` endpoint implemented for service checks
- Placeholder routes added for authentication and calendar operations
- Core logic integration and OAuth flow not yet implemented

## Planned Endpoints
- `GET /health` — Service health check
- `GET /auth/login` — Redirect user to OAuth provider
- `GET /auth/callback` — Handle OAuth callback and token exchange
- `GET /events` — Retrieve calendar events
- `POST /events` — Create a new calendar event
- `DELETE /events/{event_id}` — Delete a calendar event