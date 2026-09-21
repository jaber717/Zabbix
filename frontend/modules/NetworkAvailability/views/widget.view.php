<?php declare(strict_types = 1);

/** @var CView $this */
/** @var array $data */

$root = (new CDiv())->addClass('netops-availability');
if ($data['error'] !== null) {
	$root->addItem((new CDiv([
		(new CSpan(_('Availability data unavailable')))->addClass('na-error__title'),
		new CSpan($data['error'])
	]))->addClass('na-error'));
	(new CWidgetView($data))->addItem($root)->show();
	return;
}

$snapshot = $data['snapshot'];
$hero = $snapshot['hero'];
$root
	->setAttribute('data-hero-id', $hero['id'] ?? '')
	->setAttribute('data-hero-selected-at', (string) ($hero['selected_at'] ?? ''));

$summary = (new CDiv())->addClass('na-summary');
foreach ([
	'UP' => 'UP',
	'DOWN' => 'DOWN',
	'DEGRADED' => 'DEGRADED',
	'UNKNOWN' => 'UNKNOWN',
	'VISIBILITY_LOSS' => 'VISIBILITY LOSS',
	'MAINTENANCE' => 'MAINTENANCE',
	'IMPACTED_SITES' => 'IMPACTED SITES'
] as $key => $label) {
	$summary->addItem((new CDiv([
		(new CSpan((string) $snapshot['summary'][$key]))->addClass('na-summary__count'),
		(new CSpan($label))->addClass('na-summary__label')
	]))->addClass('na-summary__tile')->addClass('is-' . strtolower(str_replace('_', '-', $key))));
}
$root->addItem($summary);

$duration = static function(?int $since) use ($snapshot): string {
	if ($since === null) {
		return 'Unknown duration';
	}
	$seconds = max(0, $snapshot['generated_at'] - $since);
	return $seconds >= 3600 ? sprintf('%dh %02dm', intdiv($seconds, 3600), intdiv($seconds % 3600, 60))
		: ($seconds >= 60 ? sprintf('%dm %02ds', intdiv($seconds, 60), $seconds % 60) : "{$seconds}s");
};

if ($hero !== null) {
	$hero_card = (new CDiv())->addClass('na-hero')->addClass('is-p' . $hero['priority']);
	$hero_card->addItem((new CSpan('P' . $hero['priority']))->addClass('na-hero__priority'));
	$hero_card->addItem((new CDiv($hero['state']))->addClass('na-hero__state'));
	$hero_card->addItem((new CDiv($hero['name']))->addClass('na-hero__name'));
	$hero_card->addItem((new CDiv($hero['site']))->addClass('na-hero__site'));
	$details = [$hero['criticality'], $duration($hero['event_since'] ?? null)];
	if (isset($hero['affected_nodes'])) {
		$details[] = $hero['affected_nodes'] . ' affected Nodes';
		$details[] = $hero['affected_pct'] . '% visibility loss';
		$details[] = 'Source: ' . $hero['source_id'];
	}
	$hero_card->addItem((new CDiv(implode(' · ', $details)))->addClass('na-hero__meta'));
	$root->addItem($hero_card);
}

if ($snapshot['secondary'] !== []) {
	$secondary = (new CDiv())->addClass('na-secondary');
	foreach ($snapshot['secondary'] as $incident) {
		$secondary->addItem((new CDiv([
			(new CSpan('P' . $incident['priority']))->addClass('na-secondary__priority'),
			(new CSpan($incident['name']))->addClass('na-secondary__name'),
			new CSpan($incident['site']),
			new CSpan($incident['state']),
			new CSpan($incident['criticality'])
		]))->addClass('na-secondary__item'));
	}
	$root->addItem($secondary);
}

$member_dot = static function(array $member): CSpan {
	if (!$member['fresh'] || $member['raw_availability_state'] === 'UNKNOWN') {
		return (new CSpan('◌'))->addClass('is-unknown')->setTitle($member['name'] . ': stale / unknown');
	}
	if ($member['raw_availability_state'] === 'DOWN') {
		return (new CSpan('○'))->addClass('is-down')->setTitle($member['name'] . ': down');
	}
	return (new CSpan('●'))->addClass('is-up')->setTitle($member['name'] . ': up');
};

