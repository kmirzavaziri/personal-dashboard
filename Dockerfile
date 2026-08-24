FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates openssh-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir "flask>=3.1" "pydantic>=2" "pyyaml>=6.0" "jinja2>=3.1" gunicorn

COPY src/ /app/src/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DATA_DIR=/data \
    DB_ROOT=/data/db \
    STORAGE_ROOT=/data/storage \
    GIT_BRANCH=main \
    PORT=8080

EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
