# Urban Tandoor & Grill – Restaurant Assistant BOT

## Project overview

A modular Python backend for a restaurant assistant for the fictional Urban
Tandoor & Grill in Karachi, Pakistan. The project includes versioned restaurant
APIs and database health checks. OpenRouter and LangGraph configuration, a
bounded read-only database retrieval layer, the chat API, and short-lived
in-memory conversation context are in place.

The retrieval layer exposes approved reads for branches, suppliers, ingredients,
menu items, recipe ingredients, and branch menu availability. It uses fixed
SQLModel SELECT statements and validated arguments; it does not expose SQL
execution or supplier contact information to chatbot tools.

## Restaurant profile

The restaurant has two independently operated, 24/7 branches:

- `UTG-KHI-001` — PECHS
- `UTG-KHI-002` — Gulshan-e-Iqbal

Each branch maintains separate inventory, kitchen, and operations.

## Input data

The planned inventory workbook,
`Urban_Tandoor_Two_Branch_Inventory_Dataset.xlsx`, contains nine sheets:
`START_HERE`, `Dashboard`, `Branches`, `Ingredients`, `Branch_Stock`,
`Recipes`, `Menu_Availability`, `Stock_Movements`, and `Suppliers`.

The restaurant profile document is
`Urban_Tandoor_Grill_Restaurant_Profile.docx`. Both source files are stored in
`data/`. The workbook is a source for future validated imports; no restaurant
records are loaded automatically.

## Technology stack

- Python 3.12 and uv
- FastAPI and Uvicorn
- SQLModel, SQLAlchemy async, asyncpg, Alembic, and pgvector
- LangGraph, the official OpenAI Python SDK, and OpenRouter's compatible API
- Pandas and OpenPyXL
- Pydantic Settings
- pytest, pytest-asyncio, HTTPX, and Ruff

## Installation

From this project directory in PowerShell:

```powershell
uv venv
uv sync
```

Copy `.env.example` to `.env` in this project directory and set `DATABASE_URL`
to the connection string from Neon. Do not commit `.env` or share its contents.
The application adapts PostgreSQL URLs to asyncpg and requires SSL for database
connections.

Create an API key in the
[OpenRouter dashboard](https://openrouter.ai/settings/keys) and set
`OPENROUTER_API_KEY` in the local `.env` file. The default model is
`openrouter/free`, and the default API base URL is
`https://openrouter.ai/api/v1`; both can be overridden with
`OPENROUTER_MODEL` and `OPENROUTER_BASE_URL`. Keep the key on the server:
never include it in frontend code, API requests, logs, or committed files.
The key is optional for application startup.

## Run the development server

```powershell
uv run uvicorn app.main:app --reload
```

The health endpoint is available at `http://127.0.0.1:8000/health`.
The database health endpoint is available at
`http://127.0.0.1:8000/health/db` and returns HTTP 503 when the database is
unavailable or not configured.
Interactive Swagger documentation is available at
`http://127.0.0.1:8000/docs`.

## Branch API

The versioned API exposes branch listing and CRUD operations under
`/api/v1/branches`. Listing supports `limit` (1–100), `offset` (0–100000),
and an optional `is_active` filter. Deleting a branch deactivates it by setting
`is_active` to `false`; it does not physically delete the database row.

Supplier listing and CRUD operations are available under
`/api/v1/suppliers`, with the same pagination bounds and optional
`is_active`/`supply_category` filters. Supplier `is_active` is nullable; list
and read responses preserve `null`. Deleting a supplier only sets
`is_active` to `false` and leaves related records unchanged.

Ingredient listing and CRUD operations are available under
`/api/v1/ingredients`, with bounded pagination and optional `is_active`,
`category`, and `supplier_id` filters. Ingredient create/update validates
suppliers, and deleting an ingredient only sets `is_active` to `false`.

Menu item listing and CRUD operations are available under
`/api/v1/menu-items`, with bounded pagination and optional `is_active` and
`category` filters. Deleting a menu item only sets `is_active` to `false`;
nullable fields, including `price_pkr`, can be cleared through partial updates.

Recipe-item relationship endpoints are available under `/api/v1/recipe-items`.
They validate referenced menu items and ingredients, enforce a unique
menu-item/ingredient pair, and require a positive per-portion quantity with
three decimal places. Deleting a recipe item removes only that relationship
record.

Menu availability endpoints are available under `/api/v1/menu-availability`.
They validate branch and menu-item references and enforce one record per
branch/menu-item pair. The nullable `is_available` value is preserved; list
filter values may be `true`, `false`, or `null`. Deleting an availability
record removes only that relationship.

## Restaurant chat API

`POST /api/v1/chat` accepts a JSON body containing a non-empty `question` of
up to 2,000 characters and an optional `conversation_id` for follow-up questions:

```json
{"question": "What is the price of Chicken Karahi?"}
```

The response includes an opaque conversation ID. Supply it with a later
question to resolve follow-up references:

```json
{
  "question": "Which ingredients does it use?",
  "conversation_id": "d7437f95-112a-4f69-9f31-cf74a4b92ff2"
}
```

The response includes the answer, whether retrieval-backed answering completed,
a status, and the number of approved retrieval calls:

```json
{
  "answer": "The recorded price is PKR 850.00.",
  "success": true,
  "status": "completed",
  "retrieval_count": 1,
  "conversation_id": "d7437f95-112a-4f69-9f31-cf74a4b92ff2"
}
```

Conversation text is held only in bounded process memory, expires after 30
minutes by default, and is not shared across worker processes or retained after
a restart. Configure the limits with `CHAT_MEMORY_TTL_SECONDS`,
`CHAT_MEMORY_MAX_CONVERSATIONS`, `CHAT_MEMORY_MAX_MESSAGES`, and
`CHAT_MEMORY_MAX_MESSAGE_LENGTH` (defaults: 1,000 conversations, 10 messages,
and 2,000 characters per message). Expired entries are removed during store
access and cleanup. At capacity, the least-recently-used inactive conversation
is evicted; if all slots are active, new conversations receive a temporary
service-unavailable response. Expired or evicted IDs return HTTP 410.

`GET /api/v1/chat/health` reports whether an OpenRouter API key is configured;
it does not make a provider request and never returns the key. Chat requests return
sanitized HTTP 429 responses for provider rate limits and HTTP 503 responses
when the provider, configuration, or database is unavailable.

## Database migrations

Alembic uses the application's `DATABASE_URL` setting and async engine. The
URL is not stored in `alembic.ini`. Generate a candidate revision with:

```powershell
uv run alembic revision --autogenerate -m "describe schema change"
```

Review generated migration operations before applying them. To generate SQL
without connecting to the database, use:

```powershell
uv run alembic upgrade head --sql
```

Applying migrations changes the database schema and should only be done after
the migration has been reviewed and explicitly approved.

## Tests

```powershell
uv run pytest
```

## Roadmap

1. **Project initialization** — project structure, dependency management, and
   health endpoint.
2. **Configuration and database foundation** — settings, Neon PostgreSQL
   connectivity, and Alembic migrations.
3. **Restaurant data modeling and ingestion** — validate and load the supplied
   workbook into branch-aware data models.
4. **Menu and inventory services** — inventory-aware menu availability and
   recommendations.
5. **Restaurant assistant APIs** — ordering, reservations, complaints, and
   feedback workflows.
6. **Assistant capabilities** — integrate embeddings and conversational
   features as requirements are defined.
