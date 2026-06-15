from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import AppError, app_error_handler
from app.routers import auth, restaurants, users
from app.schemas import HealthResponse
from app.services.restaurant_store import restaurant_store

app = FastAPI(title=settings.app_name)
app.add_exception_handler(AppError, app_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(users.router, prefix=settings.api_prefix)
app.include_router(restaurants.router, prefix=settings.api_prefix)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        vector_store=restaurant_store.backend_name,
        chat_message_store=settings.chat_message_backend,
        chat_message_error=restaurant_store.chat_message_error,
        database_url=settings.database_url,
    )
