FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE=/data/wichtelwerk.db
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 wichtelwerk \
    && useradd --uid 10001 --gid 10001 --no-log-init --no-create-home wichtelwerk \
    && mkdir /data && chown 10001:10001 /data
COPY wichtelwerk.py translations.py schema.sql ./
COPY static/ ./static/
COPY scripts/maintenance.py ./scripts/maintenance.py
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3)"
CMD ["gunicorn", "--bind", "0.0.0.0:8765", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "wichtelwerk:create_app()"]
