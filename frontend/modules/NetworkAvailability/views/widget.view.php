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
$encode = static fn(array $value): string => base64_encode(json_encode($value,
	JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR
));
$root
	->setAttribute('data-hero-id', $hero['id'] ?? '')
	->setAttribute('data-hero-selected-at', (string) ($hero['selected_at'] ?? ''))
	->setAttribute('data-generated-at', (string) $snapshot['generated_at'])
	->setAttribute('data-refresh-seconds', '30')
	->setAttribute('data-can-edit', $data['user']['can_edit'] ? '1' : '0')
	->setAttribute('data-csrf-token', (string) ($data['user']['csrf_token'] ?? ''))
	->setAttribute('data-snapshot', $encode($snapshot))
	->setAttribute('data-configuration', $encode($data['configuration']))
	->setAttribute('data-available-hosts', $encode($data['available_hosts']))
	->setAttribute('data-instrumentation', $encode($data['instrumentation']));

$duration = static function(?int $since) use ($snapshot): string {
	if ($since === null) {
		return 'Unknown duration';
	}
	$seconds = max(0, $snapshot['generated_at'] - $since);
	if ($seconds >= 86400) {
		return sprintf('%dd %dh', intdiv($seconds, 86400), intdiv($seconds % 86400, 3600));
	}
	return $seconds >= 3600 ? sprintf('%dh %02dm', intdiv($seconds, 3600), intdiv($seconds % 3600, 60))
		: ($seconds >= 60 ? sprintf('%dm', intdiv($seconds, 60)) : "{$seconds}s");
};
$tier = static fn(?string $value): string => $value === null ? 'Tier not set'
	: 'Tier-' . substr($value, -1);
$member_dots = static function(array $node): string {
	if (count($node['members']) > 6) {
		return sprintf('%d / %d members available', $node['known_up'], count($node['members']));
	}
	$dots = '';
	foreach ($node['members'] as $member) {
		$dots .= !$member['fresh'] || $member['raw_availability_state'] === 'UNKNOWN' ? '◌'
			: ($member['raw_availability_state'] === 'DOWN' ? '○' : '●');
	}
	return $dots;
};

$stale_banner = (new CDiv([
	(new CSpan('Monitoring view is not updating'))->addClass('na-stale-view__title'),
	new CSpan('Last successful update: '),
	(new CSpan('—'))->addClass('na-stale-view__age')
]))->addClass('na-stale-view')->addClass('is-hidden');
$root->addItem($stale_banner);

$toolbar = (new CDiv())->addClass('na-toolbar');
$toolbar->addItem((new CTag('input', false))
	->setAttribute('type', 'search')->setAttribute('placeholder', 'Search Nodes or Hosts')
	->setAttribute('aria-label', 'Search Nodes or Hosts')->addClass('na-search'));
$toolbar->addItem((new CDiv([
	(new CSpan(''))->addClass('na-filter-chip__label'),
	(new CTag('button', true, 'Clear'))->setAttribute('type', 'button')->addClass('na-filter-clear')
]))->addClass('na-filter-chip')->addClass('is-hidden'));
if ($data['user']['can_edit']) {
	$toolbar->addItem((new CTag('button', true, 'Edit sites'))->setAttribute('type', 'button')
		->addClass('btn-alt')->addClass('na-edit-start'));
}
$root->addItem($toolbar);

$summary = (new CDiv())->addClass('na-summary');
foreach ([
	'DOWN' => 'DOWN', 'DEGRADED' => 'DEGRADED', 'UNKNOWN' => 'UNKNOWN',
	'VISIBILITY_LOSS' => 'VISIBILITY LOSS', 'MAINTENANCE' => 'MAINTENANCE',
	'UP' => 'UP', 'IMPACTED_SITES' => 'IMPACTED SITES'
] as $key => $label) {
	$count = (int) $snapshot['summary'][$key];
	$tile = (new CTag('button', true, [
		(new CSpan((string) $count))->addClass('na-summary__count'),
		(new CSpan($label))->addClass('na-summary__label')
	]))->addClass('na-summary__tile')->addClass('is-' . strtolower(str_replace('_', '-', $key)))
		->addClass($count === 0 ? 'is-zero' : 'is-active')
		->setAttribute('type', 'button')->setAttribute('data-filter', $key)
		->setAttribute('aria-pressed', 'false');
	if ($count === 0) {
		$tile->setAttribute('disabled', 'disabled');
	}
	$summary->addItem($tile);
}
$root->addItem($summary);

