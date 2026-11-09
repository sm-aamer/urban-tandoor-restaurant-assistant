from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.database.engine import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(
    title="Urban Tandoor & Grill – Restaurant Assistant BOT",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
