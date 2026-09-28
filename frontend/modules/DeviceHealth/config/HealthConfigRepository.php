<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Config;

use JsonException;
use RuntimeException;

final class HealthConfigRepository {
	public const DEFAULT_PATH = '/var/lib/zabbix/device-health/device-health.json';
	public function __construct(private readonly string $path = self::DEFAULT_PATH) {}
	public function load(): array {
		if (!is_readable($this->path)) {
			throw new RuntimeException("Device Health configuration is not readable: {$this->path}");
		}
		try { $document = json_decode((string) file_get_contents($this->path), true, 64, JSON_THROW_ON_ERROR); }
		catch (JsonException $e) { throw new RuntimeException('Device Health configuration JSON is invalid', previous: $e); }
		return self::validate($document);
	}
	public static function validate(mixed $document): array {
		if (!is_array($document) || ($document['schema'] ?? null) !== 'device-health-config-v1'
				|| !is_array($document['settings'] ?? null) || !is_array($document['profiles'] ?? null)
				|| !is_array($document['profile_rules'] ?? null)) {
			throw new RuntimeException('Configuration does not match device-health-config-v1');
		}
		$settings = $document['settings'];
		$multiplier = (int) ($settings['freshness_multiplier'] ?? 0);
		$grace = (int) ($settings['no_data_grace_s'] ?? 0);
		if ($multiplier < 2 || $multiplier > 20 || $grace < 300) {
			throw new RuntimeException('Freshness multiplier or no-data grace is unsafe');
		}
		foreach (['storage_rollup_include', 'storage_rollup_exclude'] as $key) {
			foreach ($settings[$key] ?? [] as $pattern) {
				if (!is_string($pattern) || @preg_match('~'.$pattern.'~', '') === false) {
					throw new RuntimeException("Invalid {$key} regular expression");
				}
			}
		}
		return $document;
	}
}
