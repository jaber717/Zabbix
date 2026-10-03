<?php declare(strict_types=1);
namespace Modules\FlowSearch\Config;

/**
 * Server-side query gateway. Two deployment modes:
 *
 *   mode=api      Zabbix PHP → HTTPS → Flow API gateway on netflow-01
 *                 (recommended; see netflow-vm/flow-api/)
 *                 Browser → Zabbix PHP → Flow API gateway → local-only ClickHouse
 *
 *   mode=clickhouse  Zabbix PHP → HTTP ClickHouse directly (lab/dev only; the
 *                 Zabbix server MUST be on the same host or the network path
 *                 must be scoped by firewall to the Zabbix-server IP).
 *
 * Hard safety contract (both modes):
 *   - time window: capped to 7 days
 *   - row cap:     10,000
 *   - byte cap:    4 GB
 *   - exec time:   10 s
 *   - memory:      2 GB
 *   - keyset pagination (TimeReceived, flow_id) — not LIMIT/OFFSET
 *   - no arbitrary SQL; every filter value is a typed bind parameter
 *
 * The compat view `netops.flow_v1` is what every method references. It is a
 * STABLE projection over Akvorado's internal schema; our UI never pins to
 * Akvorado's unstable table layout.
 */
class FlowQueryRepository {

    public const MAX_WINDOW_SECONDS = 7 * 86400;
    public const PAGE_SIZE = 50;

    private string $mode;             // 'api' | 'clickhouse'
    private string $endpoint;
    private string $username;
    private string $password;
    private string $database;
    private string $view;

    public function __construct(array $env) {
        $this->mode     = (string) ($env['FLOW_MODE'] ?? 'api');
        $this->endpoint = (string) ($env['FLOW_ENDPOINT'] ?? 'https://netflow-01.lab/api/v1');
        $this->username = (string) ($env['FLOW_USER'] ?? 'zbx_flow_ro');
        $this->password = (string) ($env['FLOW_PASS'] ?? '');
        $this->database = (string) ($env['FLOW_DB'] ?? 'akvorado');
        $this->view     = (string) ($env['FLOW_VIEW'] ?? 'netops.flow_v1');
    }

    public function search(array $filter): array {
        $window = $this->clampWindow((int) $filter['from'], (int) $filter['to']);
        $cursor = isset($filter['cursor']) ? (string) $filter['cursor'] : '';
        if ($this->mode === 'api') return $this->apiSearch($window, $filter, $cursor);
        return $this->chSearch($window, $filter, $cursor);
    }

    public function summary(array $filter): array {
        $window = $this->clampWindow((int) $filter['from'], (int) $filter['to']);
        if ($this->mode === 'api') return $this->apiCall('summary', ['filter' => $this->normalize($filter, $window)]);
        return $this->chSummary($window, $filter);
    }

    public function topN(array $filter, string $facet, int $limit = 10): array {
        $window = $this->clampWindow((int) $filter['from'], (int) $filter['to']);
        $limit = max(1, min(50, $limit));
        if ($this->mode === 'api') {
            return $this->apiCall('topn', ['filter' => $this->normalize($filter, $window), 'facet' => $facet, 'limit' => $limit]);
        }
        return $this->chTopN($window, $filter, $facet, $limit);
    }

    /** Reject invalid filters loudly. Never silently drop a restrictive filter. */
    public function validateOrThrow(array $filter): void {
        if (isset($filter['src_ip']) && $filter['src_ip'] !== '' && !filter_var($filter['src_ip'], FILTER_VALIDATE_IP)) {
            throw new \InvalidArgumentException('src_ip is not a valid IP');
        }
        if (isset($filter['dst_ip']) && $filter['dst_ip'] !== '' && !filter_var($filter['dst_ip'], FILTER_VALIDATE_IP)) {
            throw new \InvalidArgumentException('dst_ip is not a valid IP');
        }
        if (isset($filter['src_cidr']) && $filter['src_cidr'] !== '' && !$this->validCidr($filter['src_cidr'])) {
            throw new \InvalidArgumentException('src_cidr is not a valid CIDR');
        }
        if (isset($filter['dst_cidr']) && $filter['dst_cidr'] !== '' && !$this->validCidr($filter['dst_cidr'])) {
            throw new \InvalidArgumentException('dst_cidr is not a valid CIDR');
        }
        foreach (['src_port', 'dst_port'] as $f) {
            if (isset($filter[$f]) && $filter[$f] !== '' && ((int) $filter[$f] < 1 || (int) $filter[$f] > 65535)) {
                throw new \InvalidArgumentException("$f out of range");
            }
        }
        if (isset($filter['exporter']) && $filter['exporter'] !== '' && !filter_var($filter['exporter'], FILTER_VALIDATE_IP)) {
            throw new \InvalidArgumentException('exporter is not a valid IP');
        }
    }

