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
	if ($value === null) return '—';
	foreach ([[1e9, 'Gbps'], [1e6, 'Mbps'], [1e3, 'Kbps'], [1, 'bps']] as [$scale, $unit]) {
		if (abs($value) >= $scale) {
			$scaled = $value / $scale; $decimals = abs($scaled) >= 100 ? 0 : (abs($scaled) >= 10 ? 1 : 2);
			$number = number_format($scaled, $decimals, '.', '');
			return ($decimals ? rtrim(rtrim($number, '0'), '.') : $number).' '.$unit;
		}
	}
	return ($value > 0 ? number_format($value, 2, '.', '') : '0').' bps';
};
$pct = static fn(?float $value): string => $value === null ? '—' : number_format($value, 1).'%';
$capacity = static fn(?float $value): string => $value === null ? 'Not configured' : $format_bps($value);
$remaining = static fn(?float $value): string => $value === null ? '—' : ($value < 0 ? 'Over by '.$format_bps(-$value) : $format_bps($value));
$tone = static function(array $link): string {
	if ($link['data_state'] !== 'CURRENT' || $link['capacity_in_bps'] === null || $link['capacity_out_bps'] === null || $link['mapping_issue'] !== null) return 'is-unknown';
	if ($link['worst_util_pct'] !== null && $link['worst_util_pct'] >= $link['critical_util_pct']) return 'is-critical';
	if ($link['worst_util_pct'] !== null && $link['worst_util_pct'] >= $link['warning_util_pct']) return 'is-warning';
	return 'is-normal';
};

$root->addItem((new CDiv([(new CSpan('Monitoring view is not updating'))->addClass('nu-stale__title'),
	new CSpan(' Last successful update: '), (new CSpan('—'))->addClass('nu-stale__age')]))->addClass('nu-stale')->addClass('is-hidden'));
$header = (new CDiv())->addClass('nu-header');
$header->addItem((new CDiv([new CTag('h3', true, 'Network Utilization'), (new CSpan('Updated —'))->addClass('nu-updated')]))->addClass('nu-header__title'));
$ranges = (new CDiv())->addClass('nu-global-ranges')->setAttribute('aria-label', 'Traffic graph range');
foreach ([[1, '1h'], [6, '6h'], [24, '24h'], [168, '7d']] as [$hours, $label]) {
	$ranges->addItem((new CTag('button', true, $label))->setAttribute('type', 'button')->setAttribute('data-global-hours', (string) $hours)
		->addClass($hours === 1 ? 'is-active' : ''));
}
$header->addItem($ranges);
$actions = (new CDiv())->addClass('nu-header__actions');
if ($data['user']['can_edit']) $actions->addItem((new CTag('button', true, 'Edit links'))->setAttribute('type', 'button')->addClass('btn-alt')->addClass('nu-edit-start'));
$header->addItem($actions); $root->addItem($header);

$toolbar = (new CDiv())->addClass('nu-toolbar');
$toolbar->addItem((new CTag('input', false))->setAttribute('type', 'search')->setAttribute('placeholder', 'Search links, sites or devices')->setAttribute('aria-label', 'Search links')->addClass('nu-search'));
$toolbar->addItem((new CTag('select', true, [new CTag('option', true, 'All sites')]))->setAttribute('aria-label', 'Filter site')->addClass('nu-site-filter'));
$toolbar->addItem((new CTag('select', true, [new CTag('option', true, 'All roles')]))->setAttribute('aria-label', 'Filter role')->addClass('nu-role-filter'));
$sort = (new CDiv([new CSpan('Sort')]))->addClass('nu-sort');
foreach (['configured'=>'Configured', 'current'=>'Current', 'p95'=>'P95', 'headroom'=>'Remaining', 'quality'=>'Errors / Discards'] as $key=>$label) {
	$sort->addItem((new CTag('button', true, [new CSpan($label), (new CSpan($key === 'configured' ? '↑' : ''))->addClass('nu-sort-direction')]))
		->setAttribute('type', 'button')->setAttribute('data-sort', $key)->setAttribute('aria-pressed', $key === 'configured' ? 'true' : 'false')
		->addClass($key === 'configured' ? 'is-active' : ''));
}
$toolbar->addItem($sort);
$toolbar->addItem((new CDiv([(new CSpan(''))->addClass('nu-filter-label'),
	(new CTag('button', true, 'Clear'))->setAttribute('type', 'button')->addClass('nu-filter-clear')]))->addClass('nu-filter-chip')->addClass('is-hidden'));
