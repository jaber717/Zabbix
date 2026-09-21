<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Domain;

use InvalidArgumentException;
use Modules\NetworkAvailability\Config\Limits;

final class AvailabilityResolver {
	private const ACTUAL_STATES = ['UP', 'DOWN', 'DEGRADED', 'UNKNOWN'];
	private const POLICIES = [
		'ANY_REQUIRED', 'ALL_REQUIRED', 'MAJORITY_REQUIRED', 'MIN_N_REQUIRED', 'UNCONFIGURED_SINGLE_MEMBER'
	];

	public function resolve(array $nodes, int $now, ?array $current_hero = null): array {
		$resolved_nodes = [];
		$warnings = [];

		foreach ($nodes as $node) {
			try {
				$resolved_nodes[] = $this->resolveNode($node, $now);
			}
			catch (InvalidArgumentException $exception) {
				$warnings[] = sprintf('%s: %s', (string) ($node['name'] ?? $node['id'] ?? 'Node'),
					$exception->getMessage()
				);
			}
		}

		usort($resolved_nodes, static fn(array $a, array $b): int =>
			[$a['site'], $a['order'], $a['name'], $a['id']]
				<=> [$b['site'], $b['order'], $b['name'], $b['id']]
		);

		$mass_stale = $this->massStaleIncidents($resolved_nodes, $now);
		$covered_visibility_nodes = [];
		foreach ($mass_stale as $incident) {
			foreach ($incident['affected_node_ids'] as $node_id) {
				$covered_visibility_nodes[$node_id] = true;
			}
		}
		$candidates = array_merge($this->nodeIncidentCandidates($resolved_nodes, $covered_visibility_nodes), $mass_stale);
		$hero = $this->selectHero($candidates, $current_hero, $now);
		$secondary = array_values(array_filter($candidates,
			static fn(array $candidate): bool => $candidate['hero_eligible']
				&& ($hero === null || $candidate['id'] !== $hero['id'])
		));
		usort($secondary, [$this, 'compareIncidents']);
		$secondary = array_slice($secondary, 0, Limits::SECONDARY_INCIDENTS_MAX);

		$sites = $this->resolveSites($resolved_nodes);
		$summary = [
			'UP' => 0,
			'DOWN' => 0,
			'DEGRADED' => 0,
			'UNKNOWN' => 0,
			'VISIBILITY_LOSS' => 0,
			'MAINTENANCE' => 0,
			'IMPACTED_SITES' => 0
		];
		foreach ($resolved_nodes as $node) {
			$summary[$node['actual_state']]++;
			$summary['VISIBILITY_LOSS'] += $node['visibility'] === 'LOST' ? 1 : 0;
			$summary['MAINTENANCE'] += $node['maintenance'] ? 1 : 0;
		}
		foreach ($sites as $site) {
			$summary['IMPACTED_SITES'] += !in_array($site['state'], ['HEALTHY', 'MAINTENANCE', 'SUPPRESSED'], true)
				? 1
				: 0;
		}

		return [
			'generated_at' => $now,
			'summary' => $summary,
			'hero' => $hero,
			'secondary' => $secondary,
			'sites' => $sites,
			'mass_stale_incidents' => $mass_stale,
			'warnings' => $warnings
		];
	}

