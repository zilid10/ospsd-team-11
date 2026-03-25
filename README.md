# Calendar Client — OSPSD Team 11

## Purpose

This project implements a Calendar Client. The interface defines a contract for calendar operations (creating, reading, updating, and deleting events), while the concrete implementation targets Google Calendar via its API, and an initial FastAPI service layer that exposes calendar functionality over HTTP.


## Architecture

```
.
├── components/
│   ├── calendar_client_api/          # Interface
│   │   ├── src/calendar_client_api/
│   │   │   ├── client.py             # CalendarClient ABC
│   │   │   ├── event.py              # Event contract, Attendee + EventCreate + EventUpdate dataclasses
│   │   │   └── registry.py           # Registry + get_client()
│   │   └── tests/
│   │       └── test_client.py        # Unit tests: Client ABC class, get_client()
│   │       └── test_event.py         # Unit tests: Event contract, DTOs
│   │       └── test_registry.py      # Unit tests: registry
│   └── google_calendar_client_impl/  # Concrete implementation
│       ├── src/google_calendar_client_impl/
│       │   ├── client_impl.py        # GoogleCalendarClient
│       │   └── event_impl.py         # GoogleCalendarEvent
│       └── tests/
│           ├── test_authentication.py # Unit tests: auth flows (env, file, interactive, refresh)
│           ├── test_client_crud.py    # Unit tests: create, read, update, delete operations
│           └── test_event_impl.py     # Unit tests: event parsing and serialization
├── tests/
│   ├── integration/                  # DI wiring and cross-component tests
│   └── e2e/                          # End-to-end tests against real APIs
├── docs/                             # Documentation Source Files
├── mkdocs.yml
├── pyproject.toml                    # workspace config
└── .circleci/config.yml              # CI pipeline
```

## Setup

### Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** — the package manager for this project

### Installation

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
# Clone the repository
git clone <repo-url> && cd <repo-name>
```

## Toolchain Usage

| Tool | Purpose | Command |
|------|---------|---------|
| **uv** | Dependency & workspace management | `uv sync --all-packages --extra dev` |
| **ruff** | Linting & formatting | `ruff check .` / `ruff format .` |
| **mypy** | Static type checking (strict mode) | `mypy .` |
| **pytest** | Test runner with coverage (≥ 85 % threshold) | `pytest` |
| **MkDocs** | Documentation site | `mkdocs serve` / `mkdocs build` |
| **CircleCI** | Continuous integration | Triggered on push (see `.circleci/config.yml`) |

## Testing

Tests are organized into three tiers using pytest markers:

| Tier | Marker | What it covers |
|------|--------|----------------|
| **Unit** | `@pytest.mark.unit` | Isolated tests per component (ABC contracts, registry, CRUD, auth, event parsing) |
| **Integration** | `@pytest.mark.integration` | DI wiring: auto-registration, factory behavior, type hierarchies, error propagation |
| **E2E** | `@pytest.mark.e2e` | Full system tests against real Google Calendar API |

### Running tests locally

```bash
# Run all tests
uv run pytest

# Run only unit tests
uv run pytest -m unit

# Run only integration tests
uv run pytest -m integration

# Run with coverage report
uv run pytest --cov=components/calendar_client_api/src --cov=components/google_calendar_client_impl/src

# Run a specific test file
uv run pytest tests/integration/test_client_integration.py -v
```

### Linting and formatting

```bash
# Check for lint errors
uv run ruff check .

# Auto-fix lint errors
uv run ruff check . --fix

