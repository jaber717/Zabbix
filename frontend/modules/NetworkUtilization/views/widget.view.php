<?php declare(strict_types = 1);

/** @var CView $this */
/** @var array $data */

$root=(new CDiv())->addClass('netops-utilization');
if($data['error']!==null){$root->addItem((new CDiv([(new CSpan('Utilization data unavailable'))->addClass('nu-error__title'),new CSpan($data['error'])]))->addClass('nu-error'));(new CWidgetView($data))->addItem($root)->show();return;}
$snapshot=$data['snapshot'];
$encode=static fn(array $value):string=>base64_encode(json_encode($value,JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR));
$root->setAttribute('data-generated-at',(string)$snapshot['generated_at'])->setAttribute('data-refresh-seconds','60')
	->setAttribute('data-can-edit',$data['user']['can_edit']?'1':'0')->setAttribute('data-csrf-token',(string)($data['user']['csrf_token']??''))
	->setAttribute('data-snapshot',$encode($snapshot))->setAttribute('data-configuration',$encode($data['configuration']))
	->setAttribute('data-candidates',$encode($data['candidates']))->setAttribute('data-instrumentation',$encode($data['instrumentation']));
$format_bps=static function(?float $value):string{if($value===null)return 'Unknown';foreach([[1e9,'Gbps'],[1e6,'Mbps'],[1e3,'Kbps'],[1,'bps']]as[$scale,$unit])if($value>=$scale)return rtrim(rtrim(number_format($value/$scale,$value/$scale>=100?0:($value/$scale>=10?1:2),'.',''),'0'),'.').' '.$unit;return '0 bps';};
$pct=static fn(?float $v):string=>$v===null?'Unknown':number_format($v,1).'%';
$root->addItem((new CDiv([(new CSpan('Monitoring view is not updating'))->addClass('nu-stale__title'),new CSpan(' Last successful update: '),(new CSpan('—'))->addClass('nu-stale__age')]))->addClass('nu-stale')->addClass('is-hidden'));
$toolbar=(new CDiv())->addClass('nu-toolbar');
$toolbar->addItem((new CTag('input',false))->setAttribute('type','search')->setAttribute('placeholder','Search Links, Sites or Devices')->addClass('nu-search'));
$toolbar->addItem((new CTag('select',true,[new CTag('option',true,'All sites')]))->addClass('nu-site-filter'));
$toolbar->addItem((new CTag('select',true,[new CTag('option',true,'All roles')]))->addClass('nu-role-filter'));
$toolbar->addItem((new CDiv([(new CSpan(''))->addClass('nu-filter-label'),(new CTag('button',true,'Clear'))->setAttribute('type','button')->addClass('nu-filter-clear')]))->addClass('nu-filter-chip')->addClass('is-hidden'));
if($data['user']['can_edit'])$toolbar->addItem((new CTag('button',true,'Edit links'))->setAttribute('type','button')->addClass('btn-alt')->addClass('nu-edit-start'));
$root->addItem($toolbar);
$summary=(new CDiv())->addClass('nu-summary');
foreach(['HOT_NOW'=>'HOT NOW','SUSTAINED'=>'SUSTAINED','ERRORS_DISCARDS'=>'ERRORS / DISCARDS','CAPACITY_RISK'=>'CAPACITY RISK','UNKNOWN_STALE'=>'UNKNOWN / STALE','MONITORED_LINKS'=>'MONITORED LINKS']as$key=>$label){$value=$snapshot['summary'][$key];$summary->addItem((new CTag('button',true,[(new CSpan($label))->addClass('nu-summary__label'),(new CSpan((string)$value))->addClass('nu-summary__value')]))->setAttribute('type','button')->setAttribute('data-filter',$key)->addClass('nu-summary__item')->addClass($value?'has-value':'is-zero'));}
$root->addItem($summary);
$attention=(new CDiv())->addClass('nu-attention')->addItem(new CTag('h4',true,'Needs attention'));
if($snapshot['needs_attention']===[])$attention->addItem((new CDiv('No configured Links need attention'))->addClass('nu-calm'));
else foreach(array_slice($snapshot['needs_attention'],0,5)as$row)$attention->addItem((new CTag('button',true,[(new CSpan(str_replace('_',' ',$row['kind'])))->addClass('nu-attention__kind'),(new CSpan($row['label']))->addClass('nu-attention__name'),(new CSpan($row['detail']))->addClass('nu-attention__detail')]))->setAttribute('type','button')->setAttribute('data-link-id',(string)($row['link_id']??''))->addClass('nu-attention__row'));
if(count($snapshot['needs_attention'])>5)$attention->addItem((new CSpan('+'.(count($snapshot['needs_attention'])-5).' more'))->addClass('nu-more'));
$root->addItem($attention);
$section=(new CDiv())->addClass('nu-top')->addItem(new CTag('h4',true,'Top utilized links'));
$sort=(new CDiv([new CSpan('Sort: ')]))->addClass('nu-sort');foreach(['current'=>'Current','p95'=>'P95','headroom'=>'Headroom','errors'=>'Errors','discards'=>'Discards']as$key=>$label)$sort->addItem((new CTag('button',true,$label))->setAttribute('type','button')->setAttribute('data-sort',$key)->addClass($key==='current'?'is-active':''));$section->addItem($sort);
$table=(new CTag('table',true))->addClass('nu-table');$table->addItem(new CTag('thead',true,new CTag('tr',true,array_map(static fn($h)=>new CTag('th',true,$h),['Link','Site','Device','Capacity','IN','OUT','P95 24H','Headroom','Errors / Discards']))));$body=new CTag('tbody',true);
foreach($snapshot['links']as$link){if(!$link['visible'])continue;$current=$link['worst_util_pct']??-1;$body->addItem((new CTag('tr',true,[new CTag('td',true,[(new CTag('button',true,$link['display_name']))->setAttribute('type','button')->addClass('nu-link-open'),(new CDiv($link['interface']['if_name']))->addClass('nu-subtle')]),new CTag('td',true,$link['site']),new CTag('td',true,$link['host_name']),new CTag('td',true,$format_bps($link['capacity_bps'])),new CTag('td',true,[$pct($link['in_util_pct']),(new CDiv($format_bps($link['current_in_bps'])))->addClass('nu-subtle')]),new CTag('td',true,[$pct($link['out_util_pct']),(new CDiv($format_bps($link['current_out_bps'])))->addClass('nu-subtle')]),new CTag('td',true,$pct($link['p95_worst_pct'])),new CTag('td',true,$format_bps($link['headroom_bps'])),new CTag('td',true,$link['errors_total'].' / '.$link['discards_total'])]))->setAttribute('data-link-id',$link['id'])->setAttribute('data-current',(string)$current)->setAttribute('data-p95',(string)($link['p95_worst_pct']??-1))->setAttribute('data-headroom',(string)($link['headroom_bps']??PHP_INT_MAX))->setAttribute('data-errors',(string)$link['errors_total'])->setAttribute('data-discards',(string)$link['discards_total'])->setAttribute('data-site',$link['site_id'])->setAttribute('data-role',$link['role'])->setAttribute('data-search',strtolower($link['display_name'].' '.$link['host'].' '.$link['interface']['if_name'].' '.$link['site'])));}
$table->addItem($body);$section->addItem($table);
if($snapshot['links']===[])$section->addItem((new CDiv('No Links are configured. Use Edit links to select operationally important interfaces.'))->addClass('nu-onboarding'));
$root->addItem($section);
$sites=(new CDiv())->addClass('nu-sites')->addItem(new CTag('h4',true,'Sites'));
foreach($snapshot['sites']as$site){$visible_links=array_values(array_filter($site['links'],static fn($link)=>$link['visible']));$site_box=(new CDiv())->addClass('nu-site')->addClass($site['attention']?'is-affected':'is-collapsed')->setAttribute('data-site-id',$site['id']);$site_box->addItem((new CTag('button',true,[$site['name'],(new CSpan(count($visible_links).' links'.($site['attention']?' · '.$site['attention'].' attention':'')))->addClass('nu-site__count')]))->setAttribute('type','button')->addClass('nu-site__header'));$rows=(new CDiv())->addClass('nu-site__links');foreach($visible_links as$link)$rows->addItem((new CTag('button',true,[$link['display_name'],(new CSpan(($link['worst_direction']??'').' '.$pct($link['worst_util_pct'])))->addClass('nu-site__metric')]))->setAttribute('type','button')->setAttribute('data-link-id',$link['id'])->addClass('nu-site-link'));$site_box->addItem($rows);$sites->addItem($site_box);}
$root->addItem($sites);
$root->addItem((new CDiv())->addClass('nu-panel-backdrop')->addClass('is-hidden'));
$root->addItem((new CTag('aside',true))->addClass('nu-panel')->addClass('is-hidden')->setAttribute('aria-label','Link details'));
$root->addItem((new CTag('aside',true))->addClass('nu-editor')->addClass('is-hidden')->setAttribute('aria-label','Edit links'));
if($data['warnings'])$root->addItem((new CDiv(implode(' · ',$data['warnings'])))->addClass('nu-warnings'));
(new CWidgetView($data))->addItem($root)->show();
