from __future__ import annotations


class MimicRecError(Exception):
    """Base class for all domain errors. Plan B maps these to HTTP."""


class HandTeachNotSupportedError(MimicRecError):
    """Raised by an adapter that cannot provide gravity-comp / hand-teach."""


class InvalidTransitionError(MimicRecError):
    """Raised by the session state machine on illegal transitions."""


class HardwareError(MimicRecError):
    """Raised by adapters and the dispatcher on CAN/USB/driver faults."""


class RecorderError(MimicRecError):
    """Raised by the writer on persistent storage faults."""


class ReplaySafetyError(MimicRecError):
    """Raised by the replay watchdog on violated safety parameters."""
