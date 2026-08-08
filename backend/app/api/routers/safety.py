from fastapi import APIRouter

router = APIRouter(prefix="/safety", tags=["safety"])


@router.get("/", include_in_schema=False)
async def safety_root() -> dict[str, str]:
    """Placeholder safety endpoint."""
    return {"status": "not_implemented"}
