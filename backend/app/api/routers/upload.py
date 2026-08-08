from pathlib import Path
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/api/upload", tags=["upload"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


@router.post("", status_code=201)
async def create_upload(file: UploadFile = File(...)) -> dict[str, str]:
    """Validate and store an uploaded file temporarily."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")

    uploads_dir = Path(__file__).resolve().parents[3] / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4()
    original_name = file.filename or "upload"
    extension = Path(original_name).suffix
    generated_name = f"{file_id}{extension}"
    destination = uploads_dir / generated_name

    file_size = 0
    with destination.open("wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break

            file_size += len(chunk)
            if file_size > MAX_FILE_SIZE_BYTES:
                buffer.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File too large")
            buffer.write(chunk)

    return {
        "status": "uploaded",
        "file_id": str(file_id),
        "original_filename": original_name,
        "content_type": file.content_type,
    }
