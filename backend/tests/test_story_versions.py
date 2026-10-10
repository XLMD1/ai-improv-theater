import os
from copy import deepcopy
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.models import StoryVersion
from app.story_schema import Story
from app.story_versions import load_story_version, save_story_version
from test_investigation_schema import sample_data

url = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not url or not (make_url(url).database or "").endswith("_test"),
    reason="requires dedicated *_test PostgreSQL database",
)


def test_version_identity_hash_and_database_immutability():
    from sqlalchemy.orm import Session
    engine = create_engine(url)
    data = sample_data()
    data["story_id"] = str(uuid4())
    definition = Story.model_validate(data)
    with Session(engine) as db:
        version = save_story_version(db, definition)
        db.commit()
        version_id = version.id
        assert version.approval_status == "draft"
        assert load_story_version(db, version_id) == definition
        assert save_story_version(db, definition).id == version_id
        changed = deepcopy(data)
        changed["public_intro"] += "不同的稿件"
        with pytest.raises(ValueError, match="version_identity_conflict"):
            save_story_version(db, Story.model_validate(changed))
        changed["story_version"] = "draft-2"
        different = save_story_version(db, Story.model_validate(changed))
        db.commit()
        assert different.id != version_id
        assert load_story_version(db, version_id).public_intro == definition.public_intro
    for sql in [
        "UPDATE story_versions SET definition = '{}'::jsonb WHERE id = :id",
        "UPDATE story_versions SET content_hash = repeat('0',64) WHERE id = :id",
        "DELETE FROM story_versions WHERE id = :id",
    ]:
        with engine.connect() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(text(sql), {"id": version_id})
            connection.rollback()
    engine.dispose()


def test_loader_detects_corrupt_hash_without_exposing_story():
    from unittest.mock import Mock
    data = sample_data()
    row = StoryVersion(id=str(uuid4()), story_id=data["story_id"], story_version=data["story_version"],
                       schema_version=data["schema_version"], engine_version="investigation-1",
                       definition=data, content_hash="0" * 64, approval_status="draft")
    db = Mock()
    db.get.return_value = row
    with pytest.raises(ValueError, match="story_integrity_error"):
        load_story_version(db, row.id)


def test_incremental_migration_preserves_old_node_and_event_bytes():
    """A separate database at revision 0003 proves existing rows survive 0004."""
    original = make_url(url)
    database_name = "stage1_migration_" + uuid4().hex + "_test"
    migration_url = original.set(database=database_name)
    admin = create_engine(original.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": database_name})
        if exists:
            pytest.fail("migration test database already exists; use a fresh isolated cluster")
        connection.exec_driver_sql("CREATE DATABASE " + database_name)
    admin.dispose()
    config = Config("alembic.ini")
    previous = os.environ.get("MIGRATION_DATABASE_URL")
    os.environ["MIGRATION_DATABASE_URL"] = migration_url.render_as_string(hide_password=False)
    engine = create_engine(migration_url)
    try:
        command.upgrade(config, "0003_llm_calls")
        session_id, node_id, event_id = [str(uuid4()) for _ in range(3)]
        with engine.begin() as db:
            db.execute(text("INSERT INTO sessions (id,token_hash,provider,model_id,created_at) "
                            "VALUES (:id,:hash,'demo','demo',now())"), {"id": session_id, "hash": "x"*64})
            db.execute(text("INSERT INTO nodes (id,session_id,depth,scene_id,state_snapshot,rendered_scene,"
                            "canon_version,prompt_version,model_id,created_at) "
                            "VALUES (:id,:sid,0,'s1',CAST(:state AS jsonb),CAST(:render AS jsonb),'1.0.0','old','demo',now())"),
                       {"id": node_id, "sid": session_id, "state": '{"schema_version":1,"scene_id":"s1","flags":{}}',
                        "render": '{"narration":"旧节点原文","dialogue":[]}'})
            db.execute(text("INSERT INTO turn_events (id,node_id,event_type,payload,created_at) "
                            "VALUES (:id,:nid,'story_started',CAST(:payload AS jsonb),now())"),
                       {"id": event_id, "nid": node_id, "payload": '{"text":"旧事件原文"}'})
        def saved():
            with engine.connect() as db:
                return (db.execute(text("SELECT state_snapshot::text,rendered_scene::text FROM nodes WHERE id=:id"),
                                   {"id": node_id}).one(),
                        db.scalar(text("SELECT payload::text FROM turn_events WHERE id=:id"), {"id": event_id}))
        before = saved()
        command.upgrade(config, "head")
        assert saved() == before
        with engine.connect() as db:
            assert db.execute(text("SELECT story_version_id,engine_version,mode FROM sessions WHERE id=:id"),
                              {"id": session_id}).one() == (None, None, None)
            assert db.scalar(text("SELECT story_version_id FROM nodes WHERE id=:id"), {"id": node_id}) is None
        # Schema downgrade also retains every legacy node and event.
        command.downgrade(config, "0003_llm_calls")
        assert saved() == before

        command.upgrade(config, "head")
        from sqlalchemy.orm import Session
        with Session(engine) as db:
            definition = Story.model_validate(sample_data())
            saved_version = save_story_version(db, definition)
            db.commit()
            version_id = saved_version.id
        with pytest.raises(RuntimeError, match="cannot downgrade investigation records"):
            command.downgrade(config, "0003_llm_calls")
        with engine.connect() as db:
            assert db.scalar(text("SELECT content_hash FROM story_versions WHERE id=:id"),
                             {"id": version_id}) is not None
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous
