"""Optional developer smoke test for an already-running local Docker web origin.

Creates isolated Demo sessions; never deletes data or calls model providers.
Requires the backend's Python dependencies. It does not start Docker.
"""
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def validate_base_url(value):
    parts = urlsplit(value)
    if (parts.scheme != 'http' or parts.hostname not in ('localhost', '127.0.0.1', '::1')
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ('', '/')):
        raise ValueError('use a local HTTP web origin without credentials or query parameters')
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError('invalid port')
    return value.rstrip('/')


def run_checks(client):
    def request(method, path, expected=200, **kwargs):
        response = client.request(method, '/api' + path, **kwargs)
        assert response.status_code == expected, f'{method} {path}: HTTP {response.status_code}'
        return response

    assert request('GET', '/health').json()['ok'] is True
    before = request('GET', '/local-settings').json()['budget']
    start = request('POST', '/sessions', 201, json={'provider': 'demo'}).json()
    headers = {'Authorization': 'Bearer ' + start['token']}
    root = start['root']
    first_run = None

    def choose(parent, choice):
        nonlocal first_run
        turn_headers = {**headers, 'Idempotency-Key': uuid4().hex}
        body = {'parent_node_id': parent['id'], 'action': {'type': 'option', 'value': choice}}
        run = request('POST', '/turns', 202, headers=turn_headers, json=body).json()['run_id']
        again = request('POST', '/turns', 202, headers=turn_headers, json=body).json()['run_id']
        assert again == run, 'duplicate action created another run'
        first_run = first_run or run
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = request('GET', '/runs/' + run, headers=headers).json()
            if status['status'] == 'completed':
                return request('GET', '/nodes/' + status['node_id'], headers=headers).json()
            assert status['status'] not in ('failed', 'interrupted'), 'Demo action failed'
            time.sleep(.05)
        raise AssertionError('Demo action timed out')

    archive = choose(root, 'search')
    saved = archive
    assert archive['scene_id'] == 's2'
    dock = choose(archive, 'dock')
    tower = choose(archive, 'tower')
    assert (dock['scene_id'], tower['scene_id']) == ('s3', 's4')
    assert 'secret_shared' not in dock['state_snapshot']['flags']
    assert tower['state_snapshot']['flags']['secret_shared'] is True
    lighthouse = choose(dock, 'continue')
    assert lighthouse['scene_id'] == 's5'
    endings = [choose(lighthouse, choice)['scene_id'] for choice in ('reveal', 'guard', 'sink')]
    assert endings == ['e1', 'e2', 'e3']
    assert request('GET', '/nodes/' + saved['id'], headers=headers).json() == saved
    tree = request('GET', '/tree', headers=headers).json()
    assert len(tree) == 8, 'unexpected node count after idempotent actions'
    events = request('GET', '/runs/' + first_run + '/events?after=0', headers=headers)
    assert events.headers['content-type'].startswith('text/event-stream')
    assert 'event: done' in events.text
    sequences = [int(line[4:]) for line in events.text.splitlines() if line.startswith('id: ')]
    assert sequences and sequences == sorted(set(sequences))
    request('GET', '/nodes/' + saved['id'], 401)
    other = request('POST', '/sessions', 201, json={'provider': 'demo'}).json()
    request('GET', '/nodes/' + saved['id'], 404, headers={'Authorization': 'Bearer ' + other['token']})
    assert request('GET', '/local-settings').json()['budget'] == before
    return {'status': 'passed', 'endings': endings, 'saved_nodes': len(tree),
            'replay': True, 'idempotency': True, 'sse': True, 'budget_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:8080')
    parser.add_argument('--output', type=Path, default=Path('runtime/docker-smoke-report.json'))
    args = parser.parse_args()
    try:
        base = validate_base_url(args.base_url)
        with httpx.Client(base_url=base, timeout=20, follow_redirects=False, trust_env=False) as client:
            result = run_checks(client)
    except (ValueError, AssertionError, httpx.HTTPError, KeyError) as error:
        result = {'status': 'failed', 'error_type': type(error).__name__}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
