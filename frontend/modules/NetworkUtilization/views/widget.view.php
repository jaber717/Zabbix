<?php declare(strict_types = 1);

/** @var CView $this */
/** @var array $data */

$root = (new CDiv())->addClass('netops-utilization');
if ($data['error'] !== null) {
	$root->addItem((new CDiv([(new CSpan('Utilization data unavailable'))->addClass('nu-error__title'), new CSpan($data['error'])]))->addClass('nu-error'));
	(new CWidgetView($data))->addItem($root)->show();
	return;
}
$snapshot = $data['snapshot'];
$encode = static fn(array $value): string => base64_encode(json_encode($value, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));
$root->setAttribute('data-generated-at', (string) $snapshot['generated_at'])->setAttribute('data-refresh-seconds', '60')
	->setAttribute('data-can-edit', $data['user']['can_edit'] ? '1' : '0')
	->setAttribute('data-csrf-token', (string) ($data['user']['csrf_token'] ?? ''))
	->setAttribute('data-snapshot', $encode($snapshot))->setAttribute('data-configuration', $encode($data['configuration']))
	->setAttribute('data-candidates', $encode($data['candidates']))->setAttribute('data-instrumentation', $encode($data['instrumentation']));
$format_bps = static function(?float $value): string {
	if ($value === null) return 'Unknown';
	foreach ([[1e9, 'Gbps'], [1e6, 'Mbps'], [1e3, 'Kbps'], [1, 'bps']] as [$scale, $unit]) {
		if ($value >= $scale) {
			$scaled = $value / $scale;
			return number_format($scaled, $scaled >= 100 ? 0 : ($scaled >= 10 ? 1 : 2), '.', '').' '.$unit;
		}
	}
	return '0 bps';
};
$pct = static fn(?float $value): string => $value === null ? 'Unknown' : number_format($value, 1).'%';
$tone = static function(array $link): string {
	if ($link['data_state'] !== 'CURRENT' || $link['capacity_bps'] === null || $link['mapping_issue'] !== null) return 'is-unknown';
	if ($link['worst_util_pct'] !== null && $link['worst_util_pct'] >= $link['critical_util_pct']) return 'is-critical';
	if ($link['worst_util_pct'] !== null && $link['worst_util_pct'] >= $link['warning_util_pct']) return 'is-warning';
	return 'is-normal';
};
$by_id = array_column($snapshot['links'], null, 'id');

$root->addItem((new CDiv([
	(new CSpan('Monitoring view is not updating'))->addClass('nu-stale__title'),
	new CSpan(' Last successful update: '), (new CSpan('—'))->addClass('nu-stale__age')
]))->addClass('nu-stale')->addClass('is-hidden'));
$header = (new CDiv())->addClass('nu-header');
$header->addItem((new CDiv([
	(new CSpan('NETWORK OPERATIONS'))->addClass('nu-eyebrow'), new CTag('h3', true, 'Network Utilization')
]))->addClass('nu-header__title'));
$actions = (new CDiv())->addClass('nu-header__actions')->addItem((new CSpan('Updated —'))->addClass('nu-updated'));
if ($data['user']['can_edit']) $actions->addItem((new CTag('button', true, 'Edit links'))->setAttribute('type', 'button')->addClass('btn-alt')->addClass('nu-edit-start'));
$header->addItem($actions); $root->addItem($header);

$summary = (new CDiv())->addClass('nu-summary');
foreach (['HOT_NOW'=>'HOT NOW', 'SUSTAINED'=>'SUSTAINED', 'ERRORS_DISCARDS'=>'ERRORS / DISCARDS',
	'CAPACITY_RISK'=>'CAPACITY RISK', 'UNKNOWN_STALE'=>'UNKNOWN / STALE', 'MONITORED_LINKS'=>'MONITORED LINKS'] as $key=>$label) {
	$value = $snapshot['summary'][$key];
	$summary->addItem((new CTag('button', true, [
		(new CSpan((string) $value))->addClass('nu-summary__value'),
		(new CSpan($label))->addClass('nu-summary__label')
	]))->setAttribute('type', 'button')->setAttribute('data-filter', $key)
		->addClass('nu-summary__item')->addClass($value ? 'has-value' : 'is-zero')->addClass('is-'.strtolower($key)));
}
$root->addItem($summary);

$attention = (new CDiv())->addClass('nu-attention');
$attention->addItem((new CDiv([new CTag('h4', true, 'Needs attention'),
	(new CSpan(count($snapshot['needs_attention']).' items'))->addClass('nu-section-count')]))->addClass('nu-section-heading'));
