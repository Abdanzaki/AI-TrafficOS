"""User management request and response schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class UserCreate(BaseModel):
    """Schema for administrator user creation."""

    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    full_name: str = Field(..., min_length=1, max_length=150)
    role_id: Optional[int] = None
    role_name: Optional[str] = None


class UserUpdate(BaseModel):
    """Schema for updating an existing user account."""

    full_name: Optional[str] = Field(None, min_length=1, max_length=150)
    is_active: Optional[bool] = None
    role_id: Optional[int] = None
    role_name: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for serialized user account information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role_name: str
    is_active: bool
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_role_name(cls, data: Any) -> Any:
        """Extract role_name from relational role attribute if present."""
        if hasattr(data, "role") and getattr(data, "role", None) is not None:
            role_obj = getattr(data, "role")
            if hasattr(role_obj, "name"):
                setattr(data, "role_name", role_obj.name)
        elif isinstance(data, dict):
            if "role_name" not in data and "role" in data:
                role_val = data["role"]
                if isinstance(role_val, dict):
                    data["role_name"] = role_val.get("name", "")
                elif hasattr(role_val, "name"):
                    data["role_name"] = role_val.name
        return data


class PaginatedUsers(BaseModel):
    """Paginated user listing response schema."""

    items: list[UserResponse]
    total: int
    page: int
    per_page: int
    pages: int
