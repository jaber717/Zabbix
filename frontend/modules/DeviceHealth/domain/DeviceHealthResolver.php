<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Domain;

final class DeviceHealthResolver {
	private const CATEGORIES=['cpu','memory','temperature','storage','power_fan','ha'];
	public function resolve(array $devices,int $now): array {
		$resolved=[];$normalizedIssues=[];
		foreach($devices as $device){
			$metricIssues=[];foreach($device['issues'] as $issue){$category=$this->issueCategory($issue,$device['metrics']);$issue['category']=$category;$issue['device_id']=$device['hostid'];$issue['device']=$device['name'];$issue['site']=$device['site'];$normalizedIssues[$issue['id']]=$issue;$metricIssues[$category][]=$issue;}
			$columns=[];foreach(self::CATEGORIES as $category)$columns[$category]=$this->resolveMetric($category,$device,$metricIssues[$category]??[],$now);
			$severity=0;foreach($device['issues'] as $issue)$severity=max($severity,(int)$issue['severity']);
			foreach($columns as $column) if(in_array($column['data_state'],['STALE','NO_DATA','UNKNOWN'],true)&&!$column['grace_active'])$severity=max($severity,1);
			$state=$severity>=4?'CRITICAL':($severity>=2?'WARNING':($severity===1?'UNKNOWN':'HEALTHY'));
			$reasons=[];foreach($device['issues'] as $issue)$reasons[]=$issue['name'];
			if($reasons===[])foreach($columns as $label=>$column)if(in_array($column['data_state'],['STALE','NO_DATA','UNKNOWN'],true)&&!$column['grace_active'])$reasons[]=ucwords(str_replace('_',' ',$label)).' '.$column['data_state'];
			$resolved[]=$device+['columns'=>$columns,'severity'=>$severity,'state'=>$state,'reasons'=>array_values(array_unique($reasons))];
		}
		$attention=array_values($normalizedIssues);
		foreach($resolved as $device)foreach($device['columns'] as $category=>$column)if(in_array($column['data_state'],['STALE','NO_DATA','UNKNOWN'],true)&&!$column['grace_active']){
			$id='data:'.$device['hostid'].':'.$category;if(!isset($normalizedIssues[$id]))$attention[]=['id'=>$id,'device_id'=>$device['hostid'],'device'=>$device['name'],'site'=>$device['site'],'category'=>'data','severity'=>1,'name'=>ucwords(str_replace('_',' ',$category)).' '.$column['data_state'],'clock'=>$column['clock']??$now,'acknowledged'=>false,'suppressed'=>false];
		}
		usort($attention,static fn($a,$b)=>[$b['severity'],$a['clock'],$a['device']]<=>[$a['severity'],$b['clock'],$b['device']]);
		$sites=[];foreach($resolved as $device)$sites[$device['site']][]=$device;ksort($sites,SORT_NATURAL|SORT_FLAG_CASE);
		$summary=['CRITICAL'=>0,'WARNING'=>0,'RESOURCE'=>0,'HARDWARE'=>0,'HA'=>0,'UNKNOWN_STALE'=>0,'MONITORED'=>count($resolved)];
		foreach($resolved as $d){if($d['state']==='CRITICAL')$summary['CRITICAL']++;elseif($d['state']==='WARNING')$summary['WARNING']++;elseif($d['state']==='UNKNOWN')$summary['UNKNOWN_STALE']++;}
		foreach($attention as $issue){if(in_array($issue['category'],['cpu','memory','storage'],true))$summary['RESOURCE']++;if(in_array($issue['category'],['temperature','power_fan'],true))$summary['HARDWARE']++;if($issue['category']==='ha')$summary['HA']++;}
		return ['generated_at'=>$now,'summary'=>$summary,'needs_attention'=>$attention,'sites'=>$sites,'devices'=>$resolved];
	}
	private function resolveMetric(string $category,array $device,array $issues,int $now): array {
		$rows=$device['metrics'][$category]??[];$capability=$device['capabilities'][$category]??null;
		if($rows===[]){$notApplicable=$capability!==true;$first=(int)($device['missing_first_observed'][$category]??$now);$grace=$capability===true&&($now-$first)<(int)($device['no_data_grace_s']??3600);
			return ['state'=>$notApplicable?'NOT_APPLICABLE':'NO_DATA','data_state'=>$notApplicable?'NOT_APPLICABLE':'NO_DATA','value'=>null,'units'=>'','severity'=>$this->maxSeverity($issues),'grace_active'=>$grace,'clock'=>null,'details'=>[]];}
		if($category==='storage')$rollup=array_values(array_filter($rows,static fn($r)=>$r['rollup']));else$rollup=$rows;
		if($category==='storage'&&$rollup===[])return ['state'=>'NOT_APPLICABLE','data_state'=>'NOT_APPLICABLE','value'=>null,'units'=>'','severity'=>$this->maxSeverity($issues),'grace_active'=>false,'clock'=>null,'details'=>$rows,'rollup_incomplete'=>true];
		$current=array_values(array_filter($rollup,static fn($r)=>$r['freshness']['state']==='CURRENT'&&is_numeric($r['value'])));
		$stale=array_values(array_filter($rollup,static fn($r)=>$r['freshness']['state']==='STALE'));
		$nodata=array_values(array_filter($rollup,static fn($r)=>$r['freshness']['state']==='NO_DATA'));
		$unknown=array_values(array_filter($rollup,static fn($r)=>$r['freshness']['state']==='UNKNOWN'));
		$dataState=$current!==[]?'CURRENT':($stale!==[]?'STALE':($unknown!==[]?'UNKNOWN':'NO_DATA'));$selected=null;
		if($current!==[])$selected=array_reduce($current,static fn($best,$r)=>$best===null||(float)$r['value']>(float)$best['value']?$r:$best);
		$grace=$nodata!==[]&&count(array_filter($nodata,static fn($r)=>$r['freshness']['grace_active']))===count($nodata);
		return ['state'=>$dataState,'data_state'=>$dataState,'value'=>$selected['value']??null,'units'=>$selected['units']??'','severity'=>$this->maxSeverity($issues),
			'grace_active'=>$grace,'clock'=>$selected['clock']??($stale[0]['clock']??null),'age'=>$selected['freshness']['age']??($stale[0]['freshness']['age']??null),'details'=>$rows];
	}
	private function maxSeverity(array $issues): int { $max=0;foreach($issues as $issue)$max=max($max,(int)$issue['severity']);return $max; }
	private function issueCategory(array $issue,array $metrics): string {
		$itemMap=[];foreach($metrics as $category=>$rows)foreach($rows as $row)$itemMap[$row['itemid']]=$category;
		foreach($issue['itemids'] as $itemid)if(isset($itemMap[$itemid]))return $itemMap[$itemid];
		$name=strtolower($issue['name']);
		return match(true){str_contains($name,'cpu')=>'cpu',str_contains($name,'memory')=>'memory',str_contains($name,'temperature')=>'temperature',
			str_contains($name,'filesystem')||str_contains($name,'disk space')=>'storage',str_contains($name,'fan')||str_contains($name,'power')=>'power_fan',
			str_contains($name,'sync')||str_contains($name,'cluster')||str_contains($name,'failover')=>'ha',default=>'other'};
	}
}
