<?php declare(strict_types = 1);
/** @var CView $this */ /** @var array $data */
$root=(new CDiv())->addClass('netops-device-health');
if($data['error']!==null){$root->addItem((new CDiv([new CTag('strong',true,'Device health data unavailable'),new CSpan($data['error'])]))->addClass('dh-error'));(new CWidgetView($data))->addItem($root)->show();return;}
$snapshot=$data['snapshot'];$encode=static fn(array $v):string=>base64_encode(json_encode($v,JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR));
$root->setAttribute('data-snapshot',$encode($snapshot))->setAttribute('data-generated-at',(string)$snapshot['generated_at'])->setAttribute('data-refresh-seconds','30')->setAttribute('data-instrumentation',$encode($data['instrumentation']));
$content=(new CDiv())->addClass('dh-content');
$content->addItem((new CDiv([(new CSpan('Updated just now'))->addClass('dh-updated')]))->addClass('dh-header'));
$toolbar=(new CDiv())->addClass('dh-toolbar');
$toolbar->addItem((new CTag('input',false))->setAttribute('type','search')->setAttribute('placeholder','Search devices')->setAttribute('aria-label','Search devices')->addClass('dh-search'));
$siteSelect=(new CTag('select',true))->addClass('dh-site-filter')->setAttribute('aria-label','Filter by Site');$siteSelect->addItem((new CTag('option',true,'All Sites'))->setAttribute('value',''));
foreach(array_keys($snapshot['sites']) as $site)$siteSelect->addItem((new CTag('option',true,$site))->setAttribute('value',$site));$toolbar->addItem($siteSelect);
$toolbar->addItem((new CTag('select',true,[(new CTag('option',true,'Configured order'))->setAttribute('value','configured'),(new CTag('option',true,'Severity'))->setAttribute('value','severity'),(new CTag('option',true,'CPU'))->setAttribute('value','cpu'),(new CTag('option',true,'Memory'))->setAttribute('value','memory'),(new CTag('option',true,'Storage'))->setAttribute('value','storage')]))->addClass('dh-sort')->setAttribute('aria-label','Sort devices'));
$content->addItem($toolbar);
$summary=(new CDiv())->addClass('dh-summary');
foreach(['CRITICAL'=>'Critical','WARNING'=>'Warning','RESOURCE'=>'Resource','HARDWARE'=>'Hardware / sensors','HA'=>'HA','UNKNOWN_STALE'=>'Unknown / stale'] as $key=>$label){$count=(int)$snapshot['summary'][$key];$summary->addItem((new CTag('button',true,[(new CSpan((string)$count))->addClass('dh-summary__count'),(new CSpan($label))->addClass('dh-summary__label')]))->setAttribute('type','button')->setAttribute('data-summary-filter',$key)->setAttribute('aria-pressed','false')->addClass('dh-summary__chip')->addClass('is-'.strtolower(str_replace('_','-',$key)))->addClass($count===0?'is-zero':'is-active'));}
$summary->addItem((new CSpan($snapshot['summary']['MONITORED'].' monitored'))->addClass('dh-monitored'));
$content->addItem($summary);
$attention=(new CDiv())->addClass('dh-attention');$attention->addItem((new CDiv([new CTag('h4',true,'Needs Attention'),(new CSpan(count($snapshot['needs_attention']).' '.(count($snapshot['needs_attention'])===1?'item':'items')))->addClass('dh-section-count')]))->addClass('dh-section-title'));
if($snapshot['needs_attention']===[])$attention->addItem((new CDiv('No active health issues'))->addClass('dh-all-clear'));
foreach(array_slice($snapshot['needs_attention'],0,8) as $issue){$sev=(int)$issue['severity'];$row=(new CTag('button',true))->setAttribute('type','button')->setAttribute('data-device-details',(string)$issue['device_id'])->addClass('dh-attention-row')->addClass('is-severity-'.$sev);
	$row->addItem((new CDiv([(new CSpan($issue['device']))->addClass('dh-attention-row__name'),(new CSpan($issue['site'].' · '.ucwords(str_replace('_',' ',$issue['category']))))->addClass('dh-attention-row__meta')]))->addClass('dh-attention-row__identity'));
	$row->addItem((new CDiv([(new CSpan($issue['name']))->addClass('dh-attention-row__reason'),(new CSpan($issue['acknowledged']?'Acknowledged':'Unacknowledged'))->addClass('dh-attention-row__ack')]))->addClass('dh-attention-row__state'));$attention->addItem($row);}
