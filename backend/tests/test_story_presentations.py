import os
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import StoryPresentation
from app.story_schema import Story
from app.story_versions import load_narration_protocol, load_story_version, save_story_version
from test_investigation_schema import sample_data

url = os.getenv('DATABASE_URL', '')
dedicated = bool(url and make_url(url).get_backend_name() == 'postgresql'
                 and (make_url(url).database or '').endswith('_test'))


@pytest.fixture
def db():
    if not dedicated:
        pytest.skip('requires dedicated *_test PostgreSQL database')
    engine = create_engine(url)
    with Session(engine) as session:
        yield session
    engine.dispose()


def story():
    return Story.model_validate({**sample_data(), 'story_id': str(uuid4())})


def test_policy_is_fixed_with_version_without_changing_definition(db):
    definition = story()
    row = save_story_version(db, definition, narration_protocol='approved-feedback-1')
    db.commit()
    assert load_narration_protocol(db, row.id) == 'approved-feedback-1'
    assert load_story_version(db, row.id) == definition
    assert save_story_version(db, definition, narration_protocol='approved-feedback-1').id == row.id
    with pytest.raises(ValueError, match='version_identity_conflict'):
        save_story_version(db, definition)


def test_existing_legacy_version_cannot_receive_new_policy(db):
    definition = story()
    row = save_story_version(db, definition)
    db.commit()
    assert load_narration_protocol(db, row.id) == 'model-scene-1'
    with pytest.raises(ValueError, match='version_identity_conflict'):
        save_story_version(db, definition, narration_protocol='approved-feedback-1')
    assert db.get(StoryPresentation, row.id) is None


def test_unknown_requested_policy_is_rejected_before_storage():
    db = Mock()
    with pytest.raises(ValueError, match='presentation_protocol_mismatch'):
        save_story_version(db, story(), narration_protocol='future-mode')
    db.get.assert_not_called()
    db.add.assert_not_called()


def test_corrupt_stored_policy_is_not_treated_as_legacy():
    db = Mock()
    db.get.return_value = StoryPresentation(story_version_id='v', narration_protocol='future-mode')
    with pytest.raises(ValueError, match='presentation_protocol_mismatch'):
        load_narration_protocol(db, 'v')
    db.get.assert_called_once_with(StoryPresentation, 'v')


@pytest.mark.parametrize('sql', [
    "UPDATE story_presentations SET narration_protocol='approved-feedback-1' WHERE story_version_id=:id",
    'UPDATE story_presentations SET created_at=now() WHERE story_version_id=:id',
    'DELETE FROM story_presentations WHERE story_version_id=:id',
    "INSERT INTO story_presentations VALUES (:id,'approved-feedback-1',now())",
])
def test_database_rejects_mutation_or_duplicate_policy(db, sql):
    row = save_story_version(db, story(), narration_protocol='approved-feedback-1')
    db.commit()
    version_id = row.id
    with pytest.raises(IntegrityError):
        db.execute(text(sql), {'id': version_id})
    db.rollback()
    assert load_narration_protocol(db, version_id) == 'approved-feedback-1'


@pytest.mark.parametrize('missing,protocol', [(False, 'future-mode'), (True, 'approved-feedback-1')])
def test_database_rejects_unknown_policy_and_missing_version(db, missing, protocol):
    version_id = str(uuid4()) if missing else save_story_version(db, story()).id
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(text('INSERT INTO story_presentations VALUES (:id,:protocol,now())'),
                   {'id': version_id, 'protocol': protocol})
    db.rollback()


@pytest.fixture
def migration_database():
    if not dedicated:
        pytest.skip('requires dedicated *_test PostgreSQL database')
    original = make_url(url)
    name = 'presentation_migration_' + uuid4().hex + '_test'
    admin = create_engine(original.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.exec_driver_sql('CREATE DATABASE ' + name)
    engine = create_engine(original.set(database=name))
    previous = os.environ.get('MIGRATION_DATABASE_URL')
    os.environ['MIGRATION_DATABASE_URL'] = original.set(database=name).render_as_string(hide_password=False)
    try:
        yield Config('alembic.ini'), engine
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop('MIGRATION_DATABASE_URL', None)
        else:
            os.environ['MIGRATION_DATABASE_URL'] = previous
        with admin.connect() as connection:
            connection.exec_driver_sql('DROP DATABASE ' + name)
        admin.dispose()


def test_empty_presentation_migration_can_be_reversed(migration_database):
    config, engine = migration_database
    command.upgrade(config, 'head')
    command.downgrade(config, '0005_execution_records')
    with engine.connect() as db:
        assert db.scalar(text("SELECT to_regclass('story_presentations')")) is None
    command.upgrade(config, 'head')


def test_upgrade_preserves_full_legacy_rows_and_downgrade_keeps_policy(migration_database):
    config, engine = migration_database
    command.upgrade(config, '0005_execution_records')
    sid, nid, eid = [str(uuid4()) for _ in range(3)]
    with Session(engine) as db:
        version = save_story_version(db, story())
        db.commit()
        vid = version.id
    with engine.begin() as db:
        db.execute(text("INSERT INTO sessions (id,token_hash,provider,model_id,created_at) "
                        "VALUES (:id,repeat('x',64),'demo','demo',now())"), {'id': sid})
        db.execute(text("INSERT INTO nodes (id,session_id,depth,scene_id,state_snapshot,rendered_scene,"
                        "canon_version,prompt_version,model_id,created_at,story_version_id) "
                        "VALUES (:id,:sid,0,'s1','{}','{\"narration\":\"旧正文\",\"dialogue\":[]}',"
                        "'1','old','demo',now(),:vid)"), {'id': nid, 'sid': sid, 'vid': vid})
        db.execute(text("INSERT INTO turn_events (id,node_id,event_type,payload,created_at) "
                        "VALUES (:id,:nid,'story_started','{\"text\":\"旧事件\"}',now())"),
                   {'id': eid, 'nid': nid})
    def snapshot():
        with engine.connect() as db:
            return [db.scalar(text(f'SELECT row_to_json(t)::text FROM {table} t WHERE id=:id'), {'id': id_})
                    for table, id_ in [('story_versions', vid), ('nodes', nid), ('turn_events', eid)]]
    before = snapshot()
    command.upgrade(config, 'head')
    assert snapshot() == before
    with Session(engine) as db:
        assert load_narration_protocol(db, vid) == 'model-scene-1'
        assert db.get(StoryPresentation, vid) is None
        r1 = save_story_version(db, story(), narration_protocol='approved-feedback-1')
        db.commit()
        rid = r1.id
    with pytest.raises(RuntimeError, match='cannot downgrade presentation records'):
        command.downgrade(config, '0005_execution_records')
    assert snapshot() == before
    with Session(engine) as db:
        assert load_narration_protocol(db, rid) == 'approved-feedback-1'
