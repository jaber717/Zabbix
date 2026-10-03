<?php declare(strict_types=1);
/** @var CView $this */
/** @var array $data */

$root = (new CDiv())->addClass('netops-flow-search')
    ->setAttribute('data-csrf-token', (string) ($data['user']['csrf_token'] ?? ''))
    ->setAttribute('data-defaults', base64_encode(json_encode($data['defaults'])));

$toolbar = (new CDiv())->addClass('fs-toolbar');
foreach ([[15,'15M'],[60,'1H'],[360,'6H'],[1440,'24H']] as [$m,$lbl]) {
    $toolbar->addItem((new CTag('button', true, $lbl))->setAttribute('type', 'button')
        ->setAttribute('data-minutes', (string) $m)->addClass($m === 60 ? 'is-active' : ''));
}
$toolbar->addItem((new CTag('button', true, _('Run')))->setAttribute('type', 'button')->addClass('btn fs-run'));
$root->addItem($toolbar);

$filters = (new CDiv())->addClass('fs-filters');
foreach ([
    'src_ip' => _('Source IP'),
    'dst_ip' => _('Destination IP'),
    'src_cidr' => _('Source CIDR'),
    'dst_cidr' => _('Destination CIDR'),
    'src_port' => _('Source port'),
    'dst_port' => _('Destination port'),
    'protocol' => _('Protocol'),
    'exporter' => _('Exporter'),
    'interface' => _('Interface'),
] as $name => $label) {
    $filters->addItem((new CDiv([
        (new CTag('label', true, $label)),
        (new CTag('input', false))->setAttribute('type', 'text')->setAttribute('name', $name)->setAttribute('autocomplete', 'off'),
    ]))->addClass('fs-filter'));
}
$root->addItem($filters);

$summary = (new CDiv())->addClass('fs-summary is-empty')
    ->addItem((new CDiv((new CTag('span', true, '—'))))->addClass('fs-summary__traffic'))
    ->addItem((new CDiv((new CTag('span', true, '—'))))->addClass('fs-summary__packets'))
    ->addItem((new CDiv((new CTag('span', true, '—'))))->addClass('fs-summary__flows'))
    ->addItem((new CDiv((new CTag('span', true, '—'))))->addClass('fs-summary__peak'));
$root->addItem($summary);

$topn = (new CDiv())->addClass('fs-topn');
foreach (['source','destination','conversation','port','protocol','exporter','ingress'] as $facet) {
    $topn->addItem((new CDiv())->addClass('fs-topn__panel')->setAttribute('data-facet', $facet)
        ->addItem(new CTag('h4', true, ucfirst($facet)))
        ->addItem((new CTag('ol', true, ''))->addClass('fs-topn__list')));
}
$root->addItem($topn);

$results = (new CDiv())->addClass('fs-results');
$results->addItem((new CTag('table', true, ''))->addClass('fs-results__table')
    ->addItem((new CTag('thead', true,
        (new CTag('tr', true,
            implode('', array_map(static fn($h) => '<th>'.$h.'</th>',
                ['Time','Source','Destination','SrcPort','DstPort','Proto','Bytes','Packets','Exporter','Ingress','Egress'])
            )
        ))
    ))->addClass('fs-results__thead'))
    ->addItem((new CTag('tbody', true, ''))->addClass('fs-results__tbody')));
$results->addItem((new CDiv([
    (new CTag('button', true, _('Prev')))->setAttribute('type', 'button')->addClass('fs-page-prev'),
    (new CTag('span', true, '—'))->addClass('fs-page-indicator'),
    (new CTag('button', true, _('Next')))->setAttribute('type', 'button')->addClass('fs-page-next'),
]))->addClass('fs-results__pager'));
$root->addItem($results);

(new CWidgetView($data))->addItem($root)->show();
