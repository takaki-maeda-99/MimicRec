"""Protocols for named-resource adapters and SE3Delta motion mappers."""
from __future__ import annotations

from typing import Mapping, Protocol

from mimicrec.motion.types import MotionStep, ResourceCommand, ResourceState


class ResourceAdapter(Protocol):
    """One physical connection that may expose multiple actuator resources."""

    name: str
    resource_names: tuple[str, ...]

    async def connect(self) -> None: ...

    async def activate(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_resources(self) -> Mapping[str, ResourceState]: ...

    async def send_commands(
        self, commands: Mapping[str, ResourceCommand]
    ) -> None: ...

    async def safe_stop(self) -> None: ...


class MotionMapper(Protocol):
    """Map one embodiment-independent motion step onto claimed resources."""

    def map(
        self,
        step: MotionStep,
        resource_states: Mapping[str, ResourceState],
    ) -> Mapping[str, ResourceCommand]: ...


def adapter_resource_names(adapter: ResourceAdapter) -> tuple[str, ...]:
    names = tuple(str(name) for name in adapter.resource_names)
    if not names:
        raise ValueError(f"adapter {adapter.name!r} exposes no resources")
    if len(set(names)) != len(names):
        raise ValueError(f"adapter {adapter.name!r} has duplicate resource names")
    if any("." in name or not name for name in names):
        raise ValueError(
            f"adapter {adapter.name!r} resource names must be non-empty local names"
        )
    return names
