<?php declare(strict_types = 1);

namespace Modules\NetworkUtilization\Domain;

use Modules\NetworkUtilization\Config\Limits;

final class LinkUtilizationResolver {
	public function resolve(array $links, array $sites, array $settings, int $now): array {
		$resolved = array_map(fn(array $link): array => $this->resolveLink($link, $settings, $now), $links);
		usort($resolved, static fn($a, $b) => [$a['site_order'], $a['order'], $a['display_name'], $a['id']]
			<=> [$b['site_order'], $b['order'], $b['display_name'], $b['id']]);
		$stale_by_host = [];
		foreach ($resolved as $link) if ($link['data_state'] === 'STALE') $stale_by_host[$link['host']][] = $link['id'];
		$grouped_stale = [];
		foreach ($stale_by_host as $host => $ids) if (count($ids) >= 3) $grouped_stale[$host] = $ids;
		$attention = [];
		foreach ($resolved as &$link) {
			$link['stale_grouped'] = isset($grouped_stale[$link['host']]);
			if ($candidate = $this->attention($link)) $attention[] = $candidate;
		}
		unset($link);
		foreach ($grouped_stale as $host => $ids) $attention[] = ['id' => 'stale-'.$host, 'rank' => 55, 'kind' => 'MONITORING_STALE',
			'label' => "{$host} monitoring unavailable", 'detail' => count($ids).' configured Links affected', 'link_id' => null];
		usort($attention, static fn($a, $b) => [$a['rank'], $a['label'], $a['id']] <=> [$b['rank'], $b['label'], $b['id']]);
		$summary = ['HOT_NOW' => 0, 'SUSTAINED' => 0, 'ERRORS_DISCARDS' => 0, 'CAPACITY_RISK' => 0, 'UNKNOWN_STALE' => 0, 'MONITORED_LINKS' => count($resolved)];
		foreach ($resolved as $link) {
			$summary['HOT_NOW'] += $link['worst_util_pct'] !== null && $link['worst_util_pct'] >= $link['warning_util_pct'] ? 1 : 0;
			$summary['SUSTAINED'] += $link['sustained'] ? 1 : 0;
			$summary['ERRORS_DISCARDS'] += $link['errors_total'] > 0 || $link['discards_total'] > 0 ? 1 : 0;
			$summary['CAPACITY_RISK'] += $link['p95_worst_pct'] !== null && $link['p95_worst_pct'] >= $settings['capacity_risk_p95_pct'] ? 1 : 0;
			$summary['UNKNOWN_STALE'] += $link['data_state'] !== 'CURRENT' || $link['capacity_bps'] === null || $link['mapping_issue'] !== null ? 1 : 0;
		}
		$site_rows = [];
		foreach ($sites as $site) {
			$site_links = array_values(array_filter($resolved, static fn($link) => $link['site_id'] === $site['id']));
			$site_rows[] = $site + ['links' => $site_links, 'attention' => count(array_filter($site_links, static fn($l) => $l['attention_kind'] !== null))];
		}
		return ['generated_at' => $now, 'summary' => $summary, 'needs_attention' => $attention, 'links' => $resolved,
			'sites' => $site_rows, 'grouped_stale' => $grouped_stale];
	}

