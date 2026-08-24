#!/usr/bin/env sh
set -e

: "${DATA_DIR:=/data}"
: "${GIT_BRANCH:=main}"
: "${PORT:=8080}"

if [ -n "$DATA_REPO" ]; then
  REPO_URL="$DATA_REPO"
  if [ -n "$DATA_DEPLOY_KEY_B64" ]; then
    mkdir -p /root/.ssh && chmod 700 /root/.ssh
    printf '%s' "$DATA_DEPLOY_KEY_B64" | base64 -d > /root/.ssh/id_ed25519
    chmod 600 /root/.ssh/id_ed25519
    ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null
  elif [ -n "$DATA_REPO_TOKEN" ]; then
    REPO_URL=$(printf '%s' "$DATA_REPO" | sed "s#https://#https://x-access-token:${DATA_REPO_TOKEN}@#")
  fi

  if [ ! -d "$DATA_DIR/.git" ]; then
    git clone --branch "$GIT_BRANCH" "$REPO_URL" "$DATA_DIR"
  else
    git -C "$DATA_DIR" remote set-url origin "$REPO_URL"
    git -C "$DATA_DIR" pull --ff-only origin "$GIT_BRANCH" || true
  fi
  git -C "$DATA_DIR" config user.email "${GIT_AUTHOR_EMAIL:-dashboard@localhost}"
  git -C "$DATA_DIR" config user.name "${GIT_AUTHOR_NAME:-dashboard}"
fi

exec gunicorn "webapp:create_wsgi()" \
  --bind "0.0.0.0:${PORT}" \
  --workers 1 --threads 8 --timeout 120 --graceful-timeout 30