$root->addItem($toolbar);

$summary = (new CDiv())->addClass('nu-summary')->addClass('is-compact');
foreach (['HOT_NOW'=>'Hot now', 'SUSTAINED'=>'Sustained', 'UNKNOWN_STALE'=>'Data issue', 'MONITORED_LINKS'=>'Links'] as $key=>$label) {
	$value = $snapshot['summary'][$key];
	$summary->addItem((new CTag('button', true, [(new CSpan((string) $value))->addClass('nu-summary__value'), new CSpan($label)]))
		->setAttribute('type', 'button')->setAttribute('data-filter', $key)->addClass('nu-summary__item')->addClass($value ? 'has-value' : 'is-zero'));
}
$root->addItem($summary);

$top = (new CDiv())->addClass('nu-top');
$top->addItem((new CDiv([new CTag('h4', true, 'Links'), (new CSpan(count($snapshot['links']).' configured'))->addClass('nu-section-count')]))->addClass('nu-section-heading'));
$table = (new CTag('table', true))->addClass('nu-table');
$columns = new CTag('colgroup', true);
foreach (['link', 'site', 'device', 'capacity', 'in', 'out', 'p95', 'remaining', 'quality', 'graph'] as $column) $columns->addItem((new CTag('col', false))->addClass('nu-col-'.$column));
$table->addItem($columns);
$table->addItem(new CTag('thead', true, new CTag('tr', true, array_map(static fn($label) => new CTag('th', true, $label),
	['Link', 'Site', 'Device', 'Service capacity', 'IN', 'OUT', 'P95 24H', 'Remaining', 'Errors / Discards', 'Graphs']))));
