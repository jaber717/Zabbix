<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Config;

use JsonException;
use RuntimeException;
use Throwable;

final class NodeDefinitionRepository {
	public const SCHEMA = 'network-availability-config-v2';
	public const DEFAULT_PATH = '/var/lib/zabbix/network-availability/node-definitions.json';
	private const KINDS = ['host', 'ha_pair', 'cluster', 'fabric', 'logical_service'];
	private const POLICIES = ['ANY_REQUIRED', 'ALL_REQUIRED', 'MAJORITY_REQUIRED', 'MIN_N_REQUIRED'];
	private array $warnings = [];

	public function __construct(private readonly string $path = self::DEFAULT_PATH) {
	}

	public function load(): array {
		return $this->loadDocument()['nodes'];
	}

	public function loadDocument(): array {
		$this->warnings = [];
		try {
			return $this->readStrict($this->path);
		}
		catch (Throwable $exception) {
			$backup = $this->backupPath();
			if (!is_readable($backup)) {
				throw new RuntimeException('Runtime configuration is invalid and no last-known-good copy is available: '
					. $exception->getMessage(), previous: $exception
				);
			}
			$this->warnings[] = 'Runtime configuration was invalid; last-known-good configuration is in use.';
			return $this->readStrict($backup);
		}
	}

	public function warnings(): array {
		return $this->warnings;
	}

