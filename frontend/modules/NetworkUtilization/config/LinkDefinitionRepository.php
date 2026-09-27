<?php declare(strict_types = 1);

namespace Modules\NetworkUtilization\Config;

use JsonException;
use RuntimeException;
use Throwable;

final class LinkDefinitionRepository {
	public const SCHEMA = 'network-utilization-config-v1';
	public const DEFAULT_PATH = '/var/lib/zabbix/network-utilization/link-definitions.json';
	private const ROLES = ['WAN', 'ISP', 'DCI', 'CORE', 'UPLINK', 'FIREWALL', 'LOAD_BALANCER', 'SERVER', 'ACCESS', 'OTHER'];
	private array $warnings = [];

	public function __construct(private readonly string $path = self::DEFAULT_PATH) {}

	public function loadDocument(): array {
		$this->warnings = [];
		try { return $this->readStrict($this->path); }
		catch (Throwable $e) {
			if (!is_readable($this->backupPath())) {
				throw new RuntimeException('Runtime configuration is invalid and no last-known-good copy is available: '.$e->getMessage(), previous: $e);
			}
			$this->warnings[] = 'Runtime configuration was invalid; last-known-good configuration is in use.';
			return $this->readStrict($this->backupPath());
		}
	}

	public function warnings(): array { return $this->warnings; }

	public function save(array $document, int $expected_revision): array {
		$directory = dirname($this->path);
		if (!is_dir($directory) || !is_writable($directory)) throw new RuntimeException("Runtime configuration directory is not writable: {$directory}");
		$lock = fopen($directory.'/.link-definitions.lock', 'c');
		if ($lock === false || !flock($lock, LOCK_EX)) throw new RuntimeException('Unable to lock runtime configuration');
		try {
			$current = $this->loadDocument();
			$fallback = $this->warnings !== [];
			if ($current['revision'] !== $expected_revision) throw new RuntimeException('Configuration changed since editing began; reload before saving.');
			$document['schema'] = self::SCHEMA;
			$document['revision'] = $expected_revision + 1;
			$validated = self::validateDocument($document);
			$json = json_encode($validated, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR)."\n";
			$temp = $directory.'/.link-definitions.'.bin2hex(random_bytes(8)).'.tmp';
			if (file_put_contents($temp, $json, LOCK_EX) === false || !chmod($temp, 0640)) throw new RuntimeException('Unable to write staged runtime configuration');
			if (is_readable($this->path) && !$fallback) {
				$backup_temp = $this->backupPath().'.tmp';
				if (!copy($this->path, $backup_temp) || !chmod($backup_temp, 0640) || !rename($backup_temp, $this->backupPath())) {
					@unlink($temp); @unlink($backup_temp); throw new RuntimeException('Unable to preserve last-known-good configuration');
				}
			}
			if (!rename($temp, $this->path)) { @unlink($temp); throw new RuntimeException('Unable to atomically activate runtime configuration'); }
			return $validated;
		}
		finally { flock($lock, LOCK_UN); fclose($lock); }
	}

