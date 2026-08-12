# BIST Radar Dashboard

Dashboard is a React 18 + TypeScript + Vite PWA served by the isolated `bist-radar-web` container.
It is available only at `http://127.0.0.1:8770`; use an existing private SSH or Tailscale tunnel if
remote access is needed. No public bind or Cloudflare tunnel is created.

Pages are Radar, Signals, Paper Portfolio, Analysis/Shadow Intelligence, System, and symbol detail.
Financial calculations remain in FastAPI. The browser receives bounded chart windows and aggregate
read-only endpoints. Missing data is displayed as missing, never zero. Offline mode warns explicitly
and the service worker never caches API financial responses.

Desktop uses a compact side navigation and mobile uses safe-area-aware bottom navigation. The UI
contains keyboard focus states, semantic status colors, loading/error/empty states and Turkish locale
formatting. Install via the browser's PWA action when served from localhost.
