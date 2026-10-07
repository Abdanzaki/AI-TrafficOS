"""Models package.

Re-exports the declarative Base and all Phase 2 schema models.
"""

from app.core.database import Base
from app.models.ai import AIDecision, AIPrediction
from app.models.audit import AuditLog
from app.models.auth import Role, User
from app.models.emergency import EmergencyEvent
from app.models.event import Incident, VehicleEvent
from app.models.intersection import Intersection
from app.models.ml import MLModel
from app.models.notification import Notification
from app.models.road import Lane, Road
from app.models.signal import Signal, SignalPhase
from app.models.traffic import TrafficRecord

__all__ = [
    "Base",
    "Role",
    "User",
    "Road",
    "Lane",
    "Intersection",
    "Signal",
    "SignalPhase",
    "VehicleEvent",
    "Incident",
    "EmergencyEvent",
    "TrafficRecord",
    "Notification",
    "AIPrediction",
    "AIDecision",
    "AuditLog",
    "MLModel",
]
