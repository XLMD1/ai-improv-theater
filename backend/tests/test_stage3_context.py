import json
import os
import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.db import SessionLocal
from app.generation import _prompt
from app.jobs import _recent_turns
from app.main import app
from app.provider_clients import ModelResult
from app.schemas import Action
from app.demo import build_demo_scene


database_url = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not database_url or not (make_url(database_url).database or "").endswith("_test"),
    reason="stage 3 integration tests require a dedicated *_test PostgreSQL database",
)


def _turn(client: TestClient, token: str, parent: dict, choice: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    submitted = client.post(
        "/turns", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"parent_node_id": parent["id"], "action": {"type": "option", "value": choice}},
    )
    assert submitted.status_code == 202
    for _ in range(100):
        run = client.get(f"/runs/{submitted.json()['run_id']}", headers=headers).json()
        if run["status"] == "completed":
            return client.get(f"/nodes/{run['node_id']}", headers=headers).json()
        time.sleep(.01)
    pytest.fail("demo turn did not finish")


def test_recent_context_uses_only_last_three_ancestors_not_siblings():
    with TestClient(app) as client:
        created = client.post("/sessions").json()
        token, root = created["token"], created["root"]
        chosen = _turn(client, token, root, "search")
        sibling = _turn(client, token, root, "ask")
        dock = _turn(client, token, chosen, "dock")
        lighthouse = _turn(client, token, dock, "continue")

        with SessionLocal() as db:
            context = _recent_turns(db, lighthouse["id"])

        assert [turn["scene_id"] for turn in context] == ["s2", "s3", "s5"]
        assert [turn["player_action"]["value"] for turn in context] == ["search", "dock", "continue"]
        assert sibling["id"] not in json.dumps(context)
        assert "ask" not in json.dumps(context)

        action = Action(type="option", value="reveal")
        target, _ = build_demo_scene(lighthouse["state_snapshot"], action)
        prompt = _prompt(lighthouse["state_snapshot"], action, target, context)
        source = json.loads(prompt.split("背景资料：", 1)[1])
        assert source["recent_turns"] == context


def test_ai_prompt_receives_only_the_selected_branch_history():
    prompts = []

    async def fake_provider(_provider, _model_id, _key, prompt):
        context = json.loads(prompt.split("背景资料：", 1)[1])
        prompts.append(context)
        draft = {
            "narration": f"已批准的{context['user_action']['value']}分支叙述",
            "dialogue": [
                {"character_id": character_id, "text": "继续调查。", "emotion": "neutral"}
                for character_id in context["allowed_speakers"]
            ],
            "state_changes": [],
        }
        return ModelResult(json.dumps(draft, ensure_ascii=False), 100, 50)

    with TestClient(app) as client:
        client.put("/local-settings/keys/deepseek", json={"api_key": "test-key"})
        try:
            created = client.post("/sessions", json={"provider": "deepseek"}).json()
            token, root = created["token"], created["root"]
            with patch("app.generation.call_provider", side_effect=fake_provider):
                chosen = _turn(client, token, root, "search")
                _turn(client, token, root, "ask")
                dock = _turn(client, token, chosen, "dock")
        finally:
            client.delete("/local-settings/keys/deepseek")

    branch_context = prompts[-1]["recent_turns"]
    assert dock["prompt_version"] == "single-2"
    assert [turn["player_action"]["value"] for turn in branch_context if turn["player_action"]] == ["search"]
    assert "已批准的search分支叙述" in json.dumps(branch_context, ensure_ascii=False)
    assert "已批准的ask分支叙述" not in json.dumps(branch_context, ensure_ascii=False)


def test_old_free_text_is_capped_in_recent_context():
    with TestClient(app) as client:
        created = client.post("/sessions").json()
        token, root = created["token"], created["root"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}
        submitted = client.post(
            "/turns", headers=headers,
            json={"parent_node_id": root["id"], "action": {"type": "text", "value": "甲" * 500}},
        )
        assert submitted.status_code == 202
        for _ in range(100):
            run = client.get(f"/runs/{submitted.json()['run_id']}", headers=headers).json()
            if run["status"] == "completed":
                break
            time.sleep(.01)
        with SessionLocal() as db:
            recent = _recent_turns(db, run["node_id"])
        assert recent[-1]["player_action"]["value"] == "甲" * 120
