from __future__ import annotations

import pytest

from mimicrec.services.systemd import (
    SystemdUserServiceManager,
    _tcp_endpoint_ready,
    _tcp_port_available,
)


@pytest.mark.asyncio
async def test_status_parses_systemd_show_without_shell(monkeypatch):
    manager = SystemdUserServiceManager(enabled=True)
    manager._systemctl = "/usr/bin/systemctl"
    monkeypatch.setattr(
        "mimicrec.services.systemd._tcp_endpoint_ready",
        lambda _port: False,
    )
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str):
        calls.append(args)
        return (
            0,
            "LoadState=loaded\nActiveState=active\nSubState=running\n"
            "UnitFileState=disabled\nResult=success",
            "",
        )

    monkeypatch.setattr(manager, "_run", fake_run)
    status = await manager.status("rebotarm")

    assert status.installed is True
    assert status.active_state == "active"
    assert status.endpoint_ready is False
    assert "is not accepting connections yet" in (status.detail or "")
    assert calls == [
        (
            "show",
            "mimicrec-rebotarm.service",
            "--property=LoadState,ActiveState,SubState,UnitFileState,Result",
        )
    ]


@pytest.mark.asyncio
async def test_action_uses_fixed_allowlisted_unit(monkeypatch):
    manager = SystemdUserServiceManager(enabled=True)
    manager._systemctl = "/usr/bin/systemctl"
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str):
        calls.append(args)
        if args[0] == "show":
            return (
                0,
                "LoadState=loaded\nActiveState=active\nSubState=running\n"
                "UnitFileState=disabled\nResult=success",
                "",
            )
        return (0, "", "")

    monkeypatch.setattr(manager, "_run", fake_run)
    await manager.act("quest", "start")

    assert ("start", "mimicrec-quest.service") in calls
    with pytest.raises(KeyError):
        await manager.act("../../evil", "start")
    with pytest.raises(KeyError):
        await manager.act("quest", "../../evil")


def test_tcp_conflict_probe_does_not_connect_to_the_owner():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as owner:
        owner.bind(("127.0.0.1", 0))
        port = owner.getsockname()[1]
        assert _tcp_port_available(port) is False


def test_tcp_endpoint_probe_reports_accepting_listener():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert _tcp_endpoint_ready(port) is True
