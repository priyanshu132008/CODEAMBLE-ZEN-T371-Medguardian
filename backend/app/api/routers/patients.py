"""Authenticated patient profile routes."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    AuthenticatedUser,
    get_current_access_token,
    get_current_user,
)
from app.schemas.patients import PatientProfile
from app.services.patient_service import get_patient_profile


router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("/me", response_model=PatientProfile)
def get_my_patient_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    access_token: str = Depends(get_current_access_token),
) -> PatientProfile:
    """Return the patient row identified by the authenticated user ID."""
    patient = get_patient_profile(
        user_id=current_user.user_id,
        access_token=access_token,
    )
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No patient record found for the authenticated user.",
        )
    return patient
