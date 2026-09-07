from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="ForgeAI API",
    description="API for the ForgeAI autonomous software engineering agent.",
    version="0.1.0",
)


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", version="0.1.0")
