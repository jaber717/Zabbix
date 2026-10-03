# Flow Search

Server-side Flow Search over Akvorado's ClickHouse. **The browser never issues a ClickHouse query.** The PHP controller receives a declarative filter from the browser, builds a parameterised SQL statement against a read-only ClickHouse view, enforces time-window / row / byte / timeout limits, and returns rows.

## Status

v0.1.0 — scaffold on `claude/noc-flow-platform`. Backend wiring (PDO over ClickHouse HTTP), filter validation, Top-N aggregation action and view are present. **Not live-tested against a running Akvorado** because this build did not provision+boot the NetFlow VM. The compose artifacts under `../../../netflow-vm/compose/` do stand up the full Akvorado stack; once that is running, flip `FLOW_CLICKHOUSE_URL` on the Zabbix server and Flow Search becomes live.

## Query safety

- Hard time window cap: 7 days.
- `max_execution_time=10s`, `max_bytes_to_read=4GB`, `max_result_rows=10000`, `max_memory_usage=2GB` injected via SETTINGS in every query.
- Read-only ClickHouse user (`zbx_flow_ro`), granted SELECT only on the `flows_v1` view. No INSERT, no DDL.
- Server-side filter whitelist: IP, CIDR, src/dst port, protocol, exporter, interface.
- Pagination: 50 rows per page via `LIMIT N OFFSET M`.
- Short in-process cache (5 s) keyed by the normalized filter, to absorb refresh jitter.

See `sql/views.sql` and `config/FlowQueryRepository.php` for the actual SQL and bindings.
