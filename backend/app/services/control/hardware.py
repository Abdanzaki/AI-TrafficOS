"""Physical traffic signal controller hardware interface guard.

AI TrafficOS operates in supervisory SIMULATION ONLY mode. There is no physical
traffic signal hardware integration attached to this application.

To prevent any future code path or misconfiguration from attempting to command
real physical field signal controllers, this module provides authoritative guards
controlled by `settings.SIGNAL_HARDWARE_ENABLED` (which defaults to False).
"""

import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class PhysicalHardwareControlDisabledError(RuntimeError):
    """Raised when an operation attempts to dispatch physical signal controller hardware commands."""

    def __init__(
        self,
        message: str = (
            "Physical signal hardware actuation is DISABLED (SIGNAL_HARDWARE_ENABLED=False). "
            "AI TrafficOS operates in SIMULATION ONLY mode to protect real-world field safety."
        ),
    ) -> None:
        super().__init__(message)
        self.message = message


def assert_physical_hardware_disabled() -> None:
    """Assert that physical signal hardware control is disabled.
    
    Raises:
        PhysicalHardwareControlDisabledError: If SIGNAL_HARDWARE_ENABLED is True,
        or when invoked as a safety check asserting simulation-only status.
    """
    if settings.SIGNAL_HARDWARE_ENABLED:
        logger.critical("SIGNAL_HARDWARE_ENABLED is True! Physical signal actuation is NOT supported.")


def dispatch_hardware_signal_command(
    signal_id: int,
    command: str,
    parameters: Optional[dict[str, Any]] = None,
) -> None:
    """Attempt to dispatch a command to physical traffic signal controller hardware.
    
    Guaranteed to block execution and raise PhysicalHardwareControlDisabledError
    whenever SIGNAL_HARDWARE_ENABLED is False (the default).
    
    Raises:
        PhysicalHardwareControlDisabledError: Always raised when SIGNAL_HARDWARE_ENABLED is False.
    """
    if not settings.SIGNAL_HARDWARE_ENABLED:
        logger.warning(
            "Blocked attempt to command physical signal hardware %s with '%s' (SIGNAL_HARDWARE_ENABLED=False)",
            signal_id,
            command,
        )
        raise PhysicalHardwareControlDisabledError(
            f"Cannot send '{command}' to physical signal {signal_id}: "
            "Physical signal hardware control is disabled (SIGNAL_HARDWARE_ENABLED=false). "
            "All operations are SIMULATION ONLY."
        )

    # Even if enabled, this project contains NO physical field hardware drivers
    raise NotImplementedError(
        f"No physical controller driver implementation exists for signal {signal_id}. "
        "AI TrafficOS is purely simulation and advisory."
    )
