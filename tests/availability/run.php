<?php declare(strict_types = 1);

use Modules\NetworkAvailability\Domain\AvailabilityResolver;
use Modules\NetworkAvailability\Domain\ExpectedIntervalResolver;

require_once __DIR__ . '/../../frontend/modules/NetworkAvailability/config/Limits.php';
require_once __DIR__ . '/../../frontend/modules/NetworkAvailability/domain/AvailabilityResolver.php';
require_once __DIR__ . '/../../frontend/modules/NetworkAvailability/domain/ExpectedIntervalResolver.php';

if (!class_exists('CMacrosResolverHelper')) {
	class CMacrosResolverHelper {
		public static function resolveTimeUnitMacros(array $items, array $fields): array {
			foreach ($items as &$item) {
				if (($item['delay'] ?? '') === '{$RESOLVED.INTERVAL}') {
					$item['delay'] = '45s';
				}
			}
			unset($item);
			return $items;
		}
	}
}

$now = 2_000_000_000;
$tests = 0;

function check(bool $condition, string $message): void {
	global $tests;
	$tests++;
	if (!$condition) {
		throw new RuntimeException("FAIL: {$message}");
	}
}

function member(string $id, string $state, int $age = 10, array $extra = []): array {
	global $now;
	return $extra + [
		'id' => $id,
		'name' => $id,
		'hostid' => $id,
		'raw_availability_state' => $state,
		'last_success' => $now - $age,
		'expected_interval' => 60,
		'availability_source' => 'SNMP',
		'availability_source_id' => 'proxy-dc01',
		'transitions' => []
	];
}

function node(string $id, array $members, string $policy = 'MIN_N_REQUIRED', int $min_n = 1,
		array $extra = []): array {
	return $extra + [
		'id' => $id,
		'name' => $id,
		'site' => 'DC-01',
		'kind' => count($members) === 1 ? 'host' : 'cluster',
		'criticality' => 'tier2',
		'policy' => $policy,
		'min_n' => $min_n,
		'members' => $members,
		'event_since' => 1_999_999_000
	];
}

function resolved(array $node): array {
	global $now;
	return (new AvailabilityResolver())->resolveNode($node, $now);
}

// Basic host and stale truth.
check(resolved(node('single-up', [member('a', 'UP')], 'ANY_REQUIRED'))['actual_state'] === 'UP',
	'single fresh UP resolves UP');
check(resolved(node('single-down', [member('a', 'DOWN')], 'ANY_REQUIRED'))['actual_state'] === 'DOWN',
	'single fresh DOWN resolves DOWN');
check(resolved(node('any-multi', [member('a', 'UP'), member('b', 'DOWN')], 'ANY_REQUIRED'))['actual_state']
	=== 'DEGRADED', 'ANY_REQUIRED remains available but degraded when a fresh Member is down');
check(resolved(node('all-multi', [member('a', 'UP'), member('b', 'DOWN')], 'ALL_REQUIRED'))['actual_state']
	=== 'DOWN', 'ALL_REQUIRED fails when any fresh Member is down');
$stale = resolved(node('single-stale', [member('a', 'UP', 181)], 'ANY_REQUIRED'));
check($stale['actual_state'] === 'UNKNOWN' && $stale['visibility'] === 'LOST',
	'last-known UP stale is UNKNOWN/LOST, never trustworthy UP');

// HA pair, fresh and stale combinations.
$ha = resolved(node('ha-up', [member('a', 'UP'), member('b', 'UP')]));
check($ha['actual_state'] === 'UP' && $ha['visibility'] === 'FULL', '2/2 UP MIN_N(1) is UP/FULL');
$ha = resolved(node('ha-degraded', [member('a', 'UP'), member('b', 'DOWN')]));
check($ha['actual_state'] === 'DEGRADED' && $ha['visibility'] === 'FULL', '1 UP + 1 DOWN is DEGRADED/FULL');
check(resolved(node('ha-down', [member('a', 'DOWN'), member('b', 'DOWN')]))['actual_state'] === 'DOWN',
	'0 UP + 2 DOWN is DOWN');
$ha_stale = resolved(node('ha-stale', [member('a', 'UP'), member('b', 'UP', 181)]));
check($ha_stale['actual_state'] === 'UP' && $ha_stale['visibility'] === 'PARTIAL',
	'1 UP + 1 stale MIN_N(1) is UP/PARTIAL, not degraded');

// Majority cluster certainty.
check(resolved(node('c3-up', [member('a', 'UP'), member('b', 'UP'), member('c', 'UP')],
	'MAJORITY_REQUIRED'))['actual_state'] === 'UP', '3/3 majority is UP');
check(resolved(node('c3-degraded', [member('a', 'UP'), member('b', 'UP'), member('c', 'DOWN')],
	'MAJORITY_REQUIRED'))['actual_state'] === 'DEGRADED', '2 UP + 1 DOWN majority is DEGRADED');
