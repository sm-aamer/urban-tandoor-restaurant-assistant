# Urban Tandoor & Grill – Restaurant Assistant BOT

## Project overview

A modular Python backend foundation for a restaurant assistant for the fictional
Urban Tandoor & Grill in Karachi, Pakistan. This milestone provides project
scaffolding and a health endpoint only; it does not connect to a database or
implement restaurant workflows.

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
