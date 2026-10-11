"""Read-only local spoiler materials from a complete, frozen phase 2 report."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
from evals.run_stage2 import MANIFEST, load_manifest, validate_database_url


def saved_path(db, terminal_node_id, root_node_id, session_id):
    from app.models import Node
    path, seen = [], set()
    current = terminal_node_id
    while current:
        if current in seen:
            raise ValueError('review_path_invalid')
        seen.add(current)
        node = db.get(Node, current)
        if node is None or node.session_id != session_id:
            raise ValueError('review_path_invalid')
        if path and (path[-1].story_version_id != node.story_version_id or path[-1].depth != node.depth + 1):
            raise ValueError('review_path_invalid')
        path.append(node)
        if node.id == root_node_id:
            if node.parent_id is not None or node.depth != 0:
                raise ValueError('review_path_invalid')
            return list(reversed(path))
        current = node.parent_id
    raise ValueError('review_path_invalid')


def export_review(report_path: Path, database_url_env: str) -> Path:
    report_path = report_path.resolve()
    base = (ROOT / 'runtime/evals').resolve()
    if not report_path.is_relative_to(base) or report_path.name != 'report.json' or report_path.parent == base:
        raise ValueError('review_report_path_invalid')
    url = validate_database_url(os.environ.get(database_url_env, ''))
    report = json.loads(report_path.read_text(encoding='utf-8'))
    fixed = [case for case in load_manifest()['cases'] if case['suite'] == 'real_model']
    results = report.get('cases', [])
    if (report.get('suite') != 'real_model' or report.get('summary', {}).get('total') != 12
            or report.get('summary', {}).get('succeeded') != 12 or len(results) != 12
            or {case.get('id') for case in results} != {case['id'] for case in fixed}
            or any(case.get('status') != 'succeeded' for case in results)):
        raise ValueError('review_report_incomplete')
    if (report.get('manifest_sha256') != hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
            or report.get('creation_protocol') != 'controlled-content-2'
            or report.get('narration_protocol') != 'approved-feedback-1'
            or report.get('measurement') != 'real_model_with_approved_feedback'):
        raise ValueError('review_provenance_invalid')
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models import Node, StoryTask, StoryVersion, TurnEvent
    from app.story_schema import Story, canonical_hash
    from app.story_versions import load_narration_protocol, load_story_version
    by_id = {case['id']: case for case in results}
    stories = {}
    lines = ['# 阶段 2 本地人工审阅材料（有剧透）', '',
             '人工核查尚未完成。本文件仅导出已批准故事与已保存路径；请逐项填写末尾核查表。', '',
             f"评测：{report['run_id']}；服务器逐字呈现已审核反馈，真实模型用于创建和自由行动理解。", '']
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            for case in fixed:
                result = by_id[case['id']]
                if case['kind'] != 'creation':
                    continue
                root = db.get(Node, result.get('root_node_id')) if result.get('root_node_id') else None
                task = db.get(StoryTask, result.get('task_id')) if result.get('task_id') else None
                if (root is None or task is None or root.session_id != result.get('session_id')
                        or task.session_id != root.session_id or task.status != 'approved'
                        or task.root_node_id != root.id or task.candidate_version_id != root.story_version_id
                        or root.parent_id is not None or root.depth != 0):
                    raise ValueError('review_provenance_invalid')
                version = db.get(StoryVersion, root.story_version_id)
                if version.approval_status != 'approved' or load_narration_protocol(db, version.id) != 'approved-feedback-1':
                    raise ValueError('review_provenance_invalid')
                story = load_story_version(db, version.id)
                blob = (report_path.parent / (case['era'] + '-frozen.json')).read_bytes()
                frozen = json.loads(blob)
                if (hashlib.sha256(blob).hexdigest() != result.get('paths_sha256')
                        or frozen.get('content_hash') != result.get('story_hash')
                        or canonical_hash(Story.model_validate(frozen['story'])) != version.content_hash
                        or version.content_hash != result.get('story_hash')
                        or frozen.get('narration_protocol') != 'approved-feedback-1'
                        or result.get('narration_protocol') != 'approved-feedback-1'):
                    raise ValueError('review_provenance_invalid')
                stories[case['era']] = (story, root, frozen['paths'])
                lines += [f"## 故事：{case['era']} / {story.title}", '', story.public_intro, '',
                          '### 真相与证据关系', '', '```json',
                          json.dumps({'truth': story.truth.model_dump(),
                                      'evidence': [item.model_dump() for item in story.evidence],
                                      'endings': [item.model_dump() for item in story.endings]}, ensure_ascii=False, indent=2),
                          '```', '']
            for case in fixed:
                if case['kind'] != 'path':
                    continue
                result = by_id[case['id']]
                story, root, witnesses = stories[case['era']]
                ending, witness = sorted(witnesses.items())[case['index']]
                if (result.get('root_node_id') != root.id or result.get('session_id') != root.session_id
                        or not result.get('terminal_node_id') or result.get('ending_id') != ending
                        or result.get('actions') != len(witness) or result.get('free_text') != case['free_text']
                        or result.get('narration_protocol') != 'approved-feedback-1'):
                    raise ValueError('review_provenance_invalid')
                nodes = saved_path(db, result['terminal_node_id'], root.id, root.session_id)
                if len(nodes) != len(witness) + 1 or nodes[-1].state_snapshot.get('ending_id') != ending:
                    raise ValueError('review_path_invalid')
                lines += [f"## 路径：{case['id']} / {ending}", '',
                          '输入方式：' + ('自由文本' if case['free_text'] else '按钮'), '']
                for node in nodes:
                    action = db.scalar(select(TurnEvent.payload).where(TurnEvent.node_id == node.id,
                                                                      TurnEvent.event_type == 'player_action'))
                    if node.parent_id and action is None:
                        raise ValueError('review_path_invalid')
                    known = {key: node.state_snapshot[key] for key in
                             ('location_id', 'action_turn', 'discovered_evidence', 'disclosures', 'commitments', 'ending_id')}
                    lines += [f"### 第 {node.depth} 步 / {node.id}", '',
                              '玩家输入：' + json.dumps(action, ensure_ascii=False), '',
                              '当前已知状态：' + json.dumps(known, ensure_ascii=False), '',
                              node.rendered_scene['narration'], '']
                    for line in node.rendered_scene['dialogue']:
                        lines += [f"{line['character_id']}：{line['text']}", '']
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('review_provenance_invalid') from error
    finally:
        engine.dispose()
    lines += ['## 人工核查表', '', '实际审阅人：________；日期：________', '',
              '| 故事与三条路径 | 证据支持真相 | 披露时已经可知 | 无事实冲突 | 年代合理 | 三结局有区别 | 问题与具体步骤 |',
              '|---|---|---|---|---|---|---|',
              '| ancient | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | |',
              '| modern | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | |',
              '| future | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | |', '',
              '请报告所有问题，注明故事、路径和步骤；生成本文件不代表人工验收通过。', '']
    output = report_path.parent / 'human-review.md'
    output.write_text('\n'.join(lines), encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--database-url-env', default='MIGRATION_DATABASE_URL')
    args = parser.parse_args()
    try:
        path = export_review(args.report, args.database_url_env)
        print(str(path))
    except (ValueError, OSError):
        print('review_export_rejected')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
