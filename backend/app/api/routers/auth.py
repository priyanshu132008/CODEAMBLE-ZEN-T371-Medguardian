"""Authentication and authenticated-user identity routes."""

from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedUser, get_current_user


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me", response_model=AuthenticatedUser)
async def get_authenticated_user(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Return the identity represented by the validated Supabase token."""
    return current_user
