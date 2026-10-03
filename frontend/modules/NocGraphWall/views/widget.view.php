<?php declare(strict_types=1);
/** @var CView $this */
/** @var array $data */

$root = (new CDiv())->addClass('netops-noc-wall');
if ($data['error'] !== null) {
    $root->addItem((new CDiv([(new CSpan(_('NOC wall unavailable')))->addClass('ngw-error__title'), new CSpan($data['error'])]))->addClass('ngw-error'));
    (new CWidgetView($data))->addItem($root)->show();
    return;
}

$snapshot = $data['snapshot'];
$encode = static fn(array $v): string => base64_encode(json_encode($v, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));

$root
    ->setAttribute('data-generated-at', (string) $snapshot['generated_at'])
    ->setAttribute('data-refresh-seconds', '30')
    ->setAttribute('data-can-edit', $data['user']['can_edit'] ? '1' : '0')
    ->setAttribute('data-csrf-token', (string) ($data['user']['csrf_token'] ?? ''))
    ->setAttribute('data-snapshot', $encode($snapshot))
    ->setAttribute('data-configuration', $encode($data['configuration']))
    ->setAttribute('data-instrumentation', $encode($data['instrumentation']));

$header = (new CDiv())->addClass('ngw-header');
$header->addItem((new CDiv([
    new CTag('h3', true, _('NOC Graph Wall')),
    (new CSpan(_('Updated —')))->addClass('ngw-updated'),
]))->addClass('ngw-header__title'));

$ranges = (new CDiv())->addClass('ngw-ranges');
foreach ([[1,'1H'],[6,'6H'],[24,'24H'],[168,'7D']] as [$hours,$label]) {
    $ranges->addItem((new CTag('button', true, $label))
        ->setAttribute('type', 'button')
        ->setAttribute('data-hours', (string) $hours)
        ->addClass($hours === 1 ? 'is-active' : ''));
}
$header->addItem($ranges);

$actions = (new CDiv())->addClass('ngw-header__actions');
if ($data['user']['can_edit']) {
    $actions->addItem((new CTag('button', true, _('Edit wall')))->setAttribute('type', 'button')->addClass('btn-alt ngw-edit-start'));
}
$actions->addItem((new CTag('button', true, _('Full screen')))->setAttribute('type', 'button')->addClass('ngw-fullscreen'));
$header->addItem($actions);
$root->addItem($header);

$grid = (new CDiv())->addClass('ngw-grid');
foreach ($snapshot['slots'] as $slot) {
    $cell = (new CDiv())
        ->addClass('ngw-slot ngw-slot--'.strtolower($slot['state'] ?? 'ok'))
        ->setAttribute('data-position', (string) $slot['position'])
        ->setAttribute('data-kind', $slot['kind']);
    $cell->addItem((new CDiv([
        (new CSpan($slot['label']))->addClass('ngw-slot__label'),
        (new CSpan(''))->addClass('ngw-slot__value'),
    ]))->addClass('ngw-slot__header'));
    $cell->addItem((new CTag('canvas', true, ''))->addClass('ngw-slot__canvas')
        ->setAttribute('data-slot', (string) $slot['position'])
        ->setAttribute('data-series', $encode($slot['series'] ?? [])));
    if (($slot['state'] ?? 'OK') !== 'OK') {
        $cell->addItem((new CDiv((string) ($slot['notes'] ?? _('Not configured'))))->addClass('ngw-slot__hint'));
    }
    $grid->addItem($cell);
}
$root->addItem($grid);

(new CWidgetView($data))->addItem($root)->show();
