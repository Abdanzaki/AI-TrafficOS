"""Phase 2 production database schema migration.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 12:00:00.000000
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply Phase 2 production schema additions and extensions."""

    # ---------------------------------------------------------
    # 1. roles table
    # ---------------------------------------------------------
    roles_table = op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)
    op.create_index("ix_roles_created_at", "roles", ["created_at"], unique=False)

    # Seed roles: admin, traffic_officer, analyst
    now_utc = datetime.now(timezone.utc)
    op.bulk_insert(
        roles_table,
        [
            {
                "name": "admin",
                "description": "System administrator with complete access and user management privileges",
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            {
                "name": "traffic_officer",
                "description": "Traffic operations officer managing signal timings, incidents, and preemption",
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            {
                "name": "analyst",
                "description": "Traffic data analyst monitoring congestion telemetry and AI model predictions",
                "created_at": now_utc,
                "updated_at": now_utc,
            },
        ],
    )

    # ---------------------------------------------------------
    # 2. users table
    # ---------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_users_role_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role_id", "users", ["role_id"], unique=False)
    op.create_index("ix_users_created_at", "users", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 3. roads table
    # ---------------------------------------------------------
    op.create_table(
        "roads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("road_type", sa.String(length=50), nullable=False),
        sa.Column("speed_limit_kmh", sa.Integer(), nullable=True),
        sa.Column("geometry", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_roads_name", "roads", ["name"], unique=False)
    op.create_index("ix_roads_created_at", "roads", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 4. Extend intersections table
    # ---------------------------------------------------------
    op.add_column("intersections", sa.Column("code", sa.String(length=50), nullable=False))
    op.add_column(
        "intersections",
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
    )
    op.add_column("intersections", sa.Column("city", sa.String(length=100), nullable=True))
    op.add_column("intersections", sa.Column("zone", sa.String(length=100), nullable=True))
    op.add_column(
        "intersections",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_intersections_code", "intersections", ["code"])
    op.create_index("ix_intersections_code", "intersections", ["code"], unique=True)
    op.create_index("ix_intersections_status", "intersections", ["status"], unique=False)
    op.create_index("ix_intersections_created_at", "intersections", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 5. lanes table
    # ---------------------------------------------------------
    op.create_table(
        "lanes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("road_id", sa.Integer(), nullable=False),
        sa.Column("intersection_id", sa.Integer(), nullable=True),
        sa.Column("lane_number", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=50), nullable=False),
        sa.Column("lane_type", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["road_id"], ["roads.id"], name="fk_lanes_road_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["intersection_id"],
            ["intersections.id"],
            name="fk_lanes_intersection_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lanes_road_id", "lanes", ["road_id"], unique=False)
    op.create_index("ix_lanes_intersection_id", "lanes", ["intersection_id"], unique=False)
    op.create_index("ix_lanes_created_at", "lanes", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 6. signals table
    # ---------------------------------------------------------
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("intersection_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["intersection_id"],
            ["intersections.id"],
            name="fk_signals_intersection_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_signals_code"),
    )
    op.create_index("ix_signals_intersection_id", "signals", ["intersection_id"], unique=False)
    op.create_index("ix_signals_code", "signals", ["code"], unique=True)
    op.create_index("ix_signals_status", "signals", ["status"], unique=False)
    op.create_index("ix_signals_created_at", "signals", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 7. Extend signal_phases table
    # ---------------------------------------------------------
    op.add_column("signal_phases", sa.Column("signal_id", sa.Integer(), nullable=False))
    op.add_column(
        "signal_phases",
        sa.Column("phase_order", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "signal_phases",
        sa.Column("duration_seconds", sa.Integer(), server_default="30", nullable=False),
    )
    op.add_column(
        "signal_phases",
        sa.Column("state", sa.String(length=20), server_default="red", nullable=False),
    )
    op.add_column(
        "signal_phases",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "signal_phases",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_signal_phases_signal_id",
        "signal_phases",
        "signals",
        ["signal_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_signal_phases_signal_id", "signal_phases", ["signal_id"], unique=False)
    op.create_index(
        "ix_signal_phases_intersection_id",
        "signal_phases",
        ["intersection_id"],
        unique=False,
    )
    op.create_index("ix_signal_phases_created_at", "signal_phases", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 8. Extend vehicle_events table
    # ---------------------------------------------------------
    op.add_column("vehicle_events", sa.Column("lane_id", sa.Integer(), nullable=True))
    op.add_column(
        "vehicle_events",
        sa.Column("vehicle_type", sa.String(length=50), server_default="car", nullable=False),
    )
    op.add_column("vehicle_events", sa.Column("speed_kmh", sa.Float(), nullable=True))
    op.add_column("vehicle_events", sa.Column("direction", sa.String(length=50), nullable=True))
    op.add_column(
        "vehicle_events",
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "vehicle_events",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_vehicle_events_lane_id",
        "vehicle_events",
        "lanes",
        ["lane_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_vehicle_events_lane_id", "vehicle_events", ["lane_id"], unique=False)
    op.create_index(
        "ix_vehicle_events_intersection_id",
        "vehicle_events",
        ["intersection_id"],
        unique=False,
    )
    op.create_index("ix_vehicle_events_detected_at", "vehicle_events", ["detected_at"], unique=False)
    op.create_index("ix_vehicle_events_created_at", "vehicle_events", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 9. Extend incidents table
    # ---------------------------------------------------------
    op.add_column(
        "incidents",
        sa.Column("status", sa.String(length=30), server_default="reported", nullable=False),
    )
    op.add_column("incidents", sa.Column("reported_by", sa.Integer(), nullable=True))
    op.add_column("incidents", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("incidents", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("incidents", sa.Column("lon", sa.Float(), nullable=True))
    op.add_column(
        "incidents",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_incidents_reported_by",
        "incidents",
        "users",
        ["reported_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_incidents_status", "incidents", ["status"], unique=False)
    op.create_index("ix_incidents_severity", "incidents", ["severity"], unique=False)
    op.create_index("ix_incidents_reported_by", "incidents", ["reported_by"], unique=False)
    op.create_index("ix_incidents_intersection_id", "incidents", ["intersection_id"], unique=False)
    op.create_index("ix_incidents_created_at", "incidents", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 10. emergency_events table
    # ---------------------------------------------------------
    op.create_table(
        "emergency_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=True),
        sa.Column("vehicle_type", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_emergency_events_incident_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_emergency_events_incident_id", "emergency_events", ["incident_id"], unique=False)
    op.create_index("ix_emergency_events_status", "emergency_events", ["status"], unique=False)
    op.create_index("ix_emergency_events_detected_at", "emergency_events", ["detected_at"], unique=False)
    op.create_index("ix_emergency_events_created_at", "emergency_events", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 11. traffic_records table
    # ---------------------------------------------------------
    op.create_table(
        "traffic_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("intersection_id", sa.Integer(), nullable=False),
        sa.Column("lane_id", sa.Integer(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("vehicle_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("avg_speed_kmh", sa.Float(), nullable=True),
        sa.Column("congestion_level", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=50), server_default="sensor", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["intersection_id"],
            ["intersections.id"],
            name="fk_traffic_records_intersection_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lane_id"],
            ["lanes.id"],
            name="fk_traffic_records_lane_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_traffic_records_intersection_id", "traffic_records", ["intersection_id"], unique=False)
    op.create_index("ix_traffic_records_lane_id", "traffic_records", ["lane_id"], unique=False)
    op.create_index("ix_traffic_records_recorded_at", "traffic_records", ["recorded_at"], unique=False)
    op.create_index("ix_traffic_records_created_at", "traffic_records", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 12. notifications table
    # ---------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=30), server_default="info", nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_notifications_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"], unique=False)
    op.create_index("ix_notifications_severity", "notifications", ["severity"], unique=False)
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 13. ai_predictions table
    # ---------------------------------------------------------
    op.create_table(
        "ai_predictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("intersection_id", sa.Integer(), nullable=True),
        sa.Column("prediction_type", sa.String(length=50), nullable=False),
        sa.Column("predicted_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["intersection_id"],
            ["intersections.id"],
            name="fk_ai_predictions_intersection_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_predictions_intersection_id", "ai_predictions", ["intersection_id"], unique=False)
    op.create_index("ix_ai_predictions_predicted_for", "ai_predictions", ["predicted_for"], unique=False)
    op.create_index("ix_ai_predictions_created_at", "ai_predictions", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 14. ai_decisions table
    # ---------------------------------------------------------
    op.create_table(
        "ai_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column("intersection_id", sa.Integer(), nullable=True),
        sa.Column("decision_type", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="proposed", nullable=False),
        sa.Column("applied_by", sa.Integer(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["ai_predictions.id"],
            name="fk_ai_decisions_prediction_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["intersection_id"],
            ["intersections.id"],
            name="fk_ai_decisions_intersection_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["applied_by"],
            ["users.id"],
            name="fk_ai_decisions_applied_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_decisions_prediction_id", "ai_decisions", ["prediction_id"], unique=False)
    op.create_index("ix_ai_decisions_intersection_id", "ai_decisions", ["intersection_id"], unique=False)
    op.create_index("ix_ai_decisions_applied_by", "ai_decisions", ["applied_by"], unique=False)
    op.create_index("ix_ai_decisions_status", "ai_decisions", ["status"], unique=False)
    op.create_index("ix_ai_decisions_created_at", "ai_decisions", ["created_at"], unique=False)

    # ---------------------------------------------------------
    # 15. audit_logs table
    # ---------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_logs_actor_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"], unique=False)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade Phase 2 schema back to Phase 1 state."""

    # 1. Drop audit_logs
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    # 2. Drop ai_decisions
    op.drop_index("ix_ai_decisions_created_at", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_status", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_applied_by", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_intersection_id", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_prediction_id", table_name="ai_decisions")
    op.drop_table("ai_decisions")

    # 3. Drop ai_predictions
    op.drop_index("ix_ai_predictions_created_at", table_name="ai_predictions")
    op.drop_index("ix_ai_predictions_predicted_for", table_name="ai_predictions")
    op.drop_index("ix_ai_predictions_intersection_id", table_name="ai_predictions")
    op.drop_table("ai_predictions")

    # 4. Drop notifications
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_severity", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

    # 5. Drop traffic_records
    op.drop_index("ix_traffic_records_created_at", table_name="traffic_records")
    op.drop_index("ix_traffic_records_recorded_at", table_name="traffic_records")
    op.drop_index("ix_traffic_records_lane_id", table_name="traffic_records")
    op.drop_index("ix_traffic_records_intersection_id", table_name="traffic_records")
    op.drop_table("traffic_records")

    # 6. Drop emergency_events
    op.drop_index("ix_emergency_events_created_at", table_name="emergency_events")
    op.drop_index("ix_emergency_events_detected_at", table_name="emergency_events")
    op.drop_index("ix_emergency_events_status", table_name="emergency_events")
    op.drop_index("ix_emergency_events_incident_id", table_name="emergency_events")
    op.drop_table("emergency_events")

    # 7. Revert incidents extensions
    op.drop_index("ix_incidents_created_at", table_name="incidents")
    op.drop_index("ix_incidents_intersection_id", table_name="incidents")
    op.drop_index("ix_incidents_reported_by", table_name="incidents")
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_constraint("fk_incidents_reported_by", "incidents", type_="foreignkey")
    op.drop_column("incidents", "updated_at")
    op.drop_column("incidents", "lon")
    op.drop_column("incidents", "lat")
    op.drop_column("incidents", "resolved_at")
    op.drop_column("incidents", "reported_by")
    op.drop_column("incidents", "status")

    # 8. Revert vehicle_events extensions
    op.drop_index("ix_vehicle_events_created_at", table_name="vehicle_events")
    op.drop_index("ix_vehicle_events_detected_at", table_name="vehicle_events")
    op.drop_index("ix_vehicle_events_intersection_id", table_name="vehicle_events")
    op.drop_index("ix_vehicle_events_lane_id", table_name="vehicle_events")
    op.drop_constraint("fk_vehicle_events_lane_id", "vehicle_events", type_="foreignkey")
    op.drop_column("vehicle_events", "updated_at")
    op.drop_column("vehicle_events", "detected_at")
    op.drop_column("vehicle_events", "direction")
    op.drop_column("vehicle_events", "speed_kmh")
    op.drop_column("vehicle_events", "vehicle_type")
    op.drop_column("vehicle_events", "lane_id")

    # 9. Revert signal_phases extensions
    op.drop_index("ix_signal_phases_created_at", table_name="signal_phases")
    op.drop_index("ix_signal_phases_intersection_id", table_name="signal_phases")
    op.drop_index("ix_signal_phases_signal_id", table_name="signal_phases")
    op.drop_constraint("fk_signal_phases_signal_id", "signal_phases", type_="foreignkey")
    op.drop_column("signal_phases", "updated_at")
    op.drop_column("signal_phases", "is_active")
    op.drop_column("signal_phases", "state")
    op.drop_column("signal_phases", "duration_seconds")
    op.drop_column("signal_phases", "phase_order")
    op.drop_column("signal_phases", "signal_id")

    # 10. Drop signals
    op.drop_index("ix_signals_created_at", table_name="signals")
    op.drop_index("ix_signals_status", table_name="signals")
    op.drop_index("ix_signals_code", table_name="signals")
    op.drop_index("ix_signals_intersection_id", table_name="signals")
    op.drop_table("signals")

    # 11. Drop lanes
    op.drop_index("ix_lanes_created_at", table_name="lanes")
    op.drop_index("ix_lanes_intersection_id", table_name="lanes")
    op.drop_index("ix_lanes_road_id", table_name="lanes")
    op.drop_table("lanes")

    # 12. Revert intersections extensions
    op.drop_index("ix_intersections_created_at", table_name="intersections")
    op.drop_index("ix_intersections_status", table_name="intersections")
    op.drop_index("ix_intersections_code", table_name="intersections")
    op.drop_constraint("uq_intersections_code", "intersections", type_="unique")
    op.drop_column("intersections", "updated_at")
    op.drop_column("intersections", "zone")
    op.drop_column("intersections", "city")
    op.drop_column("intersections", "status")
    op.drop_column("intersections", "code")

    # 13. Drop roads
    op.drop_index("ix_roads_created_at", table_name="roads")
    op.drop_index("ix_roads_name", table_name="roads")
    op.drop_table("roads")

    # 14. Drop users
    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    # 15. Drop roles
    op.drop_index("ix_roles_created_at", table_name="roles")
    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_table("roles")
