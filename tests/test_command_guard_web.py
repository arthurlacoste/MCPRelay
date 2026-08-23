from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_guard import GuardRequest, GuardService
from command_guard_config import CustomGuardStore
from command_guard_web import ACTION_HEADER, ACTION_VALUE, MAX_COMMAND_GUARD_BODY_BYTES, register_command_guard_routes


def payload(**overrides):
    value = {
        "id": "protect-production-deploy",
        "label": "Protect production deploy",
        "enabled": True,
        "match_type": "contains",
        "pattern": "deploy production",
        "reason": "Production deployment requires manual review.",
        "remediation": {"summary": "Check target first.", "commands": ["git status --short"]},
    }
    value.update(overrides)
    return value


def client_for(tmp_path, *, authenticated=True, service=None, events=None):
    app = FastAPI()
    service = service or GuardService()
    store = CustomGuardStore(tmp_path / "command-guards.json")
    register_command_guard_routes(
        app, service, store, lambda request: authenticated,
        (lambda action, data: events.append((action, data))) if events is not None else None,
    )
    return TestClient(app), service, store


def mutation_headers():
    return {"Content-Type": "application/json", ACTION_HEADER: ACTION_VALUE}


def test_get_and_mutations_require_authentication(tmp_path):
    client, _, _ = client_for(tmp_path, authenticated=False)
    assert client.get("/rt/api/command-guards").status_code == 401
    assert client.post("/rt/api/command-guards/custom", json=payload(), headers=mutation_headers()).status_code == 401
    assert client.put("/rt/api/command-guards/custom/x", json=payload(id="x"), headers=mutation_headers()).status_code == 401
    assert client.request("DELETE", "/rt/api/command-guards/custom/x", json={}, headers=mutation_headers()).status_code == 401


def test_mutations_require_json_and_action_header(tmp_path):
    client, _, _ = client_for(tmp_path)
    assert client.post("/rt/api/command-guards/custom", content="x").status_code == 415
    assert client.post("/rt/api/command-guards/custom", json=payload()).status_code == 403
    assert client.post("/rt/api/command-guards/test", json={"command": "echo ok"}).status_code == 403


def test_crud_persists_and_updates_service_immediately(tmp_path):
    events = []
    client, service, store = client_for(tmp_path, events=events)
    created = client.post("/rt/api/command-guards/custom", json=payload(), headers=mutation_headers())
    assert created.status_code == 201
    assert service.inspect(GuardRequest("run_command", {}, "deploy production now")).guard == "custom"
    assert store.load()[0].id == "protect-production-deploy"

    duplicate = client.post("/rt/api/command-guards/custom", json=payload(), headers=mutation_headers())
    assert duplicate.status_code == 409

    updated_payload = payload(pattern="release production", enabled=False)
    updated = client.put(
        "/rt/api/command-guards/custom/protect-production-deploy",
        json=updated_payload, headers=mutation_headers(),
    )
    assert updated.status_code == 200
    assert service.inspect(GuardRequest("run_command", {}, "deploy production now")).decision == "allow"
    assert service.inspect(GuardRequest("run_command", {}, "release production now")).decision == "allow"

    enabled_payload = payload(pattern="release production", enabled=True)
    assert client.put(
        "/rt/api/command-guards/custom/protect-production-deploy",
        json=enabled_payload, headers=mutation_headers(),
    ).status_code == 200
    assert service.inspect(GuardRequest("run_command", {}, "release production now")).guard == "custom"

    deleted = client.request(
        "DELETE", "/rt/api/command-guards/custom/protect-production-deploy",
        json={}, headers=mutation_headers(),
    )
    assert deleted.status_code == 200
    assert service.inspect(GuardRequest("run_command", {}, "release production now")).decision == "allow"
    assert store.load() == ()
    assert [item[0] for item in events] == [
        "command_guard_rule_created", "command_guard_rule_updated", "command_guard_rule_updated", "command_guard_rule_deleted",
    ]
    assert all("pattern" not in data for _, data in events)


