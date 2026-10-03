<?php declare(strict_types=1);
namespace Modules\FlowSearch\Config;

/**
 * Server-side query gateway to Akvorado's ClickHouse.
 *
 * Hard safety contract (every method MUST obey):
 *   - time window: capped to 7 days.
 *   - row cap:     max_result_rows=10000
 *   - byte cap:    max_bytes_to_read=4GB
 *   - time cap:    max_execution_time=10s
 *   - memory cap:  max_memory_usage=2GB
 *   - read-only user: credentials pulled from ZABBIX_FLOW_* env; never from browser.
 *
 * The browser cannot change these. Any attempt to pass a longer window is clamped;
 * any attempt to inject SQL is rejected because every value is a bind parameter
 * on the ClickHouse HTTP interface.
 */
class FlowQueryRepository {

    public const MAX_WINDOW_SECONDS = 7 * 86400;
    public const PAGE_SIZE = 50;
    private const SETTINGS = 'SETTINGS max_execution_time=10, max_bytes_to_read=4000000000, max_result_rows=10000, max_memory_usage=2000000000, readonly=1';

    private string $endpoint;
    private string $username;
    private string $password;
    private string $database;

    public function __construct(array $env) {
        $this->endpoint = (string) ($env['FLOW_CLICKHOUSE_URL'] ?? 'http://127.0.0.1:8123');
        $this->username = (string) ($env['FLOW_CLICKHOUSE_USER'] ?? 'zbx_flow_ro');
        $this->password = (string) ($env['FLOW_CLICKHOUSE_PASS'] ?? '');
        $this->database = (string) ($env['FLOW_CLICKHOUSE_DB'] ?? 'akvorado');
    }

    public function search(array $filter): array {
        $window = $this->clampWindow((int) $filter['from'], (int) $filter['to']);
        [$where, $params] = $this->buildWhere($filter, $window);
        $page = max(1, (int) ($filter['page'] ?? 1));
        $offset = ($page - 1) * self::PAGE_SIZE;
        $sql = "SELECT TimeReceived AS time, SrcAddr, DstAddr, SrcPort, DstPort, Proto,
                       Bytes, Packets, ExporterAddress, InIfName, OutIfName
                FROM {$this->database}.flows_v1
                WHERE {$where}
                ORDER BY TimeReceived DESC
                LIMIT ".self::PAGE_SIZE." OFFSET {$offset}
                ".self::SETTINGS;
        return $this->query($sql, $params);
    }

    public function summary(array $filter): array {
        $window = $this->clampWindow((int) $filter['from'], (int) $filter['to']);
        [$where, $params] = $this->buildWhere($filter, $window);
        $sql = "SELECT sum(Bytes) AS bytes, sum(Packets) AS packets, count() AS flows,
                       max(Bytes) AS peak_bytes
                FROM {$this->database}.flows_v1
                WHERE {$where}
                ".self::SETTINGS;
        return $this->query($sql, $params)[0] ?? [];
    }

    public function topN(array $filter, string $facet, int $limit = 10): array {
        $facets = [
            'source' => 'SrcAddr',
            'destination' => 'DstAddr',
            'conversation' => 'concat(toString(SrcAddr), \' → \', toString(DstAddr))',
            'port' => 'DstPort',
            'protocol' => 'Proto',
            'exporter' => 'ExporterAddress',
            'ingress' => 'InIfName',
        ];
        if (!isset($facets[$facet])) {
            throw new \InvalidArgumentException('Unknown facet');
        }
        $window = $this->clampWindow((int) $filter['from'], (int) $filter['to']);
        [$where, $params] = $this->buildWhere($filter, $window);
        $limit = max(1, min(50, $limit));
        $sql = "SELECT {$facets[$facet]} AS key, sum(Bytes) AS bytes, sum(Packets) AS packets, count() AS flows
                FROM {$this->database}.flows_v1
                WHERE {$where}
                GROUP BY key
                ORDER BY bytes DESC
                LIMIT {$limit}
                ".self::SETTINGS;
        return $this->query($sql, $params);
    }