check(resolved(node('c3-down', [member('a', 'UP'), member('b', 'DOWN'), member('c', 'DOWN')],
	'MAJORITY_REQUIRED'))['actual_state'] === 'DOWN', '1 UP + 2 DOWN majority is DOWN');
$cluster = resolved(node('c3-partial-up', [member('a', 'UP'), member('b', 'UP'), member('c', 'UP', 181)],
	'MAJORITY_REQUIRED'));
check($cluster['actual_state'] === 'UP' && $cluster['visibility'] === 'PARTIAL',
	'2 UP + 1 stale confirms majority with PARTIAL visibility');
$cluster = resolved(node('c3-unknown', [member('a', 'UP'), member('b', 'UP', 181), member('c', 'UP', 181)],
	'MAJORITY_REQUIRED'));
check($cluster['actual_state'] === 'UNKNOWN' && $cluster['visibility'] === 'PARTIAL',
	'1 UP + 2 stale cannot confirm or fail majority');

// Overlays remain separate and exclude Hero eligibility.
$resolver = new AvailabilityResolver();
$maintenance = node('maint-down', [member('a', 'DOWN')], 'ANY_REQUIRED', 1,
	['criticality' => 'tier1', 'maintenance' => true]);
$snapshot = $resolver->resolve([$maintenance], $now);
check($snapshot['sites'][0]['nodes'][0]['actual_state'] === 'DOWN' && $snapshot['hero'] === null
	&& $snapshot['secondary'] === [] && $snapshot['sites'][0]['state'] === 'MAINTENANCE'
	&& $snapshot['summary']['IMPACTED_SITES'] === 0,
	'maintenance preserves DOWN without Hero, secondary, or impacted-Site escalation');
$suppressed = node('suppressed-down', [member('a', 'DOWN')], 'ANY_REQUIRED', 1,
	['criticality' => 'tier1', 'suppressed' => true]);
$suppressed_snapshot = $resolver->resolve([$suppressed], $now);
check($suppressed_snapshot['hero'] === null && $suppressed_snapshot['secondary'] === []
	&& $suppressed_snapshot['sites'][0]['state'] === 'SUPPRESSED'
	&& $suppressed_snapshot['summary']['IMPACTED_SITES'] === 0,
	'suppressed Node remains visible without Hero, secondary, or impacted-Site escalation');

// Hero priority and dwell.
$tier1_lost = node('tier1-lost', [member('a', 'UP', 181)], 'ANY_REQUIRED', 1, ['criticality' => 'tier1']);
$tier3_down = node('tier3-down', [member('b', 'DOWN')], 'ANY_REQUIRED', 1, ['criticality' => 'tier3']);
$hero = $resolver->resolve([$tier3_down, $tier1_lost], $now)['hero'];
check($hero['id'] === 'tier1-lost' && $hero['priority'] === 1, 'Tier-1 visibility loss beats Tier-3 DOWN');
$equal_a = node('a-down', [member('a', 'DOWN')], 'ANY_REQUIRED', 1, ['criticality' => 'tier2']);
$equal_b = node('b-down', [member('b', 'DOWN')], 'ANY_REQUIRED', 1, ['criticality' => 'tier2', 'impact' => 99]);
$hero = $resolver->resolve([$equal_a, $equal_b], $now, ['id' => 'a-down', 'selected_at' => $now - 10])['hero'];
check($hero['id'] === 'a-down', 'equal-priority active Hero remains during dwell');
$higher = node('higher-down', [member('c', 'DOWN')], 'ANY_REQUIRED', 1, ['criticality' => 'tier1']);
$hero = $resolver->resolve([$equal_a, $higher], $now, ['id' => 'a-down', 'selected_at' => $now - 10])['hero'];
check($hero['id'] === 'higher-down', 'higher-priority incident overrides active Hero dwell');

// Flapping.
$flap_times = [$now - 290, $now - 200, $now - 100, $now - 1];
$flapping = resolved(node('flap', [member('a', 'UP', 10, ['transitions' => $flap_times])], 'ANY_REQUIRED'));
check($flapping['flapping'] === true, 'transition threshold marks flapping');
$not_flapping = resolved(node('not-flap', [
	member('a', 'UP', 10, ['transitions' => [$now - 100, $now - 50]]),
	member('b', 'UP', 10, ['transitions' => [$now - 90, $now - 40]])
], 'ANY_REQUIRED'));
check($not_flapping['flapping'] === false,
	'unrelated sub-threshold Member transitions are not summed into false Node flapping');
$ordered = $resolver->resolve([
	node('order-late', [member('a', 'UP')], 'ANY_REQUIRED', 1, ['order' => 20]),
	node('order-first', [member('b', 'UP')], 'ANY_REQUIRED', 1, ['order' => 10])
], $now);
check(array_column($ordered['sites'][0]['nodes'], 'id') === ['order-first', 'order-late'],
	'explicit Node order remains deterministic across refreshes');

