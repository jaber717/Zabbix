<?php declare(strict_types = 1);

/* Isolated bulk-API performance contract for 0/1/5/10 pinned graphs. */
final class MockApiResource {
	public function __construct(private string $kind) {}
	public function get(array $params): array {
		MockApi::$calls++;
		return match ($this->kind) {
			'host' => MockApi::$hosts,
			'item' => MockApi::$items,
			'history' => MockApi::$history,
			'trend' => MockApi::$trends
		};
	}
}
final class MockApi {
	public static int $calls = 0;
	public static array $hosts = [], $items = [], $history = [], $trends = [];
}
final class API {
	public static function Host(): MockApiResource { return new MockApiResource('host'); }
	public static function Item(): MockApiResource { return new MockApiResource('item'); }
	public static function History(): MockApiResource { return new MockApiResource('history'); }
	public static function Trend(): MockApiResource { return new MockApiResource('trend'); }
}

require_once __DIR__.'/../../frontend/modules/NetworkUtilization/config/Limits.php';
require_once __DIR__.'/../../frontend/modules/NetworkUtilization/config/LinkDefinitionRepository.php';
require_once __DIR__.'/../../frontend/modules/NetworkUtilization/collector/LinkUtilizationCollectorInterface.php';
require_once __DIR__.'/../../frontend/modules/NetworkUtilization/collector/ZabbixLinkUtilizationCollector.php';
require_once __DIR__.'/../../frontend/modules/NetworkUtilization/domain/LinkUtilizationResolver.php';

use Modules\NetworkUtilization\Collector\ZabbixLinkUtilizationCollector;
use Modules\NetworkUtilization\Config\LinkDefinitionRepository;
use Modules\NetworkUtilization\Domain\LinkUtilizationResolver;

$now = 1_800_000_000;
MockApi::$hosts = ['1'=>['hostid'=>'1','host'=>'RTR-01','name'=>'RTR-01','maintenance_status'=>'0']];
$itemid = 1000;
for ($index=0; $index<10; $index++) {
	$name = "Gi0/{$index}";
	foreach ([['in',20_000_000+$index*1_000_000],['out',30_000_000+$index*1_000_000]] as [$direction,$value]) {
		$id=(string) $itemid++;
		MockApi::$items[]=['itemid'=>$id,'hostid'=>'1','name'=>"Interface [{$name}]: Bits {$direction}",
			'key_'=>"net.if.{$direction}[\"{$name}\"]",'units'=>'bps','value_type'=>3,'delay'=>'60s','lastclock'=>(string)($now-10),
			'lastvalue'=>(string)$value,'state'=>'0','error'=>'','preprocessing'=>[['type'=>'10']]];
		for($sample=0;$sample<24;$sample++) MockApi::$history[]=['itemid'=>$id,'clock'=>(string)($now-$sample*3600),'value'=>(string)($value+$sample*1000)];
		for($day=0;$day<7;$day++) MockApi::$trends[]=['itemid'=>$id,'clock'=>(string)($now-$day*86400),'num'=>'60','value_avg'=>(string)$value,'value_max'=>(string)($value+1000)];
	}
	$id=(string) $itemid++;
	MockApi::$items[]=['itemid'=>$id,'hostid'=>'1','name'=>"Interface [{$name}]: Speed",'key_'=>"net.if.speed[\"{$name}\"]",'units'=>'bps',
		'value_type'=>3,'delay'=>'1h','lastclock'=>(string)($now-10),'lastvalue'=>'1000000000','state'=>'0','error'=>'','preprocessing'=>[]];
}

$settings=['warning_util_pct'=>80,'critical_util_pct'=>90,'capacity_risk_p95_pct'=>80,'sustained_window_min'=>5];
$results=[];
foreach([0,1,5,10] as $pinned) {
	$directory=sys_get_temp_dir().'/nu-perf-'.bin2hex(random_bytes(5));mkdir($directory,0700,true);$path=$directory.'/link-definitions.json';
	$links=[];
	for($index=0;$index<10;$index++) $links[]=['id'=>'link-'.$index,'display_name'=>'Link '.$index,'site_id'=>'lab','host'=>'RTR-01',
		'interface'=>['if_name'=>"Gi0/{$index}",'if_alias'=>'','if_descr'=>''],'role'=>'UPLINK','order'=>$index*10,'visible'=>true,
		'show_graph'=>$index<$pinned,'graph_order'=>$index*10,'required'=>true,'capacity_source'=>'interface_speed'];
	file_put_contents($path,json_encode(['schema'=>LinkDefinitionRepository::SCHEMA,'revision'=>1,'settings'=>$settings,
		'sites'=>[['id'=>'lab','name'=>'LAB','order'=>0]],'links'=>$links],JSON_THROW_ON_ERROR));
	MockApi::$calls=0;$started=hrtime(true);
	$collected=(new ZabbixLinkUtilizationCollector(new LinkDefinitionRepository($path)))->collect($now);
	$analytics=hrtime(true);$snapshot=(new LinkUtilizationResolver())->resolve($collected['links'],$collected['sites'],$settings,$now);
	$total=round((hrtime(true)-$started)/1_000_000,3);$analytics_ms=round((hrtime(true)-$analytics)/1_000_000,3);
	if($collected['instrumentation']['api_call_count']!==4||MockApi::$calls!==4)throw new RuntimeException("{$pinned} graphs caused API call growth");
	if(count($snapshot['pinned_links'])!==$pinned)throw new RuntimeException("{$pinned} graph selection mismatch");
	$results[(string)$pinned]=$collected['instrumentation']+['analytics_time_ms'=>$analytics_ms,'total_widget_time_ms'=>$total];
	unlink($path);rmdir($directory);
}
if(count(array_unique(array_column($results,'api_call_count')))!==1)throw new RuntimeException('Pinned count changed API call count');
echo 'PERFORMANCE='.json_encode($results,JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR)."\nRESULT=PASS\n";
