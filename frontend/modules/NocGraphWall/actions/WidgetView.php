<?php declare(strict_types=1);
namespace Modules\NocGraphWall\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use API;
use Modules\NocGraphWall\Config\SlotDefinitionRepository;

/**
 * View controller for the NOC Graph Wall widget.
 *
 * Resolution strategy (no N+1, correctly typed):
 *   1. Load slot definitions from the server-side JSON.
 *   2. Collect every itemid across all 6 slots into one deduped list.
 *   3. One item.get for metadata (host, name, units, value_type).
 *   4. Group itemids by value_type (0=float, 3=unsigned_int).
 *      Call history.get once PER value_type (never N+1, never a single wrong
 *      history=0 call). For trend.get, Zabbix accepts both numeric types in
 *      one call because trends are already numeric, so one trend.get covers all.
 *   5. Fan results back out to each slot.
 */
class WidgetView extends CControllerDashboardWidgetView {

    // Zabbix history value_type enum (see Zabbix API docs for history object):
    //   0 = numeric float
    //   1 = character
    //   2 = log
    //   3 = numeric unsigned
    //   4 = text
    private const NUMERIC_VALUE_TYPES = [0, 3];

    // Caps for safety; a wall-time query must stay bounded.
    private const WINDOW_HARD_CAP_SECONDS = 7 * 86400;
    private const HISTORY_LIMIT_PER_CALL = 20000;
    private const TREND_LIMIT_PER_CALL   = 4000;

    protected function doAction(): void {
        $time_till = (int) ($this->getInput('to', time()));
        $time_till = min($time_till, time());
        $time_from = (int) ($this->getInput('from', $time_till - 3600));
        if ($time_till - $time_from > self::WINDOW_HARD_CAP_SECONDS) {
            $time_from = $time_till - self::WINDOW_HARD_CAP_SECONDS;
        }
        if ($time_from >= $time_till) {
            $this->setResponse(new CControllerResponseData($this->errorPayload('Invalid time window')));
            return;
        }

        $cfg_path = $this->resolveConfigPath();
        try {
            $repo = new SlotDefinitionRepository($cfg_path);
            $configuration = $repo->load();
        } catch (\Throwable $e) {
            $this->setResponse(new CControllerResponseData($this->errorPayload('Config load failed: '.$e->getMessage())));
            return;
        }

        $itemids = $this->collectItemIds($configuration['slots']);
        $items = [];
        $history_by_item = [];     // [itemid => [[clock, value, (min, max)], ...]]
        $api_calls = ['item' => 0, 'history' => 0, 'trend' => 0];

        if ($itemids !== []) {
            $items = API::Item()->get([
                'output' => ['itemid', 'name', 'key_', 'value_type', 'units', 'hostid'],
                'selectHosts' => ['host', 'name'],
                'itemids' => array_values($itemids),
                'webitems' => true,
                'preservekeys' => true,
            ]);
            $api_calls['item'] = 1;

            $window = $time_till - $time_from;
            $use_trend = $window > 6 * 3600;

            if ($use_trend) {
                // Trends are already numeric; one call covers both value_types.
                $trend = API::Trend()->get([
                    'output' => ['itemid', 'clock', 'value_min', 'value_avg', 'value_max'],
                    'itemids' => array_values($itemids),
                    'time_from' => $time_from,
                    'time_till' => $time_till,
                    'limit' => self::TREND_LIMIT_PER_CALL,
                ]);
                $api_calls['trend'] = 1;
                foreach ($trend as $row) {
                    $history_by_item[(string) $row['itemid']][] = [
                        (int) $row['clock'],
                        (float) $row['value_avg'],
                        (float) $row['value_min'],
                        (float) $row['value_max'],
                    ];
                }
            } else {
                // Group item ids by value_type; one history.get per group.
                $by_type = [];
                foreach ($items as $it) {
                    $vt = (int) ($it['value_type'] ?? -1);
                    if (!in_array($vt, self::NUMERIC_VALUE_TYPES, true)) {
                        continue;
                    }
                    $by_type[$vt][] = (int) $it['itemid'];
                }
                foreach ($by_type as $vt => $ids) {
                    if ($ids === []) continue;
                    $rows = API::History()->get([
                        'output' => 'extend',
                        'itemids' => $ids,
                        'time_from' => $time_from,
                        'time_till' => $time_till,
                        'history' => $vt,          // CORRECT per-type
                        'limit' => self::HISTORY_LIMIT_PER_CALL,
                        'sortfield' => 'clock',
                        'sortorder' => 'ASC',
                    ]);
                    $api_calls['history']++;
                    foreach ($rows as $row) {
                        $history_by_item[(string) $row['itemid']][] = [
                            (int) $row['clock'],
                            (float) $row['value'],
                        ];
                    }
                }
            }
        }

        $slots_rendered = [];
        foreach ($configuration['slots'] as $slot) {
            $slots_rendered[] = $this->renderSlot($slot, $items, $history_by_item);
        }

        $snapshot = [
            'generated_at' => time(),
            'time_from' => $time_from,
            'time_till' => $time_till,
            'slots' => $slots_rendered,
        ];

        $this->setResponse(new CControllerResponseData([
            'name' => $this->getInput('name', 'NOC Graph Wall'),
            'error' => null,
            'snapshot' => $snapshot,
            'configuration' => $configuration,
            'user' => [
                'can_edit' => $this->getUserType() >= USER_TYPE_ZABBIX_ADMIN,
                'csrf_token' => $this->getCsrfTokenHash(),
            ],
            'instrumentation' => [
                'api_calls' => $api_calls,          // {item:1, history:N, trend:0|1}
                'itemids' => count($itemids),
            ],
        ]));
    }

