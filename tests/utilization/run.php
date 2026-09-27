<?php declare(strict_types = 1);

require_once __DIR__.'/../../frontend/modules/NetworkUtilization/config/Limits.php';
require_once __DIR__.'/../../frontend/modules/NetworkUtilization/domain/LinkUtilizationResolver.php';

use Modules\NetworkUtilization\Domain\LinkUtilizationResolver;

$resolver = new LinkUtilizationResolver();
$now = 1_800_000_000;
$settings = ['warning_util_pct'=>80.0,'critical_util_pct'=>90.0,'capacity_risk_p95_pct'=>80.0,'sustained_window_min'=>5];
$pass = 0;
$assert = static function(bool $condition, string $message) use (&$pass): void {
	if (!$condition) { fwrite(STDERR, "FAIL: {$message}\n"); exit(1); }
	$pass++;
};
$history = static function(float $value, int $count = 24) use ($now): array {
	$rows=[]; for($i=$count-1;$i>=0;$i--) $rows[]=['clock'=>$now-$i*60,'value'=>$value]; return $rows;
};
$metric = static fn(float $value, array $rows, int $clock = 0): array => ['value'=>$value,'clock'=>$clock ?: $now,'expected_interval'=>60,'history'=>$rows];
$link = static function(array $overrides = []) use ($metric,$history,$now): array {
	$base=['id'=>'wan-1','display_name'=>'WAN 1','site_id'=>'dc','site'=>'DC','site_order'=>0,'host'=>'RTR-01','host_name'=>'RTR-01','hostid'=>'1',
		'interface'=>['if_name'=>'Gi0/0','if_alias'=>'WAN','if_descr'=>''],'role'=>'WAN','order'=>0,'visible'=>true,'required'=>true,'mapping_issue'=>null,
		'metrics'=>['in'=>$metric(400.0,$history(400.0)),'out'=>$metric(900.0,$history(900.0)),'capacity'=>$metric(1000.0,$history(1000.0)),
			'admin_status'=>['value'=>1],'oper_status'=>['value'=>1],'in_errors'=>['value'=>0,'mode'=>'rate'],'out_errors'=>['value'=>0,'mode'=>'rate'],
			'in_discards'=>['value'=>0,'mode'=>'rate'],'out_discards'=>['value'=>0,'mode'=>'rate']]];
	return array_replace_recursive($base,$overrides);
};

$r=$resolver->resolveLink($link(),$settings,$now);
$assert(abs($r['in_util_pct']-40.0)<.001,'IN utilization');
$assert(abs($r['out_util_pct']-90.0)<.001,'OUT utilization');
$assert(abs($r['worst_util_pct']-90.0)<.001,'full-duplex directions are not summed');
$assert($r['worst_direction']==='OUT','worst direction');
$assert(abs($r['headroom_bps']-100.0)<.001,'headroom');
$unknown=$resolver->resolveLink($link(['metrics'=>['capacity'=>['value'=>-1,'clock'=>$now,'expected_interval'=>60,'history'=>[]]]]),$settings,$now);
$assert($unknown['capacity_bps']===null&&$unknown['worst_util_pct']===null,'unknown capacity means unknown utilization');
$assert(abs($r['p95_out_pct']-90.0)<.001,'P95');
$assert($r['sustained']===true&&$r['sustained_seconds']>=300,'sustained threshold');
$stale=$resolver->resolveLink($link(['metrics'=>['in'=>['clock'=>$now-1000],'out'=>['clock'=>$now-1000]]]),$settings,$now);
$assert($stale['data_state']==='STALE'&&$stale['current_in_bps']===null,'stale current data');
$admin=$resolver->resolveLink($link(['metrics'=>['admin_status'=>['value'=>2],'oper_status'=>['value'=>2]]]),$settings,$now);
$assert($admin['admin_status']==='DOWN'&&$admin['attention_kind']!=='LINK_DOWN','admin-down differs from oper-down');
$oper=$resolver->resolveLink($link(['metrics'=>['admin_status'=>['value'=>1],'oper_status'=>['value'=>2]]]),$settings,$now);
$assert($oper['attention_kind']==='LINK_DOWN','admin-up oper-down attention');
$assert($resolver->resetSafeDelta(100,5)===null,'counter reset safe');
$assert($resolver->resetSafeDelta(100,105)===5.0,'counter delta');
$short=$resolver->percentile(array_slice($history(50),0,5));
$assert($short===null,'tiny percentile sample rejected');
$document=$resolver->resolve([$link(['visible'=>false])],[['id'=>'dc','name'=>'DC','order'=>0]],$settings,$now);
$assert($document['summary']['MONITORED_LINKS']===1,'hidden Link still monitored');
$three=[]; for($i=0;$i<3;$i++)$three[]=$link(['id'=>'l'.$i,'interface'=>['if_name'=>'Gi0/'.$i],'metrics'=>['in'=>['clock'=>$now-1000],'out'=>['clock'=>$now-1000]]]);
$group=$resolver->resolve($three,[['id'=>'dc','name'=>'DC','order'=>0]],$settings,$now);
$assert(count($group['grouped_stale']['RTR-01'])===3&&count(array_filter($group['needs_attention'],fn($a)=>$a['kind']==='MONITORING_STALE'))===1,'grouped stale device');
$ordered=$resolver->resolve([$link(['id'=>'b','order'=>20]),$link(['id'=>'a','order'=>10,'interface'=>['if_name'=>'Gi0/1']])],[['id'=>'dc','name'=>'DC','order'=>0]],$settings,$now);
$assert(array_column($ordered['links'],'id')===['a','b'],'configured order');

echo "PASS: {$pass} utilization analytics assertions\n";