	public function resolveNode(array $node, int $now): array {
		$id = trim((string) ($node['id'] ?? ''));
		$name = trim((string) ($node['name'] ?? ''));
		$members = $node['members'] ?? [];
		if ($id === '' || $name === '' || !is_array($members) || $members === []) {
			throw new InvalidArgumentException('id, name and at least one Member are required');
		}

		$configuration_required = (bool) ($node['configuration_required'] ?? false);
		$policy = strtoupper((string) ($node['policy'] ?? ''));
		if ($policy === '' && $configuration_required && count($members) === 1) {
			$policy = 'UNCONFIGURED_SINGLE_MEMBER';
		}
		if (!in_array($policy, self::POLICIES, true)) {
			throw new InvalidArgumentException("unsupported aggregation policy {$policy}");
		}
		if ($policy === 'MAJORITY_REQUIRED' && count($members) === 2
				&& !($node['allow_two_member_majority'] ?? false)) {
			throw new InvalidArgumentException('MAJORITY_REQUIRED on two Members requires an explicit override');
		}

		$required = $this->requiredMembers($policy, count($members), $node['min_n'] ?? null);
		$resolved_members = [];
		$known_up = 0;
		$known_down = 0;
		$unknown = 0;
		$degraded_member = false;
		$flapping = false;

		foreach ($members as $member) {
			$resolved = $this->resolveMember($member, $now);
			$resolved_members[] = $resolved;
			if (!$resolved['fresh'] || $resolved['raw_availability_state'] === 'UNKNOWN') {
				$unknown++;
			}
			elseif (in_array($resolved['raw_availability_state'], ['UP', 'DEGRADED'], true)) {
				$known_up++;
				$degraded_member = $degraded_member || $resolved['raw_availability_state'] === 'DEGRADED';
			}
			else {
				$known_down++;
			}
			$recent_transitions = array_filter($resolved['transitions'],
				static fn(int $transition): bool => $transition >= $now - Limits::FLAP_WINDOW_S
			);
			$flapping = $flapping || count($recent_transitions) >= Limits::FLAP_TRANSITIONS_N;
		}

		if ($known_up >= $required) {
			$actual = ($known_down > 0 || $degraded_member) ? 'DEGRADED' : 'UP';
		}
		elseif ($known_up + $unknown < $required) {
			$actual = 'DOWN';
		}
		else {
			$actual = 'UNKNOWN';
		}

		$fresh_count = count($members) - $unknown;
		$visibility = $fresh_count === count($members) ? 'FULL' : ($fresh_count === 0 ? 'LOST' : 'PARTIAL');
		$last_successes = array_filter(array_column($resolved_members, 'last_success'),
			static fn($value): bool => is_int($value) && $value > 0
		);
		$visibility_lost_at = null;
		if ($visibility === 'LOST') {
			$stale_at = array_filter(array_column($resolved_members, 'stale_at'), 'is_int');
			$visibility_lost_at = $stale_at === [] ? $now : max($stale_at);
		}

		return [
			'id' => $id,
			'name' => $name,
			'site' => (string) ($node['site'] ?? 'Unclassified'),
			'order' => (int) ($node['order'] ?? PHP_INT_MAX),
			'kind' => $node['kind'] ?? null,
			'configuration_required' => $configuration_required,
			'configuration_missing' => array_values($node['configuration_missing'] ?? []),
			'criticality' => $this->criticality($node['criticality'] ?? 'tier3'),
			'policy' => $policy,
			'required_members' => $required,
			'actual_state' => $actual,
			'visibility' => $visibility,
			'maintenance' => (bool) ($node['maintenance'] ?? false),
			'suppressed' => (bool) ($node['suppressed'] ?? false),
			'dependency_suppressed' => (bool) ($node['dependency_suppressed'] ?? false),
			'flapping' => $flapping,
			'members' => $resolved_members,
			'known_up' => $known_up,
			'known_down' => $known_down,
			'unknown_members' => $unknown,
			'availability_source_id' => $this->commonSourceId($resolved_members),
			'last_success' => $last_successes === [] ? null : max($last_successes),
			'visibility_lost_at' => $visibility_lost_at,
			'event_since' => (int) ($node['event_since'] ?? $visibility_lost_at ?? $now),
			'impact' => isset($node['impact']) ? (int) $node['impact'] : null,
			'hostids' => array_values(array_unique(array_filter(array_column($members, 'hostid'))))
		];
	}

	private function resolveMember(array $member, int $now): array {
		$state = strtoupper((string) ($member['raw_availability_state'] ?? 'UNKNOWN'));
		if (!in_array($state, self::ACTUAL_STATES, true)) {
			$state = 'UNKNOWN';
		}
		$last_success = isset($member['last_success']) ? (int) $member['last_success'] : null;
		$interval = isset($member['expected_interval']) ? (int) $member['expected_interval'] : null;
		$stale_at = $last_success !== null && $interval !== null && $interval > 0
			? $last_success + ($interval * Limits::STALE_MULTIPLIER)
			: null;
		$fresh = $stale_at !== null && $now <= $stale_at;

		return array_merge($member, [
			'id' => (string) ($member['id'] ?? $member['hostid'] ?? 'member'),
			'name' => (string) ($member['name'] ?? $member['id'] ?? 'Member'),
			'raw_availability_state' => $state,
			'last_success' => $last_success,
			'expected_interval' => $interval,
			'data_age' => $last_success === null ? null : max(0, $now - $last_success),
			'stale_at' => $stale_at,
			'fresh' => $fresh,
			'freshness' => $fresh ? 'FRESH' : 'STALE',
			'availability_source' => (string) ($member['availability_source'] ?? 'UNKNOWN'),
			'availability_source_id' => (string) ($member['availability_source_id'] ?? 'unknown'),
			'transitions' => array_values(array_map('intval', $member['transitions'] ?? []))
		]);
	}