	public static function validateDocument(array $document): array {
		if (($document['schema'] ?? null) !== self::SCHEMA || !is_int($document['revision'] ?? null) || $document['revision'] < 1
				|| !is_array($document['settings'] ?? null) || !is_array($document['sites'] ?? null) || !is_array($document['links'] ?? null)) {
			throw new RuntimeException('Configuration document does not match schema v1');
		}
		$settings = $document['settings'];
		$warning = self::percent($settings['warning_util_pct'] ?? Limits::DEFAULT_WARNING_PCT, 'warning threshold');
		$critical = self::percent($settings['critical_util_pct'] ?? Limits::DEFAULT_CRITICAL_PCT, 'critical threshold');
		$risk = self::percent($settings['capacity_risk_p95_pct'] ?? Limits::DEFAULT_CAPACITY_RISK_PCT, 'capacity risk threshold');
		$sustained = (int) ($settings['sustained_window_min'] ?? Limits::DEFAULT_SUSTAINED_MIN);
		if ($warning >= $critical || $sustained < 1 || $sustained > 120) throw new RuntimeException('Threshold ordering or sustained window is invalid');
		$normalized_settings = ['warning_util_pct' => $warning, 'critical_util_pct' => $critical,
			'capacity_risk_p95_pct' => $risk, 'sustained_window_min' => $sustained];

		$site_ids = []; $sites = [];
		foreach ($document['sites'] as $index => $site) {
			$id = self::identifier($site['id'] ?? '', "Site at index {$index}"); $name = trim((string) ($site['name'] ?? ''));
			if ($name === '' || isset($site_ids[$id])) throw new RuntimeException("Site {$id} requires a unique id and name");
			$site_ids[$id] = true; $sites[] = ['id' => $id, 'name' => $name, 'order' => (int) ($site['order'] ?? $index * 10)];
		}
		if (count($document['links']) > Limits::MAX_CONFIGURED_LINKS) throw new RuntimeException('Configured Link limit exceeded');
		$link_ids = []; $identities = []; $links = [];
		foreach ($document['links'] as $index => $link) {
			$id = self::identifier($link['id'] ?? '', "Link at index {$index}");
			$name = trim((string) ($link['display_name'] ?? '')); $site_id = trim((string) ($link['site_id'] ?? ''));
			$host = trim((string) ($link['host'] ?? '')); $if_name = trim((string) ($link['interface']['if_name'] ?? ''));
			$role = strtoupper(trim((string) ($link['role'] ?? 'OTHER')));
			if ($name === '' || !isset($site_ids[$site_id]) || $host === '' || $if_name === '' || !in_array($role, self::ROLES, true)) {
				throw new RuntimeException("Link {$id} has incomplete or invalid Site, Host, interface, name, or role");
			}
			$identity = strtolower($host."\0".$if_name);
			if (isset($link_ids[$id]) || isset($identities[$identity])) throw new RuntimeException("Duplicate Link id or Host/interface identity: {$id}");
			$link_ids[$id] = true; $identities[$identity] = true;
			$normalized = ['id' => $id, 'display_name' => $name, 'site_id' => $site_id, 'host' => $host,
				'interface' => ['if_name' => $if_name, 'if_alias' => trim((string) ($link['interface']['if_alias'] ?? '')),
					'if_descr' => trim((string) ($link['interface']['if_descr'] ?? ''))],
				'role' => $role, 'order' => (int) ($link['order'] ?? $index * 10), 'visible' => (bool) ($link['visible'] ?? true),
				'show_graph' => (bool) ($link['show_graph'] ?? false),
				'graph_order' => (int) ($link['graph_order'] ?? $index * 10),
				'required' => (bool) ($link['required'] ?? true)];
			$source = $link['capacity_source'] ?? (isset($link['capacity_override_bps']) ? 'service_override' : 'interface_speed');
			if (!in_array($source, ['interface_speed', 'service_override'], true)) throw new RuntimeException("Link {$id} capacity source is invalid");
			$legacy = $link['capacity_override_bps'] ?? null;
			$in_value = $link['service_capacity_in_bps'] ?? $legacy;
			$out_value = $link['service_capacity_out_bps'] ?? $legacy;
			$symmetric = array_key_exists('symmetric_service_bandwidth', $link) ? (bool) $link['symmetric_service_bandwidth'] : $in_value === $out_value;
			$normalized['capacity_source'] = $source;
			$normalized['symmetric_service_bandwidth'] = $symmetric;
			$normalized['capacity_warning_accepted'] = $source === 'interface_speed' && (bool) ($link['capacity_warning_accepted'] ?? false);
			if ($source === 'service_override') {
				$normalized['service_capacity_in_bps'] = self::positiveBps($in_value, "Link {$id} IN service capacity");
				$normalized['service_capacity_out_bps'] = self::positiveBps($symmetric ? $in_value : $out_value, "Link {$id} OUT service capacity");
			}
			foreach (['warning_util_pct', 'critical_util_pct'] as $field) {
				if (!array_key_exists($field, $link) || $link[$field] === null || $link[$field] === '') continue;
				$normalized[$field] = self::percent($link[$field], $field);
			}
			if (($normalized['warning_util_pct'] ?? $warning) >= ($normalized['critical_util_pct'] ?? $critical)) throw new RuntimeException("Link {$id} threshold ordering is invalid");
			$links[] = $normalized;
		}
		return ['schema' => self::SCHEMA, 'revision' => $document['revision'], 'settings' => $normalized_settings, 'sites' => $sites, 'links' => $links];
	}

	private function readStrict(string $path): array {
		if (!is_readable($path)) throw new RuntimeException("Link definition file is not readable: {$path}");
		try { $data = json_decode((string) file_get_contents($path), true, 64, JSON_THROW_ON_ERROR); }
		catch (JsonException $e) { throw new RuntimeException('Link definition JSON is invalid', previous: $e); }
		if (!is_array($data)) throw new RuntimeException('Link definition document must be an object');
		return self::validateDocument($data);
	}
	private static function identifier(mixed $value, string $context): string {
		$value = trim((string) $value);
		if (!preg_match('/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/', $value)) throw new RuntimeException("{$context} requires a stable identifier");
		return $value;
	}
	private static function percent(mixed $value, string $context): float {
		$value = (float) $value; if ($value <= 0 || $value > 100) throw new RuntimeException("{$context} must be within 0..100"); return $value;
	}
	private static function positiveBps(mixed $value, string $context): int {
		if (!is_numeric($value) || !is_finite((float) $value) || (float) $value < 1 || (float) $value > 1e15 || floor((float) $value) !== (float) $value) {
			throw new RuntimeException("{$context} must be a positive whole number of bps");
		}
		return (int) $value;
	}
	private function backupPath(): string { return dirname($this->path).'/link-definitions.last-known-good.json'; }
}
