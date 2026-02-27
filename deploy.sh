#!/usr/bin/env bash
# helper script for deploying to Railway (Linux/Mac)
set -e

# ensure git repo initialized and pushed
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "adding origin placeholder, update to your repo URL"
  git remote add origin https://github.com/<youruser>/cohub.git
fi

git add .
git commit -m "prepare for deploy" || true

git push origin main

# optional: trigger railway commands
if command -v railway >/dev/null 2>&1; then
  echo "running railway deploy steps"
  railway run python manage.py migrate
  railway run python manage.py collectstatic --noinput
else
  echo "railway CLI not installed; install with npm i -g @railway/cli"
fi
