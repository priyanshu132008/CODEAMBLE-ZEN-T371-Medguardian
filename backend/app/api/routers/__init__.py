"""API router modules."""

from .health import router as health_router
from .safety import router as safety_router
from .teach_back import router as teach_back_router
from .upload import router as upload_router
from .voice import router as voice_router

__all__ = [
    "health_router",
    "safety_router",
    "teach_back_router",
    "upload_router",
    "voice_router",
]
