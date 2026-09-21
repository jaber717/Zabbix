<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Collector;

use API;
use Modules\NetworkAvailability\Config\Limits;
use Modules\NetworkAvailability\Config\NodeDefinitionRepository;
use Modules\NetworkAvailability\Domain\ExpectedIntervalResolver;
use Throwable;

final class ZabbixAvailabilityCollector implements AvailabilityCollectorInterface {
	private const DEFAULT_AVAILABILITY_KEYS = [
		'icmpping',
		'agent.ping',
		'zabbix[host,snmp,available]',
		'zabbix[host,agent,available]'
	];

	private int $api_calls = 0;

	public function __construct(
		private readonly NodeDefinitionRepository $definitions,
		private readonly ExpectedIntervalResolver $intervals
	) {
	}

	public function collect(int $now): array {
		$started = hrtime(true);
		$this->api_calls = 0;
		$warnings = [];
		$definitions = $this->definitions->load();

		$this->api_calls++;
		$hosts = API::Host()->get([
			'output' => ['hostid', 'host', 'name', 'proxyid', 'maintenance_status'],
			'selectTags' => ['tag', 'value'],
			'monitored_hosts' => true,
			'limit' => Limits::MAX_HOSTS,
			'preservekeys' => true
		]);
		if (count($hosts) >= Limits::MAX_HOSTS) {
			$warnings[] = 'Host query reached MAX_HOSTS; snapshot may be incomplete.';
		}

		$hosts_by_name = [];
		$keys = self::DEFAULT_AVAILABILITY_KEYS;
		foreach ($hosts as $hostid => &$host) {
			$host['hostid'] = (string) $hostid;
			$host['tag_map'] = $this->tagMap($host['tags'] ?? []);
			$hosts_by_name[$host['host']] = &$host;
		}
		unset($host);
		foreach ($definitions as $definition) {
			foreach ($definition['members'] as $member) {
				if (!empty($member['availability_item_key'])) {
					$keys[] = (string) $member['availability_item_key'];
				}
			}
		}
		$keys = array_values(array_unique($keys));

		$this->api_calls++;
		$items = API::Item()->get([
			'output' => ['itemid', 'hostid', 'name', 'key_', 'delay', 'lastclock', 'lastvalue', 'value_type', 'state', 'status'],
			'hostids' => array_keys($hosts),
			'filter' => ['key_' => $keys, 'status' => 0],
			'limit' => Limits::MAX_ITEMS
		]);
		if (count($items) >= Limits::MAX_ITEMS) {
			$warnings[] = 'Availability item query reached MAX_ITEMS; snapshot may be incomplete.';
		}
		$items_by_host = [];
		foreach ($items as $item) {
			$items_by_host[$item['hostid']][$item['key_']] = $item;
		}

		$member_rows = [];
		$defined_hosts = [];
		$nodes = [];
		foreach ($definitions as $definition) {
			$node_members = [];
			foreach ($definition['members'] as $member_definition) {
				$hostname = (string) $member_definition['host'];
				$defined_hosts[$hostname] = true;
				if (!isset($hosts_by_name[$hostname])) {
					$warnings[] = "Configured Member host is not visible: {$hostname}";
					$node_members[] = $this->missingMember($hostname, $member_definition);
					continue;
				}
				$node_members[] = $this->memberFromHost($hosts_by_name[$hostname], $member_definition,
					$items_by_host, $warnings
				);
			}
			$nodes[] = [
				'id' => (string) $definition['id'],
				'name' => (string) $definition['name'],
				'site' => (string) $definition['site'],
				'kind' => (string) $definition['kind'],
				'policy' => (string) $definition['aggregation_policy'],
				'min_n' => isset($definition['min_n']) ? (int) $definition['min_n'] : null,
				'allow_two_member_majority' => (bool) ($definition['allow_two_member_majority'] ?? false),
				'criticality' => (string) $definition['criticality'],
				'order' => (int) $definition['order'],
				'maintenance' => $this->allMembersFlag($node_members, 'maintenance'),
				'suppressed' => (bool) ($definition['suppressed'] ?? false),
				'members' => $node_members
			];
			array_push($member_rows, ...$node_members);
		}

		foreach ($hosts_by_name as $hostname => $host) {
			if (isset($defined_hosts[$hostname])) {
				continue;
			}
			$member = $this->memberFromHost($host, [], $items_by_host, $warnings);
			$site = trim((string) ($host['tag_map']['site'] ?? ''));
			$missing = ['Node mapping'];
			if ($site === '') {
				$site = 'UNCLASSIFIED';
				$missing[] = 'site';
			}
			$nodes[] = [
				'id' => 'unclassified-host-' . $host['hostid'],
				'name' => (string) $host['name'],
				'site' => $site,
				'kind' => null,
				'policy' => null,
				'criticality' => (string) ($host['tag_map']['criticality'] ?? 'tier3'),
				'order' => PHP_INT_MAX,
				'configuration_required' => true,
				'configuration_missing' => $missing,
				'maintenance' => $member['maintenance'],
				'suppressed' => false,
				'members' => [$member]
			];
			$member_rows[] = $member;
		}

		$history = $this->collectTransitions($member_rows, $now, $warnings);
		foreach ($nodes as &$node) {
			foreach ($node['members'] as &$member) {
				$member['transitions'] = $history[$member['availability_item_id']] ?? [];
			}
			unset($member);
		}
		unset($node);

		[$problems, $trigger_state] = $this->collectProblemsAndDependencies(array_keys($hosts), $warnings);
		$this->applyProblemOverlays($nodes, $problems, $trigger_state);

		return [
			'nodes' => $nodes,
			'warnings' => $warnings,
			'instrumentation' => [
				'api_call_count' => $this->api_calls,
				'hosts_retrieved' => count($hosts),
				'members_resolved' => count($member_rows),
				'nodes_resolved' => count($nodes),
				'problems_retrieved' => count($problems),
				'collector_time_ms' => round((hrtime(true) - $started) / 1_000_000, 3)
			]
		];
	}

