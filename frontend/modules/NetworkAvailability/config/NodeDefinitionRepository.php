<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Config;

use JsonException;
use RuntimeException;

final class NodeDefinitionRepository {
	public function __construct(private readonly string $path) {
	}

	public function load(): array {
		if (!is_readable($this->path)) {
			throw new RuntimeException("Node definition file is not readable: {$this->path}");
		}
		try {
			$data = json_decode((string) file_get_contents($this->path), true, 32, JSON_THROW_ON_ERROR);
		}
		catch (JsonException $exception) {
			throw new RuntimeException('Node definition JSON is invalid', previous: $exception);
		}
		if (!is_array($data) || ($data['schema'] ?? null) !== 'network-availability-node-definitions-v1'
				|| !is_array($data['nodes'] ?? null)) {
			throw new RuntimeException('Node definition document does not match schema v1');
		}
		$ids = [];
		foreach ($data['nodes'] as $index => $node) {
			if (!is_array($node) || trim((string) ($node['id'] ?? '')) === ''
					|| trim((string) ($node['name'] ?? '')) === ''
					|| trim((string) ($node['site'] ?? '')) === ''
					|| trim((string) ($node['kind'] ?? '')) === ''
					|| trim((string) ($node['aggregation_policy'] ?? '')) === ''
					|| trim((string) ($node['criticality'] ?? '')) === ''
					|| !array_key_exists('order', $node) || !is_array($node['members'] ?? null)
					|| $node['members'] === []) {
				throw new RuntimeException("Node definition at index {$index} is incomplete");
			}
			if (isset($ids[$node['id']])) {
				throw new RuntimeException("Duplicate Node id: {$node['id']}");
			}
			$ids[$node['id']] = true;
			if ($node['aggregation_policy'] === 'MIN_N_REQUIRED'
					&& (!isset($node['min_n']) || (int) $node['min_n'] < 1)) {
				throw new RuntimeException("Node {$node['id']} requires a positive min_n");
			}
			foreach ($node['members'] as $member) {
				if (!is_array($member) || trim((string) ($member['host'] ?? '')) === '') {
					throw new RuntimeException("Node {$node['id']} has a Member without a stable host name");
				}
			}
		}
		return $data['nodes'];
	}
}
