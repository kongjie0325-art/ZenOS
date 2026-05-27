#!/bin/bash
set -euo pipefail

echo "Deploying ZenOS..."

cd /opt/zenos

# Pull latest
git pull origin main 2>/dev/null || true

# Rebuild and restart
docker compose build --no-cache zenos
docker compose up -d

echo "✅ ZenOS deployed!"