	public function save(array $document, int $expected_revision): array {
		$directory = dirname($this->path);
		if (!is_dir($directory) || !is_writable($directory)) {
			throw new RuntimeException("Runtime configuration directory is not writable: {$directory}");
		}

		$lock = fopen($directory . '/.node-definitions.lock', 'c');
		if ($lock === false || !flock($lock, LOCK_EX)) {
			throw new RuntimeException('Unable to lock runtime configuration');
		}

		try {
			$current = $this->loadDocument();
			$using_fallback = $this->warnings !== [];
			if ((int) $current['revision'] !== $expected_revision) {
				throw new RuntimeException('Configuration changed since editing began; reload before saving.');
			}
			$document['schema'] = self::SCHEMA;
			$document['revision'] = $expected_revision + 1;
			$validated = self::validateDocument($document);
			$json = json_encode($validated, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
			$temp = $directory . '/.node-definitions.' . bin2hex(random_bytes(8)) . '.tmp';
			if (file_put_contents($temp, $json, LOCK_EX) === false || !chmod($temp, 0640)) {
				@unlink($temp);
				throw new RuntimeException('Unable to write staged runtime configuration');
			}
			if (is_readable($this->path) && !$using_fallback) {
				$backup_temp = $this->backupPath() . '.tmp';
				if (!copy($this->path, $backup_temp) || !chmod($backup_temp, 0640)
						|| !rename($backup_temp, $this->backupPath())) {
					@unlink($backup_temp);
					@unlink($temp);
					throw new RuntimeException('Unable to preserve last-known-good configuration');
				}
			}
			if (!rename($temp, $this->path)) {
				@unlink($temp);
				throw new RuntimeException('Unable to atomically activate runtime configuration');
			}
			return $validated;
		}
		finally {
			flock($lock, LOCK_UN);
			fclose($lock);
		}
	}

	public static function validateDocument(array $document): array {
		if (($document['schema'] ?? null) !== self::SCHEMA || !is_int($document['revision'] ?? null)
				|| $document['revision'] < 1 || !is_array($document['sites'] ?? null)
				|| !is_array($document['nodes'] ?? null)) {
			throw new RuntimeException('Configuration document does not match schema v2');
		}

		$site_ids = [];
		$sites = [];
		foreach ($document['sites'] as $index => $site) {
			if (!is_array($site)) {
				throw new RuntimeException("Site at index {$index} is invalid");
			}
			$id = self::identifier($site['id'] ?? '', "Site at index {$index}");
			$name = trim((string) ($site['name'] ?? ''));
			if ($name === '') {
				throw new RuntimeException("Site {$id} requires a name");
			}
			if (isset($site_ids[$id])) {
				throw new RuntimeException("Duplicate Site id: {$id}");
			}
			$site_ids[$id] = true;
			$sites[] = ['id' => $id, 'name' => $name, 'order' => (int) ($site['order'] ?? $index * 10)];
		}

		$node_ids = [];
		$nodes = [];
		foreach ($document['nodes'] as $index => $node) {
			if (!is_array($node)) {
				throw new RuntimeException("Node at index {$index} is invalid");
			}
			$id = self::identifier($node['id'] ?? '', "Node at index {$index}");
			if (isset($node_ids[$id])) {
				throw new RuntimeException("Duplicate Node id: {$id}");
			}
			$node_ids[$id] = true;
			$name = trim((string) ($node['name'] ?? ''));
			$site_id = trim((string) ($node['site_id'] ?? ''));
			$kind = strtolower(trim((string) ($node['kind'] ?? '')));
			$policy = strtoupper(trim((string) ($node['aggregation_policy'] ?? '')));
			$tier = strtolower(trim((string) ($node['criticality'] ?? '')));
			$members = $node['members'] ?? null;
			if ($name === '' || !isset($site_ids[$site_id]) || !in_array($kind, self::KINDS, true)
					|| !in_array($policy, self::POLICIES, true) || !in_array($tier, ['tier1', 'tier2', 'tier3'], true)
					|| !is_array($members) || $members === []) {
				throw new RuntimeException("Node {$id} has incomplete or invalid Site, kind, Tier, policy, or Members");
			}
			$count = count($members);
			if (($kind === 'host' && $count !== 1) || ($kind === 'ha_pair' && $count !== 2)
					|| (in_array($kind, ['cluster', 'fabric'], true) && $count < 2)) {
				throw new RuntimeException("Node {$id} Member count is invalid for kind {$kind}");
			}
			if ($policy === 'MAJORITY_REQUIRED' && $count === 2
					&& !($node['allow_two_member_majority'] ?? false)) {
				throw new RuntimeException("Node {$id} cannot use two-Member MAJORITY_REQUIRED without explicit override");
			}
			$min_n = $policy === 'MIN_N_REQUIRED' ? (int) ($node['min_n'] ?? 0) : null;
			if ($policy === 'MIN_N_REQUIRED' && ($min_n < 1 || $min_n > $count)) {
				throw new RuntimeException("Node {$id} MIN_N must be within 1..{$count}");
			}

			$member_hosts = [];
			$normalized_members = [];
			foreach ($members as $member_index => $member) {
				if (!is_array($member)) {
					throw new RuntimeException("Node {$id} Member at index {$member_index} is invalid");
				}
				$host = trim((string) ($member['host'] ?? ''));
				if ($host === '' || isset($member_hosts[$host])) {
					throw new RuntimeException($host === '' ? "Node {$id} has a Member without a Host"
						: "Node {$id} contains duplicate Member Host {$host}"
					);
				}
				$member_hosts[$host] = true;
				$normalized = [
					'id' => self::identifier($member['id'] ?? $host, "Node {$id} Member"),
					'name' => trim((string) ($member['name'] ?? $host)) ?: $host,
					'host' => $host
				];
				foreach (['availability_item_key', 'availability_source'] as $optional) {
					if (trim((string) ($member[$optional] ?? '')) !== '') {
						$normalized[$optional] = trim((string) $member[$optional]);
					}
				}
				if (isset($member['expected_interval_s']) && (int) $member['expected_interval_s'] > 0) {
					$normalized['expected_interval_s'] = (int) $member['expected_interval_s'];
				}
				$normalized_members[] = $normalized;
			}

			$normalized_node = [
				'id' => $id,
				'name' => $name,
				'site_id' => $site_id,
				'kind' => $kind,
				'aggregation_policy' => $policy,
				'criticality' => $tier,
				'order' => (int) ($node['order'] ?? $index * 10),
				'hidden' => (bool) ($node['hidden'] ?? false),
				'description' => trim((string) ($node['description'] ?? '')),
				'members' => $normalized_members
			];
			if ($min_n !== null) {
				$normalized_node['min_n'] = $min_n;
			}
			if ($node['allow_two_member_majority'] ?? false) {
				$normalized_node['allow_two_member_majority'] = true;
			}
			$nodes[] = $normalized_node;
		}

		return ['schema' => self::SCHEMA, 'revision' => $document['revision'], 'sites' => $sites, 'nodes' => $nodes];
	}

	private function readStrict(string $path): array {
		if (!is_readable($path)) {
			throw new RuntimeException("Node definition file is not readable: {$path}");
		}
		try {
			$data = json_decode((string) file_get_contents($path), true, 64, JSON_THROW_ON_ERROR);
		}
		catch (JsonException $exception) {
			throw new RuntimeException('Node definition JSON is invalid', previous: $exception);
		}
		if (!is_array($data)) {
			throw new RuntimeException('Node definition document must be an object');
		}
		if (($data['schema'] ?? null) === 'network-availability-node-definitions-v1') {
			$data = self::migrateLegacy($data);
		}
		return self::validateDocument($data);
	}

	private static function migrateLegacy(array $legacy): array {
		$sites = [];
		$site_ids = [];
		$nodes = [];
		foreach ($legacy['nodes'] ?? [] as $node) {
			$site_name = trim((string) ($node['site'] ?? ''));
			$site_id = 'legacy-' . substr(hash('sha256', strtolower($site_name)), 0, 12);
			if (!isset($site_ids[$site_id])) {
				$site_ids[$site_id] = true;
				$sites[] = ['id' => $site_id, 'name' => $site_name, 'order' => count($sites) * 10];
			}
			$node['site_id'] = $site_id;
			$node['hidden'] = false;
			$node['description'] = '';
			unset($node['site']);
			$nodes[] = $node;
		}
		return ['schema' => self::SCHEMA, 'revision' => 1, 'sites' => $sites, 'nodes' => $nodes];
	}

	private static function identifier(mixed $value, string $context): string {
		$value = trim((string) $value);
		if ($value === '' || preg_match('/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/', $value) !== 1) {
			throw new RuntimeException("{$context} requires a stable identifier");
		}
		return $value;
	}

	private function backupPath(): string {
		return dirname($this->path) . '/node-definitions.last-known-good.json';
	}
}