	private function memberFromHost(array $host, array $definition, array $items_by_host, array &$warnings): array {
		$key = (string) ($definition['availability_item_key'] ?? '');
		if ($key === '') {
			foreach (self::DEFAULT_AVAILABILITY_KEYS as $candidate) {
				if (isset($items_by_host[$host['hostid']][$candidate])) {
					$key = $candidate;
					break;
				}
			}
		}
		$item = $key !== '' ? ($items_by_host[$host['hostid']][$key] ?? null) : null;
		$interval = $item === null
			? ['seconds' => null, 'source' => null, 'error' => 'no availability item selected']
			: $this->intervals->resolve($item,
				isset($definition['expected_interval_s']) ? (int) $definition['expected_interval_s'] : null
			);
		if ($interval['error'] !== null) {
			$warnings[] = "{$host['name']}: {$interval['error']}";
		}
		$state = 'UNKNOWN';
		$last_success = null;
		if ($item !== null && (string) $item['state'] === '0' && in_array((string) $item['lastvalue'], ['0', '1'], true)) {
			$state = (string) $item['lastvalue'] === '1' ? 'UP' : 'DOWN';
			$last_success = (int) $item['lastclock'];
		}
		$source = (string) ($definition['availability_source'] ?? $this->sourceFromKey($key));
		$source_id = (string) ($host['tag_map']['availability_source_id'] ?? '');
		if ($source_id === '') {
			$source_id = (string) $host['proxyid'] !== '0' ? 'proxy:' . $host['proxyid'] : 'local:' . strtolower($source);
		}
		return [
			'id' => (string) ($definition['id'] ?? $host['hostid']),
			'name' => (string) ($definition['name'] ?? $host['name']),
			'hostid' => (string) $host['hostid'],
			'host' => (string) $host['host'],
			'raw_availability_state' => $state,
			'availability_source' => $source,
			'availability_source_id' => $source_id,
			'availability_item_id' => $item['itemid'] ?? null,
			'availability_item_key' => $key !== '' ? $key : null,
			'value_type' => $item !== null ? (int) $item['value_type'] : null,
			'last_success' => $last_success,
			'expected_interval' => $interval['seconds'],
			'expected_interval_source' => $interval['source'],
			'maintenance' => (string) $host['maintenance_status'] === '1',
			'transitions' => []
		];
	}

	private function missingMember(string $hostname, array $definition): array {
		return [
			'id' => (string) ($definition['id'] ?? $hostname),
			'name' => (string) ($definition['name'] ?? $hostname),
			'hostid' => null,
			'host' => $hostname,
			'raw_availability_state' => 'UNKNOWN',
			'availability_source' => (string) ($definition['availability_source'] ?? 'UNKNOWN'),
			'availability_source_id' => 'unresolved',
			'availability_item_id' => null,
			'availability_item_key' => $definition['availability_item_key'] ?? null,
			'value_type' => null,
			'last_success' => null,
			'expected_interval' => $definition['expected_interval_s'] ?? null,
			'expected_interval_source' => isset($definition['expected_interval_s']) ? 'node_definition' : null,
			'maintenance' => false,
			'transitions' => []
		];
	}