	private function requiredMembers(string $policy, int $total, mixed $min_n): int {
		$required = match ($policy) {
			'ANY_REQUIRED' => 1,
			'ALL_REQUIRED' => $total,
			'MAJORITY_REQUIRED' => intdiv($total, 2) + 1,
			'MIN_N_REQUIRED' => (int) $min_n,
			'UNCONFIGURED_SINGLE_MEMBER' => 1
		};
		if ($required < 1 || $required > $total) {
			throw new InvalidArgumentException("required Member count {$required} is outside 1..{$total}");
		}
		return $required;
	}

	private function criticality(mixed $value): string {
		$value = strtolower((string) $value);
		return in_array($value, ['tier1', 'tier2', 'tier3'], true) ? $value : 'tier3';
	}

	private function commonSourceId(array $members): string {
		$sources = array_values(array_unique(array_column($members, 'availability_source_id')));
		return count($sources) === 1 ? (string) $sources[0] : 'mixed';
	}

	private function resolveSites(array $nodes): array {
		$sites = [];
		foreach ($nodes as $node) {
			$sites[$node['site']][] = $node;
		}
		$result = [];
		foreach ($sites as $name => $site_nodes) {
			$active = array_values(array_filter($site_nodes,
				static fn(array $node): bool => !$node['maintenance'] && !$node['suppressed']
			));
			$states = array_column($active, 'actual_state');
			$visibility = array_column($active, 'visibility');
			if ($active === []) {
				$state = count(array_filter($site_nodes,
					static fn(array $node): bool => $node['suppressed'] && !$node['maintenance']
				)) > 0 ? 'SUPPRESSED' : 'MAINTENANCE';
			}
			elseif (in_array('DOWN', $states, true)) {
				$state = 'IMPACTED';
			}
			elseif (in_array('LOST', $visibility, true)) {
				$state = 'VISIBILITY_LOST';
			}
			elseif (array_intersect($states, ['DEGRADED', 'UNKNOWN']) !== [] || in_array('PARTIAL', $visibility, true)) {
				$state = 'DEGRADED';
			}
			else {
				$state = 'HEALTHY';
			}
			$result[] = [
				'name' => $name,
				'state' => $state,
				'nodes' => $site_nodes,
				'healthy' => count(array_filter($site_nodes,
					static fn(array $node): bool => $node['actual_state'] === 'UP' && $node['visibility'] === 'FULL'
				)),
				'total' => count($site_nodes)
			];
		}
		usort($result, static fn(array $a, array $b): int =>
			[$a['state'] === 'HEALTHY' ? 1 : 0, $a['name']] <=> [$b['state'] === 'HEALTHY' ? 1 : 0, $b['name']]
		);
		return $result;
	}

