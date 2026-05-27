#!/bin/bash
set -euo pipefail

echo "╔══════════════════════════════════════╗"
echo "║     ZenOS Installer v0.1.0          ║"
echo "╚══════════════════════════════════════╝"

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker required. Install: https://docs.docker.com/engine/install/"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "Docker Compose required."; exit 1; }

# Create directories
mkdir -p /opt/zenos/{config,data,logs}

# Copy config if not exists
if [ ! -f /opt/zenos/.env ]; then
    cp config/.env.example /opt/zenos/.env
    echo "⚠️  Please edit /opt/zenos/.env with your API keys"
fi

# Pull and start
cd /opt/zenos
docker compose pull
docker compose up -d

echo ""
echo "✅ ZenOS installed!"
echo "  API:      http://localhost:8000"
echo "  Docs:     http://localhost:8000/docs"
echo "  Grafana:  http://localhost:3000"
echo "  Prometheus: http://localhost:9091"
