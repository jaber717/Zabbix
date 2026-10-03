<?php declare(strict_types=1);
namespace Modules\FlowSearch\Actions;

use CController;
use CControllerResponseData;
use Modules\FlowSearch\Config\FlowQueryRepository;

/**
 * POST action=flowsearch.query — single result page + summary. Server-side,
 * bounded, read-only.
 */
class Query extends CController {

    protected function checkInput(): bool {
        return $this->validateInput([
            'from' => 'int32|required',
            'to' => 'int32|required',
            'src_ip' => 'string',
            'dst_ip' => 'string',
            'src_cidr' => 'string',
            'dst_cidr' => 'string',
            'src_port' => 'int32',
            'dst_port' => 'int32',
            'protocol' => 'string',
            'exporter' => 'string',
            'interface' => 'string',
            'page' => 'int32',
        ]);
    }

    protected function checkPermissions(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_USER;
    }

    protected function doAction(): void {
        $filter = $this->getInputAll();
        try {
            $repo = new FlowQueryRepository([
                'FLOW_CLICKHOUSE_URL' => getenv('FLOW_CLICKHOUSE_URL') ?: 'http://127.0.0.1:8123',
                'FLOW_CLICKHOUSE_USER' => getenv('FLOW_CLICKHOUSE_USER') ?: 'zbx_flow_ro',
                'FLOW_CLICKHOUSE_PASS' => getenv('FLOW_CLICKHOUSE_PASS') ?: '',
                'FLOW_CLICKHOUSE_DB' => getenv('FLOW_CLICKHOUSE_DB') ?: 'akvorado',
            ]);
            $rows = $repo->search($filter);
            $summary = $repo->summary($filter);
            $this->setResponse(new CControllerResponseData([
                'ok' => true,
                'rows' => $rows,
                'summary' => $summary,
                'page_size' => FlowQueryRepository::PAGE_SIZE,
            ]));
        } catch (\InvalidArgumentException $e) {
            $this->setResponse(new CControllerResponseData(['ok' => false, 'error' => $e->getMessage()]));
        } catch (\Throwable $e) {
            $this->setResponse(new CControllerResponseData(['ok' => false, 'error' => 'Query failed']));
            error_log('[FlowSearch] query failed: '.$e->getMessage());
        }
    }
}
