<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Collector;

use API;
use Modules\DeviceHealth\Config\FirstObservedRepository;
use Modules\DeviceHealth\Config\HealthConfigRepository;
use Modules\DeviceHealth\Config\Limits;
use Modules\DeviceHealth\Domain\IssueNormalizer;
use Modules\DeviceHealth\Domain\ItemClassifier;
use Modules\DeviceHealth\Domain\MetricFreshnessPolicy;

final class ZabbixDeviceHealthCollector {
	private int $api_calls = 0;
	public function __construct(
		private readonly HealthConfigRepository $configuration,
		private readonly FirstObservedRepository $first_observed,
		private readonly MetricFreshnessPolicy $freshness,
		private readonly ItemClassifier $classifier,
		private readonly IssueNormalizer $issues
	) {}
	public function collect(int $now): array {
		$started = hrtime(true); $config = $this->configuration->load(); $warnings = [];
		$this->api_calls++; $hosts = API::Host()->get([
			'output'=>['hostid','host','name','maintenance_status'],'selectParentTemplates'=>['templateid','name'],
			'selectHostGroups'=>['groupid','name'],'selectTags'=>['tag','value'],'selectInterfaces'=>['interfaceid','type','available','error'],
			'monitored_hosts'=>true,'limit'=>Limits::MAX_HOSTS,'preservekeys'=>true
		]);
		$this->api_calls++; $items = API::Item()->get([
			'output'=>['itemid','hostid','name','key_','units','value_type','delay','lastclock','lastvalue','state','error','master_itemid','flags','status'],
			'hostids'=>array_keys($hosts),'filter'=>['status'=>0],'limit'=>Limits::MAX_ITEMS
		]);
		if (count($items) >= Limits::MAX_ITEMS) $warnings[] = 'Item discovery reached its bounded limit; snapshot may be incomplete.';
		$this->api_calls++; $triggers = API::Trigger()->get([
			'output'=>['triggerid','description','priority','value','lastchange'],'selectHosts'=>['hostid'],'selectItems'=>['itemid','hostid','key_'],
			'hostids'=>array_keys($hosts),'filter'=>['value'=>1],'monitored'=>true,'limit'=>Limits::MAX_PROBLEMS
		]);
		$this->api_calls++; $problems = API::Problem()->get([
			'output'=>['eventid','objectid','clock','name','severity','acknowledged','suppressed'],
			'hostids'=>array_keys($hosts),'suppressed'=>null,'symptom'=>false,'limit'=>Limits::MAX_PROBLEMS
		]);
		$items_by_id=[]; $items_by_host=[]; foreach($items as $item){$items_by_id[(string)$item['itemid']]=$item;$items_by_host[(string)$item['hostid']][]=$item;}
		$normalized_issues=$this->issues->normalize($problems,$triggers);
		$issues_by_host=[]; foreach($normalized_issues as $issue) foreach($issue['hostids'] as $hostid) $issues_by_host[$hostid][]=$issue;
		$devices=[]; foreach($hosts as $hostid=>$host){
			$host['hostid']=(string)$hostid; $profile=$this->profile($host,$config); $metrics=[]; $all_details=[];
			foreach($items_by_host[(string)$hostid]??[] as $item){
				$class=$this->classifier->classify($item); if($class===null) continue;
				$metric=$class['metric']; $first=$this->first_observed->getOrRecord($hostid.':'.$item['itemid'],$now);
				$fresh=$this->freshness->evaluate($item,$items_by_id,$now,(int)$config['settings']['freshness_multiplier'],$first,(int)$config['settings']['no_data_grace_s']);
				$row=['itemid'=>(string)$item['itemid'],'name'=>(string)$item['name'],'key'=>(string)$item['key_'],'units'=>(string)$item['units'],
					'value'=>is_numeric($item['lastvalue'])?(float)$item['lastvalue']:(string)$item['lastvalue'],'clock'=>(int)$item['lastclock'],
					'freshness'=>$fresh,'mount'=>$class['mount']??null,'unit'=>$class['unit']??null,'rollup'=>true];
				if($metric==='storage') $row['rollup']=$this->storageRollup($row['mount'],$config['settings']);
				$metrics[$metric][]=$row; $all_details[]=$row+['metric'=>$metric];
			}
			$missing_first_observed=[];
			foreach (($profile==='unknown'?[]:($config['profiles'][$profile]??[])) as $category=>$expected) {
				if ($expected && ($metrics[$category]??[])===[]) {
					$missing_first_observed[$category]=$this->first_observed->getOrRecord($hostid.':expected:'.$category,$now);
				}
			}
			$interface_states=array_map(static fn($i)=>(string)($i['available']??'0'),$host['interfaces']??[]);
			$availability=in_array('1',$interface_states,true)?'UP':(in_array('2',$interface_states,true)?'DOWN':'UNKNOWN');
			$devices[]=['hostid'=>(string)$hostid,'host'=>(string)$host['host'],'name'=>(string)$host['name'],
				'site'=>$this->site($host),'profile'=>$profile,'profile_status'=>$profile==='unknown'?'UNRESOLVED':'MAPPED',
				'capabilities'=>$profile==='unknown'?[]:($config['profiles'][$profile]??[]),'maintenance'=>(string)$host['maintenance_status']==='1',
				'availability'=>$availability,'metrics'=>$metrics,'metric_details'=>$all_details,'missing_first_observed'=>$missing_first_observed,
				'no_data_grace_s'=>(int)$config['settings']['no_data_grace_s'],'issues'=>$issues_by_host[(string)$hostid]??[]];
		}
		$this->first_observed->save();
		return ['devices'=>$devices,'warnings'=>$warnings,'configuration'=>$config,'instrumentation'=>[
			'api_call_count'=>$this->api_calls,'hosts_retrieved'=>count($hosts),'items_retrieved'=>count($items),
			'problems_retrieved'=>count($normalized_issues),'history_rows'=>0,'trend_rows'=>0,
			'collector_time_ms'=>round((hrtime(true)-$started)/1_000_000,3)
		]];
	}
	private function profile(array $host,array $config): string {
		$templates=array_column($host['parentTemplates']??[],'name');
		foreach($config['profile_rules'] as $rule) if(in_array((string)$rule['template'],$templates,true)) return (string)$rule['profile'];
		return 'unknown';
	}
	private function site(array $host): string {
		foreach($host['tags']??[] as $tag) if(strtolower((string)$tag['tag'])==='site'&&trim((string)$tag['value'])!=='') return trim((string)$tag['value']);
		$groups=array_values(array_filter(array_map(static fn($g)=>(string)$g['name'],$host['hostgroups']??[]),static fn($n)=>$n!=='Discovered hosts'));
		return $groups[0]??'Unassigned';
	}
	private function storageRollup(?string $mount,array $settings): bool {
		if($mount===null)return false;
		foreach($settings['storage_rollup_exclude']??[] as $pattern)if(preg_match('~'.$pattern.'~',$mount)===1)return false;
		foreach($settings['storage_rollup_include']??[] as $pattern)if(preg_match('~'.$pattern.'~',$mount)===1)return true;
		return false;
	}
}