	public function resolveLink(array $link, array $settings, int $now): array {
		$warning = (float) ($link['warning_util_pct'] ?? $settings['warning_util_pct']);
		$critical = (float) ($link['critical_util_pct'] ?? $settings['critical_util_pct']);
		$in = $this->metric($link['metrics']['in'] ?? null, $now); $out = $this->metric($link['metrics']['out'] ?? null, $now);
		$capacity_metric = $this->metric($link['metrics']['capacity'] ?? null, $now);
		$capacity = isset($link['capacity_override_bps']) ? (float) $link['capacity_override_bps']
			: ($capacity_metric['current'] !== null && $capacity_metric['current'] > 0 ? $capacity_metric['current'] : null);
		$in_util = $capacity && $in['current'] !== null ? 100 * $in['current'] / $capacity : null;
		$out_util = $capacity && $out['current'] !== null ? 100 * $out['current'] / $capacity : null;
		$worst = $this->maxNullable($in_util, $out_util); $direction = $worst === null ? null : ($out_util !== null && $out_util >= ($in_util ?? -1) ? 'OUT' : 'IN');
		$p95_in_bps = $this->percentile($in['history']); $p95_out_bps = $this->percentile($out['history']);
		$p95_in = $capacity && $p95_in_bps !== null ? 100 * $p95_in_bps / $capacity : null;
		$p95_out = $capacity && $p95_out_bps !== null ? 100 * $p95_out_bps / $capacity : null;
		$peak_bps = $this->maxNullable($in['peak'], $out['peak']); $p95_worst = $this->maxNullable($p95_in, $p95_out);
		$series = $this->mergeWorstSeries($in['history'], $out['history'], $capacity);
		$sustained_s = $this->sustainedDuration($series, $warning, $now, max($in['expected_interval'], $out['expected_interval']));
		$data_state = $in['stale'] || $out['stale'] ? 'STALE' : (($in['current'] === null || $out['current'] === null) ? 'UNKNOWN' : 'CURRENT');
		$errors = $this->quality($link['metrics'], 'errors'); $discards = $this->quality($link['metrics'], 'discards');
		$oper = $this->status($link['metrics']['oper_status'] ?? null, false); $admin = $this->status($link['metrics']['admin_status'] ?? null, true);
		$result = $link + ['current_in_bps' => $data_state === 'CURRENT' ? $in['current'] : null, 'current_out_bps' => $data_state === 'CURRENT' ? $out['current'] : null,
			'in_util_pct' => $data_state === 'CURRENT' ? $in_util : null, 'out_util_pct' => $data_state === 'CURRENT' ? $out_util : null,
			'worst_util_pct' => $data_state === 'CURRENT' ? $worst : null, 'worst_direction' => $direction,
			'capacity_bps' => $capacity, 'capacity_source' => isset($link['capacity_override_bps']) ? 'override' : ($capacity ? 'reported' : 'unknown'),
			'headroom_bps' => $capacity && $data_state === 'CURRENT' && $worst !== null ? max(0.0, $capacity * (1 - $worst / 100)) : null,
			'p95_in_pct' => $p95_in, 'p95_out_pct' => $p95_out, 'p95_worst_pct' => $p95_worst,
			'p95_in_bps' => $p95_in_bps, 'p95_out_bps' => $p95_out_bps, 'peak_bps' => $peak_bps,
			'sustained_seconds' => $data_state === 'CURRENT' ? $sustained_s : 0,
			'sustained' => $data_state === 'CURRENT' && $sustained_s >= $settings['sustained_window_min'] * 60,
			'spike' => $data_state === 'CURRENT' && $worst !== null && $worst >= $warning && $sustained_s < $settings['sustained_window_min'] * 60,
			'warning_util_pct' => $warning, 'critical_util_pct' => $critical, 'data_state' => $data_state,
			'data_age_s' => max($in['age'], $out['age']), 'admin_status' => $admin, 'oper_status' => $oper,
			'errors_total' => $errors, 'discards_total' => $discards, 'sparkline_in' => $in['sparkline'], 'sparkline_out' => $out['sparkline']];
		$result['attention_kind'] = $this->attention($result)['kind'] ?? null;
		return $result;
	}

	public function percentile(array $samples): ?float {
		$values = array_values(array_filter(array_column($samples, 'value'), 'is_numeric'));
		if (count($values) < Limits::MIN_PERCENTILE_SAMPLES) return null;
		sort($values, SORT_NUMERIC); $rank = (count($values) - 1) * .95; $low = (int) floor($rank); $high = (int) ceil($rank);
		return (float) ($values[$low] + ($values[$high] - $values[$low]) * ($rank - $low));
	}

	public function resetSafeDelta(float $previous, float $current): ?float { return $current >= $previous ? $current - $previous : null; }

