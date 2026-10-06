"""Database-backed in-memory hash map registries for topological network elements.

Provides cached O(1) junction, signal, and phase lookups across routing and
corridor planning workflows, eliminating N+1 database round-trips.
"""

from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intersection import Intersection
from app.models.signal import Signal, SignalPhase


class NetworkRegistry:
    """Pre-loaded in-memory hash registry of intersections, signals, and signal phases.

    Traffic-engineering and computational rationale:
        Dynamic traffic routing, A* corridor exploration, and emergency green-wave planning
        frequently inspect junction topology, municipal intersection codes, signal hardware,
        and phase cycle durations for dozens or hundreds of candidate nodes per planning cycle.
        Issuing single-record SELECT queries inside path traversal or signal scheduling loops
        creates catastrophic N+1 database overhead, inflating response times by orders of
        magnitude.

        NetworkRegistry hydrates all active intersection physical records, signal controllers,
        and phase definitions into memory using exactly three bulk indexed queries. The resulting
        hash tables guarantee O(1) average-time dictionary lookups, allowing route solvers
        and corridor coordinators to access network attributes with sub-microsecond latency
        and zero redundant database I/O.
    """

    def __init__(
        self,
        junction_by_id: dict[int, Intersection],
        junction_by_code: dict[str, int],
        signals_by_intersection: dict[int, list[Signal]],
        phases_by_signal: dict[int, list[SignalPhase]],
    ) -> None:
        """Initialize registry with pre-hydrated mappings."""
        self.junction_by_id = junction_by_id
        self.junction_by_code = junction_by_code
        self.signals_by_intersection = signals_by_intersection
        self.phases_by_signal = phases_by_signal

    @classmethod
    async def build(cls, session: AsyncSession) -> "NetworkRegistry":
        """Construct and populate a NetworkRegistry instance from database entities.

        Executes exactly three bulk queries:
        1. All Intersection records -> junction_by_id and junction_by_code.
        2. All Signal controller units -> signals_by_intersection.
        3. All SignalPhase timing definitions -> phases_by_signal.

        Parameters:
            session: Active asynchronous SQLAlchemy session.

        Returns:
            NetworkRegistry: Fully hydrated in-memory network registry.
        """
        # Query 1: All intersections
        inter_stmt = select(Intersection).order_by(Intersection.id)
        inter_res = await session.execute(inter_stmt)
        intersections = inter_res.scalars().all()

        junction_by_id: dict[int, Intersection] = {}
        junction_by_code: dict[str, int] = {}
        for j in intersections:
            junction_by_id[j.id] = j
            if j.code:
                junction_by_code[j.code] = j.id

        # Query 2: All traffic signal controllers
        sig_stmt = select(Signal).order_by(Signal.intersection_id, Signal.id)
        sig_res = await session.execute(sig_stmt)
        signals = sig_res.scalars().all()

        signals_by_intersection: dict[int, list[Signal]] = defaultdict(list)
        for s in signals:
            signals_by_intersection[s.intersection_id].append(s)

        # Query 3: All signal phases
        phase_stmt = select(SignalPhase).order_by(SignalPhase.signal_id, SignalPhase.phase_order)
        phase_res = await session.execute(phase_stmt)
        phases = phase_res.scalars().all()

        phases_by_signal: dict[int, list[SignalPhase]] = defaultdict(list)
        for p in phases:
            phases_by_signal[p.signal_id].append(p)

        return cls(
            junction_by_id=junction_by_id,
            junction_by_code=junction_by_code,
            signals_by_intersection=dict(signals_by_intersection),
            phases_by_signal=dict(phases_by_signal),
        )

    def get_junction(self, intersection_id: int) -> Optional[Intersection]:
        """Retrieve Intersection entity by its primary key identifier in O(1) time."""
        return self.junction_by_id.get(intersection_id)

    def get_junction_by_code(self, code: str) -> Optional[int]:
        """Retrieve intersection primary key identifier by municipal code in O(1) time."""
        return self.junction_by_code.get(code)

    def signals_for(self, intersection_id: int) -> list[Signal]:
        """Retrieve list of traffic signal controllers installed at the intersection in O(1) time."""
        return list(self.signals_by_intersection.get(intersection_id, []))

    def phases_for(self, signal_id: int) -> list[SignalPhase]:
        """Retrieve list of signal phases configured for the signal controller in O(1) time."""
        return list(self.phases_by_signal.get(signal_id, []))
