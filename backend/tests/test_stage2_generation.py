import json
import os
import time
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.canon import initial_state
from app.demo import build_demo_scene
from app.generation import _prompt
from app.main import app
from app.schemas import Action


database_url = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not database_url or not (make_url(database_url).database or "").endswith("_test"),
    reason="stage 2 integration tests require a dedicated *_test PostgreSQL database",
)


def wait_for_run(client: TestClient, headers: dict, run_id: str) -> dict:
    for _ in range(100):
        run = client.get(f"/runs/{run_id}", headers=headers).json()
        if run["status"] in ("completed", "failed", "interrupted"):
            return run
        time.sleep(.01)
    pytest.fail("run did not finish")


def deepseek_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 120, "completion_tokens": 80}},
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )


def submit_search(client: TestClient, headers: dict, root: dict, key: str | None = None) -> httpx.Response:
    return client.post(
        "/turns", headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={"parent_node_id": root["id"], "action": {"type": "option", "value": "search"}},
    )


def test_deepseek_prompt_specifies_array_shape_with_all_speakers():
    action = Action(type="option", value="search")
    state = initial_state()
    target, _ = build_demo_scene(state, action)
    prompt = _prompt(state, action, target)
    assert "dialogue 和 state_changes 必须是数组" in prompt
    assert "emotion 只能是 neutral、joy、fear、anger、sadness" in prompt
    example = json.loads(prompt.split("输出格式示例：", 1)[1].split("背景资料：", 1)[0])
    assert [line["character_id"] for line in example["dialogue"]] == ["c1", "c2"]
    assert example["state_changes"] == []


def test_deepseek_candidate_uses_fixed_route_and_replays_without_model_call():
    draft = {
        "narration": "林岚在旧档案室的柜底发现了带盐渍的日志。",
        "dialogue": [
            {"character_id": "c1", "text": "这些页码被人撕过。", "emotion": "fear"},
            {"character_id": "c2", "text": "先别让其他人知道。", "emotion": "neutral"},
        ],
        "state_changes": [{"kind": "relation_delta", "key": "c1:c3", "value": 1}],
    }
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek", "model_id": "deepseek-flash"}).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            with patch("httpx.AsyncClient.post", return_value=deepseek_response(json.dumps(draft, ensure_ascii=False))) as model_post:
                submitted = client.post(
                    "/turns", headers={**headers, "Idempotency-Key": str(uuid4())},
                    json={"parent_node_id": created["root"]["id"], "action": {"type": "option", "value": "search"}},
                )
                assert submitted.status_code == 202
                run = wait_for_run(client, headers, submitted.json()["run_id"])
                assert run["status"] == "completed", run
                node = client.get(f"/nodes/{run['node_id']}", headers=headers).json()
                assert node["scene_id"] == "s2"
                assert node["rendered_scene"]["narration"] == draft["narration"]
                assert [option["id"] for option in node["rendered_scene"]["options"]] == ["dock", "tower"]
                assert node["state_snapshot"]["flags"]["clue_found"] is True
                assert node["state_snapshot"]["relations"]["c1:c3"] == 1
                assert node["model_id"] == "deepseek:deepseek-flash"
                budget = client.get("/local-settings").json()["budget"]
                assert budget["estimated_spend_cny"] > 0
                assert budget["limit_cny"] == 100
                assert model_post.call_count == 1
                replay = client.get(f"/nodes/{node['id']}", headers=headers).json()
                assert replay["rendered_scene"] == node["rendered_scene"]
                assert model_post.call_count == 1
        finally:
            client.delete("/local-settings/keys/deepseek")


def test_model_cannot_double_apply_a_deterministic_relation_change():
    draft = {
        "narration": "两人在档案室找到日志。",
        "dialogue": [
            {"character_id": "c1", "text": "找到了。", "emotion": "joy"},
            {"character_id": "c2", "text": "先确认真伪。", "emotion": "neutral"},
        ],
        "state_changes": [{"kind": "relation_delta", "key": "c1:c2", "value": 1}],
    }
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek"}).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            with patch("httpx.AsyncClient.post", return_value=deepseek_response(json.dumps(draft, ensure_ascii=False))):
                submitted = submit_search(client, headers, created["root"])
                run = wait_for_run(client, headers, submitted.json()["run_id"])
            node = client.get(f"/nodes/{run['node_id']}", headers=headers).json()
            assert node["rendered_scene"]["fallback"] is False
            assert node["state_snapshot"]["relations"]["c1:c2"] == 1
        finally:
            client.delete("/local-settings/keys/deepseek")


