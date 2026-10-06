"""Pydantic schemas for routing, green corridor, priority dispatch, and telemetry."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RouteRequest(BaseModel):
    """Request payload for optimal route calculation."""

    from_intersection_id: int = Field(..., description="Origin intersection identifier")
    to_intersection_id: int = Field(..., description="Destination intersection identifier")
    algorithm: Literal["dijkstra", "astar"] = Field("astar", description="Pathfinding algorithm ('dijkstra' or 'astar')")
    time_weight: float = Field(1.0, ge=0.0, description="CostProfile travel time delay multiplier")
    congestion_weight: float = Field(1.0, ge=0.0, description="CostProfile congestion penalty multiplier")
    distance_weight: float = Field(0.15, ge=0.0, description="CostProfile distance penalty multiplier")
    condition_weight: float = Field(0.5, ge=0.0, description="CostProfile roadway hierarchy friction multiplier")


class RouteEdgeResponse(BaseModel):
    """Directed roadway segment traversed within calculated route."""

    model_config = ConfigDict(from_attributes=True)

    road_id: int = Field(..., description="Corridor road identifier")
    from_intersection_id: int = Field(..., description="Origin intersection identifier")
    to_intersection_id: int = Field(..., description="Destination intersection identifier")
    length_km: float = Field(..., description="Physical segment length in kilometers")
    cost_minutes: float = Field(..., description="Segment traversal impedance in minutes")


class RouteResponse(BaseModel):
    """Calculated optimal path response across network topology."""

    model_config = ConfigDict(from_attributes=True)

    algorithm: str = Field(..., description="Algorithm used ('dijkstra' or 'astar')")
    path: list[int] = Field(..., description="Ordered list of intersection node identifiers")
    edges: list[RouteEdgeResponse] = Field(..., description="Ordered sequence of traversed edges")
    total_cost_minutes: float = Field(..., description="Aggregated traversal cost in minutes")
    total_distance_km: float = Field(..., description="Aggregated physical distance in kilometers")


class GreenCorridorRequest(BaseModel):
    """Request payload for emergency vehicle green-corridor route planning."""

    from_intersection_id: int = Field(..., description="Origin intersection identifier")
    to_intersection_id: int = Field(..., description="Destination intersection identifier")
    emergency_speed_kmh: float = Field(60.0, ge=20.0, le=120.0, description="Cruising emergency speed in km/h (20-120)")


class SignalActionResponse(BaseModel):
    """Preemption or extension directive for a signal controller along the green corridor."""

    model_config = ConfigDict(from_attributes=True)

    intersection_id: int = Field(..., description="Junction identifier")
    signal_id: Optional[int] = Field(None, description="Signal controller identifier, or None if unsignalized")
    action: str = Field(..., description="Operational action ('extend_green', 'preempt', 'monitor')")
    duration_seconds: float = Field(..., description="Duration of signal control action in seconds")
    reason: str = Field(..., description="Operational justification and timing description")


class GreenCorridorResponse(BaseModel):
    """Coordinated green-wave emergency preemption corridor plan."""

    model_config = ConfigDict(from_attributes=True)

    corridor_id: str = Field(..., description="Unique UUID string identifying corridor plan")
    path: list[int] = Field(..., description="Ordered list of intersection node identifiers")
    signal_actions: list[SignalActionResponse] = Field(..., description="Ordered signal control directives")
    estimated_minutes: float = Field(..., description="Estimated travel time in minutes at emergency speed")
    from_intersection_id: int = Field(..., description="Origin intersection identifier")
    to_intersection_id: int = Field(..., description="Destination intersection identifier")


class CongestionRankingItem(BaseModel):
    """Corridor congestion ranking entry."""

    model_config = ConfigDict(from_attributes=True)

    road_id: int = Field(..., description="Road segment identifier")
    road_name: str = Field(..., description="Road corridor name")
    from_intersection_id: Optional[int] = Field(None, description="Origin intersection identifier")
    to_intersection_id: Optional[int] = Field(None, description="Destination intersection identifier")
    congestion_level: float = Field(..., ge=0.0, le=100.0, description="Congestion percentage (0-100)")
    rank: int = Field(..., ge=1, description="Congestion ranking (1 = highest congestion)")


class DispatchNextResponse(BaseModel):
    """Response payload for dispatched priority queue item."""

    model_config = ConfigDict(from_attributes=True)

    kind: str = Field(..., description="Item classification ('incident' or 'emergency')")
    ref_id: int = Field(..., description="Primary key identifier of underlying entity")
    severity: str = Field(..., description="Assessed severity ranking")
    label: str = Field(..., description="Operational summary label")
    new_status: str = Field(..., description="Updated database status ('acknowledged' or 'dispatched')")
    message: str = Field(..., description="Operational confirmation message")


class TelemetryIngestItem(BaseModel):
    """Single lane-level telemetry sensor observation for ingestion."""

    lane_id: int = Field(..., description="Lane identifier")
    congestion_level: float = Field(..., ge=0.0, le=100.0, description="Congestion percentage scale (0-100)")
    vehicle_count: int = Field(..., ge=0, description="Observed vehicle count")
    avg_speed_kmh: Optional[float] = Field(None, ge=0.0, description="Average vehicular speed in km/h")


class TelemetryIngestResponse(BaseModel):
    """Response reporting staging counts for ingested telemetry batch."""

    staged: int = Field(..., description="Number of items successfully staged into buffer")
    dropped: int = Field(..., description="Number of items dropped due to buffer capacity backpressure")


class TelemetryFlushResponse(BaseModel):
    """Response reporting flushed telemetry buffer persistence counts."""

    staged: int = Field(..., description="Number of items drained from ingest buffer")
    persisted: int = Field(..., description="Number of TrafficRecord rows persisted to database")
    dropped: int = Field(..., description="Number of items dropped due to unresolved associations")


class GraphStatsResponse(BaseModel):
    """Topology metrics for hydrated road network graph."""

    intersection_count: int = Field(..., description="Total intersections / nodes in graph")
    road_count: int = Field(..., description="Total road corridors loaded")
    directed_edge_count: int = Field(..., description="Total directed edges in network graph")
