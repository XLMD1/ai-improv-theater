import os
import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.canon import initial_state
from app.main import app
from app.schemas import StateChange
from app.state import StoryValidationError, apply_state_changes


database_url = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not database_url or not (make_url(database_url).database or "").endswith("_test"),
    reason="stage 1 integration tests require a dedicated *_test PostgreSQL database",
)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def start(client: TestClient):
    response = client.post("/sessions")
    assert response.status_code == 201
    data = response.json()
    return {"Authorization": f"Bearer {data['token']}"}, data["root"]


def turn(client: TestClient, headers: dict, parent: dict, choice: str) -> dict:
    response = client.post(
        "/turns", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"parent_node_id": parent["id"], "action": {"type": "option", "value": choice}},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    for _ in range(100):
        run = client.get(f"/runs/{run_id}", headers=headers).json()
        if run["status"] == "completed":
            result = client.get(f"/nodes/{run['node_id']}", headers=headers)
            assert result.status_code == 200
            return result.json()
        assert run["status"] not in ("failed", "interrupted"), run
        time.sleep(.01)
    pytest.fail("demo run did not finish")


def test_three_endings_are_reachable_and_state_is_consistent(client):
    headers, root = start(client)
    archive = turn(client, headers, root, "search")
    assert archive["scene_id"] == "s2"
    assert archive["state_snapshot"]["flags"]["clue_found"] is True
    dock = turn(client, headers, archive, "dock")
    tower = turn(client, headers, archive, "tower")
    assert {dock["scene_id"], tower["scene_id"]} == {"s3", "s4"}
    assert tower["state_snapshot"]["flags"]["secret_shared"] is True
    assert "secret_shared" not in dock["state_snapshot"]["flags"]
    lighthouse = turn(client, headers, dock, "continue")
    assert lighthouse["scene_id"] == "s5"
    endings = [turn(client, headers, lighthouse, choice) for choice in ("reveal", "guard", "sink")]
    assert [ending["scene_id"] for ending in endings] == ["e1", "e2", "e3"]
    assert [ending["state_snapshot"]["ending_id"] for ending in endings] == ["e1", "e2", "e3"]
    assert all(ending["parent_id"] == lighthouse["id"] for ending in endings)


def test_illegal_transition_and_flag_are_rejected_without_mutation():
    parent = initial_state()
    with pytest.raises(StoryValidationError, match="illegal scene transition"):
        apply_state_changes(parent, "e1", [])
    with pytest.raises(StoryValidationError, match="invalid flag change"):
        apply_state_changes(parent, "s2", [StateChange(kind="flag_set", key="invented", value=1)])
    assert parent == initial_state()


def test_sibling_branches_are_isolated(client):
    headers, root = start(client)
    search = turn(client, headers, root, "search")
    ask = turn(client, headers, root, "ask")
    assert search["parent_id"] == ask["parent_id"] == root["id"]
    assert search["state_snapshot"]["relations"]["c1:c2"] == 1
    assert ask["state_snapshot"]["relations"]["c1:c2"] == -1
    tree = client.get("/tree", headers=headers).json()
    assert {search["id"], ask["id"]}.issubset({item["id"] for item in tree})
    labels = {item["id"]: item["action_label"] for item in tree}
    assert labels[search["id"]] == "前往档案室寻找日志"
    assert labels[ask["id"]] == "先问周砚隐瞒了什么"


def test_replay_reads_saved_bytes_without_generating(client):
    headers, root = start(client)
    saved = turn(client, headers, root, "search")
    with patch("app.jobs.build_demo_scene", side_effect=AssertionError("must not generate")):
        response = client.get(f"/nodes/{saved['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["rendered_scene"] == saved["rendered_scene"]
    assert response.json()["state_snapshot"] == saved["state_snapshot"]


def test_invalid_option_and_foreign_session_are_rejected(client):
    headers, root = start(client)
    other_headers, _ = start(client)
    bad_option = client.post(
        "/turns", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"parent_node_id": root["id"], "action": {"type": "option", "value": "not-here"}},
    )
    assert bad_option.status_code == 409
    assert client.get(f"/nodes/{root['id']}", headers=other_headers).status_code == 404


def test_idempotency_key_does_not_create_a_second_branch(client):
    headers, root = start(client)
    key = str(uuid4())
    request = {"parent_node_id": root["id"], "action": {"type": "option", "value": "search"}}
    first = client.post("/turns", headers={**headers, "Idempotency-Key": key}, json=request)
    assert first.status_code == 202
    second = client.post("/turns", headers={**headers, "Idempotency-Key": key}, json=request)
    assert second.status_code == 202
    assert second.json()["run_id"] == first.json()["run_id"]
    wrong = client.post(
        "/turns", headers={**headers, "Idempotency-Key": key},
        json={"parent_node_id": root["id"], "action": {"type": "option", "value": "ask"}},
    )
    assert wrong.status_code == 409
    for _ in range(100):
        if client.get(f"/runs/{first.json()['run_id']}", headers=headers).json()["status"] == "completed":
            break
        time.sleep(.01)
    tree = client.get("/tree", headers=headers).json()
    assert len(tree) == 2
