"""API router modules."""

from .health import router as health_router
from .auth import router as auth_router
from .patients import router as patients_router
from .safety import router as safety_router
from .teach_back import router as teach_back_router
from .upload import router as upload_router
from .voice import router as voice_router

__all__ = [
    "auth_router",
    "health_router",
    "patients_router",
    "safety_router",
    "teach_back_router",
    "upload_router",
    "voice_router",
]