$sites = (new CDiv())->addClass('na-sites');
foreach ($snapshot['sites'] as $site) {
	$open = !in_array($site['state'], ['HEALTHY', 'MAINTENANCE', 'SUPPRESSED'], true);
	$site_box = (new CDiv())
		->addClass('na-site')
		->addClass($open ? 'is-open' : 'is-collapsed')
		->setAttribute('data-site-id', hash('sha256', $site['name']))
		->setAttribute('data-default-open', $open ? '1' : '0');
	$site_box->addItem((new CTag('button', true, [
		(new CSpan($open ? '▼' : '▶'))->addClass('na-site__chevron'),
		(new CSpan($site['name']))->addClass('na-site__name'),
		new CSpan($site['state']),
		new CSpan($site['healthy'] . '/' . $site['total'] . ' Healthy')
	]))->addClass('na-site__header')->setAttribute('type', 'button'));
	$node_list = (new CDiv())->addClass('na-site__nodes');
	foreach ($site['nodes'] as $node) {
		$card = (new CDiv())->addClass('na-node')->addClass('is-' . strtolower($node['actual_state']));
		$card->addItem((new CDiv([
			(new CSpan($node['name']))->addClass('na-node__name'),
			new CSpan($node['kind'] ?? 'UNCLASSIFIED'),
			(new CSpan($node['actual_state']))->addClass('na-node__state'),
			new CSpan('Visibility: ' . $node['visibility'])
		]))->addClass('na-node__heading'));
		if ($node['configuration_required']) {
			$card->addItem((new CDiv([
				(new CSpan('UNCLASSIFIED'))->addClass('na-config__label'),
				new CSpan('Configuration required · Missing: ' . implode(' / ', $node['configuration_missing']))
			]))->addClass('na-config'));
		}
		$dots = (new CDiv())->addClass('na-members');
		foreach ($node['members'] as $member) {
			$dots->addItem($member_dot($member));
		}
		$dots->addItem(new CSpan(sprintf('%d up / %d down / %d unknown',
			$node['known_up'], $node['known_down'], $node['unknown_members']
		)));
		$card->addItem($dots);
		$fresh_members = count(array_filter($node['members'],
			static fn(array $member): bool => $member['fresh']
		));
		$badges = [];
		foreach (['maintenance' => 'MAINT', 'suppressed' => 'SUPPRESSED', 'flapping' => 'FLAPPING'] as $key => $label) {
			if ($node[$key]) {
				$badges[] = (new CSpan($label))->addClass('na-badge');
			}
		}
		$card->addItem((new CDiv([
			new CSpan($node['criticality']),
			new CSpan($node['policy'] . ' (' . $node['required_members'] . ' required)'),
			new CSpan(sprintf('Freshness: %d/%d fresh', $fresh_members, count($node['members']))),
			new CSpan($duration($node['event_since'])),
			new CSpan('Source: ' . $node['availability_source_id']),
			...$badges
		]))->addClass('na-node__meta'));
		if ($node['hostids'] !== []) {
			$url = (new CUrl('zabbix.php'))->setArgument('action', 'problem.view')
				->setArgument('filter_set', '1')->setArgument('hostids', $node['hostids']);
			$card->addItem((new CLink(_('Problems'), $url->getUrl()))->addClass('na-node__action'));
		}
		$node_list->addItem($card);
	}
	$site_box->addItem($node_list);
	$sites->addItem($site_box);
}
$root->addItem($sites);

if ($snapshot['warnings'] !== []) {
	$warnings = (new CList())->addClass('na-warnings');
	foreach ($snapshot['warnings'] as $warning) {
		$warnings->addItem($warning);
	}
	$root->addItem((new CDiv([new CSpan(_('Configuration / collection warnings')), $warnings]))->addClass('na-warning-box'));
}

if ($data['user']['debug_mode']) {
	$root->addItem((new CDiv('Availability instrumentation: ' . json_encode($data['instrumentation'], JSON_THROW_ON_ERROR)))
		->addClass('na-debug'));
}

(new CWidgetView($data))->addItem($root)->show();