    protected function checkInput(): bool {
        return $this->validateInput([
            'name' => 'string',
            'from' => 'int32',
            'to' => 'int32',
        ]);
    }

    protected function checkPermissions(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_USER;
    }

    private function collectItemIds(array $slots): array {
        $ids = [];
        foreach ($slots as $slot) {
            switch ($slot['kind'] ?? '') {
                case 'paired_interface':
                    if (!empty($slot['in_itemid'])) $ids[(int) $slot['in_itemid']] = (int) $slot['in_itemid'];
                    if (!empty($slot['out_itemid'])) $ids[(int) $slot['out_itemid']] = (int) $slot['out_itemid'];
                    break;
                case 'single_item':
                    if (!empty($slot['itemid'])) $ids[(int) $slot['itemid']] = (int) $slot['itemid'];
                    break;
                case 'aggregate':
                    foreach ($slot['itemids'] ?? [] as $i) if ($i) $ids[(int) $i] = (int) $i;
                    break;
            }
        }
        return $ids;
    }

    private function renderSlot(array $slot, array $items, array $history): array {
        $base = [
            'position' => $slot['position'],
            'label' => $slot['label'],
            'kind' => $slot['kind'],
            'series' => [],
            'state' => 'OK',
            'notes' => $slot['notes'] ?? null,
        ];
        if (($slot['kind'] ?? '') === 'empty') {
            $base['state'] = 'EMPTY';
            return $base;
        }
        switch ($slot['kind']) {
            case 'paired_interface':
                if (empty($slot['in_itemid']) || empty($slot['out_itemid'])) {
                    $base['state'] = 'UNCONFIGURED';
                    break;
                }
                $base['series'][] = $this->seriesFor('in',  (int) $slot['in_itemid'],  $items, $history);
                $base['series'][] = $this->seriesFor('out', (int) $slot['out_itemid'], $items, $history);
                $base['unit'] = $slot['unit'] ?? 'bps';
                $base['capacity_bps'] = $slot['capacity_bps'] ?? null;
                break;
            case 'single_item':
                if (empty($slot['itemid'])) { $base['state'] = 'UNCONFIGURED'; break; }
                $base['series'][] = $this->seriesFor('value', (int) $slot['itemid'], $items, $history);
                $base['unit'] = $slot['unit'] ?? '';
                break;
            case 'aggregate':
                if (empty($slot['itemids'])) { $base['state'] = 'UNCONFIGURED'; break; }
                $base['series'][] = $this->aggregateSeries($slot['itemids'], $history);
                $base['unit'] = $slot['unit'] ?? '';
                break;
        }
        // Honest "unknown" state when the item exists but produced no points.
        if ($base['state'] === 'OK' && $base['series']
            && !array_filter($base['series'], static fn($s) => !empty($s['points']))) {
            $base['state'] = 'NO_DATA';
        }
        return $base;
    }

    private function seriesFor(string $role, int $itemid, array $items, array $history): array {
        $meta = $items[$itemid] ?? null;
        $points = $history[(string) $itemid] ?? [];
        return [
            'role' => $role,
            'itemid' => $itemid,
            'host' => $meta['hosts'][0]['name'] ?? '—',
            'name' => $meta['name'] ?? '—',
            'units' => $meta['units'] ?? '',
            'value_type' => isset($meta['value_type']) ? (int) $meta['value_type'] : null,
            'points' => $points,                     // [[clock, value, (min, max)], ...]
        ];
    }

    private function aggregateSeries(array $itemids, array $history): array {
        $by_clock = [];
        foreach ($itemids as $itemid) {
            foreach ($history[(string) $itemid] ?? [] as $pt) {
                $clock = (int) $pt[0];
                $v = (float) $pt[1];
                $by_clock[$clock] = ($by_clock[$clock] ?? 0.0) + $v;
            }
        }
        ksort($by_clock);
        $points = [];
        foreach ($by_clock as $clock => $value) $points[] = [$clock, $value];
        return ['role' => 'aggregate', 'itemids' => $itemids, 'points' => $points];
    }

    private function errorPayload(string $message): array {
        return [
            'name' => 'NOC Graph Wall',
            'error' => $message,
            'snapshot' => ['generated_at' => time(), 'slots' => []],
            'configuration' => ['slots' => []],
            'user' => ['can_edit' => false, 'csrf_token' => ''],
            'instrumentation' => [],
        ];
    }

    private function resolveConfigPath(): string {
        $base = getenv('ZABBIX_DATA_DIR') ?: '/var/lib/zabbix';
        return rtrim($base, '/').'/noc_graph_wall/slot-definitions.json';
    }
}