$attention = (new CDiv())->addClass('na-attention');
$attention->addItem((new CDiv('Needs attention'))->addClass('na-section-title'));
if ($snapshot['needs_attention'] === []) {
	$attention->addItem((new CDiv('All monitored nodes are up · last evaluated just now'))
		->addClass('na-all-clear'));
}
else {
	foreach ($snapshot['needs_attention'] as $index => $incident) {
		$problem_count = count($incident['problems'] ?? []);
		$meta = ($incident['site'] ?? 'Unassigned') . ' · ' . $tier($incident['criticality'] ?? null);
		$row = (new CTag('button', true, [
			(new CSpan('P' . $incident['priority']))->addClass('na-attention__priority'),
			(new CSpan($incident['state']))->addClass('na-attention__state'),
			(new CSpan($incident['name']))->addClass('na-attention__name')->setTitle($incident['name']),
			(new CSpan($meta))->addClass('na-attention__meta'),
			(new CSpan(isset($incident['members']) && count($incident['members']) > 1 ? $member_dots($incident) : ''))
				->addClass('na-attention__members'),
			(new CSpan($duration($incident['event_since'] ?? null)))->addClass('na-attention__duration'),
			(new CSpan($problem_count > 0 ? (($incident['acknowledged'] ?? false) ? 'Acknowledged' : 'Unacknowledged') : ''))
				->addClass('na-attention__ack')
		]))->setAttribute('type', 'button')->addClass('na-attention__row')
			->addClass('is-' . strtolower($incident['state']))
			->setAttribute('data-node-id', (string) $incident['id']);
		if ($index >= 4) {
			$row->addClass('is-extra')->addClass('is-hidden');
		}
		$attention->addItem($row);
	}
	if (count($snapshot['needs_attention']) > 4) {
		$attention->addItem((new CTag('button', true, '+' . (count($snapshot['needs_attention']) - 4) . ' more'))
			->setAttribute('type', 'button')->addClass('na-attention-more'));
	}
}
$root->addItem($attention);

$render_node = static function(array $node) use ($member_dots, $duration, $tier): CDiv {
	$is_healthy = $node['actual_state'] === 'UP' && $node['visibility'] === 'FULL'
		&& !$node['maintenance'] && !$node['suppressed'];
	$card = (new CDiv())->addClass('na-node')->addClass('is-' . strtolower($node['actual_state']))
		->addClass($is_healthy ? 'is-healthy' : 'is-problem')
		->addClass($node['hidden'] ? 'is-config-hidden' : '')
		->setAttribute('data-node-id', $node['id'])
		->setAttribute('data-state', $node['actual_state'])
		->setAttribute('data-visibility', $node['visibility'])
		->setAttribute('data-search', strtolower($node['name'] . ' ' . implode(' ', array_column($node['members'], 'host'))));
	$heading = (new CDiv([
		(new CSpan($node['name']))->addClass('na-node__name')->setTitle($node['name']),
		(new CSpan($is_healthy ? '' : $node['actual_state']))->addClass('na-node__state')
	]))->addClass('na-node__heading');
	$card->addItem($heading);
	if (!$is_healthy) {
		$card->addItem((new CDiv([
			new CSpan($tier($node['criticality'])),
			(new CSpan($member_dots($node)))->addClass('na-members__dots')
		]))->addClass('na-node__status-line'));
		$problem_member = null;
		foreach ($node['members'] as $member) {
			if (!$member['fresh'] || $member['raw_availability_state'] !== 'UP') {
				$problem_member = $member;
				break;
			}
		}
		if ($problem_member !== null) {
			$card->addItem((new CDiv(sprintf('%s member: %s · %s%s',
				$problem_member['fresh'] ? $problem_member['raw_availability_state'] : 'STALE',
				$problem_member['name'], $duration($node['event_since']),
				count($node['problems']) > 0 ? ' · ' . ($node['acknowledged'] ? 'Acknowledged' : 'Unacknowledged') : ''
			)))->addClass('na-node__problem-line'));
		}
	}
	elseif ($node['criticality'] === 'tier1') {
		$card->addItem((new CSpan('Tier-1'))->addClass('na-node__tier'));
	}
	return $card;
};

