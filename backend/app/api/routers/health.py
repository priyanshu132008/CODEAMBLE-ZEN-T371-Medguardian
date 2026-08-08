from fastapi import APIRouter

router = APIRouter(prefix="", tags=["health"])


@router.get("/", include_in_schema=False)
async def health_check() -> dict[str, str]:
    """Simple health-check endpoint."""
    return {"status": "ok"}