	private function collectTransitions(array $members, int $now, array &$warnings): array {
		$by_type = [];
		foreach ($members as $member) {
			if ($member['availability_item_id'] === null || $member['value_type'] === null) {
				continue;
			}
			$by_type[(int) $member['value_type']][] = (string) $member['availability_item_id'];
		}
		if ($by_type === []) {
			return [];
		}
		$rows = [];
		foreach ($by_type as $value_type => $itemids) {
			try {
				$this->api_calls++;
				$type_rows = API::History()->get([
					'output' => ['itemid', 'clock', 'value'],
					'history' => $value_type,
					'itemids' => array_values(array_unique($itemids)),
					'time_from' => $now - Limits::FLAP_WINDOW_S,
					'sortfield' => ['itemid', 'clock'],
					'sortorder' => 'ASC',
					'limit' => Limits::MAX_HISTORY_ROWS
				]);
				$rows = array_merge($rows, $type_rows);
				if (count($type_rows) >= Limits::MAX_HISTORY_ROWS) {
					$warnings[] = sprintf('Flap history reached MAX_HISTORY_ROWS for value type %d; '
						. 'flapping status may be incomplete.', $value_type
					);
				}
			}
			catch (Throwable $exception) {
				$warnings[] = sprintf('Flap history unavailable for value type %d: %s',
					$value_type, $exception->getMessage()
				);
			}
		}
		$values = [];
		$transitions = [];
		foreach ($rows as $row) {
			$itemid = (string) $row['itemid'];
			$value = (string) $row['value'];
			if (isset($values[$itemid]) && $values[$itemid] !== $value) {
				$transitions[$itemid][] = (int) $row['clock'];
			}
			$values[$itemid] = $value;
		}
		return $transitions;
	}

	private function collectProblemsAndDependencies(array $hostids, array &$warnings): array {
		try {
			$this->api_calls++;
			$triggers = API::Trigger()->get([
				'output' => ['triggerid', 'lastchange'],
				'selectHosts' => ['hostid'],
				'selectDependencies' => ['triggerid'],
				'hostids' => $hostids,
				'filter' => ['value' => 1],
				'monitored' => true,
				'preservekeys' => true
			]);
			$this->api_calls++;
			$problems = API::Problem()->get([
				'output' => ['eventid', 'objectid', 'clock', 'severity', 'suppressed'],
				'hostids' => $hostids,
				'suppressed' => null,
				'symptom' => false,
				'limit' => Limits::MAX_ITEMS
			]);
		}
		catch (Throwable $exception) {
			$warnings[] = 'Problem/dependency overlay unavailable: ' . $exception->getMessage();
			return [[], []];
		}
		$active = array_fill_keys(array_keys($triggers), true);
		$state = [];
		foreach ($triggers as $triggerid => $trigger) {
			$dependent = false;
			foreach ($trigger['dependencies'] ?? [] as $dependency) {
				$dependent = $dependent || isset($active[$dependency['triggerid']]);
			}
			foreach ($trigger['hosts'] ?? [] as $host) {
				$state[$host['hostid']][$triggerid] = ['dependent' => $dependent];
			}
		}
		return [$problems, $state];
	}

	private function applyProblemOverlays(array &$nodes, array $problems, array $trigger_state): void {
		$problem_by_trigger = [];
		foreach ($problems as $problem) {
			$problem_by_trigger[$problem['objectid']] = $problem;
		}
		foreach ($nodes as &$node) {
			$node_problems = [];
			foreach ($node['members'] as $member) {
				foreach ($trigger_state[$member['hostid']] ?? [] as $triggerid => $state) {
					if (isset($problem_by_trigger[$triggerid])) {
						$node_problems[] = $problem_by_trigger[$triggerid] + $state;
					}
				}
			}
			if ($node_problems !== []) {
				$node['event_since'] = min(array_map('intval', array_column($node_problems, 'clock')));
				$node['suppressed'] = $node['suppressed'] || count(array_filter($node_problems,
					static fn(array $problem): bool => (string) ($problem['suppressed'] ?? '0') === '1'
				)) === count($node_problems);
				$node['dependency_suppressed'] = count(array_filter($node_problems,
					static fn(array $problem): bool => $problem['dependent']
				)) === count($node_problems);
			}
		}
		unset($node);
	}

	private function tagMap(array $tags): array {
		$result = [];
		foreach ($tags as $tag) {
			if (!array_key_exists((string) $tag['tag'], $result)) {
				$result[(string) $tag['tag']] = (string) $tag['value'];
			}
		}
		return $result;
	}

	private function sourceFromKey(string $key): string {
		return match (true) {
			$key === 'icmpping' => 'ICMP',
			$key === 'agent.ping', str_contains($key, ',agent,') => 'Zabbix Agent',
			str_contains($key, ',snmp,') => 'SNMP',
			$key === '' => 'UNKNOWN',
			default => 'other'
		};
	}

	private function allMembersFlag(array $members, string $key): bool {
		return $members !== [] && count(array_filter($members, static fn(array $member): bool => (bool) $member[$key]))
			=== count($members);
	}
}
