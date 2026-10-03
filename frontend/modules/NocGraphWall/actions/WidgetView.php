<?php declare(strict_types=1);
namespace Modules\NocGraphWall\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use API;
use Modules\NocGraphWall\Config\SlotDefinitionRepository;

/**
 * View controller for the NOC Graph Wall widget.
 *
 * Resolution strategy (no N+1):
 *   1. Load slot definitions from the server-side JSON.
 *   2. Collect every itemid across all 6 slots into one deduped list.
 *   3. One item.get for metadata (host, name, units, value_type).
 *   4. One history.get OR trend.get per time range (1h/6h use history, 24h/7d use trend).
 *   5. Fan results back out to each slot.
 */
class WidgetView extends CControllerDashboardWidgetView {

    protected function doAction(): void {
        $time_from = (int) ($this->getInput('from', time() - 3600));
        $time_till = (int) ($this->getInput('to', time()));
        $time_from = max($time_from, time() - 7 * 86400); // hard cap: 7d
        $time_till = min($time_till, time());

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
        $history = [];
        if ($itemids !== []) {
            $items = API::Item()->get([
                'output' => ['itemid', 'name', 'key_', 'value_type', 'units', 'hostid'],
                'selectHosts' => ['host', 'name'],
                'itemids' => array_values($itemids),
                'webitems' => true,
                'preservekeys' => true,
            ]);
            $window = $time_till - $time_from;
            $use_trend = $window > 6 * 3600;
            $raw = $use_trend
                ? API::Trend()->get([
                    'output' => ['itemid', 'clock', 'value_min', 'value_avg', 'value_max'],
                    'itemids' => array_values($itemids),
                    'time_from' => $time_from,
                    'time_till' => $time_till,
                    'limit' => 2048,
                ])
                : API::History()->get([
                    'output' => 'extend',
                    'itemids' => array_values($itemids),
                    'time_from' => $time_from,
                    'time_till' => $time_till,
                    'history' => 0,
                    'limit' => 10000,
                    'sortfield' => 'clock',
                    'sortorder' => 'ASC',
                ]);
            foreach ($raw as $row) {
                $history[(string) $row['itemid']][] = $row;
            }
        }

        $slots_rendered = [];
        foreach ($configuration['slots'] as $slot) {
            $slots_rendered[] = $this->renderSlot($slot, $items, $history, $time_from, $time_till);
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
                'can_edit' => $this->isAdmin(),
                'csrf_token' => $this->getCsrfTokenHash(),
            ],
            'instrumentation' => [
                'api_items_called' => $itemids ? 1 : 0,
                'api_history_called' => $itemids ? 1 : 0,
                'itemids' => count($itemids),
            ],
        ]));
    }

    protected function checkInput(): bool {
        $fields = [
            'name' => 'string',
            'from' => 'int32',
            'to' => 'int32',
        ];
        return $this->validateInput($fields);
    }

    protected function checkPermissions(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_USER;
    }

    private function isAdmin(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_ADMIN;
    }

    private function collectItemIds(array $slots): array {
        $ids = [];
        foreach ($slots as $slot) {
            switch ($slot['kind'] ?? '') {
                case 'paired_interface':
                    if (!empty($slot['in_itemid'])) $ids[$slot['in_itemid']] = (int) $slot['in_itemid'];
                    if (!empty($slot['out_itemid'])) $ids[$slot['out_itemid']] = (int) $slot['out_itemid'];
                    break;
                case 'single_item':
                    if (!empty($slot['itemid'])) $ids[$slot['itemid']] = (int) $slot['itemid'];
                    break;
                case 'aggregate':
                    foreach ($slot['itemids'] ?? [] as $i) if ($i) $ids[$i] = (int) $i;
                    break;
            }
        }
        return $ids;
    }

    private function renderSlot(array $slot, array $items, array $history, int $from, int $till): array {
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
                $base['series'][] = $this->seriesFor('in', (int) $slot['in_itemid'], $items, $history);
                $base['series'][] = $this->seriesFor('out', (int) $slot['out_itemid'], $items, $history);
                $base['unit'] = $slot['unit'] ?? 'bps';
                $base['capacity_bps'] = $slot['capacity_bps'] ?? null;
                break;
            case 'single_item':
                if (empty($slot['itemid'])) {
                    $base['state'] = 'UNCONFIGURED';
                    break;
                }
                $base['series'][] = $this->seriesFor('value', (int) $slot['itemid'], $items, $history);
                $base['unit'] = $slot['unit'] ?? '';
                break;
            case 'aggregate':
                if (empty($slot['itemids'])) {
                    $base['state'] = 'UNCONFIGURED';
                    break;
                }
                // sum values across itemids on matching clocks
                $base['series'][] = $this->aggregateSeries($slot['itemids'], $history);
                $base['unit'] = $slot['unit'] ?? '';
                break;
        }
        return $base;
    }

    private function seriesFor(string $role, int $itemid, array $items, array $history): array {
        $meta = $items[$itemid] ?? null;
        $points = [];
        foreach ($history[(string) $itemid] ?? [] as $row) {
            $points[] = [
                (int) $row['clock'],
                isset($row['value_avg']) ? (float) $row['value_avg'] : (float) ($row['value'] ?? 0),
            ];
        }
        return [
            'role' => $role,
            'itemid' => $itemid,
            'host' => $meta['hosts'][0]['name'] ?? '—',
            'name' => $meta['name'] ?? '—',
            'units' => $meta['units'] ?? '',
            'points' => $points,
        ];
    }

    private function aggregateSeries(array $itemids, array $history): array {
        $by_clock = [];
        foreach ($itemids as $itemid) {
            foreach ($history[(string) $itemid] ?? [] as $row) {
                $clock = (int) $row['clock'];
                $value = isset($row['value_avg']) ? (float) $row['value_avg'] : (float) ($row['value'] ?? 0);
                $by_clock[$clock] = ($by_clock[$clock] ?? 0.0) + $value;
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
        // Zabbix convention: ZABBIX_DATA_DIR when set, else /var/lib/zabbix.
        $base = getenv('ZABBIX_DATA_DIR') ?: '/var/lib/zabbix';
        return rtrim($base, '/').'/noc_graph_wall/slot-definitions.json';
    }
}
