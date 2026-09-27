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
$tier = static fn(?string $value): string => $value === null ? 'No tier'
	: 'Tier-' . substr($value, -1);
$plural = static fn(int $count, string $singular, ?string $plural = null): string =>
	$count.' '.($count === 1 ? $singular : ($plural ?? $singular.'s'));
$member_dots = static function(array $node): ?CDiv {
	$glyphs = (new CDiv())->addClass('na-member-glyphs');
	$members = $node['members'] ?? [];
	if (count($members) <= 1) {
		return null;
	}
	if (count($members) > 6) {
		return $glyphs->addItem((new CSpan(sprintf('%d/%d available', $node['known_up'], count($members))))
			->addClass('na-member-glyphs__summary'));
	}
	foreach ($members as $member) {
		$state = !$member['fresh'] || $member['raw_availability_state'] === 'UNKNOWN' ? 'stale'
			: ($member['raw_availability_state'] === 'DOWN' ? 'down' : 'up');
		$glyphs->addItem((new CSpan(['up' => '●', 'down' => '○', 'stale' => '◌'][$state]))
			->addClass('is-'.$state)->setAttribute('title', $member['name'].' · '.strtoupper($state)));
	}
	return $glyphs;
};

$stale_banner = (new CDiv([
	(new CSpan('Monitoring view is not updating'))->addClass('na-stale-view__title'),
	new CSpan('Last successful update: '),
	(new CSpan('—'))->addClass('na-stale-view__age')
]))->addClass('na-stale-view')->addClass('is-hidden');
$content = (new CDiv([$stale_banner]))->addClass('na-content');

$header = (new CDiv())->addClass('na-header');
$header->addItem((new CSpan('Updated just now'))->addClass('na-updated'));
$total_nodes = array_sum(array_intersect_key($snapshot['summary'], array_flip(['UP', 'DOWN', 'DEGRADED', 'UNKNOWN'])));
$header->addItem((new CSpan($snapshot['summary']['UP'].'/'.$total_nodes.' up'))->addClass('na-up-note'));
if ($data['user']['can_edit']) {
	$header->addItem((new CTag('button', true, 'Edit sites'))->setAttribute('type', 'button')
		->addClass('btn-alt')->addClass('na-edit-start'));
}
$content->addItem($header);

$toolbar = (new CDiv())->addClass('na-toolbar');
$toolbar->addItem((new CTag('input', false))
	->setAttribute('type', 'search')->setAttribute('placeholder', 'Search Nodes or Hosts')
	->setAttribute('aria-label', 'Search Nodes or Hosts')->addClass('na-search'));
