<?php declare(strict_types=1);
namespace Modules\FlowSearch\Actions;

use CController;
use CControllerResponseData;
use Modules\FlowSearch\Config\FlowQueryRepository;

/**
 * POST action=flowsearch.topn — top-10 by a named facet.
 * Facet whitelist in FlowQueryRepository::topN.
 */
class TopN extends CController {

    protected function checkInput(): bool {
        return $this->validateInput([
            'from' => 'int32|required',
            'to' => 'int32|required',
            'facet' => 'string|required',
            'limit' => 'int32',
            'src_ip' => 'string', 'dst_ip' => 'string',
            'src_cidr' => 'string', 'dst_cidr' => 'string',
            'src_port' => 'int32', 'dst_port' => 'int32',
            'protocol' => 'string', 'exporter' => 'string', 'interface' => 'string',
        ]);
    }

    protected function checkPermissions(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_USER;
    }

    protected function doAction(): void {
        $filter = $this->getInputAll();
        $facet = (string) $this->getInput('facet');
        $limit = (int) $this->getInput('limit', 10);
        try {
            $repo = new FlowQueryRepository([
                'FLOW_CLICKHOUSE_URL' => getenv('FLOW_CLICKHOUSE_URL') ?: 'http://127.0.0.1:8123',
                'FLOW_CLICKHOUSE_USER' => getenv('FLOW_CLICKHOUSE_USER') ?: 'zbx_flow_ro',
                'FLOW_CLICKHOUSE_PASS' => getenv('FLOW_CLICKHOUSE_PASS') ?: '',
                'FLOW_CLICKHOUSE_DB' => getenv('FLOW_CLICKHOUSE_DB') ?: 'akvorado',
            ]);
            $rows = $repo->topN($filter, $facet, $limit);
            $this->setResponse(new CControllerResponseData(['ok' => true, 'facet' => $facet, 'rows' => $rows]));
        } catch (\InvalidArgumentException $e) {
            $this->setResponse(new CControllerResponseData(['ok' => false, 'error' => $e->getMessage()]));
        } catch (\Throwable $e) {
            $this->setResponse(new CControllerResponseData(['ok' => false, 'error' => 'Query failed']));
            error_log('[FlowSearch] topN failed: '.$e->getMessage());
        }
    }
}
