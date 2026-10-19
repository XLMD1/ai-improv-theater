FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 RUNTIME_DIR=/app/runtime
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY deploy/docker/api_entrypoint.py ./api_entrypoint.py
RUN pip install --no-cache-dir . \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /app/runtime \
    && chown app:app /app/runtime
USER app
EXPOSE 8000
ENTRYPOINT ["python", "/app/api_entrypoint.py"]
