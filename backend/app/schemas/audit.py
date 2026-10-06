"""Audit logging schemas module."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, model_validator


class AuditLogResponse(BaseModel):
    """Immutable audit trail log record schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: Optional[int] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    details: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
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


class PaginatedAuditLogs(BaseModel):
    """Paginated audit logs response schema."""

    items: list[AuditLogResponse]
    total: int
    page: int
    per_page: int
    pages: int
