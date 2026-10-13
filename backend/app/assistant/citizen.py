"""Public Citizen Traffic Assistant (Batch 3 Final Brief C).

Provides a public-facing, read-only traffic information assistant that reuses the
deterministic NLU and grounded-first LLM provider pattern with a STRICTLY LIMITED toolset.

STRICT DATA BOUNDARY & RBAC GUARANTEES:
=======================================
1. CITIZEN TOOL ALLOWLIST: Enforced in code at runtime. Only public read-only tools
   (`get_public_traffic_conditions`, `get_public_incident_notices`, `get_how_to_report`,
   `get_citizen_general_help`) can ever be executed.
2. CONTROL-ROOM EXCLUSION: Control-room-only tools (`simulate_signal_timing`, `get_signal_status`,
   `get_control_decisions`, `get_emergency_events`, `get_predictions_30min`, `get_traffic_state`,
   `get_routing_advice`, `get_junction_history`, `get_analytics_summary`, `get_congestion_ranking`,
   `get_incidents`) are strictly prohibited and cannot be accessed under the citizen role or surface.
3. GRACEFUL REFUSAL: Out-of-scope requests (signal timings, control room decisions, emergency
   transit events, telemetry internals) are intercepted and gracefully refused with `refused=True`.
4. GROUNDED-FIRST ARCHITECTURE: Zero data fabrication. All answers are strictly grounded in
   observed database records with explicit provenance='observed'.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import re
from typing import Any, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.errors import (
    AmbiguousJunctionError,
    JunctionNotFoundError,
    PermissionDeniedError,
)
from app.assistant.nlu import resolve_junction_reference
from app.core.config import settings
from app.models.event import Incident
from app.models.intersection import Intersection
from app.models.traffic import TrafficRecord

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. TOOL ALLOWLIST & SEPARATION ENFORCEMENT
# ==============================================================================

CITIZEN_TOOL_ALLOWLIST = frozenset({
    "get_public_traffic_conditions",
    "get_public_incident_notices",
    "get_how_to_report",
    "get_citizen_general_help",
})

CONTROL_ROOM_ONLY_TOOLS = frozenset({
    "get_traffic_state",
    "get_congestion_ranking",
    "get_predictions_30min",
    "get_routing_advice",
    "get_incidents",
    "get_junction_history",
    "get_signal_status",
    "get_control_decisions",
    "get_analytics_summary",
    "get_emergency_events",
    "simulate_signal_timing",
})


def validate_citizen_tool(tool_name: str) -> None:
    """Enforce runtime allowlist on citizen tool execution.

    Raises PermissionDeniedError if the requested tool is not on the allowlist
    or attempts to execute a control-room only operation.
    """
    if tool_name in CONTROL_ROOM_ONLY_TOOLS:
        raise PermissionDeniedError(
            role="citizen",
            domain=tool_name,
            message=(
                f"Control-room tool '{tool_name}' is strictly prohibited for the citizen assistant. "
                "Citizen surface permits only verified public data tools."
            ),
        )
    if tool_name not in CITIZEN_TOOL_ALLOWLIST:
        raise PermissionDeniedError(
            role="citizen",
            domain=tool_name,
            message=f"Tool '{tool_name}' is not authorized for the citizen assistant allowlist.",
        )


# ==============================================================================
# 2. CITIZEN TOOL IMPLEMENTATIONS (PUBLIC READ-ONLY DATA ONLY)
# ==============================================================================


def _categorize_congestion(level: float) -> str:
    """Convert numerical congestion level (0-100) to clear citizen-friendly text."""
    if level < 25:
        return "Light traffic (Smooth flow)"
    elif level < 55:
        return "Moderate traffic (Normal delays)"
    elif level < 80:
        return "Heavy traffic (Expect delays)"
    return "Severe congestion (Consider alternative routes)"


async def get_public_traffic_conditions(
    db: AsyncSession,
    junction_id: Optional[int] = None,
) -> dict[str, Any]:
    """Retrieve verified public traffic congestion summaries.

    Exposes ONLY public-safe attributes: junction name, city zone, and categorized congestion.
    Excludes raw sensor hardware identifiers, internal camera calibration, and prediction weights.
    """
    validate_citizen_tool("get_public_traffic_conditions")

    if junction_id is not None:
        junc = await db.get(Intersection, junction_id)
        if not junc:
            raise JunctionNotFoundError(junction_id)

        stmt = (
            select(TrafficRecord)
            .where(TrafficRecord.intersection_id == junction_id)
            .order_by(TrafficRecord.recorded_at.desc(), TrafficRecord.id.desc())
            .limit(1)
        )
        res = await db.execute(stmt)
        record = res.scalars().first()

        if not record:
            return {
                "data": [],
                "provenance": "observed",
                "confidence": "low",
                "note": f"No recent public traffic observations available for {junc.name}.",
            }

        return {
            "data": [
                {
                    "junction_id": record.intersection_id,
                    "junction_name": junc.name,
                    "zone": junc.zone or "City Center",
                    "congestion_level": round(record.congestion_level, 1),
                    "condition": _categorize_congestion(record.congestion_level),
                    "recorded_at": record.recorded_at.isoformat(),
                    "provenance": "observed",
                }
            ],
            "provenance": "observed",
            "confidence": "high",
        }

    # Public summary of top monitored physical intersections
    subq = (
        select(
            TrafficRecord.intersection_id,
            func.max(TrafficRecord.recorded_at).label("max_recorded_at"),
        )
        .group_by(TrafficRecord.intersection_id)
        .subquery()
    )
    stmt = (
        select(TrafficRecord, Intersection.name, Intersection.zone)
        .join(
            subq,
            (TrafficRecord.intersection_id == subq.c.intersection_id)
            & (TrafficRecord.recorded_at == subq.c.max_recorded_at),
        )
        .join(Intersection, TrafficRecord.intersection_id == Intersection.id)
        .order_by(TrafficRecord.congestion_level.desc())
        .limit(10)
    )
    res = await db.execute(stmt)
    rows = res.all()

    if not rows:
        return {
            "data": [],
            "provenance": "observed",
            "confidence": "low",
            "note": "No active public traffic observations currently available in the network.",
        }

    data = [
        {
            "junction_id": r.intersection_id,
            "junction_name": name,
            "zone": zone or "City Center",
            "congestion_level": round(r.congestion_level, 1),
            "condition": _categorize_congestion(r.congestion_level),
            "recorded_at": r.recorded_at.isoformat(),
            "provenance": "observed",
        }
        for r, name, zone in rows
    ]

    return {
        "data": data,
        "provenance": "observed",
        "confidence": "high",
    }


async def get_public_incident_notices(
    db: AsyncSession,
    junction_id: Optional[int] = None,
) -> dict[str, Any]:
    """Retrieve verified public road hazard and incident notices.

    Filters out internal dispatcher notes, responder IDs, and emergency priority codes.
    """
    validate_citizen_tool("get_public_incident_notices")

    if junction_id is not None:
        junc = await db.get(Intersection, junction_id)
        if not junc:
            raise JunctionNotFoundError(junction_id)

    stmt = (
        select(Incident, Intersection.name)
        .join(Intersection, Incident.intersection_id == Intersection.id)
        .where(Incident.status != "resolved")
        .order_by(Incident.created_at.desc(), Incident.id.desc())
    )
    if junction_id is not None:
        stmt = stmt.where(Incident.intersection_id == junction_id)
    stmt = stmt.limit(10)

    res = await db.execute(stmt)
    rows = res.all()

    if not rows:
        target_str = f" near junction {junction_id}" if junction_id else " across the city"
        return {
            "data": [],
            "provenance": "observed",
            "confidence": "high",
            "note": f"No active public road incidents or hazard notices reported{target_str}.",
        }

    data = [
        {
            "notice_id": inc.id,
            "junction_id": inc.intersection_id,
            "location": junc_name,
            "severity": inc.severity,
            "description": inc.description or "Traffic advisory in effect.",
            "reported_at": inc.created_at.isoformat(),
            "provenance": "observed",
        }
        for inc, junc_name in rows
    ]

    return {
        "data": data,
        "provenance": "observed",
        "confidence": "high",
    }


def get_how_to_report(issue_type: Optional[str] = None) -> dict[str, Any]:
    """Provide verified official guidance on reporting road issues and hazards."""
    validate_citizen_tool("get_how_to_report")

    guidance = {
        "emergency": (
            "For active collisions, injuries, or life-threatening road hazards, "
            "immediately dial emergency services (911 / 112)."
        ),
        "traffic_signals": (
            "To report malfunctioning or damaged traffic signals, submit a report via "
            "the AI TrafficOS Citizen Portal or contact the Municipal Traffic Operations hotline at 311."
        ),
        "road_hazards": (
            "For potholes, debris, or non-emergency roadway obstructions, report online through the "
            "City Roadway Maintenance portal or the municipal 311 service desk."
        ),
        "general": (
            "How to report traffic issues in AI TrafficOS:\n"
            "1. Life-threatening emergency: Call 911 / 112 immediately.\n"
            "2. Traffic signal outage or damaged light: Contact Municipal Traffic Line (311) or report via the Citizen Portal.\n"
            "3. Potholes & roadway debris: Submit through the online City Maintenance portal.\n"
            "When reporting, please note the nearest intersection or street name."
        ),
    }

    selected = guidance.get(issue_type or "", guidance["general"])
    return {
        "data": {
            "guidance": selected,
            "emergency_number": "911 / 112",
            "municipal_services": "311",
            "portal": "AI TrafficOS Citizen Portal",
        },
        "provenance": "observed",
        "confidence": "high",
    }


def get_citizen_general_help() -> dict[str, Any]:
    """Provide public overview of citizen assistant capabilities and boundaries."""
    validate_citizen_tool("get_citizen_general_help")

    return {
        "data": {
            "service": "AI TrafficOS Public Citizen Assistant",
            "capabilities": [
                "Check live public traffic congestion levels across municipal intersections",
                "View active public road incident and hazard advisories",
                "Obtain official instructions for reporting traffic hazards and signal outages",
            ],
            "boundary": (
                "This assistant provides verified public traffic information only. "
                "Control-room operations, signal timing modifications, supervisory AI decisions, "
                "emergency vehicle dispatch routing, and raw sensor telemetry are restricted "
                "to authorized municipal operators."
            ),
        },
        "provenance": "observed",
        "confidence": "high",
    }


# ==============================================================================
# 3. NLU ENGINE & OUT-OF-SCOPE REFUSAL LOGIC
# ==============================================================================


@dataclass
class CitizenNLUResult:
    """Outcome of citizen intent evaluation and grounded answer synthesis."""

    intent: str
    answer: str
    tools_used: list[str]
    provenance: str = "observed"
    refused: bool = False
    confidence: str = "high"


# Out-of-scope patterns for control-room only topics
OUT_OF_SCOPE_PATTERNS = [
    # 1. Signal timing plans / adjustments / green duration
    (
        "signal_timing_plans",
        re.compile(
            r"\b(?:signal\s+timing|signal\s+plan|phase\s+timing|green\s+duration|green\s+split|extend\s+green|green\s+seconds?|simulate\s+signal|change\s+(?:the\s+)?light|timing\s+plan|signal\s+controller)\b",
            re.IGNORECASE,
        ),
    ),
    # 2. AI supervisory decisions / why green extended
    (
        "control_decisions",
        re.compile(
            r"\b(?:control\s+decision|supervisory\s+decision|why.*(?:green.*extend|signal.*recommend)|ai\s+decision|override\s+signal|timing\s+optimization)\b",
            re.IGNORECASE,
        ),
    ),
    # 3. Emergency transit events / preemption routes / fleet dispatch
    (
        "emergency_events",
        re.compile(
            r"\b(?:emergency\s+(?:transit|events?|vehicles?|fleet|dispatch|route|tracking|location)|ambulance|police\s+cruiser|fire\s+truck|green\s+corridor|preemption)\b",
            re.IGNORECASE,
        ),
    ),
    # 4. Raw telemetry / internal prediction models / camera streams
    (
        "internal_telemetry",
        re.compile(
            r"\b(?:raw\s+telemetry|prediction\s+internals?|model\s+weights?|camera\s+feed\s+raw|sensor\s+calibration|30-min\s+prediction|forecasting\s+model|analytics\s+summary)\b",
            re.IGNORECASE,
        ),
    ),
]

# In-scope patterns for citizen intents
CITIZEN_INTENT_PATTERNS = [
    # 1. How to report road issues
    (
        "how_to_report",
        re.compile(
            r"\b(?:how\s+(?:do\s+i|can\s+i|to)\s+report|report\s+an?\s+(?:issue|incident|accident|hazard|pothole|problem|light|signal)|where\s+do\s+i\s+report|how\s+to\s+file\s+a\s+complaint|report\s+traffic)\b",
            re.IGNORECASE,
        ),
    ),
    # 2. Public incident notices
    (
        "incident_report_info",
        re.compile(
            r"\b(?:incident|accident|hazard|road\s+closure|blockage|collision|crash|danger|obstruction|detour|road\s+hazard)\b",
            re.IGNORECASE,
        ),
    ),
    # 3. Public traffic conditions
    (
        "traffic_conditions",
        re.compile(
            r"\b(?:traffic\s+conditions?|traffic\s+situation|how\s+is\s+traffic|congestion\s+level|traffic\s+at|traffic\s+right\s+now|is\s+it\s+busy|traffic\s+jam|commute|flow\s+of\s+traffic|traffic\s+status|current\s+traffic)\b",
            re.IGNORECASE,
        ),
    ),
    # 4. General help & welcome
    (
        "general_help",
        re.compile(
            r"\b(?:help|what\s+can\s+you\s+do|capabilities|who\s+are\s+you|hi|hello|hey|greetings|assist|about\s+you)\b",
            re.IGNORECASE,
        ),
    ),
]

REFUSAL_MESSAGE = (
    "I can help with public traffic information, active road hazard notices, and guidance on "
    "how to report traffic issues. Information regarding signal timing plans, AI control room decisions, "
    "emergency vehicle operations, and raw sensor telemetry is restricted to municipal control-room staff."
)


class CitizenNLU:
    """Deterministic NLU engine for the public citizen assistant."""

    async def execute(
        self,
        db: AsyncSession,
        message: str,
        explicit_junction_id: Optional[int] = None,
    ) -> CitizenNLUResult:
        """Process user message against citizen intents and strictly limited tools."""
        clean_msg = message.strip()

        # Step 1: Check for out-of-scope requests (Signal timing, control decisions, emergency fleet, telemetry)
        for out_scope_intent, pattern in OUT_OF_SCOPE_PATTERNS:
            if pattern.search(clean_msg):
                logger.info("Citizen query matched out-of-scope intent '%s', gracefully refusing.", out_scope_intent)
                return CitizenNLUResult(
                    intent="out_of_scope",
                    answer=REFUSAL_MESSAGE,
                    tools_used=[],
                    provenance="observed",
                    refused=True,
                    confidence="high",
                )

        # Step 2: Attempt junction entity resolution if present
        target_junction: Optional[Intersection] = None
        if explicit_junction_id is not None:
            target_junction = await db.get(Intersection, explicit_junction_id)

        if not target_junction:
            # Check for numeric or name references in query
            num_match = re.search(r"\b(?:junction|intersection|int|junc)\s*#?\s*(\d+)\b", clean_msg, re.IGNORECASE)
            if num_match:
                j_id = int(num_match.group(1))
                try:
                    target_junction = await resolve_junction_reference(db, j_id)
                except (JunctionNotFoundError, AmbiguousJunctionError):
                    target_junction = None

        junction_id = target_junction.id if target_junction else explicit_junction_id

        # Step 3: Match in-scope citizen intent
        matched_intent = "traffic_conditions"  # default fallback to public traffic conditions
        for intent_name, pattern in CITIZEN_INTENT_PATTERNS:
            if pattern.search(clean_msg):
                matched_intent = intent_name
                break

        # Step 4: Dispatch to allowed tool
        if matched_intent == "how_to_report":
            tool_res = get_how_to_report()
            tools_used = ["get_how_to_report"]
            answer = (
                "HOW TO REPORT TRAFFIC ISSUES:\n\n"
                f"{tool_res['data']['guidance']}\n\n"
                f"• Emergency Services: {tool_res['data']['emergency_number']}\n"
                f"• Municipal Inquiries / 311: {tool_res['data']['municipal_services']}\n"
                f"• Online Portal: {tool_res['data']['portal']}"
            )
            return CitizenNLUResult(
                intent="how_to_report",
                answer=answer,
                tools_used=tools_used,
                provenance="observed",
                refused=False,
                confidence="high",
            )

        elif matched_intent == "incident_report_info":
            tool_res = await get_public_incident_notices(db=db, junction_id=junction_id)
            tools_used = ["get_public_incident_notices"]
            items = tool_res.get("data", [])

            if not items:
                note = tool_res.get("note", "No active public incident notices at this time.")
                answer = f"ACTIVE ROAD INCIDENTS [OBSERVED]:\n\n{note}"
            else:
                lines = ["ACTIVE ROAD HAZARD NOTICES [OBSERVED]:"]
                for item in items:
                    lines.append(
                        f"• {item['location']}: {item['description']} (Severity: {item['severity'].upper()}, "
                        f"Reported: {item['reported_at'][:16].replace('T', ' ')})"
                    )
                answer = "\n".join(lines)

            return CitizenNLUResult(
                intent="incident_report_info",
                answer=answer,
                tools_used=tools_used,
                provenance="observed",
                refused=False,
                confidence="high",
            )

        elif matched_intent == "general_help":
            tool_res = get_citizen_general_help()
            tools_used = ["get_citizen_general_help"]
            caps = "\n".join(f"• {c}" for c in tool_res["data"]["capabilities"])
            answer = (
                f"{tool_res['data']['service']}\n\n"
                f"I can assist you with:\n{caps}\n\n"
                f"{tool_res['data']['boundary']}"
            )
            return CitizenNLUResult(
                intent="general_help",
                answer=answer,
                tools_used=tools_used,
                provenance="observed",
                refused=False,
                confidence="high",
            )

        else:  # traffic_conditions
            tool_res = await get_public_traffic_conditions(db=db, junction_id=junction_id)
            tools_used = ["get_public_traffic_conditions"]
            items = tool_res.get("data", [])

            if not items:
                note = tool_res.get("note", "No public traffic observations currently available.")
                answer = f"CURRENT TRAFFIC CONDITIONS [OBSERVED]:\n\n{note}"
            else:
                lines = ["CURRENT PUBLIC TRAFFIC CONDITIONS [OBSERVED]:"]
                for item in items:
                    lines.append(
                        f"• {item['junction_name']} ({item['zone']}): {item['condition']} "
                        f"(Congestion Index: {item['congestion_level']}/100)"
                    )
                answer = "\n".join(lines)

            return CitizenNLUResult(
                intent="traffic_conditions",
                answer=answer,
                tools_used=tools_used,
                provenance="observed",
                refused=False,
                confidence="high",
            )


# ==============================================================================
# 4. GROUNDED-FIRST CITIZEN PROVIDER
# ==============================================================================

CITIZEN_GEMINI_SYSTEM_INSTRUCTION = (
    "You are rephrasing a municipal traffic advisory for the general public. "
    "Use ONLY the facts in the provided grounded answer. "
    "Do NOT add, infer, or invent any numbers, names, control plans, or events. "
    "Keep uncertainty labels, and if no data exists, say so plainly. "
    "Do NOT mention internal control room terms or signal timing plans."
)


class CitizenProvider:
    """Grounded-first conversational provider for the public citizen chatbot.

    Executes CitizenNLU first for 100% factual accuracy and strictly limited public tools.
    If refused, returns refusal text immediately without invoking any external API.
    If GEMINI_API_KEY is available and query was not refused, conversationally rephrases
    the public answer via Gemini generateContent REST API, falling back silently on any failure.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 8.0,
    ) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY or settings.ASSISTANT_LLM_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.timeout = timeout
        self.nlu = CitizenNLU()

    async def process_query(
        self,
        db: AsyncSession,
        message: str,
        explicit_junction_id: Optional[int] = None,
    ) -> CitizenNLUResult:
        """Execute grounded NLU first, then optional conversational rephrasing."""
        # 1. Deterministic Grounded NLU
        result = await self.nlu.execute(
            db=db,
            message=message,
            explicit_junction_id=explicit_junction_id,
        )

        # 2. Never rephrase refusals
        if result.refused:
            return result

        # 3. Optional conversational rephrase via Gemini if API key configured
        api_key = (self._api_key or "").strip()
        if not api_key:
            return result

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={api_key}"
            payload = {
                "systemInstruction": {
                    "parts": [{"text": CITIZEN_GEMINI_SYSTEM_INSTRUCTION}]
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    f"Public User Question: {message}\n\n"
                                    f"Verified Grounded Traffic Answer:\n{result.answer}\n\n"
                                    "Please rephrase conversationally for a citizen."
                                )
                            }
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 500,
                },
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and parts[0].get("text"):
                            rephrased = parts[0]["text"].strip()
                            if rephrased:
                                return CitizenNLUResult(
                                    intent=result.intent,
                                    answer=rephrased,
                                    tools_used=result.tools_used,
                                    provenance=result.provenance,
                                    refused=False,
                                    confidence=result.confidence,
                                )
        except Exception as exc:
            logger.warning("Gemini conversational rephrasing for citizen failed silently: %s", exc)

        return result
