"""Road schemas module."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.lane import LaneResponse


class RoadCreate(BaseModel):
    """Schema for creating a road segment."""

    name: str = Field(..., min_length=1, max_length=150, description="Roadway name")
    road_type: str = Field(..., min_length=1, max_length=50, description="Road classification (e.g. arterial, collector, local)")
    speed_limit_kmh: Optional[int] = Field(None, ge=0, description="Speed limit in km/h")
    geometry: Optional[str] = Field(None, description="GeoJSON / WKT geometry representation")
    from_intersection_id: Optional[int] = Field(None, description="Origin intersection ID")
    to_intersection_id: Optional[int] = Field(None, description="Destination intersection ID")
    length_km: Optional[float] = Field(None, ge=0.0, description="Road segment length in km")
    capacity_veh_per_hr: Optional[int] = Field(None, ge=0, description="Hourly vehicle capacity")
    is_bidirectional: Optional[bool] = Field(True, description="Whether traffic flows bidirectionally")

    @model_validator(mode="after")
    def validate_endpoints(self) -> "RoadCreate":
        """Validate that origin and destination intersections are not identical."""
        if (
            self.from_intersection_id is not None
            and self.to_intersection_id is not None
            and self.from_intersection_id == self.to_intersection_id
        ):
            raise ValueError("from_intersection_id and to_intersection_id cannot be the same")
        return self


class RoadUpdate(BaseModel):
    """Schema for updating a road segment."""

    name: Optional[str] = Field(None, min_length=1, max_length=150)
    road_type: Optional[str] = Field(None, min_length=1, max_length=50)
    speed_limit_kmh: Optional[int] = Field(None, ge=0)
    geometry: Optional[str] = None
    from_intersection_id: Optional[int] = Field(None, description="Origin intersection ID")
    to_intersection_id: Optional[int] = Field(None, description="Destination intersection ID")
    length_km: Optional[float] = Field(None, ge=0.0, description="Road segment length in km")
    capacity_veh_per_hr: Optional[int] = Field(None, ge=0, description="Hourly vehicle capacity")
    is_bidirectional: Optional[bool] = Field(None, description="Whether traffic flows bidirectionally")

    @model_validator(mode="after")
    def validate_endpoints(self) -> "RoadUpdate":
        """Validate that origin and destination intersections are not identical."""
        if (
            self.from_intersection_id is not None
            and self.to_intersection_id is not None
            and self.from_intersection_id == self.to_intersection_id
        ):
            raise ValueError("from_intersection_id and to_intersection_id cannot be the same")
        return self


class RoadResponse(BaseModel):
    """Schema for road response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    road_type: str
    speed_limit_kmh: Optional[int] = None
    geometry: Optional[str] = None
    from_intersection_id: Optional[int] = None
    to_intersection_id: Optional[int] = None
    length_km: Optional[float] = None
    capacity_veh_per_hr: Optional[int] = None
    is_bidirectional: bool = True
    created_at: datetime
    updated_at: datetime
    lanes: Optional[list[LaneResponse]] = None

    @model_validator(mode="before")
    @classmethod
    def handle_unloaded_lanes(cls, data: Any) -> Any:
        """Prevent lazy loading missing greenlet error on lanes relation."""
        if hasattr(data, "__dict__"):
            d = dict(data.__dict__)
            d.pop("_sa_instance_state", None)
            if "lanes" not in data.__dict__:
                d["lanes"] = None
            return d
        return data


class PaginatedRoads(BaseModel):
    """Paginated road listing response schema."""

    items: list[RoadResponse]
    total: int
    page: int
    per_page: int
    pages: int