def test_get_exposes_provider_builtin_and_custom_rules(tmp_path):
    client, _, _ = client_for(tmp_path)
    client.post("/rt/api/command-guards/custom", json=payload(), headers=mutation_headers())
    response = client.get("/rt/api/command-guards")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "builtin"
    assert body["fallback"] == "builtin"
    assert body["disabled"] is False
    assert len(body["builtin"]) == 18
    assert body["custom"][0]["id"] == "protect-production-deploy"


def test_invalid_create_update_and_builtin_mutations_are_rejected(tmp_path):
    client, _, _ = client_for(tmp_path)
    invalid = payload(match_type="regex")
    assert client.post("/rt/api/command-guards/custom", json=invalid, headers=mutation_headers()).status_code == 422
    assert client.put("/rt/api/command-guards/custom/missing", json=payload(id="missing"), headers=mutation_headers()).status_code == 404
    assert client.put("/rt/api/command-guards/builtin/git.reset-hard", json={}, headers=mutation_headers()).status_code == 404
    assert client.request("DELETE", "/rt/api/command-guards/builtin/git.reset-hard", json={}, headers=mutation_headers()).status_code == 404


def test_test_endpoint_inspects_without_executing_requested_command(tmp_path, monkeypatch):
    import command_guard
    monkeypatch.setattr(command_guard.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not execute")))
    client, _, _ = client_for(tmp_path)
    client.post("/rt/api/command-guards/custom", json=payload(), headers=mutation_headers())
    response = client.post(
        "/rt/api/command-guards/test", json={"command": "deploy production now", "cwd": "/tmp/project"}, headers=mutation_headers(),
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "deny"
    assert response.json()["guard"] == "custom"


def test_oversized_command_guard_body_is_rejected(tmp_path):
    client, _, _ = client_for(tmp_path)
    response = client.post(
        "/rt/api/command-guards/custom",
        content=b"x" * (MAX_COMMAND_GUARD_BODY_BYTES + 1),
        headers=mutation_headers(),
    )
    assert response.status_code == 413


def test_test_endpoint_can_evaluate_unsaved_candidate_without_persisting(tmp_path):
    client, service, store = client_for(tmp_path)
    response = client.post(
        "/rt/api/command-guards/test",
        json={"command": "deploy production now", "candidate": payload()},
        headers=mutation_headers(),
    )
    assert response.status_code == 200
    assert response.json()["guard"] == "custom"
    assert response.json()["rule"] == "custom.protect-production-deploy"
    assert service.custom_rules() == ()
    assert store.load() == ()


def test_test_endpoint_rejects_invalid_unsaved_candidate(tmp_path):
    client, _, _ = client_for(tmp_path)
    response = client.post(
        "/rt/api/command-guards/test",
        json={"command": "deploy production now", "candidate": payload(match_type="regex")},
        headers=mutation_headers(),
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_rule"


def test_unsaved_edit_candidate_replaces_saved_rule_during_test(tmp_path):
    client, _, _ = client_for(tmp_path)
    assert client.post(
        "/rt/api/command-guards/custom", json=payload(), headers=mutation_headers(),
    ).status_code == 201
    candidate = payload(pattern="release production")
    old_command = client.post(
        "/rt/api/command-guards/test",
        json={"command": "deploy production now", "candidate": candidate},
        headers=mutation_headers(),
    )
    new_command = client.post(
        "/rt/api/command-guards/test",
        json={"command": "release production now", "candidate": candidate},
        headers=mutation_headers(),
    )
    assert old_command.status_code == 200
    assert old_command.json()["decision"] == "allow"
    assert new_command.json()["rule"] == "custom.protect-production-deploy"


def test_disabled_provider_ignores_unsaved_candidate(tmp_path):
    client, _, _ = client_for(tmp_path, service=GuardService(provider="disabled"))
    response = client.post(
        "/rt/api/command-guards/test",
        json={"command": "deploy production now", "candidate": payload()},
        headers=mutation_headers(),
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "allow"
    assert response.json()["guard"] == "disabled"


def test_disabled_provider_still_validates_unsaved_candidate(tmp_path):
    client, _, _ = client_for(tmp_path, service=GuardService(provider="disabled"))
    response = client.post(
        "/rt/api/command-guards/test",
        json={"command": "echo ok", "candidate": payload(match_type="regex")},
        headers=mutation_headers(),
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_rule"
