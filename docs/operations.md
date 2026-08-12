# Autonomous Operations

`docker compose up -d --build` runs PostgreSQL, migration, API, autonomous worker, and web. All use
`restart: unless-stopped`, so operation is independent of SSH, tmux, or Codex sessions.

The worker wakes every 30 seconds but schedules scans only after the next completed 15-minute
boundary plus an availability buffer. A PostgreSQL advisory lock prevents duplicate workers from
running the same job. Persistent `worker_state`, signal snapshots, outcomes, notification events and
last processed data support restart recovery. Research failures are bounded and isolated from API
health; existing bars are not deleted.

Useful commands:

```text
docker compose ps
docker compose logs -f bist-radar-worker
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8770/healthz
docker compose restart bist-radar-api bist-radar-worker bist-radar-web
```

Only the `bist-radar` compose project may be operated. API and web bind to localhost. No existing
server network, volume, tunnel, firewall, or unrelated container is changed.