    private function clampWindow(int $from, int $to): array {
        $to = min($to, time());
        $from = max($from, $to - self::MAX_WINDOW_SECONDS);
        if ($from >= $to) {
            throw new \InvalidArgumentException('Invalid time window');
        }
        return [$from, $to];
    }

    private function buildWhere(array $filter, array $window): array {
        [$from, $to] = $window;
        $conditions = ['TimeReceived BETWEEN {from:DateTime} AND {to:DateTime}'];
        $params = ['from' => date('Y-m-d H:i:s', $from), 'to' => date('Y-m-d H:i:s', $to)];
        if (!empty($filter['src_ip']) && filter_var($filter['src_ip'], FILTER_VALIDATE_IP)) {
            $conditions[] = 'SrcAddr = toIPv6({src_ip:String})';
            $params['src_ip'] = $filter['src_ip'];
        }
        if (!empty($filter['dst_ip']) && filter_var($filter['dst_ip'], FILTER_VALIDATE_IP)) {
            $conditions[] = 'DstAddr = toIPv6({dst_ip:String})';
            $params['dst_ip'] = $filter['dst_ip'];
        }
        if (!empty($filter['src_cidr']) && $this->validCidr($filter['src_cidr'])) {
            $conditions[] = 'isIPAddressInRange(toString(SrcAddr), {src_cidr:String})';
            $params['src_cidr'] = $filter['src_cidr'];
        }
        if (!empty($filter['dst_cidr']) && $this->validCidr($filter['dst_cidr'])) {
            $conditions[] = 'isIPAddressInRange(toString(DstAddr), {dst_cidr:String})';
            $params['dst_cidr'] = $filter['dst_cidr'];
        }
        if (isset($filter['src_port']) && (int) $filter['src_port'] > 0 && (int) $filter['src_port'] < 65536) {
            $conditions[] = 'SrcPort = {src_port:UInt16}';
            $params['src_port'] = (int) $filter['src_port'];
        }
        if (isset($filter['dst_port']) && (int) $filter['dst_port'] > 0 && (int) $filter['dst_port'] < 65536) {
            $conditions[] = 'DstPort = {dst_port:UInt16}';
            $params['dst_port'] = (int) $filter['dst_port'];
        }
        if (!empty($filter['protocol']) && is_string($filter['protocol'])) {
            $conditions[] = 'Proto = {protocol:String}';
            $params['protocol'] = strtoupper(substr($filter['protocol'], 0, 8));
        }
        if (!empty($filter['exporter']) && filter_var($filter['exporter'], FILTER_VALIDATE_IP)) {
            $conditions[] = 'ExporterAddress = toIPv6({exporter:String})';
            $params['exporter'] = $filter['exporter'];
        }
        if (!empty($filter['interface']) && is_string($filter['interface'])) {
            $conditions[] = '(InIfName = {iface:String} OR OutIfName = {iface:String})';
            $params['iface'] = substr($filter['interface'], 0, 64);
        }
        return [implode(' AND ', $conditions), $params];
    }

    private function validCidr(string $cidr): bool {
        if (!preg_match('#^([0-9a-f.:]+)/(\d+)$#i', $cidr, $m)) return false;
        if (!filter_var($m[1], FILTER_VALIDATE_IP)) return false;
        $mask = (int) $m[2];
        return $mask >= 0 && $mask <= 128;
    }

    private function query(string $sql, array $params): array {
        $url = rtrim($this->endpoint, '/').'/?database='.rawurlencode($this->database).'&default_format=JSON';
        foreach ($params as $k => $v) {
            $url .= '&param_'.rawurlencode($k).'='.rawurlencode((string) $v);
        }
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $sql,
            CURLOPT_USERPWD => $this->username.':'.$this->password,
            CURLOPT_HTTPHEADER => ['Content-Type: text/plain'],
            CURLOPT_CONNECTTIMEOUT => 2,
            CURLOPT_TIMEOUT => 12,
        ]);
        $body = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        if ($body === false) {
            throw new \RuntimeException('ClickHouse unreachable: '.$err);
        }
        if ($code !== 200) {
            throw new \RuntimeException('ClickHouse HTTP '.$code.': '.substr((string) $body, 0, 200));
        }
        $decoded = json_decode($body, true);
        return $decoded['data'] ?? [];
    }
}
