<?php declare(strict_types = 1);

namespace Modules\NetworkUtilization\Collector;

use API;
use Modules\NetworkUtilization\Config\Limits;
use Modules\NetworkUtilization\Config\LinkDefinitionRepository;
use Throwable;

final class ZabbixLinkUtilizationCollector implements LinkUtilizationCollectorInterface {
	private int $api_calls = 0;
	public function __construct(private readonly LinkDefinitionRepository $definitions) {}

	public function collect(int $now): array {
		$started = hrtime(true); $this->api_calls = 0; $config = $this->definitions->loadDocument(); $warnings = $this->definitions->warnings();
		$sites = array_column($config['sites'], null, 'id');
		$this->api_calls++;
		$hosts = API::Host()->get(['output'=>['hostid','host','name','maintenance_status'], 'monitored_hosts'=>true,
			'limit'=>Limits::MAX_HOSTS, 'preservekeys'=>true]);
		$hosts_by_name = []; foreach ($hosts as $id => $host) { $host['hostid']=(string)$id; $hosts_by_name[$host['host']]=$host; }
		$this->api_calls++;
		$items = API::Item()->get(['output'=>['itemid','hostid','name','key_','units','value_type','delay','lastclock','lastvalue','state','error'],
			'selectPreprocessing'=>'extend', 'hostids'=>array_keys($hosts), 'filter'=>['status'=>0], 'limit'=>Limits::MAX_DISCOVERY_ITEMS]);
		if (count($items) >= Limits::MAX_DISCOVERY_ITEMS) $warnings[]='Interface item discovery reached its bounded limit.';
		$catalog = []; $item_by_id = [];
		foreach ($items as $item) {
			$item['itemid']=(string)$item['itemid']; $item_by_id[$item['itemid']]=$item; $identity=$this->interfaceIdentity($item);
			if ($identity !== null) $catalog[(string)$item['hostid']][$identity['if_name']][]=$item+$identity;
		}
		$links=[]; $history_ids=[];
		foreach ($config['links'] as $definition) {
			$site=$sites[$definition['site_id']]; $raw=$definition+['site'=>$site['name'],'site_order'=>$site['order'],'host_name'=>$definition['host'],
				'current_ifindex'=>null,'current_alias'=>$definition['interface']['if_alias'],'metrics'=>[],'mapping_issue'=>null];
			$host=$hosts_by_name[$definition['host']]??null;
			if ($host===null) { $raw['mapping_issue']='Configured Host is not visible'; $links[]=$raw; continue; }
			$matches=$catalog[$host['hostid']][$definition['interface']['if_name']]??[];
			if ($matches===[]) { $raw['mapping_issue']='Interface name is not currently resolved'; $links[]=$raw; continue; }
			$raw['hostid']=$host['hostid']; $raw['host_name']=$host['name'];
			foreach ($matches as $item) {
				$type=$this->metricType($item); if ($type===null) continue;
				if (isset($raw['metrics'][$type])) { $raw['mapping_issue']="Ambiguous {$type} items for exact interface name"; continue; }
				$metric=$this->metric($item,$type); if ($metric===null) { if (in_array($type,['in','out'],true)) $raw['mapping_issue']='Traffic Item units/preprocessing are unsupported'; continue; }
				$raw['metrics'][$type]=$metric; $history_ids[$item['value_type']][]=$item['itemid'];
				$raw['current_ifindex']=$raw['current_ifindex']??$this->ifIndex($item['key_']);
				$raw['current_alias']=$raw['current_alias']?:($item['if_alias']??'');
			}
			if (!isset($raw['metrics']['in'],$raw['metrics']['out']) && $raw['mapping_issue']===null) $raw['mapping_issue']='Traffic Items are missing for the exact interface name';
			$links[]=$raw;
		}
		$history_rows=0; $history_by_item=[];
		foreach ($history_ids as $value_type=>$ids) {
			$ids=array_values(array_unique($ids)); if ($ids===[]) continue; $this->api_calls++;
			$rows=API::History()->get(['output'=>['itemid','clock','value'],'history'=>(int)$value_type,'itemids'=>$ids,
				'time_from'=>$now-Limits::P95_WINDOW_S,'sortfield'=>['itemid','clock'],'sortorder'=>'ASC','limit'=>Limits::MAX_HISTORY_ROWS]);
			$history_rows+=count($rows); if (count($rows)>=Limits::MAX_HISTORY_ROWS) $warnings[]='24-hour history reached its bounded limit; affected P95 values are unavailable.';
			foreach ($rows as $row) $history_by_item[(string)$row['itemid']][]=['clock'=>(int)$row['clock'],'value'=>(float)$row['value']];
		}
		$trend_rows=0; $traffic_ids=[]; foreach ($links as $link) foreach (['in','out'] as $type) if (isset($link['metrics'][$type])) $traffic_ids[]=$link['metrics'][$type]['itemid'];
		$trends=[]; if ($traffic_ids!==[]) { $this->api_calls++; try {
			$trends=API::Trend()->get(['output'=>['itemid','clock','num','value_avg','value_max'],'itemids'=>array_values(array_unique($traffic_ids)),
				'time_from'=>$now-7*86400,'sortfield'=>['itemid','clock'],'sortorder'=>'ASC','limit'=>20000]); $trend_rows=count($trends);
		} catch(Throwable $e) { $warnings[]='Seven-day trends unavailable: '.$e->getMessage(); } }
		$trend_by_item=[]; foreach($trends as $row) $trend_by_item[(string)$row['itemid']][]=$row;
		foreach ($links as &$link) foreach ($link['metrics'] as &$metric) {
			$factor=$metric['factor']; $metric['history']=array_map(static fn($row)=>['clock'=>$row['clock'],'value'=>$row['value']*$factor],$history_by_item[$metric['itemid']]??[]);
			$metric['trends_7d']=array_map(static fn($row)=>['clock'=>(int)$row['clock'],'value'=>(float)$row['value_avg']*$factor],$trend_by_item[$metric['itemid']]??[]);
		}
		unset($link,$metric);
		$candidates=[]; foreach ($catalog as $hostid=>$interfaces) foreach ($interfaces as $if_name=>$candidate_items) {
			$host=$hosts[$hostid]; $types=[]; $alias=''; $capacity=null; $status=null;
			foreach($candidate_items as $item){$t=$this->metricType($item); if($t)$types[$t]=true; $alias=$alias?:($item['if_alias']??''); if($t==='capacity'&&is_numeric($item['lastvalue'])&&(float)$item['lastvalue']>0)$capacity=(float)$item['lastvalue']; if($t==='oper_status')$status=$item['lastvalue'];}
			if(isset($types['in'])||isset($types['out'])) $candidates[]=['hostid'=>(string)$hostid,'host'=>$host['host'],'host_name'=>$host['name'],'if_name'=>$if_name,
				'if_alias'=>$alias,'ifindex'=>$this->ifIndex($candidate_items[0]['key_']),'capacity_bps'=>$capacity,'oper_status'=>$status,'metric_types'=>array_keys($types)];
		}
		return ['configuration'=>$config,'links'=>$links,'sites'=>$config['sites'],'candidates'=>$candidates,'warnings'=>$warnings,
			'instrumentation'=>['api_call_count'=>$this->api_calls,'hosts_retrieved'=>count($hosts),'links_configured'=>count($links),
				'items_retrieved'=>count($items),'history_rows'=>$history_rows,'trend_rows'=>$trend_rows,
				'collector_time_ms'=>round((hrtime(true)-$started)/1_000_000,3)]];
	}

