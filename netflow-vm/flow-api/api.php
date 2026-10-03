<?php declare(strict_types=1);
/**
 * flow-api/api.php — bounded, read-only Flow query gateway.
 *
 * Deployed on netflow-01, fronted by nginx on 127.0.0.1 from PHP-FPM, exposed
 * on 0.0.0.0:443 by nginx with firewalld restricted to the Zabbix server IP.
 * See flow-api/README.md.
 */

// Hard caps mirrored on this side so a malformed client cannot overshoot.
const MAX_WINDOW_SECONDS = 7 * 86400;
const PAGE_SIZE_MAX = 50;
const CH_URL  = 'http://127.0.0.1:8123';
const CH_USER = 'flow_api_ro';
const CH_DB   = 'akvorado';
const VIEW    = 'netops.flow_v1';

respond_or_die();

function respond_or_die(): void {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');

    $op = basename((string) ($_SERVER['PATH_INFO'] ?? $_SERVER['REQUEST_URI'] ?? ''));
    if ($op === '') { http_response_code(404); echo '{"error":"not_found"}'; exit; }
    if ($op === 'healthz') {
        $ch = @file_get_contents(CH_URL.'/ping');
        $ok = (trim((string) $ch) === 'Ok.');
        http_response_code($ok ? 200 : 503);
        echo json_encode(['ok' => $ok]);
        return;
    }

    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        http_response_code(405); echo '{"error":"method_not_allowed"}'; return;
    }

    if (!authenticate()) {
        http_response_code(401); echo '{"error":"unauthorized"}'; return;
    }

    $raw = file_get_contents('php://input') ?: '';
    try {
        $req = json_decode($raw, true, 32, JSON_THROW_ON_ERROR);
    } catch (\Throwable $e) {
        http_response_code(400); echo json_encode(['error' => 'invalid_json']); return;
    }

    try {
        $filter = normalize_filter($req['filter'] ?? []);
    } catch (\InvalidArgumentException $e) {
        http_response_code(400);
        echo json_encode(['error' => 'bad_filter', 'detail' => $e->getMessage()]);
        return;
    }

    $ch_pass = file_exists('/etc/flow-api/ch-pass') ? trim((string) file_get_contents('/etc/flow-api/ch-pass')) : '';

    try {
        switch ($op) {
            case 'search':
                $cursor = (string) ($req['cursor'] ?? '');
                $page_size = min(PAGE_SIZE_MAX, max(1, (int) ($req['page_size'] ?? PAGE_SIZE_MAX)));
                echo json_encode(op_search($filter, $cursor, $page_size, $ch_pass));
                break;
            case 'summary':
                echo json_encode(op_summary($filter, $ch_pass));
                break;
            case 'topn':
                $facet = (string) ($req['facet'] ?? '');
                $limit = min(50, max(1, (int) ($req['limit'] ?? 10)));
                echo json_encode(op_topn($filter, $facet, $limit, $ch_pass));
                break;
            default:
                http_response_code(404); echo '{"error":"unknown_op"}';
        }
    } catch (\InvalidArgumentException $e) {
        http_response_code(400); echo json_encode(['error' => 'bad_request', 'detail' => $e->getMessage()]);
    } catch (\Throwable $e) {
        http_response_code(502); echo json_encode(['error' => 'backend', 'detail' => 'query_failed']);
        error_log('[flow-api] '.$e->getMessage());
    }
}

function authenticate(): bool {
    $hdr = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (!preg_match('#^Bearer\s+(\S+)$#', $hdr, $m)) return false;
    $provided = hash('sha256', $m[1]);
    foreach (glob('/etc/flow-api/clients/*.token.sha256') ?: [] as $f) {
        $expected = trim((string) @file_get_contents($f));
        if ($expected !== '' && hash_equals($expected, $provided)) return true;
    }
    return false;
}

