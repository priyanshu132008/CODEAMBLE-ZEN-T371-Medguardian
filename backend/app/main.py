from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    health_router,
    safety_router,
    teach_back_router,
    upload_router,
    voice_router,
)
from app.core.config import settings

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(safety_router)
app.include_router(teach_back_router)
app.include_router(upload_router)
app.include_router(voice_router)