$affected_sites = (new CDiv())->addClass('na-sites')->addClass('na-affected-sites');
$affected_sites->addItem((new CDiv('Affected sites'))->addClass('na-section-title'));
$healthy_sites = [];
$unassigned = null;
foreach ($snapshot['sites'] as $site) {
	if ($site['id'] === '__unassigned__') {
		$unassigned = $site;
		continue;
	}
	$healthy = $site['state'] === 'HEALTHY';
	if ($healthy) {
		$healthy_sites[] = $site;
	}
	$problem_parts = [];
	foreach (['down' => 'down', 'degraded' => 'degraded', 'unknown' => 'unknown', 'visibility_loss' => 'visibility'] as $key => $label) {
		if ($site[$key] > 0) {
			$problem_parts[] = $site[$key] . ' ' . $label;
		}
	}
	$site_box = (new CDiv())->addClass('na-site')->addClass($healthy ? 'is-healthy' : 'is-affected')
		->addClass($healthy ? 'is-collapsed' : 'is-open')
		->setAttribute('data-site-id', $site['id'])
		->setAttribute('data-issue-signature', $site['issue_signature'])
		->setAttribute('data-default-open', $healthy ? '0' : '1');
	$site_box->addItem((new CTag('button', true, [
		(new CSpan($healthy ? '▶' : '▼'))->addClass('na-site__chevron'),
		(new CSpan($site['name']))->addClass('na-site__name'),
		new CSpan(implode(' · ', $problem_parts)),
		new CSpan($site['healthy'] . '/' . $site['total'] . ' up'),
		(new CSpan(''))->addClass('na-site__recovered')
	]))->addClass('na-site__header')->setAttribute('type', 'button'));
	$nodes = (new CDiv())->addClass('na-site__nodes');
	foreach ($site['nodes'] as $node) {
		$nodes->addItem($render_node($node));
	}
	$site_box->addItem($nodes);
	$affected_sites->addItem($site_box);
}
$root->addItem($affected_sites);

if ($healthy_sites !== []) {
	$healthy = (new CDiv())->addClass('na-healthy-sites');
	$healthy->addItem((new CSpan('Healthy sites ' . count($healthy_sites)))->addClass('na-section-title'));
	foreach ($healthy_sites as $site) {
		$healthy->addItem((new CTag('button', true, '● ' . $site['name'] . ' ' . $site['total']))
			->setAttribute('type', 'button')->setAttribute('data-site-open', $site['id'])
			->addClass('na-healthy-chip'));
	}
	$root->addItem($healthy);
}

if ($unassigned !== null) {
	$section = (new CDiv())->addClass('na-unassigned')->setAttribute('data-site-id', '__unassigned__');
	$section->addItem((new CTag('button', true, [
		(new CSpan('▶'))->addClass('na-unassigned__chevron'),
		new CSpan('Unassigned hosts (' . $unassigned['total'] . ')')
	]))->setAttribute('type', 'button')->addClass('na-unassigned__header'));
	$rows = (new CDiv())->addClass('na-unassigned__rows');
	if ($data['configuration']['sites'] !== []) {
		$rows->addClass('is-hidden');
	}
	foreach ($unassigned['nodes'] as $node) {
		$row_items = [
			(new CSpan($node['actual_state'] === 'UP' ? '●' : ($node['actual_state'] === 'DOWN' ? '○' : '◌')))
				->addClass('na-unassigned__dot'),
			(new CSpan($node['name']))->addClass('na-unassigned__name')->setTitle($node['name']),
			new CSpan($node['actual_state']),
			new CSpan('Unassigned')
		];
		if ($data['user']['can_edit']) {
			$row_items[] = (new CTag('button', true, 'Assign to site →'))->setAttribute('type', 'button')
				->setAttribute('data-quick-assign', $node['members'][0]['host'])->addClass('link-action');
		}
		$rows->addItem((new CDiv($row_items))->addClass('na-unassigned__row')
			->setAttribute('data-node-id', $node['id'])->setAttribute('data-state', $node['actual_state'])
			->setAttribute('data-search', strtolower($node['name'] . ' ' . $node['members'][0]['host'])));
	}
	$section->addItem($rows);
	$root->addItem($section);
}

$root->addItem((new CDiv())->addClass('na-panel-backdrop')->addClass('is-hidden'));
$root->addItem((new CDiv())->addClass('na-details-panel')->addClass('is-hidden')
	->setAttribute('role', 'dialog')->setAttribute('aria-label', 'Node details'));
$root->addItem((new CDiv())->addClass('na-editor-panel')->addClass('is-hidden')
	->setAttribute('role', 'dialog')->setAttribute('aria-label', 'Edit sites'));

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
