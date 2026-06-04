# FastAPI Authentication & User Management Service

[![FastAPI](https://img.shields.io/badge/FastAPI-0.136.3+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-4169E1.svg?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7+-DC382D.svg?style=flat&logo=redis&logoColor=white)](https://redis.io/)
[![Linter: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A robust, enterprise-grade authentication and user management backend built with **FastAPI**, **SQLAlchemy** (asynchronous), and **Redis**. Designed with best-practice security patterns, clean architecture, and performance in mind.

---

## 🚀 Key Features

*   **🔒 Secure Password Hashing:** Uses `Argon2` (via `pwdlib`) for strong, modern password hashing. Includes timing-attack mitigation (using bcrypt-hashed dummy values for non-existent users) and automatic silent rehashing when configuration upgrades are made.
*   **🔑 Stateless JWT Authentication with Stateful Revocation:** Generates short-lived JWT access tokens and long-lived refresh tokens. Blacklists logged-out or rotated tokens in Redis using their unique JWT ID (`jti`).
*   **♻️ Refresh Token Rotation (RTR):** Protects against replay attacks. Every time a refresh token is used, it is rotated and the old one is blacklisted.
*   **🚨 Nuclear Session Revocation:** If a blacklisted refresh token is reused (indicating a potential token theft), **all sessions** for that user are immediately revoked.
*   **🗄️ Fully Asynchronous DB Stack:** Combines `SQLAlchemy 2.0` (async engine), `asyncpg` driver, and `Alembic` for migrations.
*   **⚡ High-Performance Redis Pool:** Uses a shared connection pool via `redis-py` (async client) to prevent connection leaks under high traffic, caching user tokens, blacklists, and rate-limiting.
*   **🛠️ Developer Convenience:** Pre-configured environment settings via Pydantic, automated migrations using a helper script (`migrate.sh`), and code styling with `Ruff`.

---

## 🏗️ Architecture & Project Structure

The project follows a clean service-oriented architecture separating the route layers, core logic, database access, and validation schemas.

```text
FastAPI Server/
├── alembic/                # Alembic database migration scripts & versions
│   └── versions/           # Version history files (e.g. 0001_create_users_table)
├── app/
│   ├── core/               # Configuration settings, security helper libraries
│   │   ├── config.py       # Pydantic Settings management (loads .env)
│   │   └── security.py     # Hashing (Argon2), JWT token sign/decode functions
│   ├── db/                 # DB connections, sessions, & redis client initializers
│   │   ├── redis.py        # Redis client pool, key schemas (blacklist, cache)
│   │   └── sessions.py     # SQLAlchemy Async Engine, AsyncSession, and get_db dependency
│   ├── dependencies/       # Shared FastAPI route dependencies
│   │   └── auth.py         # Token parsing, current active user/superuser check
│   ├── models/             # SQLAlchemy ORM Models
│   │   ├── base.py         # Declarative base & TimestampMixin for audit trails
│   │   └── user.py         # User ORM model
│   ├── routes/             # FastAPI Route routers
│   │   ├── auth.py         # Authentication endpoints (register, login, refresh, logout, me)
│   │   └── main.py         # Global Router matching prefixes (e.g. /api/v1)
│   ├── schemas/            # Pydantic validation schemas
│   │   ├── auth.py         # Request/Response models for token operations
│   │   ├── shared.py       # Shared payload models
│   │   └── user.py         # Create, Read, Update, and Summary user models
│   ├── services/           # Service layer encapsulating business logic
│   │   └── auth.py         # AuthService (registration, login, refresh logic)
│   └── main.py             # FastAPI App creation, lifespan startup/shutdown, CORS
├── alembic.ini             # Alembic configuration
├── migrate.sh              # Bash helper script for Alembic migrations
├── pyproject.toml          # Project dependencies and tool configurations (using uv)
├── requirement.txt         # Standard requirements format (for fallback installs)
└── uv.lock                 # Lock file for uv dependency manager
```

---

## 🔒 Security Implementation Details

### 1. Token-Based Auth Flow
```mermaid
sequenceDiagram
    autonumber
    Client->>API (Router): POST /auth/login (credentials)
    API (Router)->>Service: AuthService.login()
    Service->>Database: Fetch user & verify Argon2 password hash
    Service->>Service: Generate JWT Access & Refresh Token (unique jtis)
    Service-->>Client: Return TokenPair (access_token, refresh_token)
    Note over Client, API (Router): Access routes with Bearer <access_token>
```

### 2. Refresh Token Rotation & Token Theft Protection
*   **Rotation:** When a client issues `POST /auth/refresh`, the `AuthService` decodes the refresh token, checks that it is not blacklisted, blacklists its `jti` in Redis, and issues a *brand new* access + refresh token pair.
*   **Theft Mitigation:** If an attacker steals a refresh token and tries to use it *after* the legitimate client has already rotated it, the backend catches the `jti` in the blacklist. This triggers the **nuclear option**:
    *   The service instantly writes a `revoke_all:{user_id}` flag in Redis with a timestamp.
    *   Any future token verification checks will reject *any* token issued prior to this timestamp, logging out all active devices for the compromised user.

### 3. Password Verification timing attacks
*   During login, if a user is not found, the service performs a password verification check against a dummy bcrypt hash. This ensures that the response timing remains identical whether the user exists or not, mitigating user enumeration timing attacks.

---

## 🛠️ Setup & Local Installation

### Prerequisites
*   **Python 3.12+**
*   **PostgreSQL** (running and accessible)
*   **Redis** (running and accessible)

### 1. Clone the repository and initialize virtual environment
It is highly recommended to use [uv](https://github.com/astral-sh/uv) for fast package management:
```bash
# Clone the repository
cd "FastAPI Server"

# Create and activate virtual environment
uv venv
source .venv/bin/activate
```

Alternatively, standard `pip` can be used:
```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies
```bash
# Using uv (recommended)
uv sync

# Using pip
pip install -r requirement.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the project root folder. You can use the values below as a reference:

```env
APP_NAME="FastAPI Server"
ENVIRONMENT="dev"
SECRET_KEY="your-super-secret-random-key"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Note: Database URL MUST use the asyncpg driver
DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/your_db_name"
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

REDIS_URL="redis://localhost:6379/0"
REDIS_MAX_CONNECTIONS=20
```

---

## 🗄️ Database Migrations

The project uses `Alembic` for database schema migrations. A convenience script `migrate.sh` is provided in the project root.

> [!IMPORTANT]
> Always run migrations from the project root directory. Do not run them from inside `alembic/`.

### Common Commands:

*   **Apply pending migrations:**
    ```bash
    bash migrate.sh upgrade
    ```
*   **Autogenerate a new migration from model changes:**
    ```bash
    bash migrate.sh generate "add new field to user model"
    ```
*   **Roll back the last migration:**
    ```bash
    bash migrate.sh downgrade -1
    ```
*   **Check migration history:**
    ```bash
    bash migrate.sh history
    ```
*   **Reset database to empty state (Downgrade to base):**
    ```bash
    bash migrate.sh reset
    ```

---

## ⚡ Running the API Server

Launch the development server using FastAPI's standard entrypoint:

```bash
# Using uv
uv run fastapi dev

# Or directly using uvicorn
uvicorn app.main:app --reload
```

The server will start running at `http://127.0.0.1:8000`.

### API Documentation
*   **Interactive OpenAPI Docs (Swagger UI):** Available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
    *   *Note:* The documentation Swagger UI utilizes `OAuth2PasswordRequestForm` so you can use the **"Authorize"** button directly to test secure endpoints.
*   *Note:* ReDocs are disabled by default in `app/main.py`.

---

## 🔌 API Endpoints Reference

All API routes are prefixed with `/api/v1`.

### 📂 Authentication Module (`/api/v1/auth`)

| Method | Endpoint | Description | Auth Required | Request Payload / Params | Success Response (200/201) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **POST** | `/register` | Register a new user account | No | `UserCreate` (email, username, password) | `UserRead` (created user data) |
| **POST** | `/login` | Authenticate & get Access + Refresh token pair | No | Form Data (`username` or `email`, `password`) | `TokenResponse` (token pair, expiry) |
| **POST** | `/refresh` | Rotate old refresh token for a new token pair | No | `RefreshRequest` (refresh_token) | `TokenResponse` (rotated token pair) |
| **POST** | `/logout` | Logout & blacklist tokens | **Yes** (Access Token) | Optional `RefreshRequest` | `MessageResponse` ("Successfully logged out.") |
| **GET** | `/me` | Get profile details of authenticated user | **Yes** (Access Token) | None | `UserRead` (user details) |

---

## 🛠️ Code Quality & Testing

### Code Quality (Ruff)
Ruff is configured in `pyproject.toml` as a linter and formatter. To lint or format the codebase, run:
```bash
# Run linter checks
uv run ruff check .

# Auto-fix fixable linter errors
uv run ruff check . --fix

# Format code
uv run ruff format .
```

### Running Tests
The project is configured for testing using `pytest` and `pytest-asyncio`.
```bash
# Run all tests
uv run pytest

# Run tests with test coverage output
uv run pytest --cov=app
```