// Mass stale: one Site incident, individual Nodes remain inspectable but not independent candidates.
$mass = [];
for ($i = 0; $i < 6; $i++) {
	$mass[] = node("mass-{$i}", [member("m{$i}", 'UP', 181 + $i)], 'ANY_REQUIRED', 1,
		['criticality' => 'tier1']);
}
$mass_snapshot = $resolver->resolve($mass, $now);
check(count($mass_snapshot['mass_stale_incidents']) === 1, 'shared-source mass stale creates one Site incident');
check($mass_snapshot['hero']['id'] === $mass_snapshot['mass_stale_incidents'][0]['id'],
	'mass visibility incident is the Hero');
check(count($mass_snapshot['sites'][0]['nodes']) === 6 && count($mass_snapshot['secondary']) === 0,
	'affected Nodes remain inspectable under Site, not independent top-level incidents');

$small = [
	node('small-a', [member('a', 'UP', 181, ['availability_source_id' => 'proxy-a'])], 'ANY_REQUIRED'),
	node('small-b', [member('b', 'UP', 181, ['availability_source_id' => 'proxy-b'])], 'ANY_REQUIRED')
];
$small_snapshot = $resolver->resolve($small, $now);
check(count($small_snapshot['mass_stale_incidents']) === 1
	&& $small_snapshot['mass_stale_incidents'][0]['source_id'] === 'multiple',
	'all-stale small Site aggregates even below min N and across sources');

// Configuration validation and debt.
$bad_majority = node('bad-majority', [member('a', 'UP'), member('b', 'UP')], 'MAJORITY_REQUIRED');
$bad = $resolver->resolve([$bad_majority], $now);
check($bad['sites'] === [] && str_contains($bad['warnings'][0], 'explicit override'),
	'two-Member majority is rejected without explicit override');
$unclassified = resolved([
	'id' => 'u1', 'name' => 'host-x', 'site' => 'UNCLASSIFIED', 'kind' => null, 'policy' => null,
	'configuration_required' => true, 'configuration_missing' => ['site', 'Node mapping'],
	'criticality' => 'tier3', 'members' => [member('x', 'UP')]
]);
check($unclassified['actual_state'] === 'UP' && $unclassified['configuration_required']
	&& $unclassified['policy'] === 'UNCONFIGURED_SINGLE_MEMBER' && $unclassified['kind'] === null,
	'unclassified Host shows truth without fabricating kind or production policy');

// Services never override Member truth; dependency-suppressed child is inspectable but not Hero.
$service_conflict = node('service-ok-stale', [member('a', 'UP', 181)], 'ANY_REQUIRED', 1,
	['service_status' => 'OK', 'criticality' => 'tier1']);
check($resolver->resolve([$service_conflict], $now)['sites'][0]['nodes'][0]['actual_state'] === 'UNKNOWN',
	'Service OK cannot override stale Member truth');
$parented = node('dependent-child', [member('a', 'DOWN')], 'ANY_REQUIRED', 1,
	['criticality' => 'tier1', 'dependency_suppressed' => true]);
$dependency_snapshot = $resolver->resolve([$parented], $now);
check($dependency_snapshot['hero'] === null
	&& $dependency_snapshot['sites'][0]['nodes'][0]['actual_state'] === 'DOWN',
	'dependency-suppressed child remains inspectable but is not independently Hero');

// Expected interval safety.
$intervals = new ExpectedIntervalResolver();
check($intervals->resolve(['delay' => '30s'])['seconds'] === 30, 'fixed seconds resolve');
check($intervals->resolve(['delay' => '5m'])['seconds'] === 300, 'fixed suffixed interval resolves');
check($intervals->resolve(['delay' => '{$RESOLVED.INTERVAL}'])['seconds'] === 45,
	'frontend macro resolver may supply a fixed effective interval');
check($intervals->resolve(['delay' => '{$PING.INTERVAL}'])['seconds'] === null,
	'unresolved macro never invents an interval');
check($intervals->resolve(['delay' => '1m;30s/1-5,09:00-18:00'])['seconds'] === null,
	'flexible interval requires explicit configuration');
check($intervals->resolve(['delay' => '{$PING.INTERVAL}'], 45)['seconds'] === 45,
	'central Member fallback resolves otherwise unsafe effective interval');

$invalid_raw = resolved(node('invalid-raw', [member('a', 'BROKEN')], 'ANY_REQUIRED'));
check($invalid_raw['actual_state'] === 'UNKNOWN' && $invalid_raw['members'][0]['raw_availability_state'] === 'UNKNOWN',
	'invalid raw Member state is normalized to UNKNOWN');

printf("PASS: %d Availability v1 assertions\n", $tests);
