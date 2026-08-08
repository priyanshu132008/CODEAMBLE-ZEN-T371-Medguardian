from fastapi import APIRouter

router = APIRouter(prefix="/teach-back", tags=["teach_back"])


@router.post("/", status_code=202)
async def create_teach_back() -> dict[str, str]:
    """Placeholder teach-back endpoint."""
    return {"status": "not_implemented"}
