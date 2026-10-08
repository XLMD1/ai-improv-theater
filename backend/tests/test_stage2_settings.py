import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.main import app


database_url = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not database_url or not (make_url(database_url).database or "").endswith("_test"),
    reason="stage 2 integration tests require a dedicated *_test PostgreSQL database",
)


def test_local_settings_never_echoes_api_key_and_loses_it_after_clear():
    with TestClient(app) as client:
        initial = client.get("/local-settings")
        assert initial.status_code == 200
        assert initial.json()["providers"]["deepseek"] == {
            "model_id": "deepseek-flash", "configured": False, "available": True,
        }

        saved = client.put("/local-settings/keys/deepseek", json={"api_key": "test-secret-value"})
        assert saved.status_code == 200
        assert saved.json() == {"configured": True}
        assert "test-secret-value" not in client.get("/local-settings").text

        cleared = client.delete("/local-settings/keys/deepseek")
        assert cleared.status_code == 200
        assert cleared.json() == {"configured": False}
        assert client.get("/local-settings").json()["providers"]["deepseek"]["configured"] is False


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_browser_can_preflight_key_changes(method: str):
    with TestClient(app) as client:
        response = client.options(
            "/local-settings/keys/deepseek",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert method in response.headers["access-control-allow-methods"]


def test_ai_session_pins_provider_and_rejects_unverified_model():
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-deepseek-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek", "model_id": "deepseek-flash"})
            assert created.status_code == 201, created.text
            data = created.json()
            assert data["provider"] == "deepseek"
            assert data["model_id"] == "deepseek-flash"
            current = client.get("/session", headers={"Authorization": f"Bearer {data['token']}"})
            assert current.json() == {"provider": "deepseek", "model_id": "deepseek-flash"}

            wrong = client.post("/sessions", json={"provider": "deepseek", "model_id": "invented"})
            assert wrong.status_code == 422
        finally:
            client.delete("/local-settings/keys/deepseek")


def test_new_ai_story_requires_key_but_demo_stays_keyless():
    with TestClient(app) as client:
        client.delete("/local-settings/keys/openai")
        ai = client.post("/sessions", json={"provider": "openai", "model_id": "gpt-6-luna"})
        assert ai.status_code == 409
        demo = client.post("/sessions")
        assert demo.status_code == 201
        assert demo.json()["provider"] == "demo"


def test_openai_key_and_story_remain_pending_verification():
    with TestClient(app) as client:
        status = client.get("/local-settings").json()["providers"]["openai"]
        assert status["available"] is False
        assert status["configured"] is False
        saved = client.put("/local-settings/keys/openai", json={"api_key": "test-openai-key"})
        assert saved.status_code == 409
        assert "待开发验证" in saved.json()["detail"]
        assert client.delete("/local-settings/keys/openai").status_code == 409
        created = client.post("/sessions", json={"provider": "openai", "model_id": "gpt-6-luna"})
        assert created.status_code == 409


def test_invalid_api_key_is_rejected_without_echoing_input():
    with TestClient(app) as client:
        long_key = "private-sentinel-" + "x" * 550
        response = client.put("/local-settings/keys/deepseek", json={"api_key": long_key})
        assert response.status_code == 422
        assert long_key not in response.text
        assert client.put("/local-settings/keys/deepseek", json={"api_key": "   "}).status_code == 422
        assert client.get("/local-settings").json()["providers"]["deepseek"]["configured"] is False


def test_restarted_key_store_blocks_new_turn_but_not_old_replay():
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        created = client.post("/sessions", json={"provider": "deepseek"}).json()
        headers = {"Authorization": f"Bearer {created['token']}"}
        client.delete("/local-settings/keys/deepseek")
        blocked = client.post(
            "/turns", headers={**headers, "Idempotency-Key": "after-restart"},
            json={"parent_node_id": created["root"]["id"], "action": {"type": "option", "value": "search"}},
        )
        assert blocked.status_code == 409
        assert client.get(f"/nodes/{created['root']['id']}", headers=headers).status_code == 200
