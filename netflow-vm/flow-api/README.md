# flow-api — Flow query gateway on netflow-01

A small, bounded, read-only HTTPS gateway that fronts ClickHouse so the Zabbix PHP controller never speaks ClickHouse directly. This fixes the earlier design flaw where ClickHouse was documented as loopback-only *and* expected to be reachable at `http://netflow-01:8123` from another VM — those two were incompatible.

## Shape

```
Browser  →  Zabbix PHP (FlowSearch module)
                   │  HTTPS, Bearer token
                   ▼
    netflow-01   nginx (TLS)
                   │  localhost
                   ▼
                 PHP-FPM (api.php)
                   │  localhost
                   ▼
                 ClickHouse (loopback-only)
```

Firewalld on `netflow-01` opens TCP/443 (the gateway) **only** to the Zabbix server's IP. Nothing else on the Internet or the LAN can reach ClickHouse.

## Endpoints

| Path | Method | Body | Notes |
|---|---|---|---|
| `/api/v1/search` | POST | `{filter, cursor?, page_size?}` | Keyset-paginated rows from `netops.flow_v1`. |
| `/api/v1/summary` | POST | `{filter}` | bytes, packets, flows, **peak_bps over 1-min buckets** (not max row). |
| `/api/v1/topn` | POST | `{filter, facet, limit}` | Top-N over a whitelisted facet. |
| `/healthz` | GET | — | 200 OK = nginx + php-fpm + ClickHouse ping all live. |

## Auth

- One bearer token per client, hashed and compared constant-time server-side.
- Tokens live in `/etc/flow-api/clients/<name>.token.sha256`. The plaintext token is handed to the Zabbix server once, through a sealed systemd credential, and never sees Git.
- `flow-api` logs refuse request logging of the Authorization header.

## Guardrails (hard-coded in `api.php`)

- Time window ≤ 7 days.
- Row cap 10 000.
- Byte cap 4 GB.
- Execution time ≤ 10 s.
- Memory ≤ 2 GB.
- Max 8 concurrent queries per client (nginx `limit_conn`).
- Server-side validation: invalid IP / CIDR / port returns HTTP 400 with the exact field. **An invalid restrictive filter never degrades to a broader query.**
- Pagination: keyset `(TimeReceived DESC, flow_id DESC)` — no `OFFSET`.

## Deploy

Deployed by `/opt/akvorado/bin/flow-api-install.sh` (cloud-init runs it after containers are healthy). It writes `nginx.conf`, `php-fpm.conf`, `api.php`, installs the self-signed TLS cert (or imports the internal CA cert if `FLOW_API_TLS_PEM` is supplied), and enables `flow-api.service`.