    // --- API-mode (production path) ------------------------------------------------

    private function apiSearch(array $window, array $filter, string $cursor): array {
        $body = $this->apiCall('search', [
            'filter' => $this->normalize($filter, $window),
            'cursor' => $cursor,
            'page_size' => self::PAGE_SIZE,
        ]);
        return $body;    // {rows, next_cursor, has_more}
    }

    private function apiCall(string $op, array $body): array {
        $ch = curl_init(rtrim($this->endpoint, '/').'/'.$op);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => json_encode($body, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR),
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'Authorization: Bearer '.$this->password,     // bearer token issued by flow-api
            ],
            CURLOPT_CONNECTTIMEOUT => 2,
            CURLOPT_TIMEOUT => 12,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
        ]);
        $resp = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        if ($resp === false) {
            throw new \RuntimeException('Flow API unreachable: '.$err);
        }
        if ($code >= 400) {
            throw new \RuntimeException('Flow API HTTP '.$code);
        }
        return json_decode($resp, true) ?: [];
    }

    private function normalize(array $filter, array $window): array {
        [$from, $to] = $window;
        $out = ['from' => $from, 'to' => $to];
        foreach (['src_ip','dst_ip','src_cidr','dst_cidr','protocol','exporter','interface'] as $k) {
            if (!empty($filter[$k])) $out[$k] = (string) $filter[$k];
        }
        foreach (['src_port','dst_port'] as $k) {
            if (isset($filter[$k]) && $filter[$k] !== '') $out[$k] = (int) $filter[$k];
        }
        return $out;
    }

    // --- Direct ClickHouse mode (lab/dev only) -------------------------------------

    private function chSearch(array $window, array $filter, string $cursor): array {
        [$where, $params] = $this->chWhere($filter, $window, $cursor);
        $sql = "SELECT TimeReceived, SrcAddr, DstAddr, SrcPort, DstPort, Proto, Bytes, Packets, ExporterAddress, InIfName, OutIfName, flow_id
                FROM {$this->view}
                WHERE {$where}
                ORDER BY TimeReceived DESC, flow_id DESC
                LIMIT ".(self::PAGE_SIZE + 1)."
                ".$this->chSettings();
        $rows = $this->chQuery($sql, $params);
        $has_more = count($rows) > self::PAGE_SIZE;
        if ($has_more) array_pop($rows);
        $next_cursor = '';
        if ($has_more && $rows) {
            $last = $rows[count($rows) - 1];
            $next_cursor = $last['TimeReceived'].'|'.$last['flow_id'];
        }
        return ['rows' => $rows, 'has_more' => $has_more, 'next_cursor' => $next_cursor];
    }

    private function chSummary(array $window, array $filter): array {
        [$where, $params] = $this->chWhere($filter, $window, '');
        $sql = "SELECT sum(Bytes) AS bytes, sum(Packets) AS packets, count() AS flows,
                       sum(Bytes * if(SamplingRate > 0, SamplingRate, 1)) AS bytes_sampled
                FROM {$this->view}
                WHERE {$where}
                ".$this->chSettings();
        $rows = $this->chQuery($sql, $params);
        $r = $rows[0] ?? [];
        // Peak bps over 1-minute buckets — NOT max(Bytes) of a single flow row.
        $peakSql = "SELECT max(bps) AS peak_bps FROM (
                        SELECT toStartOfMinute(TimeReceived) AS b, sum(Bytes) * 8 / 60 AS bps
                        FROM {$this->view}
                        WHERE {$where}
                        GROUP BY b
                    )
                    ".$this->chSettings();
        $peakRows = $this->chQuery($peakSql, $params);
        $r['peak_bps'] = ($peakRows[0]['peak_bps'] ?? 0);
        return $r;
    }

    private function chTopN(array $window, array $filter, string $facet, int $limit): array {
        $facets = [
            'source' => 'SrcAddr',
            'destination' => 'DstAddr',
            'conversation' => 'concat(toString(SrcAddr), \' → \', toString(DstAddr))',
            'port' => 'DstPort',
            'protocol' => 'Proto',
            'exporter' => 'ExporterAddress',
            'ingress' => 'InIfName',
        ];
        if (!isset($facets[$facet])) throw new \InvalidArgumentException('Unknown facet');
        [$where, $params] = $this->chWhere($filter, $window, '');
        $sql = "SELECT {$facets[$facet]} AS key, sum(Bytes) AS bytes, sum(Packets) AS packets, count() AS flows
                FROM {$this->view}
                WHERE {$where}
                GROUP BY key
                ORDER BY bytes DESC
                LIMIT {$limit}
                ".$this->chSettings();
        return $this->chQuery($sql, $params);
    }

    private function chSettings(): string {
        return 'SETTINGS max_execution_time=10, max_bytes_to_read=4000000000, max_result_rows=10000, max_memory_usage=2000000000, readonly=1';
    }

    private function chWhere(array $filter, array $window, string $cursor): array {
        [$from, $to] = $window;
        $conditions = ['TimeReceived BETWEEN {from:DateTime} AND {to:DateTime}'];
        $params = ['from' => date('Y-m-d H:i:s', $from), 'to' => date('Y-m-d H:i:s', $to)];
        if (!empty($filter['src_ip'])) { $conditions[] = 'SrcAddr = toIPv6({src_ip:String})'; $params['src_ip'] = $filter['src_ip']; }
        if (!empty($filter['dst_ip'])) { $conditions[] = 'DstAddr = toIPv6({dst_ip:String})'; $params['dst_ip'] = $filter['dst_ip']; }
        if (!empty($filter['src_cidr'])) { $conditions[] = 'isIPAddressInRange(toString(SrcAddr), {src_cidr:String})'; $params['src_cidr'] = $filter['src_cidr']; }
        if (!empty($filter['dst_cidr'])) { $conditions[] = 'isIPAddressInRange(toString(DstAddr), {dst_cidr:String})'; $params['dst_cidr'] = $filter['dst_cidr']; }
        if (!empty($filter['src_port'])) { $conditions[] = 'SrcPort = {src_port:UInt16}'; $params['src_port'] = (int) $filter['src_port']; }
        if (!empty($filter['dst_port'])) { $conditions[] = 'DstPort = {dst_port:UInt16}'; $params['dst_port'] = (int) $filter['dst_port']; }
        if (!empty($filter['protocol'])) { $conditions[] = 'Proto = {protocol:String}'; $params['protocol'] = strtoupper(substr($filter['protocol'], 0, 8)); }
        if (!empty($filter['exporter'])) { $conditions[] = 'ExporterAddress = toIPv6({exporter:String})'; $params['exporter'] = $filter['exporter']; }
        if (!empty($filter['interface'])) { $conditions[] = '(InIfName = {iface:String} OR OutIfName = {iface:String})'; $params['iface'] = substr($filter['interface'], 0, 64); }
        if ($cursor !== '' && strpos($cursor, '|') !== false) {
            [$cTime, $cFlow] = explode('|', $cursor, 2);
            $conditions[] = '(TimeReceived < {cursor_time:DateTime} OR (TimeReceived = {cursor_time:DateTime} AND flow_id < {cursor_flow:UInt64}))';
            $params['cursor_time'] = $cTime;
            $params['cursor_flow'] = (int) $cFlow;
        }
        return [implode(' AND ', $conditions), $params];
    }

    private function chQuery(string $sql, array $params): array {
        $url = rtrim($this->endpoint, '/').'/?database='.rawurlencode($this->database).'&default_format=JSON';
        foreach ($params as $k => $v) $url .= '&param_'.rawurlencode($k).'='.rawurlencode((string) $v);
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
        if ($body === false) throw new \RuntimeException('ClickHouse unreachable: '.$err);
        if ($code !== 200) throw new \RuntimeException('ClickHouse HTTP '.$code.': '.substr((string) $body, 0, 200));
        $decoded = json_decode($body, true);
        return $decoded['data'] ?? [];
    }

    private function clampWindow(int $from, int $to): array {
        $to = min($to, time());
        $from = max($from, $to - self::MAX_WINDOW_SECONDS);
        if ($from >= $to) throw new \InvalidArgumentException('Invalid time window');
        return [$from, $to];
    }

    private function validCidr(string $cidr): bool {
        if (!preg_match('#^([0-9a-f.:]+)/(\d+)$#i', $cidr, $m)) return false;
        if (!filter_var($m[1], FILTER_VALIDATE_IP)) return false;
        $mask = (int) $m[2];
        return $mask >= 0 && $mask <= 128;
    }
}
