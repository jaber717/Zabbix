<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Domain;

use Throwable;

final class MetricFreshnessPolicy {
	public function expectedInterval(array $item, array $items_by_id): ?int {
		$seen = [];
		while (true) {
			$id = (string) ($item['itemid'] ?? '');
			if ($id !== '') { if (isset($seen[$id])) return null; $seen[$id] = true; }
			$delay = trim((string) ($item['delay'] ?? ''));
			if (str_contains($delay, '{') && class_exists('CMacrosResolverHelper')) {
				try {
					$resolved = \CMacrosResolverHelper::resolveTimeUnitMacros([$item], ['delay']);
					$delay = trim((string) ($resolved[0]['delay'] ?? ''));
				}
				catch (Throwable) { return null; }
			}
			if (preg_match('/^([1-9][0-9]*)([smhdw]?)$/', $delay, $m)) {
				return (int) $m[1] * match($m[2]) { '', 's'=>1, 'm'=>60, 'h'=>3600, 'd'=>86400, 'w'=>604800 };
			}
			$master = (string) ($item['master_itemid'] ?? '0');
			if ($master === '0' || !isset($items_by_id[$master])) return null;
			$item = $items_by_id[$master];
		}
	}
	public function evaluate(array $item, array $items_by_id, int $now, int $multiplier, int $first_observed, int $grace): array {
		$clock = (int) ($item['lastclock'] ?? 0);
		$interval = $this->expectedInterval($item, $items_by_id);
		if ($clock <= 0) return ['state'=>'NO_DATA','age'=>null,'expected_interval'=>$interval,'grace_active'=>($now-$first_observed)<$grace];
		$age = max(0, $now - $clock);
		if ($interval === null) return ['state'=>'UNKNOWN','age'=>$age,'expected_interval'=>null,'grace_active'=>false];
		return ['state'=>$age > $interval*$multiplier ? 'STALE' : 'CURRENT', 'age'=>$age,
			'expected_interval'=>$interval, 'grace_active'=>false];
	}
}
