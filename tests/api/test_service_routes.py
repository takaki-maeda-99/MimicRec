from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from mimicrec.services.systemd import SERVICES, ServiceStatus
from mimicrec.types import SessionState


def _status(service_id: str, *, active: bool = False) -> ServiceStatus:
    definition = SERVICES[service_id]
    return ServiceStatus(
        id=definition.id,
        unit=definition.unit,
        label=definition.label,
        description=definition.description,
        safety_critical=definition.safety_critical,
        control_enabled=True,
        installed=True,
        active_state="active" if active else "inactive",
        sub_state="running" if active else "dead",
        unit_file_state="disabled",
        result="success",
        endpoint_ready=active,
        conflict=False,
    )


class FakeServiceManager:
    def __init__(self):
        self.actions: list[tuple[str, str]] = []

    def definition(self, service_id: str):
        if service_id not in SERVICES:
            raise KeyError(f"unknown managed service: {service_id}")
        return SERVICES[service_id]

    async def list_status(self):
        return [_status("rebotarm"), _status("quest", active=True)]

    async def act(self, service_id: str, action: str):
        self.actions.append((service_id, action))
        return _status(service_id, active=action != "stop")


@pytest.mark.asyncio
async def test_service_list_reports_only_allowlisted_units(app):
    app.state.service_manager = FakeServiceManager()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/services")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["rebotarm", "quest"]


@pytest.mark.asyncio
async def test_service_mutation_requires_csrf_header(app):
    manager = FakeServiceManager()
    app.state.service_manager = manager
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/services/quest/start", json={})

    assert response.status_code == 403
    assert manager.actions == []


@pytest.mark.asyncio
async def test_service_mutation_rejects_nonlocal_direct_client(app):
    manager = FakeServiceManager()
    app.state.service_manager = manager
    transport = ASGITransport(app=app, client=("192.0.2.10", 4321))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/services/quest/start",
            headers={"X-MimicRec-Control": "1"},
            json={},
        )

    assert response.status_code == 403
    assert manager.actions == []


@pytest.mark.asyncio
async def test_cors_preflight_rejects_unconfigured_web_origin(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/api/services/quest/start",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-MimicRec-Control",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_rebotarm_start_requires_hardware_confirmation(app):
    manager = FakeServiceManager()
    app.state.service_manager = manager
    headers = {"X-MimicRec-Control": "1"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        refused = await client.post(
            "/api/services/rebotarm/start", headers=headers, json={}
        )
        accepted = await client.post(
            "/api/services/rebotarm/start",
            headers=headers,
            json={"confirm_hardware_ready": True},
        )

    assert refused.status_code == 409
    assert accepted.status_code == 200
    assert manager.actions == [("rebotarm", "start")]


@pytest.mark.asyncio
async def test_service_changes_are_blocked_during_active_session(app):
    manager = FakeServiceManager()
    app.state.service_manager = manager
    app.state.session_manager = SimpleNamespace(
        session=SimpleNamespace(
            state=SessionState.READY,
            stopped=asyncio.Event(),
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/services/quest/stop",
            headers={"X-MimicRec-Control": "1"},
            json={},
        )

    assert response.status_code == 409
    assert manager.actions == []


@pytest.mark.asyncio
async def test_unknown_services_and_actions_are_not_forwarded(app):
    manager = FakeServiceManager()
    app.state.service_manager = manager
    headers = {"X-MimicRec-Control": "1"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        unknown_service = await client.post(
            "/api/services/arbitrary/start", headers=headers, json={}
        )
        unknown_action = await client.post(
            "/api/services/quest/run-command", headers=headers, json={}
        )

    assert unknown_service.status_code == 404
    assert unknown_action.status_code == 404
    assert manager.actions == []


@pytest.mark.asyncio
async def test_clear_fault_requires_confirmation_and_uses_daemon(app, monkeypatch):
    manager = FakeServiceManager()
    app.state.service_manager = manager
    calls = []

    async def fake_clear(target_app):
        calls.append(target_app)
        return {"ok": True, "mode": "gravity_comp", "motors": {}}

    monkeypatch.setattr(
        "mimicrec.api.routes.services._clear_rebotarm_fault", fake_clear
    )
    headers = {"X-MimicRec-Control": "1"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        refused = await client.post(
            "/api/services/rebotarm/clear-fault", headers=headers, json={}
        )
        accepted = await client.post(
            "/api/services/rebotarm/clear-fault",
            headers=headers,
            json={"confirm_hardware_ready": True},
        )

    assert refused.status_code == 409
    assert accepted.status_code == 200
    assert accepted.json()["mode"] == "gravity_comp"
    assert calls == [app]
    assert manager.actions == []


@pytest.mark.asyncio
async def test_clear_fault_is_rebotarm_only(app):
    app.state.service_manager = FakeServiceManager()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/services/quest/clear-fault",
            headers={"X-MimicRec-Control": "1"},
            json={"confirm_hardware_ready": True},
        )
    assert response.status_code == 404
