from fastapi import APIRouter

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/", status_code=202)
async def create_voice_analysis() -> dict[str, str]:
    """Placeholder voice endpoint."""
    return {"status": "not_implemented"}
