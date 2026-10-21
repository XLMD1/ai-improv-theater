import importlib.util
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy.engine import make_url


def entrypoint():
    path = Path(__file__).resolve().parents[2] / 'deploy/docker/api_entrypoint.py'
    assert path.is_file(), 'Docker migration-first entrypoint is missing'
    spec = importlib.util.spec_from_file_location('docker_api_entrypoint', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('password', [None, ''])
def test_missing_password_stops_before_migration_or_server(password, monkeypatch, capsys):
    module = entrypoint()
    monkeypatch.delenv('POSTGRES_PASSWORD', raising=False)
    if password is not None:
        monkeypatch.setenv('POSTGRES_PASSWORD', password)
    def forbidden(*args, **kwargs):
        pytest.fail('external process launched without database configuration')
    monkeypatch.setattr(module.subprocess, 'run', forbidden)
    monkeypatch.setattr(module.os, 'execvp', forbidden)
    assert module.main() == 2
    assert 'POSTGRES_PASSWORD' in capsys.readouterr().err


def test_password_punctuation_reaches_both_database_urls_without_corruption():
    module = entrypoint()
    result = module.database_environment({'POSTGRES_PASSWORD': 'p@ss:/?#%$ word'})
    for key in ('DATABASE_URL', 'MIGRATION_DATABASE_URL'):
        url = make_url(result[key])
        assert url.password == 'p@ss:/?#%$ word'
        assert (url.host, url.port, url.database, url.username) == ('db', 5432, 'theater', 'theater')


def test_failed_migration_never_starts_api_or_echoes_connection(monkeypatch, capsys):
    module = entrypoint()
    monkeypatch.setenv('POSTGRES_PASSWORD', 'PRIVATE_PASSWORD_SENTINEL')
    monkeypatch.setenv('DATABASE_URL', os.environ.get('DATABASE_URL', ''))
    monkeypatch.setenv('MIGRATION_DATABASE_URL', os.environ.get('MIGRATION_DATABASE_URL', ''))
    def fail(*args, **kwargs):
        assert args[0][1:] == ['-m', 'alembic', 'upgrade', 'head']
        raise subprocess.CalledProcessError(1, args[0], stderr='PRIVATE_PASSWORD_SENTINEL')
    def forbidden(*args):
        pytest.fail('API launched after migration failure')
    monkeypatch.setattr(module.subprocess, 'run', fail)
    monkeypatch.setattr(module.os, 'execvp', forbidden)
    assert module.main() == 1
    output = capsys.readouterr()
    assert 'PRIVATE_PASSWORD_SENTINEL' not in output.out + output.err
    assert 'migration' in output.err.lower()


def test_api_exec_receives_migrated_connection_and_single_worker(monkeypatch):
    module = entrypoint()
    monkeypatch.setenv('POSTGRES_PASSWORD', 'fixture-password')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://wrong@wrong/wrong')
    monkeypatch.setenv('MIGRATION_DATABASE_URL', 'postgresql://wrong@wrong/wrong')
    migrated = []
    def migrate(command, **kwargs):
        assert command[1:] == ['-m', 'alembic', 'upgrade', 'head']
        assert kwargs['check'] is True
        url = make_url(os.environ['MIGRATION_DATABASE_URL'])
        assert (url.host, url.password) == ('db', 'fixture-password')
        assert os.environ['DATABASE_URL'] == os.environ['MIGRATION_DATABASE_URL']
        migrated.append(True)
    def launch(executable, command):
        assert migrated == [True]
        assert command[1:] == ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000', '--workers', '1']
        assert executable == command[0]
        raise SystemExit(73)
    monkeypatch.setattr(module.subprocess, 'run', migrate)
    monkeypatch.setattr(module.os, 'execvp', launch)
    with pytest.raises(SystemExit) as result:
        module.main()
    assert result.value.code == 73