def test_invalid_proposal_is_rejected_before_fixed_key_deduplication():
    draft = {
        "narration": "档案室里找到日志。",
        "dialogue": [
            {"character_id": "c1", "text": "找到了。", "emotion": "joy"},
            {"character_id": "c2", "text": "先确认真伪。", "emotion": "neutral"},
        ],
        "state_changes": [{"kind": "flag_set", "key": "clue_found", "value": 2}],
    }
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek"}).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            with patch("httpx.AsyncClient.post", return_value=deepseek_response(json.dumps(draft, ensure_ascii=False))):
                submitted = submit_search(client, headers, created["root"])
                run = wait_for_run(client, headers, submitted.json()["run_id"])
            node = client.get(f"/nodes/{run['node_id']}", headers=headers).json()
            assert node["rendered_scene"]["fallback"] is True
            assert node["state_snapshot"]["flags"] == {}
        finally:
            client.delete("/local-settings/keys/deepseek")


def test_ai_idempotency_and_sse_resume_do_not_repeat_model_call():
    draft = {
        "narration": "档案室里找到日志。",
        "dialogue": [
            {"character_id": "c1", "text": "线索就在这里。", "emotion": "joy"},
            {"character_id": "c2", "text": "仔细检查。", "emotion": "neutral"},
        ],
        "state_changes": [],
    }
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek"}).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            key = str(uuid4())
            with patch("httpx.AsyncClient.post", return_value=deepseek_response(json.dumps(draft, ensure_ascii=False))) as model_post:
                first = submit_search(client, headers, created["root"], key)
                second = submit_search(client, headers, created["root"], key)
                assert first.json()["run_id"] == second.json()["run_id"]
                run = wait_for_run(client, headers, first.json()["run_id"])
            assert run["status"] == "completed"
            assert model_post.call_count == 1
            assert len(client.get("/tree", headers=headers).json()) == 2
            full = client.get(f"/runs/{run['id']}/events?after=0", headers=headers).text
            seqs = [int(line[4:]) for line in full.splitlines() if line.startswith("id: ")]
            assert seqs == list(range(1, len(seqs) + 1))
            replay = client.get(f"/runs/{run['id']}/events?after={seqs[2]}", headers=headers).text
            replay_seqs = [int(line[4:]) for line in replay.splitlines() if line.startswith("id: ")]
            assert replay_seqs == seqs[3:]
        finally:
            client.delete("/local-settings/keys/deepseek")


def test_budget_limit_rejects_ai_turn_before_model_call():
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek"}).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            with patch("app.jobs.total_spend_cny", return_value=Decimal("100")), patch("httpx.AsyncClient.post") as model_post:
                response = submit_search(client, headers, created["root"])
            assert response.status_code == 409
            assert len(client.get("/tree", headers=headers).json()) == 1
            model_post.assert_not_called()
        finally:
            client.delete("/local-settings/keys/deepseek")


def test_invalid_candidate_becomes_committed_fallback_without_leaking_raw_text():
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek"}).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            with patch("httpx.AsyncClient.post", return_value=deepseek_response("RAW_UNAPPROVED_TEXT")):
                submitted = submit_search(client, headers, created["root"])
                run = wait_for_run(client, headers, submitted.json()["run_id"])
            assert run["status"] == "completed"
            node = client.get(f"/nodes/{run['node_id']}", headers=headers).json()
            assert node["rendered_scene"]["fallback"] is True
            assert node["scene_id"] == "s2"
            assert node["state_snapshot"]["flags"] == {}
            events = client.get(f"/runs/{run['id']}/events", headers=headers).text
            assert "RAW_UNAPPROVED_TEXT" not in events
        finally:
            client.delete("/local-settings/keys/deepseek")


def test_provider_authentication_failure_creates_no_ghost_node():
    failure = httpx.Response(
        401, json={"error": {"message": "invalid-test-key"}},
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "invalid-test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek"}).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            with patch("httpx.AsyncClient.post", return_value=failure):
                submitted = submit_search(client, headers, created["root"])
                run = wait_for_run(client, headers, submitted.json()["run_id"])
            assert run["status"] == "failed"
            assert run["node_id"] is None
            assert "invalid-test-key" not in client.get(f"/runs/{run['id']}/events", headers=headers).text
            assert len(client.get("/tree", headers=headers).json()) == 1
        finally:
            client.delete("/local-settings/keys/deepseek")


def test_missing_provider_usage_cannot_be_recorded_as_zero_cost():
    draft = {
        "narration": "档案室里找到日志。",
        "dialogue": [
            {"character_id": "c1", "text": "找到了。", "emotion": "joy"},
            {"character_id": "c2", "text": "先确认真伪。", "emotion": "neutral"},
        ],
        "state_changes": [],
    }
    response = httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(draft, ensure_ascii=False)}}]},
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )
    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek"}).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            with patch("httpx.AsyncClient.post", return_value=response):
                submitted = submit_search(client, headers, created["root"])
                run = wait_for_run(client, headers, submitted.json()["run_id"])
            assert run["status"] == "failed"
            assert run["node_id"] is None
            assert len(client.get("/tree", headers=headers).json()) == 1
        finally:
            client.delete("/local-settings/keys/deepseek")
