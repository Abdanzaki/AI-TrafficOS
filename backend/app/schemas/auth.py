"""Authentication request and response schemas."""

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Schema for public user registration."""

    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    full_name: str = Field(..., min_length=1, max_length=150, description="Full name of the user")


class LoginRequest(BaseModel):
    """Schema for user credentials authentication."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Schema for JWT access and refresh token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    """Schema for token refresh request."""

    refresh_token: str