function normalize_filter(array $f): array {
    $to = min((int) ($f['to'] ?? time()), time());
    $from = (int) ($f['from'] ?? ($to - 3600));
    if ($to - $from > MAX_WINDOW_SECONDS) $from = $to - MAX_WINDOW_SECONDS;
    if ($from >= $to) throw new \InvalidArgumentException('Invalid time window');

    $out = ['from' => $from, 'to' => $to];
    if (!empty($f['src_ip'])) {
        if (!filter_var($f['src_ip'], FILTER_VALIDATE_IP)) throw new \InvalidArgumentException('src_ip');
        $out['src_ip'] = $f['src_ip'];
    }
    if (!empty($f['dst_ip'])) {
        if (!filter_var($f['dst_ip'], FILTER_VALIDATE_IP)) throw new \InvalidArgumentException('dst_ip');
        $out['dst_ip'] = $f['dst_ip'];
    }
    foreach (['src_cidr' => 'src_cidr', 'dst_cidr' => 'dst_cidr'] as $k => $v) {
        if (!empty($f[$k])) {
            if (!valid_cidr($f[$k])) throw new \InvalidArgumentException($v);
            $out[$k] = $f[$k];
        }
    }
    foreach (['src_port', 'dst_port'] as $k) {
        if (isset($f[$k]) && $f[$k] !== '') {
            $p = (int) $f[$k];
            if ($p < 1 || $p > 65535) throw new \InvalidArgumentException($k);
            $out[$k] = $p;
        }
    }
    if (!empty($f['protocol']) && !preg_match('/^[A-Za-z0-9]{1,8}$/', (string) $f['protocol'])) {
        throw new \InvalidArgumentException('protocol');
    } elseif (!empty($f['protocol'])) {
        $out['protocol'] = strtoupper((string) $f['protocol']);
    }
    if (!empty($f['exporter'])) {
        if (!filter_var($f['exporter'], FILTER_VALIDATE_IP)) throw new \InvalidArgumentException('exporter');
        $out['exporter'] = $f['exporter'];
    }
    if (!empty($f['interface'])) {
        if (strlen((string) $f['interface']) > 64 || !preg_match('/^[\w.\-\/:]+$/', (string) $f['interface'])) {
            throw new \InvalidArgumentException('interface');
        }
        $out['interface'] = $f['interface'];
    }
    return $out;
}

function valid_cidr(string $cidr): bool {
    if (!preg_match('#^([0-9a-f.:]+)/(\d+)$#i', $cidr, $m)) return false;
    if (!filter_var($m[1], FILTER_VALIDATE_IP)) return false;
    $mask = (int) $m[2];
    return $mask >= 0 && $mask <= 128;
}

function where_clause(array $f, string $cursor): array {
    $cond = ['TimeReceived BETWEEN {from:DateTime} AND {to:DateTime}'];
    $p = ['from' => date('Y-m-d H:i:s', $f['from']), 'to' => date('Y-m-d H:i:s', $f['to'])];
    if (!empty($f['src_ip']))  { $cond[] = 'SrcAddr = toIPv6({src_ip:String})';          $p['src_ip']  = $f['src_ip']; }
    if (!empty($f['dst_ip']))  { $cond[] = 'DstAddr = toIPv6({dst_ip:String})';          $p['dst_ip']  = $f['dst_ip']; }
    if (!empty($f['src_cidr'])) { $cond[] = 'isIPAddressInRange(toString(SrcAddr), {src_cidr:String})'; $p['src_cidr'] = $f['src_cidr']; }
    if (!empty($f['dst_cidr'])) { $cond[] = 'isIPAddressInRange(toString(DstAddr), {dst_cidr:String})'; $p['dst_cidr'] = $f['dst_cidr']; }
    if (!empty($f['src_port'])) { $cond[] = 'SrcPort = {src_port:UInt16}';               $p['src_port'] = (int) $f['src_port']; }
    if (!empty($f['dst_port'])) { $cond[] = 'DstPort = {dst_port:UInt16}';               $p['dst_port'] = (int) $f['dst_port']; }
    if (!empty($f['protocol'])) { $cond[] = 'Proto = {protocol:String}';                 $p['protocol'] = $f['protocol']; }
    if (!empty($f['exporter'])) { $cond[] = 'ExporterAddress = toIPv6({exporter:String})'; $p['exporter'] = $f['exporter']; }
    if (!empty($f['interface'])) { $cond[] = '(InIfName = {iface:String} OR OutIfName = {iface:String})'; $p['iface'] = $f['interface']; }
    if ($cursor !== '' && strpos($cursor, '|') !== false) {
        [$ct, $cf] = explode('|', $cursor, 2);
        $cond[] = '(TimeReceived < {cursor_time:DateTime} OR (TimeReceived = {cursor_time:DateTime} AND flow_id < {cursor_flow:UInt64}))';
        $p['cursor_time'] = $ct; $p['cursor_flow'] = (int) $cf;
    }
    return [implode(' AND ', $cond), $p];
}

