import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals import export_stage2_review as review_export


def test_partial_report_cannot_be_exported_as_review_material(tmp_path, monkeypatch):
    monkeypatch.setattr(review_export, 'ROOT', tmp_path)
    monkeypatch.setenv('REVIEW_TEST_DATABASE', os.environ['DATABASE_URL'])
    report = tmp_path / 'runtime/evals/review-test/report.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'suite': 'real_model', 'summary': {'total': 12, 'succeeded': 3}}), encoding='utf-8')
    with pytest.raises(ValueError, match='review_report_incomplete'):
        review_export.export_review(report, 'REVIEW_TEST_DATABASE')
    assert not (report.parent / 'human-review.md').exists()


@pytest.mark.parametrize('fault', ['foreign_session', 'wrong_root', 'missing_parent', 'cycle'])
def test_saved_parent_chain_rejects_invalid_members(fault):
    root = SimpleNamespace(id='root', session_id='s', parent_id=None, story_version_id='v', depth=0)
    leaf = SimpleNamespace(id='leaf', session_id='s', parent_id='root', story_version_id='v', depth=1)
    rows = {'root': root, 'leaf': leaf}
    if fault == 'foreign_session':
        leaf.session_id = 'other'
    elif fault == 'wrong_root':
        rows['root'] = SimpleNamespace(id='root', session_id='s', parent_id='other', story_version_id='v', depth=1)
    elif fault == 'missing_parent':
        leaf.parent_id = 'missing'
    else:
        leaf.parent_id = 'leaf'
    db = Mock()
    db.get.side_effect = lambda model, id_: rows.get(id_)
    with pytest.raises(ValueError, match='review_path_invalid'):
        review_export.saved_path(db, 'leaf', 'root', 's')


@pytest.fixture(scope='module')
def complete_report(tmp_path_factory):
    from app.local_settings import put_key, clear_key
    from app.provider_clients import ProviderOutcome
    from pydantic import SecretStr
    from test_custom_story_creation import successful_provider
    from evals import run_stage2
    root = tmp_path_factory.mktemp('review')
    async def provider(*args):
        inp = json.loads(args[3].split('\n输入数据：', 1)[1])
        if 'text' in inp:
            index = inp['action_labels'].index(inp['text'])
            return ProviderOutcome(json.dumps({'result': {'status': 'recognized', 'action': inp['available_actions'][index]}}),
                                   20, 20, request_sent=True)
        return await successful_provider(*args)
    put_key('deepseek', SecretStr('review-fixture-private-key'))
    try:
        with patch.object(run_stage2, 'ROOT', root), patch('app.story_operations.call_operation_provider', side_effect=provider), patch.object(
                run_stage2, '_text', side_effect=lambda story, action, mapping, node: next(
                    o['label'] for o in node.rendered_scene['options'] if mapping[o['id']] == action)):
            report, path = run_stage2.run_suite('real_model', 'DATABASE_URL')
        assert report['summary']['succeeded'] == 12, report['summary']
        yield root, report, path
    finally:
        clear_key('deepseek')


def copy_report(complete_report, tmp_path, monkeypatch):
    root, original, source = complete_report
    monkeypatch.setattr(review_export, 'ROOT', tmp_path)
    monkeypatch.setenv('REVIEW_TEST_DATABASE', os.environ['DATABASE_URL'])
    path = tmp_path / 'runtime/evals/copied/report.json'
    path.parent.mkdir(parents=True)
    for file in source.parent.glob('*-frozen.json'):
        (path.parent / file.name).write_bytes(file.read_bytes())
    return deepcopy(original), path


def test_export_uses_saved_paths_and_excludes_siblings_and_credentials(complete_report, tmp_path, monkeypatch):
    from app.db import SessionLocal
    from app.models import Node, TurnEvent
    report, path = copy_report(complete_report, tmp_path, monkeypatch)
    selected = next(r for r in report['cases'] if r['id'] == 'ancient_ending_1')
    with SessionLocal.begin() as db:
        root = db.get(Node, selected['root_node_id'])
        sibling = Node(session_id=root.session_id, parent_id=root.id, depth=1, scene_id=root.scene_id,
            story_version_id=root.story_version_id, state_snapshot=root.state_snapshot,
            rendered_scene={'narration': 'SIBLING_SECRET_SENTINEL', 'dialogue': []}, canon_version=root.canon_version,
            prompt_version=root.prompt_version, model_id=root.model_id)
        db.add(sibling)
    path.write_text(json.dumps(report), encoding='utf-8')
    with patch('app.story_operations.call_operation_provider', side_effect=AssertionError('export called provider')), patch(
            'app.investigation_jobs.decide', side_effect=AssertionError('export adjudicated')):
        output = review_export.export_review(path, 'REVIEW_TEST_DATABASE')
    text = output.read_text(encoding='utf-8')
    assert output == path.parent / 'human-review.md'
    assert 'SIBLING_SECRET_SENTINEL' not in text
    assert 'review-fixture-private-key' not in text and 'token_hash' not in text and 'postgresql' not in text
    assert '人工核查尚未完成' in text and text.count('## 路径：') == 9
    with SessionLocal() as db:
        nodes = review_export.saved_path(db, selected['terminal_node_id'], selected['root_node_id'], root.session_id)
        assert len(nodes) == 22 and nodes[0].id == selected['root_node_id']
        for node in nodes:
            assert node.rendered_scene['narration'] in text
        action = db.scalar(select(TurnEvent.payload).where(TurnEvent.node_id == nodes[1].id,
                                                          TurnEvent.event_type == 'player_action'))
        assert action['value'] in text
    assert json.loads(path.read_text(encoding='utf-8'))['manual_reviewers'] == 0
    assert set(report['usage']['operations']) == {'story.content_generate', 'story.semantic_check', 'action.interpret'}
    assert report['usage']['operations']['action.interpret']['ledger_calls'] == 63


@pytest.mark.parametrize('fault', ['missing_terminal', 'wrong_root', 'cross_session', 'frozen_hash', 'manifest_hash', 'duplicate_case'])
def test_export_rejects_incomplete_or_mismatched_provenance(complete_report, tmp_path, monkeypatch, fault):
    report, path = copy_report(complete_report, tmp_path, monkeypatch)
    selected = next(r for r in report['cases'] if r['id'] == 'ancient_ending_1')
    if fault == 'missing_terminal':
        selected.pop('terminal_node_id')
    elif fault == 'wrong_root':
        selected['root_node_id'] = selected['terminal_node_id']
    elif fault == 'cross_session':
        selected['terminal_node_id'] = next(r['terminal_node_id'] for r in report['cases'] if r['id'] == 'modern_ending_1')
    elif fault == 'frozen_hash':
        report['cases'][0]['story_hash'] = '0' * 64
    elif fault == 'manifest_hash':
        report['manifest_sha256'] = '0' * 64
    else:
        report['cases'][-1] = deepcopy(report['cases'][0])
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(ValueError):
        review_export.export_review(path, 'REVIEW_TEST_DATABASE')
    assert not (path.parent / 'human-review.md').exists()


def test_export_refuses_paths_outside_runtime_evals(tmp_path, monkeypatch):
    monkeypatch.setattr(review_export, 'ROOT', tmp_path)
    path = tmp_path / 'report.json'
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='review_report_path_invalid'):
        review_export.export_review(path, 'DATABASE_URL')
