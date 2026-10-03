# Upstream Akvorado vendoring

The directory `akvorado-v2026.10.0/` is a **verbatim** copy of the files we need from the official Akvorado v2026.10.0 docker-compose quickstart release:

```
docker-compose-quickstart.tar.gz
  → https://github.com/akvorado/akvorado/releases/download/v2026.10.0/docker-compose-quickstart.tar.gz
```

Files vendored:

| Vendored path | Upstream path |
|---|---|
| `akvorado-v2026.10.0/docker/docker-compose.yml` | `docker/docker-compose.yml` |
| `akvorado-v2026.10.0/docker/versions.yml` | `docker/versions.yml` |
| `akvorado-v2026.10.0/.env` | `.env` |
| `akvorado-v2026.10.0/docker/clickhouse/server.xml` | `docker/clickhouse/server.xml` |
| `akvorado-v2026.10.0/docker/clickhouse/observability.xml` | `docker/clickhouse/observability.xml` |
| `akvorado-v2026.10.0/config/akvorado.yaml` | `config/akvorado.yaml` |
| `akvorado-v2026.10.0/config/inlet.yaml` | `config/inlet.yaml` |
| `akvorado-v2026.10.0/config/outlet.yaml` | `config/outlet.yaml` |
| `akvorado-v2026.10.0/config/console.yaml` | `config/console.yaml` |

Policy: **do not edit the vendored files.** All NetOps-local changes live in `../overlay/` and are applied by `../bin/compose-up.sh` via `COMPOSE_FILE` layering, exactly the way upstream's own `.env` layers `docker-compose-prometheus.yml`, `docker-compose-grafana.yml`, etc.

To bump the Akvorado version:

1. Download the new quickstart tarball from the release page.
2. Re-vendor the files listed above (same paths).
3. Re-pin digests (`../bin/pin-digests.sh`).
4. Re-run `../bin/validate.sh` for schema compatibility.
5. Commit as a single `chore(flow): bump Akvorado to vX.Y.Z` commit — no overlay changes mixed in.

## What the official v2026.10.0 architecture actually is

Per the vendored `docker-compose.yml` + `versions.yml`:

| Component | Image | Role |
|---|---|---|
| `kafka` | `apache/kafka:4.3.1` | KRaft mode, single-broker. **Not Confluent cp-kafka.** |
| `redis` | `valkey/valkey:9.0` | Session/metadata cache. (Service name is `redis`; image is Valkey.) |
| `clickhouse` | `clickhouse/clickhouse-server:26.8` | Flow store. |
| `traefik` | `traefik:v3.7` | Reverse-proxy; private entrypoint on `:8080` loopback, public on `:8081`. |
| `akvorado-orchestrator` | `quay.io/akvorado/akvorado:2026.10.0` | Central controller that configures inlet/outlet/console. |
| `akvorado-inlet` | same image | Receives NetFlow/IPFIX/sFlow on 2055/4739/6343 UDP. |
| `akvorado-outlet` | same image | Reads Kafka, writes ClickHouse. |
| `akvorado-console` | same image | Web UI (served via Traefik `console-auth` middleware). |
| `kafka-ui` | `kafbat/kafka-ui:v1.5.0` | Optional Kafka inspector (routed by Traefik under `/kafka-ui`). |

Our previous build was wrong on: missing orchestrator, missing redis/valkey, missing Traefik, wrong Kafka image (Confluent), wrong ClickHouse version (25.3), wrong Akvorado registry (ghcr not quay), wrong inlet ports (only 2055, missing 4739/6343). This vendoring + overlay fixes all seven.