if(count($snapshot['needs_attention'])>8)$attention->addItem((new CSpan('+'.(count($snapshot['needs_attention'])-8).' more'))->addClass('dh-more'));
$content->addItem($attention);
$matrix=(new CDiv())->addClass('dh-matrix');$matrix->addItem((new CDiv([new CTag('h4',true,'Device health matrix')]))->addClass('dh-section-title'));
$metricLabel=['cpu'=>'CPU','memory'=>'Memory','temperature'=>'Temperature','storage'=>'Storage','power_fan'=>'Power / Fan','ha'=>'HA'];
$format=static function(array $m):string{if($m['data_state']==='NOT_APPLICABLE')return '—';if($m['data_state']==='NO_DATA')return $m['grace_active']?'Pending data':'No data';if($m['data_state']==='STALE')return 'Stale'.($m['age']!==null?' · '.max(1,(int)ceil($m['age']/60)).'m':'');if($m['value']===null)return '—';$unit=trim((string)$m['units']);return number_format((float)$m['value'],((float)$m['value']<10?1:0)).($unit!==''?' '.$unit:'');};
foreach($snapshot['sites'] as $site=>$devices){$siteBox=(new CTag('section',true))->addClass('dh-site')->setAttribute('data-site',$site);$problemCount=count(array_filter($devices,static fn($d)=>$d['state']!=='HEALTHY'));
	$siteBox->addItem((new CTag('button',true,[(new CSpan($site))->addClass('dh-site__name'),(new CSpan(count($devices).' '.(count($devices)===1?'device':'devices').' · '.$problemCount.' '.($problemCount===1?'issue':'issues')))->addClass('dh-site__summary')]))->setAttribute('type','button')->setAttribute('aria-expanded','true')->addClass('dh-site__header'));
	$table=(new CTag('table',true))->addClass('dh-table');$head=(new CTag('tr',true));foreach(array_merge(['Device'],array_values($metricLabel),['State / reason']) as $label)$head->addItem(new CTag('th',true,$label));$table->addItem((new CTag('thead',true,$head)));
	$body=(new CTag('tbody',true));foreach($devices as $device){$row=(new CTag('tr',true))->setAttribute('data-device-id',$device['hostid'])->setAttribute('data-site-name',$device['site'])->setAttribute('data-state',$device['state'])->setAttribute('data-search',strtolower($device['name'].' '.$device['host'].' '.$device['site'].' '.$device['profile']))->setAttribute('data-severity',(string)$device['severity'])->addClass('is-'.$device['state']);
		$identity=(new CTag('button',true,[(new CSpan($device['availability']==='UP'?'●':($device['availability']==='DOWN'?'○':'◌')))->addClass('dh-availability is-'.strtolower($device['availability'])),(new CSpan($device['name']))->addClass('dh-device-name'),(new CSpan(ucwords(str_replace('_',' ',$device['profile']))))->addClass('dh-device-profile')]))->setAttribute('type','button')->setAttribute('data-device-details',$device['hostid'])->addClass('dh-device-button');$row->addItem(new CTag('td',true,$identity));
		foreach(array_keys($metricLabel) as $metric){$m=$device['columns'][$metric];$cell=(new CTag('td',true))->setAttribute('data-label',$metricLabel[$metric])->addClass('dh-metric')->addClass('is-data-'.strtolower($m['data_state']))->addClass('is-severity-'.$m['severity']);$cell->addItem((new CSpan($format($m)))->addClass('dh-metric__value'));
			if($m['data_state']==='CURRENT'&&is_numeric($m['value'])&&in_array($metric,['cpu','memory','storage'],true))$cell->addItem((new CDiv((new CSpan())->setAttribute('style','width:'.max(0,min(100,(float)$m['value'])).'%')))->addClass('dh-microbar'));$row->addItem($cell);}
		$reason=$device['reasons'][0]??($device['state']==='HEALTHY'?'No active trigger problems':'Data status requires review');if(count($device['reasons'])>1)$reason.=' +'.(count($device['reasons'])-1);$row->addItem((new CTag('td',true,[(new CSpan($device['state']))->addClass('dh-state'),(new CSpan($reason))->addClass('dh-reason')]))->setAttribute('data-label','State / reason'));$body->addItem($row);}
	$table->addItem($body);$siteBox->addItem((new CDiv($table))->addClass('dh-table-wrap'));$matrix->addItem($siteBox);}
$content->addItem($matrix);
$content->addItem((new CDiv())->addClass('dh-panel-backdrop')->addClass('is-hidden'));
$content->addItem((new CTag('aside',true))->addClass('dh-details')->addClass('is-hidden')->setAttribute('aria-label','Device health details'));
$content->addItem((new CDiv([(new CSpan('Monitoring view is not updating'))->addClass('dh-self-stale__title'),(new CSpan('—'))->addClass('dh-self-stale__age')]))->addClass('dh-self-stale')->addClass('is-hidden'));
if($data['warnings']!==[])$content->addItem((new CDiv(implode(' · ',$data['warnings'])))->addClass('dh-warnings'));
$root->addItem($content);(new CWidgetView($data))->addItem($root)->show();
