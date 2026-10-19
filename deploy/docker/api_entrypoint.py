"""Docker-only startup; source installs retain their existing configuration path."""
import os
import subprocess
import sys

from sqlalchemy import URL


def database_environment(environ):
    password = environ.get('POSTGRES_PASSWORD')
    if not password:
        raise ValueError('POSTGRES_PASSWORD must be set')
    try:
        port = int(environ.get('POSTGRES_PORT', '5432'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError('POSTGRES_PORT must be a valid port') from None
    url = URL.create('postgresql+psycopg',
        username=environ.get('POSTGRES_USER', 'theater'), password=password,
        host=environ.get('POSTGRES_HOST', 'db'), port=port,
        database=environ.get('POSTGRES_DB', 'theater')).render_as_string(hide_password=False)
    return {'DATABASE_URL': url, 'MIGRATION_DATABASE_URL': url}


def main():
    try:
        os.environ.update(database_environment(os.environ))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                       check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        print('Database migration failed; API was not started. Check database readiness and migration configuration.', file=sys.stderr)
        return 1
    print('Database migrations complete; starting API.', flush=True)
    os.execvp(sys.executable, [sys.executable, '-m', 'uvicorn', 'app.main:app',
                              '--host', '0.0.0.0', '--port', '8000', '--workers', '1'])


if __name__ == '__main__':
    raise SystemExit(main())
