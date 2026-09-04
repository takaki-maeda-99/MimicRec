"""Concurrent runtime for independently configured motion groups.

Readers and dispatchers are isolated per physical adapter, so a slow base or
arm cannot serialize an unrelated device.  Motion groups claim fully-qualified
resources (``adapter.local_resource``); conflicting claims are rejected before
any hardware connection is opened.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Callable, Mapping

from mimicrec.motion.base import MotionMapper, ResourceAdapter, adapter_resource_names
from mimicrec.motion.input import MotionSource
from mimicrec.motion.types import MotionStep, ResourceCommand, ResourceState
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MotionInput:
    name: str
    source: MotionSource
    slot: LatestValue[MotionStep]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("motion input name must not be empty")


@dataclass(frozen=True)
class MotionGroup:
    name: str
    input_slot: LatestValue[MotionStep]
    mapper: MotionMapper
    output_resources: tuple[str, ...]
    control_rate_hz: float = 60.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("motion group name must not be empty")
        outputs = tuple(str(resource) for resource in self.output_resources)
        if not outputs or len(set(outputs)) != len(outputs):
            raise ValueError(
                f"motion group {self.name!r} must claim unique output resources"
            )
        if not all("." in output for output in outputs):
            raise ValueError("motion group resources must be fully qualified")
        if self.control_rate_hz <= 0.0:
            raise ValueError("motion group control_rate_hz must be > 0")
        object.__setattr__(self, "output_resources", outputs)


SnapshotCallback = Callable[
    [
        int,
        Mapping[str, ResourceState],
        Mapping[str, ResourceCommand],
        Mapping[str, MotionStep],
    ],
    None,
]


class MotionRuntime:
    """Own the lifecycle and concurrent loops for a graph of motion groups."""

    def __init__(
        self,
        *,
        adapters: Mapping[str, ResourceAdapter],
        motion_groups: list[MotionGroup],
        motion_inputs: list[MotionInput] | None = None,
        error_bus: ErrorBus | None = None,
        state_rate_hz: float = 100.0,
        snapshot_rate_hz: float | None = None,
        on_snapshot: SnapshotCallback | None = None,
    ) -> None:
        if not adapters:
            raise ValueError("MotionRuntime requires at least one adapter")
        if state_rate_hz <= 0.0:
            raise ValueError("state_rate_hz must be > 0")
        if snapshot_rate_hz is not None and snapshot_rate_hz <= 0.0:
            raise ValueError("snapshot_rate_hz must be > 0")
        self.adapters = dict(adapters)
        self.motion_groups = list(motion_groups)
        self.motion_inputs = list(motion_inputs or [])
        self.error_bus = error_bus or ErrorBus()
        self.state_rate_hz = float(state_rate_hz)
        self.snapshot_rate_hz = snapshot_rate_hz
        self.on_snapshot = on_snapshot

        self._resource_owner: dict[str, str] = {}
        self._resource_states: dict[str, LatestValue[ResourceState]] = {}
        self._adapter_goals: dict[
            str, LatestValue[dict[str, ResourceCommand]]
        ] = {}
        self._latest_commands: dict[str, ResourceCommand] = {}
        self._latest_steps: dict[str, MotionStep] = {}
        self._tasks: list[asyncio.Task] = []
        self._stopped = asyncio.Event()
        self._inputs_paused = False
        self._connected: list[str] = []
        self._connected_inputs: list[MotionInput] = []
        self._validate_graph()

    @property
    def resource_names(self) -> tuple[str, ...]:
        return tuple(self._resource_states)

    def state(self, resource: str) -> LatestValue[ResourceState]:
        try:
            return self._resource_states[resource]
        except KeyError as exc:
            raise KeyError(f"unknown resource {resource!r}") from exc

    def snapshot_states(self) -> dict[str, ResourceState]:
        result: dict[str, ResourceState] = {}
        for name, slot in self._resource_states.items():
            stamped = slot.peek()
            if stamped is not None:
                result[name] = stamped.value
        return result

    def snapshot_commands(self) -> dict[str, ResourceCommand]:
        return dict(self._latest_commands)

    def pause_inputs(self) -> None:
        self._inputs_paused = True

    def resume_inputs(self) -> None:
        self._inputs_paused = False

    def inject_step(self, group_name: str, step: MotionStep) -> None:
        for group in self.motion_groups:
            if group.name == group_name:
                group.input_slot.set(step, t_mono_ns=step.t_mono_ns)
                return
        raise KeyError(f"unknown motion group {group_name!r}")

    def _validate_graph(self) -> None:
        if any(not name or "." in name for name in self.adapters):
            raise ValueError("adapter ids must be non-empty and cannot contain '.'")
        for adapter_id, adapter in self.adapters.items():
            for local_name in adapter_resource_names(adapter):
                qualified = f"{adapter_id}.{local_name}"
                self._resource_states[qualified] = LatestValue()
            self._adapter_goals[adapter_id] = LatestValue()

        group_names: set[str] = set()
        input_names: set[str] = set()
        input_slot_ids: set[int] = set()
        for motion_input in self.motion_inputs:
            if motion_input.name in input_names:
                raise ValueError(f"duplicate motion input name {motion_input.name!r}")
            input_names.add(motion_input.name)
            input_slot_ids.add(id(motion_input.slot))
        for group in self.motion_groups:
            if group.name in group_names:
                raise ValueError(f"duplicate motion group name {group.name!r}")
            group_names.add(group.name)
            if self.motion_inputs and id(group.input_slot) not in input_slot_ids:
                raise ValueError(
                    f"motion group {group.name!r} uses an unregistered input slot"
                )
            for resource in group.output_resources:
                if resource not in self._resource_states:
                    raise ValueError(
                        f"motion group {group.name!r} claims unknown resource "
                        f"{resource!r}"
                    )
                previous = self._resource_owner.get(resource)
                if previous is not None:
                    raise ValueError(
                        f"resource {resource!r} is claimed by both "
                        f"{previous!r} and {group.name!r}"
                    )
                self._resource_owner[resource] = group.name

    async def start(self) -> None:
        if self._tasks or self._connected:
            raise RuntimeError("MotionRuntime is already started")
        self._stopped.clear()
        try:
            # Connect concurrently, then remember every successfully connected
            # device for deterministic rollback if another one fails.
            results = await asyncio.gather(
                *(adapter.connect() for adapter in self.adapters.values()),
                return_exceptions=True,
            )
            for (adapter_id, _adapter), result in zip(self.adapters.items(), results):
                if not isinstance(result, BaseException):
                    self._connected.append(adapter_id)
            failures = [result for result in results if isinstance(result, BaseException)]
            if failures:
                raise failures[0]
            # Connecting owns the transport but must not imply actuation.
            # Activate only after every adapter is connected, so a missing
            # device cannot leave one arm enabled while graph startup fails.
            activation_results = await asyncio.gather(
                *(
                    self._activate_adapter(adapter)
                    for adapter_id, adapter in self.adapters.items()
                    if adapter_id in self._connected
                ),
                return_exceptions=True,
            )
            activation_failures = [
                result
                for result in activation_results
                if isinstance(result, BaseException)
            ]
            if activation_failures:
                raise activation_failures[0]
            input_results = await asyncio.gather(
                *(item.source.connect() for item in self.motion_inputs),
                return_exceptions=True,
            )
            for item, result in zip(self.motion_inputs, input_results):
                if not isinstance(result, BaseException):
                    self._connected_inputs.append(item)
            input_failures = [
                result for result in input_results if isinstance(result, BaseException)
            ]
            if input_failures:
                raise input_failures[0]
        except BaseException:
            await asyncio.gather(
                *(
                    self._safe_stop(self.adapters[adapter_id])
                    for adapter_id in self._connected
                ),
                return_exceptions=True,
            )
            await self._disconnect_inputs()
            await self._disconnect_connected()
            raise

        for adapter_id, adapter in self.adapters.items():
            self._tasks.append(
                asyncio.create_task(
                    self._run_reader(adapter_id, adapter),
                    name=f"motion-reader:{adapter_id}",
                )
            )
            self._tasks.append(
                asyncio.create_task(
                    self._run_dispatcher(adapter_id, adapter),
                    name=f"motion-dispatcher:{adapter_id}",
                )
            )
        for group in self.motion_groups:
            self._tasks.append(
                asyncio.create_task(
                    self._run_group(group), name=f"motion-group:{group.name}"
                )
            )
        for motion_input in self.motion_inputs:
            self._tasks.append(
                asyncio.create_task(
                    self._run_input(motion_input),
                    name=f"motion-input:{motion_input.name}",
                )
            )
        if self.on_snapshot is not None and self.snapshot_rate_hz is not None:
            self._tasks.append(
                asyncio.create_task(self._run_snapshots(), name="motion-snapshots")
            )

    async def stop(self) -> None:
        self._stopped.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        await asyncio.gather(
            *(self._safe_stop(adapter) for adapter in self.adapters.values()),
            return_exceptions=True,
        )
        await self._disconnect_inputs()
        await self._disconnect_connected()

    async def _disconnect_inputs(self) -> None:
        connected = list(reversed(self._connected_inputs))
        self._connected_inputs.clear()
        for item in connected:
            try:
                await item.source.disconnect()
            except Exception:
                logger.warning(
                    "motion input %s disconnect failed", item.name, exc_info=True
                )

    async def _disconnect_connected(self) -> None:
        connected = list(reversed(self._connected))
        self._connected.clear()
        for adapter_id in connected:
            try:
                await self.adapters[adapter_id].disconnect()
            except Exception:
                logger.warning(
                    "motion adapter %s disconnect failed", adapter_id, exc_info=True
                )

    @staticmethod
    async def _activate_adapter(adapter: ResourceAdapter) -> None:
        activate = getattr(adapter, "activate", None)
        if activate is not None:
            await activate()

    @staticmethod
    async def _safe_stop(adapter: ResourceAdapter) -> None:
        safe_stop = getattr(adapter, "safe_stop", None)
        if safe_stop is not None:
            await safe_stop()

    async def _publish_error(self, error: Exception) -> None:
        logger.warning("motion runtime error: %s", error)
        await self.error_bus.publish(error)

    async def _run_reader(
        self, adapter_id: str, adapter: ResourceAdapter
    ) -> None:
        interval = 1.0 / self.state_rate_hz
        expected = set(adapter_resource_names(adapter))
        while not self._stopped.is_set():
            started = time.monotonic()
            try:
                states = dict(await adapter.read_resources())
                unknown = set(states) - expected
                if unknown:
                    raise ValueError(
                        f"adapter {adapter_id!r} returned undeclared resources "
                        f"{sorted(unknown)}"
                    )
                stamp = time.monotonic_ns()
                for local_name, state in states.items():
                    self._resource_states[f"{adapter_id}.{local_name}"].set(
                        state, t_mono_ns=stamp
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._publish_error(exc)
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))

    async def _run_input(self, motion_input: MotionInput) -> None:
        while not self._stopped.is_set():
            try:
                step = await motion_input.source.read_step()
                if not self._inputs_paused:
                    motion_input.slot.set(step, t_mono_ns=step.t_mono_ns)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._publish_error(exc)
                await asyncio.sleep(0.01)

    async def _run_group(self, group: MotionGroup) -> None:
        interval = 1.0 / group.control_rate_hz
        last_input_seq = 0
        claimed = set(group.output_resources)
        while not self._stopped.is_set():
            started = time.monotonic()
            stamped = group.input_slot.peek()
            if stamped is not None and group.input_slot.seq > last_input_seq:
                last_input_seq = group.input_slot.seq
                states = self.snapshot_states()
                try:
                    commands = dict(group.mapper.map(stamped.value, states))
                    unexpected = set(commands) - claimed
                    if unexpected:
                        raise ValueError(
                            f"motion group {group.name!r} emitted unclaimed resources "
                            f"{sorted(unexpected)}"
                        )
                    self._enqueue_commands(commands)
                    self._latest_steps[group.name] = stamped.value
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self._publish_error(exc)
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))

    def _enqueue_commands(self, commands: Mapping[str, ResourceCommand]) -> None:
        per_adapter: dict[str, dict[str, ResourceCommand]] = {}
        for qualified, command in commands.items():
            adapter_id, local_name = qualified.split(".", 1)
            per_adapter.setdefault(adapter_id, {})[local_name] = command
            self._latest_commands[qualified] = command
        for adapter_id, batch in per_adapter.items():
            # Merge with an unsent batch so disjoint motion groups sharing one
            # physical bus do not erase each other's latest command.
            slot = self._adapter_goals[adapter_id]
            pending = slot.peek()
            merged = dict(pending.value) if pending is not None else {}
            merged.update(batch)
            slot.set(merged, t_mono_ns=time.monotonic_ns())

    async def _run_dispatcher(
        self, adapter_id: str, adapter: ResourceAdapter
    ) -> None:
        goal = self._adapter_goals[adapter_id]
        last_seq = 0
        while not self._stopped.is_set():
            try:
                stamped = await goal.wait_for_new(since_seq=last_seq)
                last_seq = goal.seq
                await adapter.send_commands(stamped.value)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._publish_error(exc)

    async def _run_snapshots(self) -> None:
        assert self.snapshot_rate_hz is not None
        assert self.on_snapshot is not None
        interval = 1.0 / self.snapshot_rate_hz
        while not self._stopped.is_set():
            started = time.monotonic()
            try:
                self.on_snapshot(
                    time.monotonic_ns(),
                    self.snapshot_states(),
                    self.snapshot_commands(),
                    dict(self._latest_steps),
                )
            except Exception as exc:
                await self._publish_error(exc)
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))