$toolbar->addItem((new CDiv([
	(new CSpan(''))->addClass('na-filter-chip__label'),
	(new CTag('button', true, 'Clear'))->setAttribute('type', 'button')->addClass('na-filter-clear')
]))->addClass('na-filter-chip')->addClass('is-hidden'));
$summary = (new CDiv())->addClass('na-summary');
foreach ([
	'DOWN' => 'DOWN', 'DEGRADED' => 'DEGRADED', 'UNKNOWN' => 'UNKNOWN',
	'VISIBILITY_LOSS' => 'VISIBILITY LOSS', 'MAINTENANCE' => 'MAINTENANCE',
	'IMPACTED_SITES' => 'IMPACTED SITES'
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
$content->addItem($summary);

$attention = (new CDiv())->addClass('na-attention');
$impacted_site_names = [];
foreach ($snapshot['sites'] as $site) {
	if (!in_array($site['state'], ['HEALTHY', 'MAINTENANCE', 'SUPPRESSED'], true)) {
		$impacted_site_names[$site['name']] = true;
	}
}
$attention_count = count($snapshot['needs_attention']);
$attention->addItem((new CDiv([new CTag('h4', true, 'Needs attention'),
	(new CSpan($plural($attention_count, 'item')))->addClass('na-section-count')]))->addClass('na-section-title'));
if ($snapshot['needs_attention'] === []) {
	$attention->addItem((new CDiv('No active incidents requiring attention'))
		->addClass('na-all-clear'));
}
else {
	foreach ($snapshot['needs_attention'] as $index => $incident) {
		$problem_count = count($incident['problems'] ?? []);
		$meta = $incident['site'] ?? 'Unassigned';
		$badges = (new CDiv())->addClass('na-attention__badges');
		$badges->addItem((new CSpan($tier($incident['criticality'] ?? null)))
			->addClass(($incident['criticality'] ?? null) === null ? 'na-badge is-no-tier' : 'na-badge is-tier'));
		if ($incident['maintenance'] ?? false) $badges->addItem((new CSpan('Maintenance'))->addClass('na-badge is-maintenance'));
		if (($incident['visibility'] ?? 'FULL') !== 'FULL') $badges->addItem((new CSpan(ucfirst(strtolower($incident['visibility'])).' visibility'))->addClass('na-badge is-visibility'));
		if ($incident['flapping'] ?? false) $badges->addItem((new CSpan('Flapping'))->addClass('na-badge is-flapping'));
		$main = (new CDiv([
			(new CDiv([(new CSpan($incident['name']))->addClass('na-attention__name')->setTitle($incident['name']), $badges]))->addClass('na-attention__name-line'),
			(new CSpan($meta))->addClass('na-attention__meta')->setTitle($meta)
		]))->addClass('na-attention__main');
		$summary = (new CDiv([
			(new CSpan('P'.$incident['priority'].' · '.$incident['state'].' · '.$duration($incident['event_since'] ?? null)))
				->addClass('na-attention__state'),
			$member_dots($incident)
		]))->addClass('na-attention__summary');
		$open = (new CTag('button', true, [$main, $summary]))->setAttribute('type', 'button')
			->setAttribute('data-node-id', (string) $incident['id'])->addClass('na-attention__open');
		$row = (new CDiv([$open]))->addClass('na-attention__row')
			->addClass('is-'.strtolower($incident['state']))
			->addClass(($incident['maintenance'] ?? false) ? 'is-maintenance' : '')
			->setAttribute('data-state', (string) $incident['state'])
			->setAttribute('data-visibility', (string) ($incident['visibility'] ?? ($incident['state'] === 'VISIBILITY_LOST' ? 'LOST' : 'FULL')))
			->setAttribute('data-impacted-site', isset($impacted_site_names[$incident['site'] ?? 'Unassigned']) ? '1' : '0')
			->setAttribute('data-search', strtolower($incident['name'].' '.($incident['site'] ?? 'Unassigned').' '.implode(' ', array_column($incident['members'] ?? [], 'host'))));
		if ($problem_count > 0) {
			$row->addItem((new CTag('button', true, ($incident['acknowledged'] ?? false) ? 'Acknowledged' : 'Unacknowledged'))
				->setAttribute('type', 'button')->setAttribute('data-ack-node-id', (string) $incident['id'])
				->addClass('na-attention__ack-action')->addClass(($incident['acknowledged'] ?? false) ? 'is-acked' : ''));
		}
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
$content->addItem($attention);
$content->addItem($toolbar);

$render_node = static function(array $node) use ($member_dots, $duration, $tier): CDiv {
	$is_healthy = $node['actual_state'] === 'UP' && $node['visibility'] === 'FULL'
		&& !$node['maintenance'] && !$node['suppressed'];
	$card = (new CDiv())->addClass('na-node')->addClass('is-' . strtolower($node['actual_state']))
		->addClass($is_healthy ? 'is-healthy' : 'is-problem')
		->addClass($node['hidden'] ? 'is-config-hidden' : '')
		->addClass($node['maintenance'] ? 'is-maintenance' : '')
		->setAttribute('role', 'button')->setAttribute('tabindex', '0')
		->setAttribute('data-node-id', $node['id'])
		->setAttribute('data-state', $node['actual_state'])
		->setAttribute('data-visibility', $node['visibility'])
		->setAttribute('data-search', strtolower($node['name'] . ' ' . implode(' ', array_column($node['members'], 'host'))));
	$member_status = $member_dots($node);
	$heading_items = [
		(new CSpan(''))->addClass('na-state-dot')->setAttribute('aria-label', $node['actual_state']),
		(new CSpan($node['name']))->addClass('na-node__name')->setTitle($node['name'])
	];
	if ($is_healthy) {
		if ($node['criticality'] === 'tier1') {
			$heading_items[] = (new CSpan('T1'))->addClass('na-badge')->addClass('is-tier')->addClass('is-healthy-tier');
		}
		if ($member_status !== null) {
			$heading_items[] = $member_status;
		}
	}
	else {
		$heading_items[] = (new CSpan($node['actual_state']))->addClass('na-node__state');
	}
	$heading = (new CDiv($heading_items))->addClass('na-node__heading');
	$card->addItem($heading);
	if ($is_healthy) {
		return $card;
	}
	$badges = (new CDiv())->addClass('na-node__badges');
	$badges->addItem((new CSpan($tier($node['criticality'])))->addClass('na-badge')
		->addClass($node['criticality'] === null ? 'is-no-tier' : 'is-tier'));
	if ($node['visibility'] !== 'FULL') $badges->addItem((new CSpan(ucfirst(strtolower($node['visibility'])).' visibility'))->addClass('na-badge is-visibility'));
	if ($node['maintenance']) $badges->addItem((new CSpan('Maintenance'))->addClass('na-badge is-maintenance'));
	if ($node['flapping']) $badges->addItem((new CSpan('Flapping'))->addClass('na-badge is-flapping'));
	$card->addItem((new CDiv([$badges, $member_status]))->addClass('na-node__status-line'));
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
	return $card;
};

$affected_sites = (new CDiv())->addClass('na-sites')->addClass('na-affected-sites');
$affected_sites->addItem((new CDiv([new CTag('h4', true, 'Affected sites')]))->addClass('na-section-title'));
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
	$affected_nodes = count(array_filter($site['nodes'], static fn(array $node): bool =>
		$node['actual_state'] !== 'UP' || $node['visibility'] !== 'FULL'
	));
	$site_summary = $plural($affected_nodes, 'problem').' · '.$plural((int) $site['total'], 'node');
	$site_box = (new CDiv())->addClass('na-site')->addClass($healthy ? 'is-healthy' : 'is-affected')
		->addClass($healthy ? 'is-collapsed' : 'is-open')
		->setAttribute('data-site-id', $site['id'])
		->setAttribute('data-issue-signature', $site['issue_signature'])
		->setAttribute('data-default-open', $healthy ? '0' : '1');
	$site_box->addItem((new CTag('button', true, [
		(new CSpan($healthy ? '▶' : '▼'))->addClass('na-site__chevron'),
		(new CSpan($site['name']))->addClass('na-site__name')->setTitle($site['name']),
		(new CSpan($site_summary))->addClass('na-site__issues'),
		(new CSpan($site['healthy'] . '/' . $site['total'] . ' healthy'))->addClass('na-site__count'),
		(new CSpan(''))->addClass('na-site__recovered')
	]))->addClass('na-site__header')->setAttribute('type', 'button'));
	$nodes = (new CDiv())->addClass('na-site__nodes');
	foreach ($site['nodes'] as $node) {
		$nodes->addItem($render_node($node));
	}
	$site_box->addItem($nodes);
	$affected_sites->addItem($site_box);
}
$content->addItem($affected_sites);

if ($healthy_sites !== []) {
	$healthy = (new CDiv())->addClass('na-healthy-sites');
	$healthy->addItem((new CSpan('Healthy sites · ' . $plural(count($healthy_sites), 'site')))->addClass('na-section-title'));
	foreach ($healthy_sites as $site) {
		$healthy->addItem((new CTag('button', true, '● ' . $site['name'] . ' · ' . $plural((int) $site['total'], 'node')))
			->setAttribute('type', 'button')->setAttribute('data-site-open', $site['id'])
			->addClass('na-healthy-chip'));
	}
	$content->addItem($healthy);
}

if ($unassigned !== null) {
	$section = (new CDiv())->addClass('na-unassigned')->setAttribute('data-site-id', '__unassigned__')
		->setAttribute('data-impacted-site', isset($impacted_site_names[$unassigned['name']]) ? '1' : '0');
	$section->addItem((new CTag('button', true, [
		(new CSpan('▶'))->addClass('na-unassigned__chevron'),
		new CSpan('Unassigned hosts · ' . $plural((int) $unassigned['total'], 'host'))
	]))->setAttribute('type', 'button')->addClass('na-unassigned__header'));
	$rows = (new CDiv())->addClass('na-unassigned__rows');
	if ($data['configuration']['sites'] !== []) {
		$rows->addClass('is-hidden');
	}
	foreach ($unassigned['nodes'] as $node) {
		$row_items = [
			(new CSpan(''))->addClass('na-state-dot')->addClass('is-'.strtolower($node['actual_state']))->setAttribute('aria-label', $node['actual_state']),
			(new CSpan($node['name']))->addClass('na-unassigned__name')->setTitle($node['name']),
			new CSpan($node['actual_state']),
			new CSpan('Unassigned · No tier')
		];
		if ($data['user']['can_edit']) {
			$row_items[] = (new CTag('button', true, 'Assign to site →'))->setAttribute('type', 'button')
				->setAttribute('data-quick-assign', $node['members'][0]['host'])->addClass('link-action');
		}
		$rows->addItem((new CDiv($row_items))->addClass('na-unassigned__row')
			->setAttribute('role', 'button')->setAttribute('tabindex', '0')
			->setAttribute('data-node-id', $node['id'])->setAttribute('data-state', $node['actual_state'])
			->setAttribute('data-visibility', $node['visibility'])
			->setAttribute('data-search', strtolower($node['name'] . ' ' . $node['members'][0]['host'])));
	}
	$section->addItem($rows);
	$content->addItem($section);
}

$root->addItem($content);

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
	$content->addItem((new CDiv([new CSpan(_('Configuration / collection warnings')), $warnings]))->addClass('na-warning-box'));
}
if ($data['user']['debug_mode']) {
	$content->addItem((new CDiv('Availability instrumentation: ' . json_encode($data['instrumentation'], JSON_THROW_ON_ERROR)))
		->addClass('na-debug'));
}

(new CWidgetView($data))->addItem($root)->show();
