# Cloudflare Tunnel publication

## Active architecture

`https://radar.simsekhome.site` is published through the existing remotely managed Cloudflare
Tunnel. The connector deployment is persisted outside this repository at
`/home/msimsek/cloudflared-bist-radar/compose.yml` and is attached to the external
`bist-radar-network` network:

```text
Browser (HTTPS)
  -> radar.simsekhome.site
  -> existing remotely managed tunnel
  -> bist-radar-web:80
  -> /api reverse proxy
  -> bist-radar-api:8765 (private Docker network)
```

Only `bist-radar-web` is a tunnel origin. PostgreSQL, the worker, migrations, and FastAPI port 8765
have no public hostname. Host ports 8765 and 8770 remain bound to `127.0.0.1`.

The connector credential remains in a mode-`0600` environment file outside Git. Never copy or print
the token. The Compose deployment preserves `restart: unless-stopped`; a connector restart retains
Docker DNS resolution for `bist-radar-web`.

## Authentication

The origin does not implement application login. Cloudflare Access state cannot be inspected from
this host because no scoped control-plane credential is installed. For a private dashboard, create a
Zero Trust self-hosted Access application for `radar.simsekhome.site`, allow only the owner's verified
identity/email, deny all others, and verify the login boundary externally.

## Caching and security

HTML and API responses are `no-store`; API responses are also `private`. Only hashed static assets
receive a long immutable cache policy. Nginx supplies CSP, frame, content-type, referrer, and browser
permissions headers. The browser calls relative `/api` URLs, so the private API address is not
exposed.

## Restart and troubleshooting

Run `docker compose up -d` from `/home/msimsek/cloudflared-bist-radar` to reconcile the connector.
Verify four registered edge connections, then test `http://bist-radar-web:80/healthz` from the
connector network namespace and the external HTTPS page plus `/api/dashboard/summary`. A `502`
usually indicates origin network/DNS reachability; transient `530` responses can occur while all edge
connections are re-registering immediately after restart. Existing remote ingress rules must never be
rewritten from this host.