$body = new CTag('tbody', true);
foreach ($snapshot['links'] as $link) {
	$traffic_cell = static function(string $direction) use ($link, $pct, $format_bps): CTag {
		$key = strtolower($direction); $parts = [(new CSpan($format_bps($link['current_'.$key.'_bps'])))->addClass('nu-traffic-bps')];
		if ($link[$key.'_util_pct'] !== null) {
			$parts[] = (new CSpan($pct($link[$key.'_util_pct'])))->addClass('nu-traffic-pct');
			$parts[] = (new CDiv([(new CSpan())->setAttribute('style', 'width:'.min(100, max(0, $link[$key.'_util_pct'])).'%')]))->addClass('nu-util-bar')->setAttribute('aria-hidden', 'true');
		}
		return (new CTag('td', true, $parts))->addClass('nu-traffic-cell')->setAttribute('data-label', $direction);
	};
	$capacity_known = $link['capacity_in_bps'] !== null && $link['capacity_out_bps'] !== null;
	$p95_out_is_worst = $link['p95_out_pct'] !== null && ($link['p95_in_pct'] === null || $link['p95_out_pct'] >= $link['p95_in_pct']);
	if ($link['p95_in_pct'] === null && $link['p95_out_pct'] === null) $p95_out_is_worst = ($link['p95_out_bps'] ?? -1) >= ($link['p95_in_bps'] ?? -1);
	$p95_bps = $p95_out_is_worst ? $link['p95_out_bps'] : $link['p95_in_bps'];
	$capacity_text = !$capacity_known ? 'Capacity required' : ($link['capacity_in_bps'] === $link['capacity_out_bps']
		? $capacity($link['capacity_in_bps']) : 'IN '.$capacity($link['capacity_in_bps']).' / OUT '.$capacity($link['capacity_out_bps']));
	$graph_actions = new CDiv();
	if ($data['user']['can_edit']) {
		$graph_actions->addItem((new CTag('button', true, $link['show_graph'] ? 'In graphs ✓' : '+ Add to graphs'))->setAttribute('type', 'button')
			->setAttribute('data-graph-toggle', $link['show_graph'] ? 'remove' : 'add')->setAttribute('data-link-id', $link['id'])->addClass('btn-alt')->addClass('nu-graph-toggle'));
	}
	elseif ($link['show_graph']) $graph_actions->addItem((new CSpan('In graphs ✓'))->addClass('nu-graph-status'));
	$body->addItem((new CTag('tr', true, [
		(new CTag('td', true, [(new CTag('button', true, $link['display_name']))->setAttribute('type', 'button')->setAttribute('data-details-link-id', $link['id'])->setAttribute('title', $link['display_name'])->addClass('nu-link-open'),
			(new CDiv($link['interface']['if_name'].($link['current_alias'] !== '' ? ' · '.$link['current_alias'] : '')))->setAttribute('title', $link['interface']['if_name'].' · '.$link['current_alias'])->addClass('nu-subtle')]))->addClass('nu-link-cell')->setAttribute('data-label', 'Link'),
		(new CTag('td', true, $link['site']))->setAttribute('title', $link['site'])->setAttribute('data-label', 'Site'),
		(new CTag('td', true, $link['host_name']))->setAttribute('title', $link['host_name'])->setAttribute('data-label', 'Device'),
		(new CTag('td', true, [new CSpan($capacity_text), $capacity_known ? (new CDiv($link['capacity_source'] === 'service_override' ? 'Service' : 'Interface speed'))->addClass('nu-subtle') : null]))->setAttribute('data-label', 'Capacity')->addClass($capacity_known ? '' : 'nu-unknown'),
		$traffic_cell('IN'), $traffic_cell('OUT'),
		(new CTag('td', true, [(new CSpan($format_bps($p95_bps)))->addClass('nu-traffic-bps'),
			(new CSpan($pct($link['p95_worst_pct'])))->addClass('nu-traffic-pct')]))->setAttribute('data-label', 'P95 24H'),
		(new CTag('td', true, $remaining($link['worst_headroom_bps'])))->setAttribute('data-label', 'Remaining'),
		(new CTag('td', true, $link['errors_total'].' / '.$link['discards_total']))->setAttribute('data-label', 'Errors / Discards'),
		(new CTag('td', true, $graph_actions))->setAttribute('data-label', 'Graphs')->addClass('nu-graph-cell')
	]))->setAttribute('data-link-id', $link['id'])->setAttribute('data-configured', (string) ($link['site_order'] * 100000 + $link['order']))
		->setAttribute('data-current', $link['worst_util_pct'] === null ? '' : (string) $link['worst_util_pct'])
		->setAttribute('data-p95', $link['p95_worst_pct'] === null ? '' : (string) $link['p95_worst_pct'])
		->setAttribute('data-headroom', $link['worst_headroom_bps'] === null ? '' : (string) $link['worst_headroom_bps'])
		->setAttribute('data-quality', (string) ($link['errors_total'] + $link['discards_total']))
		->setAttribute('data-site', $link['site_id'])->setAttribute('data-role', $link['role'])
		->setAttribute('data-search', strtolower($link['display_name'].' '.$link['host'].' '.$link['interface']['if_name'].' '.$link['site']))->addClass($tone($link)));
}
$table->addItem($body); $top->addItem($table);
if ($snapshot['links'] === []) $top->addItem((new CDiv('No Links are configured. Use Edit links to select operationally important interfaces.'))->addClass('nu-onboarding'));
$root->addItem($top);

