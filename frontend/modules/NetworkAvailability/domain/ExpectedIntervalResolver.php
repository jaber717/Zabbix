<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Domain;

use Throwable;

final class ExpectedIntervalResolver {
	/**
	 * Resolve a trustworthy fixed interval. Complex flexible/scheduled intervals
	 * require an explicit per-Member fallback in the central Node definition.
	 */
	public function resolve(array $item, ?int $configured_seconds = null): array {
		if ($configured_seconds !== null) {
			return $configured_seconds > 0
				? ['seconds' => $configured_seconds, 'source' => 'node_definition', 'error' => null]
				: ['seconds' => null, 'source' => null, 'error' => 'configured interval must be greater than zero'];
		}

		$delay = trim((string) ($item['delay'] ?? ''));
		if ($delay === '') {
			return ['seconds' => null, 'source' => null, 'error' => 'availability item has no update interval'];
		}

		if (str_contains($delay, '{') && class_exists('CMacrosResolverHelper')) {
			try {
				$resolved = \CMacrosResolverHelper::resolveTimeUnitMacros([$item], ['delay']);
				$delay = trim((string) ($resolved[0]['delay'] ?? ''));
			}
			catch (Throwable) {
				return ['seconds' => null, 'source' => null, 'error' => 'Zabbix could not resolve update interval macros'];
			}
		}

		if ($delay === '' || strpbrk($delay, '{};/') !== false) {
			return [
				'seconds' => null,
				'source' => null,
				'error' => 'effective interval is macro-based, flexible, or scheduled; configure expected_interval_s'
			];
		}

		if (!preg_match('/^([1-9][0-9]*)([smhdw]?)$/', $delay, $matches)) {
			return ['seconds' => null, 'source' => null, 'error' => 'fixed update interval is not safely parseable'];
		}
		$multiplier = match ($matches[2]) {
			'', 's' => 1,
			'm' => 60,
			'h' => 3600,
			'd' => 86400,
			'w' => 604800
		};
		return ['seconds' => (int) $matches[1] * $multiplier, 'source' => 'resolved_fixed_delay', 'error' => null];
	}
}
