import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
import os

import pytest


def runner():
    path = Path(__file__).resolve().parents[2] / 'scripts/test-docker.py'
    assert path.is_file(), 'Docker smoke runner is missing'
    spec = importlib.util.spec_from_file_location('docker_smoke', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('url', [
    'https://example.com', 'http://localhost.evil.example',
    'http://user:password@localhost:8080', 'http://localhost:8080/?token=secret',
])
def test_smoke_refuses_nonlocal_or_credentialed_targets(url):
    with pytest.raises(ValueError):
        runner().validate_base_url(url)


def test_smoke_accepts_local_origin_without_requiring_host_python_services():
    assert runner().validate_base_url('http://localhost:18080/') == 'http://localhost:18080'


@pytest.mark.skipif(not os.getenv('DATABASE_URL', '').endswith('_test'), reason='requires independent test database')
def test_demo_smoke_runs_against_real_api_under_same_origin_prefix():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.main import app
    @asynccontextmanager
    async def lifespan(_):
        async with app.router.lifespan_context(app):
            yield
    proxy_shape = FastAPI(lifespan=lifespan)
    proxy_shape.mount('/api', app)
    with TestClient(proxy_shape) as client:
        result = runner().run_checks(client)
    assert result['endings'] == ['e1', 'e2', 'e3']
    assert result['status'] == 'passed'
    assert result['replay'] is True and result['idempotency'] is True and result['sse'] is True
    assert not any('token' in key or 'password' in key for key in result)
