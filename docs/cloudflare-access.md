# Cloudflare Tunnel publication

## Current status

Publication is intentionally **pending**. The existing connector is a remotely managed Cloudflare
Tunnel and this host has neither a local `config.yml` nor a scoped Cloudflare API/Access credential.
The reserved target is `radar.simsekhome.site`; it did not resolve at the time of the readiness audit.
Do not create the hostname without an Access policy because the dashboard contains personal paper
portfolio and signal data.

## Intended architecture

```text
Browser (HTTPS + Cloudflare Access)
  -> radar.simsekhome.site
  -> existing remotely-managed tunnel
  -> bist-radar-web:80
  -> /api reverse proxy
  -> bist-radar-api:8765 (private Docker network)
```

Only `bist-radar-web` is an allowed origin. PostgreSQL, the worker, migrations, and FastAPI port 8765
must not receive public hostnames. Host ports 8765 and 8770 remain bound to `127.0.0.1`.

## Required Cloudflare control-plane changes

1. In Zero Trust, create a self-hosted Access application for `radar.simsekhome.site`.
2. Add an Allow policy containing only the owner's verified identity/email; leave all other users
   denied. Test the authentication boundary before publishing the DNS route.
3. On the existing tunnel for `simsekhome.site`, add the public hostname without changing existing
   ingress entries. Point it to `http://bist-radar-web:80` only after making the connector's
   `bist-radar-network` attachment persistent in its real deployment definition.
4. Confirm the final catch-all remains `http_status:404` and verify every existing hostname.
5. Test `/`, a hashed `/assets/` URL, and `/api/dashboard/summary` over HTTPS. The API response must
   carry `Cache-Control: no-store, private` and must not reveal port 8765.

The current connector was created without Compose/systemd metadata. A one-off `docker network
connect` is not an acceptable persistent deployment and must not be used as the final topology.

## Restart and troubleshooting

After the connector has a source-controlled or otherwise documented deployment definition, restart
only the connector during a maintenance window. Confirm four edge connections, the existing routes,
the Access login boundary, and BIST Radar health. A `502` indicates origin network reachability;
`404` indicates no matching remote ingress; an unresolved hostname indicates the DNS route was not
created. Never copy tunnel tokens, account identifiers, origin certificates, or Access credentials
into this repository or application logs.