	private function interfaceIdentity(array $item): ?array {
		$name=(string)$item['name']; $key=(string)$item['key_']; $if_name=''; $alias='';
		if (preg_match('/^net\.if\.(?:in|out)\["([^"]+)"/', $key,$m)) $if_name=$m[1];
		elseif (preg_match('/^Interface \[([^\]]+)\]:/', $name,$m)) $if_name=$m[1];
		elseif (preg_match('/^Interface ([^(]+)\(([^)]*)\):/', $name,$m)) { $if_name=trim($m[1]); $alias=trim($m[2]); }
		elseif (preg_match('/^Interface ([^:]+):/', $name,$m)) $if_name=trim($m[1]);
		return $if_name===''?null:['if_name'=>$if_name,'if_alias'=>$alias];
	}
	private function metricType(array $item): ?string {
		$key=strtolower((string)$item['key_']); $name=strtolower((string)$item['name']);
		if (str_contains($key,'net.if.speed')||str_contains($key,'/speed"]')) return 'capacity';
		if (str_contains($key,'admin')&&str_contains($key,'status')) return 'admin_status';
		if (str_contains($key,'net.if.status')||str_contains($key,'operstate')) return 'oper_status';
		if (str_contains($key,'discards')||str_contains($key,'dropped')||str_contains($key,'.drops')) return str_contains($key,'.out')?'out_discards':'in_discards';
		if (str_contains($key,'errors')||str_contains($key,'.error')) return str_contains($key,'.out')?'out_errors':'in_errors';
		if ((str_starts_with($key,'net.if.in[')||str_contains($key,'bigip.net.in.bytes.rate')) && (($item['units']??'')==='bps'||($item['units']??'')==='Bps')) return 'in';
		if ((str_starts_with($key,'net.if.out[')||str_contains($key,'bigip.net.out.bytes.rate')) && (($item['units']??'')==='bps'||($item['units']??'')==='Bps')) return 'out';
		return null;
	}
	private function metric(array $item,string $type): ?array {
		$units=(string)($item['units']??''); $factor=1.0;
		$pre=array_column($item['preprocessing']??[],'type'); $mode=(in_array('10',array_map('strval',$pre),true)||in_array(10,$pre,true))?'rate':'counter';
		if(in_array($type,['in','out'],true)){
			if($units==='Bps')$factor=8.0; elseif($units!=='bps')return null;
			// Raw octet/counter values are not current traffic rates. Refuse them instead
			// of inventing semantics; the operator will see a configuration issue.
			if($mode!=='rate')return null;
		}
		return ['itemid'=>(string)$item['itemid'],'key'=>(string)$item['key_'],'units'=>$units,'value'=>is_numeric($item['lastvalue'])?(float)$item['lastvalue']*$factor:null,
			'clock'=>(int)$item['lastclock'],'expected_interval'=>$this->delay((string)$item['delay']),'value_type'=>(int)$item['value_type'],'factor'=>$factor,
			'mode'=>$mode,'fresh'=>(int)$item['lastclock']>0,'status_family'=>str_contains($item['key_'],'operstate')?'linux':'ifmib','history'=>[]];
	}
	private function delay(string $delay): int { if(preg_match('/^(\d+)([smhd]?)$/',$delay,$m)){return (int)$m[1]*([''=>1,'s'=>1,'m'=>60,'h'=>3600,'d'=>86400][$m[2]]);} return 60; }
	private function ifIndex(string $key): ?int { return preg_match('/\.(\d+)(?:\]|$)/',$key,$m)?(int)$m[1]:(preg_match('/\[(\d+)\]/',$key,$m)?(int)$m[1]:null); }
}
