from fastapi import FastAPI

app = FastAPI(
    title="Urban Tandoor & Grill – Restaurant Assistant BOT",
    version="0.1.0",
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
