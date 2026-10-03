# NOC Graph Wall

A fixed-slot graph wallboard for NOC monitors. **Graphs are the product.** No inventory tables, no Needs-Attention drawers, no severity reshuffling, no auto Top-N — operator muscle memory is a feature.

## Status

v0.1.0 — scaffold on branch `claude/noc-flow-platform`. Server-side action classes, view, CSS, and JS are present and configuration-driven. **Not yet live-validated against the production Zabbix** because this build did not have access to Zabbix API credentials. See `../../../docs/CODEX-HANDOFF-noc-flow.md` for the exact completion steps.

## Layout

Six graph slots. Default is 3 columns × 2 rows on ≥1920 px (NOC monitor), 2 columns × 3 rows on narrower primary screens, single column on <900 px. Slot positions are stable — never reordered by the backend.

## Data flow

```
Browser
  ↓ XHR (widget.netops_noc_graph_wall.view)
Zabbix PHP controller (WidgetView.php)
  ↓ bounded, batched
Zabbix API history.get / trend.get
  ↓
server-rendered snapshot JSON embedded in widget data-* (base64)
  ↓
traffic-chart.js reuses the proven Network Utilization chart renderer
```

No N+1: a single `item.get` resolves all slot items in one call; one `history.get` or `trend.get` per time-range bucket covers all slots.

## Configuration

Slot bindings persist server-side in `config/slot-definitions.json` (merged with `slot-definitions.example.json`). Each slot specifies either:

- a paired `in_itemid` + `out_itemid` (interface IN/OUT),
- a single `itemid` (CPU / memory / temperature / other numeric),
- an `aggregate` descriptor (sum of multiple items — e.g. aggregated STC capacity across edge devices).

A slot's label and sort position are explicit. Browser localStorage is only used for per-viewer convenience (last-selected time range, fullscreen flag) — never for critical config.

## Time ranges

`1H`, `6H`, `24H`, `7D`. 1H and 6H use `history.get`; 24H and 7D use `trend.get` to keep API load bounded.

## Refresh

Default 30 s auto-refresh. Only one in-flight XHR per widget — refresh skips if the previous call is still pending.

## Edit mode

An editor overlay (role gated) lets admins pick each slot's item(s) by searching hosts + items via `nocgraphwall.items.search` (server-side, paginated, bounded). Reorder is manual (drag within the 6-slot grid). No automatic Top-N replacement.

## Visual

Blue/light + Dark. Validated resolutions: 2200, 1920, 1440, 1200, 900. Full-screen toggle hides the Zabbix chrome. **Real-browser screenshots are pending** — add them under `evidence/noc-graph-wall/` once a staging Zabbix with real items is reachable.
