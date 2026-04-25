from __future__ import annotations


class MimicRecError(Exception):
    """Base class for all domain errors. Plan B maps these to HTTP."""


class HandTeachNotSupportedError(MimicRecError):
    """Raised by an adapter that cannot provide gravity-comp / hand-teach."""


class InvalidTransitionError(MimicRecError):
    """Raised by the session state machine on illegal transitions."""


class HardwareError(MimicRecError):
    """Raised by adapters and the dispatcher on CAN/USB/driver faults."""


class FatalHardwareError(HardwareError):
    """Hardware error that cannot be recovered without operator intervention
    (e.g. motor alarm latched, bus completely unresponsive). Subscribers may
    treat this as a signal to end the session entirely; transient
    HardwareErrors do not trigger session shutdown."""


class RecorderError(MimicRecError):
    """Raised by the writer on persistent storage faults."""


class ReplaySafetyError(MimicRecError):
    """Raised by the replay watchdog on violated safety parameters."""