$graphs = (new CDiv())->addClass('nu-graphs');
$graphs->addItem((new CDiv([new CTag('h4', true, 'Traffic graphs'), (new CSpan(count($snapshot['pinned_links']).' Links'))->addClass('nu-graph-count')]))->addClass('nu-section-heading'));
$graphs->addItem((new CDiv('No graphs selected. Choose important Links above and click “Add to graphs”.'))->addClass('nu-graph-empty')->addClass($snapshot['pinned_links'] === [] ? '' : 'is-hidden'));
$graph_list = (new CDiv())->addClass('nu-graph-list');
foreach ($snapshot['links'] as $link) {
	$graph_capacity_known = $link['capacity_in_bps'] !== null && $link['capacity_out_bps'] !== null;
	$graph_capacity_text = !$graph_capacity_known ? 'Capacity required' : ($link['capacity_in_bps'] === $link['capacity_out_bps']
		? $capacity($link['capacity_in_bps']) : 'IN '.$capacity($link['capacity_in_bps']).' / OUT '.$capacity($link['capacity_out_bps']));
	$direction = $link['worst_headroom_bps'] === null ? null : (($link['remaining_out_bps'] ?? INF) <= ($link['remaining_in_bps'] ?? INF) ? 'OUT' : 'IN');
	$card = (new CDiv())->addClass('nu-graph-card')->addClass($link['show_graph'] ? '' : 'is-hidden')->setAttribute('data-graph-link-id', $link['id']);
	$identity = (new CDiv([new CTag('h5', true, $link['display_name']),
		(new CSpan($link['site'].' · '.$link['host_name'].' · '.$link['interface']['if_name']))->setAttribute('title', $link['site'].' · '.$link['host_name'].' · '.$link['interface']['if_name'])->addClass('nu-graph-meta'),
		(new CSpan(!$graph_capacity_known ? 'Capacity required' : 'Service '.$graph_capacity_text.($link['port_speed_bps'] !== null ? ' · Port '.$format_bps($link['port_speed_bps']) : '')))->addClass('nu-graph-capacity')]))->addClass('nu-graph-identity');
	$card_actions = (new CDiv())->addClass('nu-graph-actions');
	if ($data['user']['can_edit']) $card_actions->addItem([
		(new CTag('button', true, '↑'))->setAttribute('type', 'button')->setAttribute('data-graph-move', 'up')->setAttribute('aria-label', 'Move graph up'),
		(new CTag('button', true, '↓'))->setAttribute('type', 'button')->setAttribute('data-graph-move', 'down')->setAttribute('aria-label', 'Move graph down'),
		(new CTag('button', true, 'Remove'))->setAttribute('type', 'button')->setAttribute('data-graph-remove', $link['id'])->addClass('btn-link')
	]);
	$card->addItem((new CDiv([$identity, $card_actions]))->addClass('nu-graph-header'));
	$metrics = (new CDiv())->addClass('nu-graph-metrics');
	foreach ([['IN', $link['current_in_bps'], $link['in_util_pct']], ['OUT', $link['current_out_bps'], $link['out_util_pct']],
		['P95 IN', $link['p95_in_bps'], $link['p95_in_pct']], ['P95 OUT', $link['p95_out_bps'], $link['p95_out_pct']]] as [$label, $bps, $util]) {
		$metrics->addItem((new CDiv([new CSpan($label), (new CTag('strong', true, $format_bps($bps)))->addClass('nu-graph-metric__bps'),
			new CSpan($util === null ? '—' : $pct($util))]))->addClass('nu-graph-metric'));
	}
	$metrics->addItem((new CDiv([new CSpan($direction === null ? 'Remaining' : 'Remaining '.$direction),
		(new CTag('strong', true, $remaining($link['worst_headroom_bps'])))->addClass('nu-graph-metric__bps')]))->addClass('nu-graph-metric'));
	$metrics->addItem((new CDiv([new CSpan('Quality'), new CTag('strong', true, $link['errors_total'].' err · '.$link['discards_total'].' disc')]))->addClass('nu-graph-metric'));
	$card->addItem($metrics); $card->addItem((new CDiv())->addClass('nu-pinned-chart')); $graph_list->addItem($card);
}
$graphs->addItem($graph_list); $root->addItem($graphs);

$root->addItem((new CDiv())->addClass('nu-panel-backdrop')->addClass('is-hidden'));
$root->addItem((new CTag('aside', true))->addClass('nu-panel')->addClass('is-hidden')->setAttribute('aria-label', 'Link details'));
$root->addItem((new CTag('aside', true))->addClass('nu-editor')->addClass('is-hidden')->setAttribute('aria-label', 'Edit links'));
if ($data['warnings']) $root->addItem((new CDiv(implode(' · ', $data['warnings'])))->addClass('nu-warnings'));
(new CWidgetView($data))->addItem($root)->show();