if ($snapshot['needs_attention'] === []) $attention->addItem((new CDiv('No configured Links need attention'))->addClass('nu-calm'));
foreach ($snapshot['needs_attention'] as $index=>$row) {
	$link = $by_id[$row['link_id'] ?? ''] ?? null;
	$meta = $link === null ? $row['detail'] : $link['site'].' · '.$link['host_name'].' · '.$link['interface']['if_name'];
	$primary = $link !== null && $link['worst_util_pct'] !== null
		? $link['worst_direction'].' '.$pct($link['worst_util_pct']).' · '.$format_bps($link['worst_direction'] === 'IN' ? $link['current_in_bps'] : $link['current_out_bps'])
		: $row['detail'];
	$secondary = $link === null ? '' : implode(' · ', array_filter([
		$link['sustained'] ? 'Sustained '.floor($link['sustained_seconds']/60).'m' : null,
		$link['p95_worst_pct'] !== null ? 'P95 '.$pct($link['p95_worst_pct']) : null,
		$link['headroom_bps'] !== null ? $format_bps($link['headroom_bps']).' headroom' : null,
		($link['errors_total'] > 0 || $link['discards_total'] > 0) ? $link['errors_total'].' errors / '.$link['discards_total'].' discards' : null
	]));
	$attention->addItem((new CTag('button', true, [
		(new CSpan(str_replace('_', ' ', $row['kind'])))->addClass('nu-attention__kind'),
		(new CDiv([(new CSpan($row['label']))->addClass('nu-attention__name'),
			(new CSpan($meta))->addClass('nu-attention__meta')]))->addClass('nu-attention__identity'),
		(new CDiv([(new CSpan($primary))->addClass('nu-attention__primary'),
			(new CSpan($secondary))->addClass('nu-attention__secondary')]))->addClass('nu-attention__metrics')
	]))->setAttribute('type', 'button')->setAttribute('data-link-id', (string) ($row['link_id'] ?? ''))
		->addClass('nu-attention__row')->addClass($index >= 5 ? 'is-extra is-hidden' : '')
		->addClass(in_array($row['kind'], ['CONFIG_OR_DATA', 'MONITORING_STALE'], true) ? 'is-neutral' : 'is-active'));
}
if (count($snapshot['needs_attention']) > 5) $attention->addItem((new CTag('button', true, '+'.(count($snapshot['needs_attention'])-5).' more'))->setAttribute('type', 'button')->addClass('nu-more'));
$root->addItem($attention);

$top = (new CDiv())->addClass('nu-top');
$heading = (new CDiv())->addClass('nu-section-heading')->addItem(new CTag('h4', true, 'Top utilized links'));
$sort = (new CDiv([new CSpan('Sort by')]))->addClass('nu-sort');
foreach (['current'=>'Current', 'p95'=>'P95', 'headroom'=>'Headroom', 'errors'=>'Errors', 'discards'=>'Discards'] as $key=>$label) {
	$sort->addItem((new CTag('button', true, $label))->setAttribute('type', 'button')->setAttribute('data-sort', $key)->addClass($key === 'current' ? 'is-active' : ''));
}
$heading->addItem($sort); $top->addItem($heading);
$toolbar = (new CDiv())->addClass('nu-toolbar');
$toolbar->addItem((new CTag('input', false))->setAttribute('type', 'search')->setAttribute('placeholder', 'Search links, sites or devices')->setAttribute('aria-label', 'Search links')->addClass('nu-search'));
$toolbar->addItem((new CTag('select', true, [new CTag('option', true, 'All sites')]))->setAttribute('aria-label', 'Filter site')->addClass('nu-site-filter'));
$toolbar->addItem((new CTag('select', true, [new CTag('option', true, 'All roles')]))->setAttribute('aria-label', 'Filter role')->addClass('nu-role-filter'));
$toolbar->addItem((new CDiv([(new CSpan(''))->addClass('nu-filter-label'),
	(new CTag('button', true, 'Clear'))->setAttribute('type', 'button')->addClass('nu-filter-clear')]))->addClass('nu-filter-chip')->addClass('is-hidden'));
$top->addItem($toolbar);
$table = (new CTag('table', true))->addClass('nu-table');
$table->addItem(new CTag('thead', true, new CTag('tr', true, array_map(static fn($label) => new CTag('th', true, $label),
	['Link', 'Site', 'Device', 'Capacity', 'IN', 'OUT', 'P95 24H', 'Headroom', 'Errors / Discards']))));