	private function massStaleIncidents(array $nodes, int $now): array {
		$site_totals = [];
		$lost_by_site = [];
		foreach ($nodes as $node) {
			if ($node['maintenance'] || $node['suppressed']) {
				continue;
			}
			$site_totals[$node['site']] = ($site_totals[$node['site']] ?? 0) + 1;
			if ($node['visibility'] !== 'LOST') {
				continue;
			}
			$lost_by_site[$node['site']][] = $node;
		}
		$groups = [];
		foreach ($lost_by_site as $site => $lost_nodes) {
			if (count($lost_nodes) === $site_totals[$site]) {
				$sources = array_values(array_unique(array_column($lost_nodes, 'availability_source_id')));
				$groups[$site . "\x1f" . (count($sources) === 1 ? $sources[0] : 'multiple')] = $lost_nodes;
				continue;
			}
			foreach ($lost_nodes as $node) {
				$groups[$site . "\x1f" . $node['availability_source_id']][] = $node;
			}
		}

		$incidents = [];
		foreach ($groups as $key => $affected) {
			[$site, $source] = explode("\x1f", $key, 2);
			$total = $site_totals[$site];
			$count = count($affected);
			$pct = $total > 0 ? ($count / $total) * 100 : 0;
			$starts = array_values(array_filter(array_column($affected, 'visibility_lost_at'), 'is_int'));
			$within_window = $starts !== [] && max($starts) - min($starts) <= Limits::MASS_STALE_WINDOW_S;
			$all_stale = $count === $total;
			if (!$all_stale && (!$within_window || $count < Limits::MASS_STALE_MIN_N
					|| $pct < Limits::MASS_STALE_THRESHOLD_PCT)) {
				continue;
			}
			$criticality = 'tier3';
			foreach ($affected as $node) {
				if ($this->tierNumber($node['criticality']) < $this->tierNumber($criticality)) {
					$criticality = $node['criticality'];
				}
			}
			$incidents[] = $this->incident([
				'id' => 'visibility:' . hash('sha256', $key),
				'name' => 'Monitoring visibility lost',
				'site' => $site,
				'state' => 'VISIBILITY_LOST',
				'criticality' => $criticality,
				'event_since' => $starts === [] ? $now : min($starts),
				'impact' => $count,
				'source_id' => $source,
				'affected_nodes' => $count,
				'affected_node_ids' => array_column($affected, 'id'),
				'affected_pct' => round($pct, 1),
				'dependency_suppressed' => false,
				'maintenance' => false,
				'suppressed' => false,
				'flapping' => false
			]);
		}
		return $incidents;
	}

	private function nodeIncidentCandidates(array $nodes, array $covered_visibility_nodes): array {
		$result = [];
		foreach ($nodes as $node) {
			$state = $node['visibility'] === 'LOST' ? 'VISIBILITY_LOST' : $node['actual_state'];
			if ($state === 'VISIBILITY_LOST' && isset($covered_visibility_nodes[$node['id']])) {
				continue;
			}
			if ($state === 'UP') {
				continue;
			}
			$result[] = $this->incident($node + [
				'state' => $state,
				'source_id' => $node['availability_source_id']
			]);
		}
		return $result;
	}

	private function incident(array $source): array {
		$priority = $this->priority($source['criticality'], $source['state']);
		return $source + [
			'priority' => $priority,
			'hero_eligible' => $priority !== null && !$source['maintenance'] && !$source['suppressed']
				&& !$source['dependency_suppressed']
		];
	}

	private function priority(string $criticality, string $state): ?int {
		return match ($criticality . ':' . $state) {
			'tier1:DOWN', 'tier1:UNKNOWN', 'tier1:VISIBILITY_LOST' => 1,
			'tier1:DEGRADED', 'tier2:DOWN', 'tier2:UNKNOWN', 'tier2:VISIBILITY_LOST' => 2,
			'tier2:DEGRADED', 'tier3:DOWN', 'tier3:UNKNOWN', 'tier3:VISIBILITY_LOST' => 3,
			'tier3:DEGRADED' => 4,
			default => null
		};
	}

	private function selectHero(array $candidates, ?array $current, int $now): ?array {
		$eligible = array_values(array_filter($candidates, static fn(array $candidate): bool => $candidate['hero_eligible']));
		usort($eligible, [$this, 'compareIncidents']);
		if ($eligible === []) {
			return null;
		}
		$best = $eligible[0];
		if ($current === null || !isset($current['id'], $current['selected_at'])) {
			return $best + ['selected_at' => $now];
		}
		$active = null;
		foreach ($eligible as $candidate) {
			if ($candidate['id'] === $current['id']) {
				$active = $candidate;
				break;
			}
		}
		if ($active === null || $best['priority'] < $active['priority']
				|| $now - (int) $current['selected_at'] >= Limits::HERO_DWELL_S) {
			return $best + ['selected_at' => $now];
		}
		return $active + ['selected_at' => (int) $current['selected_at']];
	}

	private function compareIncidents(array $a, array $b): int {
		return [
			$a['priority'] ?? 99,
			-($a['impact'] ?? 0),
			$a['event_since'] ?? PHP_INT_MAX,
			$a['site'] ?? '',
			$a['name'] ?? '',
			$a['id']
		] <=> [
			$b['priority'] ?? 99,
			-($b['impact'] ?? 0),
			$b['event_since'] ?? PHP_INT_MAX,
			$b['site'] ?? '',
			$b['name'] ?? '',
			$b['id']
		];
	}

	private function tierNumber(string $criticality): int {
		return (int) substr($criticality, -1);
	}
}
