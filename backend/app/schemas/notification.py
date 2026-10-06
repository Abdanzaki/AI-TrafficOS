"""Notification schemas module.

Defines schemas for targeted operator alerts, broadcasts, and status updates.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotificationCreate(BaseModel):
    """Schema for creating a targeted notification to a user."""

    user_id: int = Field(..., description="Target recipient user ID")
    title: str = Field(..., min_length=1, max_length=200, description="Notification title")
    message: str = Field(..., min_length=1, description="Notification body message")
    severity: str = Field("info", min_length=1, max_length=30, description="Severity (info, warning, error, critical)")
    entity_type: Optional[str] = Field(None, max_length=50, description="Optional associated entity type")
    entity_id: Optional[int] = Field(None, description="Optional associated entity ID")


class NotificationBroadcastCreate(BaseModel):
    """Schema for creating a system-wide broadcast notification."""

    title: str = Field(..., min_length=1, max_length=200, description="Notification title")
    message: str = Field(..., min_length=1, description="Notification body message")
    severity: str = Field("info", min_length=1, max_length=30, description="Severity (info, warning, error, critical)")
    entity_type: Optional[str] = Field(None, max_length=50, description="Optional associated entity type")
    entity_id: Optional[int] = Field(None, description="Optional associated entity ID")


class NotificationReadUpdate(BaseModel):
    """Schema for marking a notification as read."""

    is_read: bool = Field(True, description="Mark as read flag")


class NotificationResponse(BaseModel):
    """Schema for notification response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    title: str
    message: str
    severity: str
    is_read: bool
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def handle_unloaded_relationships(cls, data: Any) -> Any:
        """Prevent lazy loading missing greenlet error on relationships."""
        if hasattr(data, "__dict__"):
            d = dict(data.__dict__)
            d.pop("_sa_instance_state", None)
            return d
        return data


class PaginatedNotifications(BaseModel):
    """Paginated notifications listing response schema."""

    items: list[NotificationResponse]
    total: int
    page: int
    per_page: int
    pages: int