function settings(): string {
    return 'SETTINGS max_execution_time=10, max_bytes_to_read=4000000000, max_result_rows=10000, max_memory_usage=2000000000, readonly=1';
}

function ch_query(string $sql, array $params, string $pass): array {
    $url = CH_URL.'/?database='.rawurlencode(CH_DB).'&default_format=JSON';
    foreach ($params as $k => $v) $url .= '&param_'.rawurlencode($k).'='.rawurlencode((string) $v);
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $sql,
        CURLOPT_USERPWD => CH_USER.':'.$pass,
        CURLOPT_HTTPHEADER => ['Content-Type: text/plain'],
        CURLOPT_CONNECTTIMEOUT => 2,
        CURLOPT_TIMEOUT => 12,
    ]);
    $body = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($body === false) throw new \RuntimeException('ch_unreachable');
    if ($code !== 200) throw new \RuntimeException('ch_http_'.$code);
    return json_decode($body, true)['data'] ?? [];
}

function op_search(array $f, string $cursor, int $page, string $pass): array {
    [$w, $p] = where_clause($f, $cursor);
    $sql = "SELECT TimeReceived, SrcAddr, DstAddr, SrcPort, DstPort, Proto, Bytes, Packets, ExporterAddress, InIfName, OutIfName, flow_id
            FROM ".VIEW." WHERE $w
            ORDER BY TimeReceived DESC, flow_id DESC
            LIMIT ".($page + 1)." ".settings();
    $rows = ch_query($sql, $p, $pass);
    $has_more = count($rows) > $page;
    if ($has_more) array_pop($rows);
    $next = '';
    if ($has_more && $rows) { $last = $rows[count($rows) - 1]; $next = $last['TimeReceived'].'|'.$last['flow_id']; }
    return ['rows' => $rows, 'has_more' => $has_more, 'next_cursor' => $next];
}

function op_summary(array $f, string $pass): array {
    [$w, $p] = where_clause($f, '');
    $sql = "SELECT sum(Bytes) AS bytes, sum(Packets) AS packets, count() AS flows,
                   sum(Bytes * if(SamplingRate > 0, SamplingRate, 1)) AS bytes_sampled
            FROM ".VIEW." WHERE $w ".settings();
    $r = ch_query($sql, $p, $pass)[0] ?? [];
    // Peak bps over 1-minute buckets, not max row.
    $peak_sql = "SELECT max(bps) AS peak_bps FROM (
                   SELECT toStartOfMinute(TimeReceived) AS b, sum(Bytes) * 8 / 60 AS bps
                   FROM ".VIEW." WHERE $w GROUP BY b
                 ) ".settings();
    $pr = ch_query($peak_sql, $p, $pass);
    $r['peak_bps'] = $pr[0]['peak_bps'] ?? 0;
    return $r;
}

function op_topn(array $f, string $facet, int $limit, string $pass): array {
    $facets = [
        'source' => 'SrcAddr', 'destination' => 'DstAddr',
        'conversation' => 'concat(toString(SrcAddr), \' → \', toString(DstAddr))',
        'port' => 'DstPort', 'protocol' => 'Proto',
        'exporter' => 'ExporterAddress', 'ingress' => 'InIfName',
    ];
    if (!isset($facets[$facet])) throw new \InvalidArgumentException('facet');
    [$w, $p] = where_clause($f, '');
    $sql = "SELECT {$facets[$facet]} AS key, sum(Bytes) AS bytes, sum(Packets) AS packets, count() AS flows
            FROM ".VIEW." WHERE $w
            GROUP BY key ORDER BY bytes DESC LIMIT {$limit} ".settings();
    return ch_query($sql, $p, $pass);
}
