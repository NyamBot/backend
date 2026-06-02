from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import auth, restaurants, users
from app.schemas import HealthResponse

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(restaurants.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    vector_store_name = "pgvector" if settings.database_url.startswith(("postgresql://", "postgres://")) else "sqlite-vector"
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        vector_store=vector_store_name,
        database_url=settings.database_url,
    )