	private function metric(?array $metric, int $now): array {
		$interval = max(1, (int) ($metric['expected_interval'] ?? 60)); $clock = (int) ($metric['clock'] ?? 0);
		$age = $clock > 0 ? max(0, $now - $clock) : PHP_INT_MAX; $fresh = $clock > 0 && $age <= max(300, 2 * $interval);
		$history = array_values(array_filter($metric['history'] ?? [], static fn($row) => isset($row['clock'], $row['value']) && is_numeric($row['value'])));
		$spark = array_values(array_filter($history, static fn($row) => $row['clock'] >= $now - Limits::SPARKLINE_WINDOW_S));
		return ['current' => $fresh && isset($metric['value']) && is_numeric($metric['value']) ? max(0.0, (float) $metric['value']) : null,
			'stale' => !$fresh, 'age' => $age, 'expected_interval' => $interval, 'history' => $history,
			'peak' => $history === [] ? null : max(array_column($history, 'value')), 'sparkline' => $spark];
	}
	private function quality(array $metrics, string $kind): float {
		$total = 0.0;
		foreach (["in_{$kind}", "out_{$kind}"] as $name) {
			$m = $metrics[$name] ?? null; if (!$m || !isset($m['value']) || !is_numeric($m['value'])) continue;
			if (($m['mode'] ?? 'rate') === 'counter') {
				$rows = $m['history'] ?? []; $count = count($rows); if ($count >= 2) $total += $this->resetSafeDelta((float) $rows[$count - 2]['value'], (float) $rows[$count - 1]['value']) ?? 0;
			} else $total += max(0.0, (float) $m['value']);
		}
		return $total;
	}
	private function status(?array $metric, bool $admin): string {
		if (!$metric || !isset($metric['value'])) return 'UNKNOWN'; $v = (int) $metric['value'];
		if ($admin) return $v === 1 ? 'UP' : ($v === 2 ? 'DOWN' : 'UNKNOWN');
		if (($metric['status_family'] ?? 'ifmib') === 'linux') return $v === 6 ? 'UP' : (in_array($v, [1,2,3], true) ? 'DOWN' : 'UNKNOWN');
		return $v === 1 ? 'UP' : ($v === 2 ? 'DOWN' : 'UNKNOWN');
	}
	private function mergeWorstSeries(array $in, array $out, ?float $capacity): array {
		if (!$capacity) return []; $rows = [];
		// Direction samples commonly arrive a few seconds apart. A minute bucket preserves
		// full-duplex max(direction) semantics without treating each direction as a gap.
		foreach (array_merge($in, $out) as $row) { $clock = intdiv((int) $row['clock'], 60) * 60; $rows[$clock] = max($rows[$clock] ?? 0, 100 * (float) $row['value'] / $capacity); }
		ksort($rows); return array_map(static fn($clock, $value) => ['clock' => $clock, 'value' => $value], array_keys($rows), $rows);
	}
	private function sustainedDuration(array $series, float $threshold, int $now, int $interval): int {
		$start = $now; $last = $now;
		for ($i = count($series) - 1; $i >= 0; $i--) { $row = $series[$i]; if ($row['value'] < $threshold || $last - $row['clock'] > max(300, 2 * $interval)) break; $start = $row['clock']; $last = $row['clock']; }
		return max(0, $now - $start);
	}
	private function attention(array $l): ?array {
		$rank = null; $kind = null; $detail = '';
		if (($l['admin_status'] ?? '') === 'UP' && ($l['oper_status'] ?? '') === 'DOWN' && ($l['required'] ?? true)) { $rank=10; $kind='LINK_DOWN'; $detail='Admin UP · Oper DOWN'; }
		elseif (($l['sustained'] ?? false) && ($l['worst_util_pct'] ?? 0) >= ($l['critical_util_pct'] ?? 90)) { $rank=20; $kind='SUSTAINED_CRITICAL'; $detail='Sustained '.round($l['worst_util_pct']).'%'; }
		elseif (($l['errors_total'] ?? 0) > 0 || ($l['discards_total'] ?? 0) > 0) { $rank=30; $kind='ERRORS_DISCARDS'; $detail='Errors/discards increasing'; }
		elseif (($l['worst_util_pct'] ?? 0) >= ($l['critical_util_pct'] ?? 90)) { $rank=40; $kind='CURRENT_CRITICAL'; $detail=($l['worst_direction'] ?? '').' '.round($l['worst_util_pct']).'%'; }
		elseif (($l['sustained'] ?? false)) { $rank=50; $kind='SUSTAINED_WARNING'; $detail='Sustained '.round($l['worst_util_pct']).'%'; }
		elseif (($l['mapping_issue'] ?? null) !== null || ($l['capacity_bps'] ?? null) === null || ($l['data_state'] ?? '') !== 'CURRENT') { if ($l['stale_grouped'] ?? false) return null; $rank=60; $kind='CONFIG_OR_DATA'; $detail=$l['mapping_issue'] ?? (($l['data_state'] ?? '') === 'STALE' ? 'Data stale' : 'Capacity unknown'); }
		return $rank === null ? null : ['id'=>'attention-'.$l['id'], 'rank'=>$rank, 'kind'=>$kind, 'label'=>$l['display_name'], 'detail'=>$detail, 'link_id'=>$l['id']];
	}
	private function maxNullable(?float ...$values): ?float { $v = array_values(array_filter($values, static fn($x) => $x !== null)); return $v === [] ? null : max($v); }
}