$body = new CTag('tbody', true);
foreach ($snapshot['links'] as $link) {
	if (!$link['visible']) continue;
	$traffic_cell = static function(string $direction) use ($link, $pct, $format_bps): CTag {
		$key = strtolower($direction);
		return (new CTag('td', true, [
			(new CSpan($pct($link[$key.'_util_pct'])))->addClass('nu-traffic-pct'),
			(new CSpan($format_bps($link['current_'.$key.'_bps'])))->addClass('nu-traffic-bps')
		]))->addClass('nu-traffic-cell')->setAttribute('data-label', $direction);
	};
	$body->addItem((new CTag('tr', true, [
		(new CTag('td', true, [(new CTag('button', true, $link['display_name']))->setAttribute('type', 'button')->addClass('nu-link-open'),
			(new CDiv($link['interface']['if_name']))->addClass('nu-subtle')]))->addClass('nu-link-cell'),
		new CTag('td', true, $link['site']), new CTag('td', true, $link['host_name']),
		(new CTag('td', true, $format_bps($link['capacity_bps'])))->addClass($link['capacity_bps'] === null ? 'nu-unknown' : ''),
		$traffic_cell('IN'), $traffic_cell('OUT'),
		new CTag('td', true, $pct($link['p95_worst_pct'])),
		(new CTag('td', true, $format_bps($link['headroom_bps'])))->addClass($link['headroom_bps'] === null ? 'nu-unknown' : ''),
		new CTag('td', true, $link['errors_total'].' / '.$link['discards_total'])
	]))->setAttribute('data-link-id', $link['id'])->setAttribute('data-current', (string) ($link['worst_util_pct'] ?? -1))
		->setAttribute('data-p95', (string) ($link['p95_worst_pct'] ?? -1))
		->setAttribute('data-headroom', (string) ($link['headroom_bps'] ?? PHP_INT_MAX))
		->setAttribute('data-errors', (string) $link['errors_total'])->setAttribute('data-discards', (string) $link['discards_total'])
		->setAttribute('data-site', $link['site_id'])->setAttribute('data-role', $link['role'])
		->setAttribute('data-search', strtolower($link['display_name'].' '.$link['host'].' '.$link['interface']['if_name'].' '.$link['site']))
		->addClass($tone($link)));
}
$table->addItem($body); $top->addItem($table);
if ($snapshot['links'] === []) $top->addItem((new CDiv('No Links are configured. Use Edit links to select operationally important interfaces.'))->addClass('nu-onboarding'));
$root->addItem($top);

$sites = (new CDiv())->addClass('nu-sites')->addItem((new CDiv([new CTag('h4', true, 'Sites')]))->addClass('nu-section-heading'));
foreach ($snapshot['sites'] as $site) {
	$visible = array_values(array_filter($site['links'], static fn($link) => $link['visible']));
	$hot = count(array_filter($site['links'], static fn($link) => $link['worst_util_pct'] !== null && $link['worst_util_pct'] >= $link['warning_util_pct']));
	$sustained = count(array_filter($site['links'], static fn($link) => $link['sustained']));
	$site_box = (new CDiv())->addClass('nu-site')->addClass($site['attention'] ? 'is-affected' : 'is-collapsed')->setAttribute('data-site-id', $site['id']);
	$site_box->addItem((new CTag('button', true, [
		(new CSpan($site['name']))->addClass('nu-site__name'),
		(new CSpan($hot.' hot · '.$sustained.' sustained · '.count($visible).' links'))->addClass('nu-site__count')
	]))->setAttribute('type', 'button')->addClass('nu-site__header'));
	$rows = (new CDiv())->addClass('nu-site__links');
	foreach ($visible as $link) $rows->addItem((new CTag('button', true, [
		(new CSpan($link['display_name']))->addClass('nu-site-link__name'),
		(new CSpan($link['host_name'].' · '.$link['interface']['if_name']))->addClass('nu-site-link__host'),
		(new CSpan(($link['worst_direction'] ?? '').' '.$pct($link['worst_util_pct'])))->addClass('nu-site__metric')
	]))->setAttribute('type', 'button')->setAttribute('data-link-id', $link['id'])->addClass('nu-site-link')->addClass($tone($link)));
	$site_box->addItem($rows); $sites->addItem($site_box);
}
$root->addItem($sites);
$root->addItem((new CDiv())->addClass('nu-panel-backdrop')->addClass('is-hidden'));
$root->addItem((new CTag('aside', true))->addClass('nu-panel')->addClass('is-hidden')->setAttribute('aria-label', 'Link details'));
$root->addItem((new CTag('aside', true))->addClass('nu-editor')->addClass('is-hidden')->setAttribute('aria-label', 'Edit links'));
if ($data['warnings']) $root->addItem((new CDiv(implode(' · ', $data['warnings'])))->addClass('nu-warnings'));
(new CWidgetView($data))->addItem($root)->show();
