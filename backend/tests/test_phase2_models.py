"""Test Phase 2 database models and metadata."""

import pytest
from app.core.database import Base
from app.models import (
    AIDecision,
    AIPrediction,
    AuditLog,
    EmergencyEvent,
    Incident,
    Intersection,
    Lane,
    Notification,
    Road,
    Role,
    Signal,
    SignalPhase,
    TrafficRecord,
    User,
    VehicleEvent,
)


def test_phase2_models_metadata() -> None:
    """Verify all 15 required Phase 2 tables are registered in Base.metadata with required columns."""
    table_names = set(Base.metadata.tables.keys())
    expected_tables = {
        "roles",
        "users",
        "roads",
        "intersections",
        "lanes",
        "signals",
        "signal_phases",
        "vehicle_events",
        "incidents",
        "emergency_events",
        "traffic_records",
        "notifications",
        "ai_predictions",
        "ai_decisions",
        "audit_logs",
    }
    assert expected_tables.issubset(table_names)

    # 1. roles
    roles_cols = Base.metadata.tables["roles"].columns
    for col in ["id", "name", "description", "created_at", "updated_at"]:
        assert col in roles_cols

    # 2. users
    users_cols = Base.metadata.tables["users"].columns
    for col in ["id", "email", "hashed_password", "full_name", "role_id", "is_active", "last_login_at", "created_at", "updated_at"]:
        assert col in users_cols

    # 3. roads
    roads_cols = Base.metadata.tables["roads"].columns
    for col in ["id", "name", "road_type", "speed_limit_kmh", "geometry", "created_at", "updated_at"]:
        assert col in roads_cols

    # 4. intersections
    inter_cols = Base.metadata.tables["intersections"].columns
    for col in ["id", "name", "code", "status", "city", "zone", "lat", "lon", "created_at", "updated_at"]:
        assert col in inter_cols

    # 5. lanes
    lanes_cols = Base.metadata.tables["lanes"].columns
    for col in ["id", "road_id", "intersection_id", "lane_number", "direction", "lane_type", "created_at", "updated_at"]:
        assert col in lanes_cols

    # 6. signals
    signals_cols = Base.metadata.tables["signals"].columns
    for col in ["id", "intersection_id", "code", "status", "created_at", "updated_at"]:
        assert col in signals_cols

    # 7. signal_phases
    sp_cols = Base.metadata.tables["signal_phases"].columns
    for col in ["id", "signal_id", "intersection_id", "name", "phase_order", "duration_seconds", "state", "is_active", "created_at", "updated_at"]:
        assert col in sp_cols

    # 8. vehicle_events
    ve_cols = Base.metadata.tables["vehicle_events"].columns
    for col in ["id", "intersection_id", "lane_id", "event_type", "vehicle_type", "speed_kmh", "direction", "confidence", "detected_at", "created_at", "updated_at"]:
        assert col in ve_cols

    # 9. incidents
    inc_cols = Base.metadata.tables["incidents"].columns
    for col in ["id", "intersection_id", "severity", "status", "description", "reported_by", "resolved_at", "lat", "lon", "created_at", "updated_at"]:
        assert col in inc_cols

    # 10. emergency_events
    ee_cols = Base.metadata.tables["emergency_events"].columns
    for col in ["id", "incident_id", "vehicle_type", "priority", "status", "detected_at", "cleared_at", "created_at", "updated_at"]:
        assert col in ee_cols

    # 11. traffic_records
    tr_cols = Base.metadata.tables["traffic_records"].columns
    for col in ["id", "intersection_id", "lane_id", "recorded_at", "vehicle_count", "avg_speed_kmh", "congestion_level", "source", "created_at", "updated_at"]:
        assert col in tr_cols

    # 12. notifications
    notif_cols = Base.metadata.tables["notifications"].columns
    for col in ["id", "user_id", "title", "message", "severity", "is_read", "entity_type", "entity_id", "created_at", "updated_at"]:
        assert col in notif_cols

    # 13. ai_predictions
    aip_cols = Base.metadata.tables["ai_predictions"].columns
    for col in ["id", "intersection_id", "prediction_type", "predicted_for", "payload", "confidence", "model_version", "created_at", "updated_at"]:
        assert col in aip_cols

    # 14. ai_decisions
    aid_cols = Base.metadata.tables["ai_decisions"].columns
    for col in ["id", "prediction_id", "intersection_id", "decision_type", "payload", "status", "applied_by", "rationale", "created_at", "updated_at"]:
        assert col in aid_cols

    # 15. audit_logs
    al_cols = Base.metadata.tables["audit_logs"].columns
    for col in ["id", "actor_user_id", "action", "entity_type", "entity_id", "details", "ip_address", "created_at", "updated_at"]:
        assert col in al_cols
