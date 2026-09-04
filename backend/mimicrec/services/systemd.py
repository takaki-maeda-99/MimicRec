"""Narrow, shell-free access to MimicRec's allow-listed systemd user units."""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ServiceDefinition:
    id: str
    unit: str
    label: str
    description: str
    safety_critical: bool = False
    tcp_port: int | None = None


@dataclass(frozen=True)
class ServiceStatus:
    id: str
    unit: str
    label: str
    description: str
    safety_critical: bool
    control_enabled: bool
    installed: bool
    active_state: str
    sub_state: str
    unit_file_state: str
    result: str
    endpoint_ready: bool
    detail: str | None = None
    conflict: bool = False

    def model_dict(self) -> dict:
        return asdict(self)


SERVICES: dict[str, ServiceDefinition] = {
    "rebotarm": ServiceDefinition(
        id="rebotarm",
        unit="mimicrec-rebotarm.service",
        label="reBotArm daemon",
        description="Hardware safety daemon and ZMQ control endpoint",
        safety_critical=True,
        tcp_port=5558,
    ),
    "so101": ServiceDefinition(
        id="so101",
        unit="mimicrec-so101.service",
        label="SO-101 daemon",
        description="Feetech bus owner, heartbeat watchdog, and ZMQ endpoint",
        safety_critical=True,
        tcp_port=5559,
    ),
    "quest": ServiceDefinition(
        id="quest",
        unit="mimicrec-quest.service",
        label="Quest ROS 2 bridge",
        description="Unity ROS TCP endpoint and MimicRec Quest bridge",
        tcp_port=10000,
    ),
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ServiceCommandError(RuntimeError):
    pass


class SystemdUserServiceManager:
    """Control only the units declared in ``SERVICES``.

    Commands are passed as argv directly to ``systemctl``. Unit names, command
    names, paths, and arguments are never accepted from an HTTP request.
    """

    def __init__(self, *, enabled: bool | None = None, timeout_s: float = 12.0):
        self.enabled = (
            _env_flag("MIMICREC_SERVICE_CONTROL_ENABLED")
            if enabled is None
            else enabled
        )
        self.timeout_s = timeout_s
        self._systemctl = shutil.which("systemctl")
        self._lock = asyncio.Lock()

    def definition(self, service_id: str) -> ServiceDefinition:
        try:
            return SERVICES[service_id]
        except KeyError as exc:
            raise KeyError(f"unknown managed service: {service_id}") from exc

    async def _run(self, *args: str) -> tuple[int, str, str]:
        if self._systemctl is None:
            raise ServiceCommandError("systemctl is not installed on this host")
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                self._systemctl,
                "--user",
                "--no-pager",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_s
            )
        except asyncio.TimeoutError as exc:
            if proc is not None:
                proc.kill()
                await proc.communicate()
            raise ServiceCommandError("systemd operation timed out") from exc
        return (
            int(proc.returncode or 0),
            stdout_b.decode(errors="replace").strip(),
            stderr_b.decode(errors="replace").strip(),
        )

    async def status(self, service_id: str) -> ServiceStatus:
        definition = self.definition(service_id)
        if self._systemctl is None:
            return self._unavailable(definition, "systemctl is not installed")

        code, stdout, stderr = await self._run(
            "show",
            definition.unit,
            "--property=LoadState,ActiveState,SubState,UnitFileState,Result",
        )
        props: dict[str, str] = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                props[key] = value

        load_state = props.get("LoadState", "not-found")
        installed = load_state == "loaded"
        detail = None
        if not installed:
            detail = stderr or "Unit is not installed; run scripts/install_user_services.sh"
        elif code != 0:
            detail = stderr or "Unable to read unit state"

        active_state = props.get("ActiveState", "unknown")
        endpoint_ready = (
            _tcp_endpoint_ready(definition.tcp_port)
            if installed and definition.tcp_port is not None
            else False
        )
        conflict = False
        if installed and active_state != "active" and definition.tcp_port is not None:
            conflict = not _tcp_port_available(definition.tcp_port)
            if conflict:
                detail = (
                    f"TCP port {definition.tcp_port} is owned outside this managed unit; "
                    "stop the existing process before starting it here"
                )
        elif (
            installed
            and active_state == "active"
            and definition.tcp_port is not None
            and not endpoint_ready
        ):
            detail = (
                f"Service process is active, but tcp://localhost:{definition.tcp_port} "
                "is not accepting connections yet; hardware may be disconnected "
                "or still reconnecting"
            )

        return ServiceStatus(
            id=definition.id,
            unit=definition.unit,
            label=definition.label,
            description=definition.description,
            safety_critical=definition.safety_critical,
            control_enabled=self.enabled,
            installed=installed,
            active_state=active_state,
            sub_state=props.get("SubState", "unknown"),
            unit_file_state=props.get("UnitFileState", "unknown"),
            result=props.get("Result", "unknown"),
            endpoint_ready=endpoint_ready,
            detail=detail,
            conflict=conflict,
        )

    async def list_status(self) -> list[ServiceStatus]:
        return [await self.status(service_id) for service_id in SERVICES]

    async def act(self, service_id: str, action: str) -> ServiceStatus:
        definition = self.definition(service_id)
        if not self.enabled:
            raise ServiceCommandError(
                "service control is disabled; run scripts/install_user_services.sh"
            )
        if action not in {"start", "stop", "restart"}:
            raise KeyError(f"unsupported service action: {action}")

        async with self._lock:
            before = await self.status(service_id)
            if not before.installed:
                raise ServiceCommandError(before.detail or "unit is not installed")
            if before.conflict and action in {"start", "restart"}:
                raise ServiceCommandError(before.detail or "service port is already in use")
            code, _stdout, stderr = await self._run(action, definition.unit)
            if code != 0:
                raise ServiceCommandError(
                    stderr or f"systemctl {action} failed with exit code {code}"
                )
            after = await self.status(service_id)
            if action in {"start", "restart"} and after.active_state != "active":
                raise ServiceCommandError(
                    f"{definition.unit} did not become active "
                    f"({after.active_state}/{after.sub_state}); inspect its user journal"
                )
            if action == "stop" and after.active_state == "active":
                raise ServiceCommandError(
                    f"{definition.unit} is still active after stop"
                )
            return after

    def _unavailable(self, definition: ServiceDefinition, detail: str) -> ServiceStatus:
        return ServiceStatus(
            id=definition.id,
            unit=definition.unit,
            label=definition.label,
            description=definition.description,
            safety_critical=definition.safety_critical,
            control_enabled=self.enabled,
            installed=False,
            active_state="unknown",
            sub_state="unknown",
            unit_file_state="unknown",
            result="unknown",
            endpoint_ready=False,
            detail=detail,
        )


def _tcp_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _tcp_endpoint_ready(port: int, *, timeout_s: float = 0.15) -> bool:
    """Return whether a local service is currently accepting TCP clients.

    A unit can be ``active/running`` while its hardware reconnect loop is
    still running. MimicRec daemons bind ZMQ only after their hardware is
    usable, so this distinguishes process liveness from endpoint readiness
    without sending an application command.
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_s):
            return True
    except OSError:
        return False
