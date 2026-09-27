<?php declare(strict_types = 1);

use Modules\NetworkAvailability\Config\NodeDefinitionRepository;

require_once __DIR__ . '/../../frontend/modules/NetworkAvailability/config/NodeDefinitionRepository.php';

$tests = 0;
function assert_config(bool $condition, string $message): void {
	global $tests;
	$tests++;
	if (!$condition) {
		throw new RuntimeException("FAIL: {$message}");
	}
}

$directory = sys_get_temp_dir() . '/network-availability-' . bin2hex(random_bytes(6));
if (!mkdir($directory, 0750, true)) {
	throw new RuntimeException('Unable to create temporary configuration directory');
}
$path = $directory . '/node-definitions.json';
$initial = [
	'schema' => NodeDefinitionRepository::SCHEMA,
	'revision' => 1,
	'sites' => [],
	'nodes' => []
];
file_put_contents($path, json_encode($initial, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR));
$repository = new NodeDefinitionRepository($path);

try {
	assert_config($repository->loadDocument() === $initial, 'empty schema-v2 document loads');

	$quick_assign = $initial;
	$quick_assign['sites'][] = ['id' => 'cnt-dc', 'name' => 'CNT-DC', 'order' => 10];
	$quick_assign['nodes'][] = [
		'id' => 'dr-fw01', 'name' => 'DR Firewall', 'site_id' => 'cnt-dc', 'kind' => 'host',
		'aggregation_policy' => 'ANY_REQUIRED', 'criticality' => 'tier1', 'order' => 10,
		'hidden' => false, 'description' => '',
		'members' => [['id' => 'dr-fw01-member', 'name' => 'DR-FW01', 'host' => 'DR-FW01']]
	];
	$saved = $repository->save($quick_assign, 1);
	assert_config($saved['revision'] === 2 && $repository->loadDocument()['nodes'][0]['name'] === 'DR Firewall',
		'Quick Assign persists after reload');
	assert_config(is_file($directory . '/node-definitions.last-known-good.json'),
		'atomic save preserves last-known-good configuration');
	assert_config(glob($directory . '/.node-definitions.*.tmp') === [], 'atomic save leaves no staged file');

	$edited = $saved;
	$edited['sites'][0]['name'] = 'CNT-DC-RENAMED';
	$edited['sites'][0]['order'] = 30;
	$edited['nodes'][0]['name'] = 'DR Firewall Renamed';
	$edited['nodes'][0]['order'] = 40;
	$edited['nodes'][0]['hidden'] = true;
	$saved = $repository->save($edited, 2);
	$reloaded = $repository->loadDocument();
	assert_config($reloaded['sites'][0]['name'] === 'CNT-DC-RENAMED', 'Site rename persists');
	assert_config($reloaded['nodes'][0]['name'] === 'DR Firewall Renamed', 'Node rename persists');
	assert_config($reloaded['sites'][0]['order'] === 30 && $reloaded['nodes'][0]['order'] === 40,
		'Site and Node order persist');
	assert_config($reloaded['nodes'][0]['hidden'] === true, 'hidden layout state persists');

	$invalid = $saved;
	$invalid['nodes'][0]['criticality'] = '';
	$before = hash_file('sha256', $path);
	try {
		$repository->save($invalid, 3);
		assert_config(false, 'Tier-less configuration must be rejected');
	}
	catch (RuntimeException $exception) {
		assert_config(str_contains($exception->getMessage(), 'Tier'), 'Tier is mandatory during assignment');
	}
	assert_config(hash_file('sha256', $path) === $before, 'invalid configuration cannot replace valid configuration');

	file_put_contents($path, '{"schema":"network-availability-config-v2","revision":3,"sites":[],"nodes":[BROKEN');
	$fallback = $repository->loadDocument();
	assert_config($fallback['revision'] === 2 && $repository->warnings() !== [],
		'malformed live configuration falls back without destroying the dashboard');
}
finally {
	foreach (glob($directory . '/*') ?: [] as $file) {
		unlink($file);
	}
	foreach (glob($directory . '/.*') ?: [] as $file) {
		if (is_file($file)) unlink($file);
	}
	rmdir($directory);
}

printf("PASS: %d Availability configuration assertions\n", $tests);
