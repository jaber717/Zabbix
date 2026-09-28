<?php declare(strict_types = 1);
require_once __DIR__.'/../../frontend/modules/DeviceHealth/domain/MetricFreshnessPolicy.php';
require_once __DIR__.'/../../frontend/modules/DeviceHealth/domain/IssueNormalizer.php';
require_once __DIR__.'/../../frontend/modules/DeviceHealth/domain/DeviceHealthResolver.php';
use Modules\DeviceHealth\Domain\MetricFreshnessPolicy;use Modules\DeviceHealth\Domain\IssueNormalizer;use Modules\DeviceHealth\Domain\DeviceHealthResolver;
$pass=0;$assert=static function(bool $ok,string $message)use(&$pass){if(!$ok){fwrite(STDERR,"FAIL: $message\n");exit(1);}$pass++;};$now=1800000000;
$fresh=new MetricFreshnessPolicy();$master=['itemid'=>'1','delay'=>'60','master_itemid'=>'0','lastclock'=>$now-100];$dependent=['itemid'=>'2','delay'=>'0','master_itemid'=>'1','lastclock'=>$now-100];
$r=$fresh->evaluate($dependent,['1'=>$master,'2'=>$dependent],$now,3,$now-4000,3600);$assert($r['expected_interval']===60&&$r['state']==='CURRENT','dependent metric uses master interval');
$dependent['lastclock']=$now-181;$r=$fresh->evaluate($dependent,['1'=>$master,'2'=>$dependent],$now,3,$now-4000,3600);$assert($r['state']==='STALE','per-item stale policy');
$dependent['lastclock']=0;$r=$fresh->evaluate($dependent,['1'=>$master,'2'=>$dependent],$now,3,$now-60,3600);$assert($r['state']==='NO_DATA'&&$r['grace_active'],'no-data grace');
$unresolved=['itemid'=>'3','delay'=>'{$UNRESOLVED}','master_itemid'=>'0','lastclock'=>$now-10];$r=$fresh->evaluate($unresolved,['3'=>$unresolved],$now,3,$now-4000,3600);$assert($r['state']==='UNKNOWN','unresolved interval is not falsely current');
$issues=(new IssueNormalizer())->normalize([
	['eventid'=>'9','objectid'=>'7','clock'=>$now-10,'name'=>'High CPU','severity'=>4,'acknowledged'=>'0','suppressed'=>'0'],
	['eventid'=>'9','objectid'=>'7','clock'=>$now-10,'name'=>'High CPU','severity'=>4,'acknowledged'=>'0','suppressed'=>'0']
],[['triggerid'=>'7','hosts'=>[['hostid'=>'1']],'items'=>[['itemid'=>'10']]]]);$assert(count($issues)===1&&$issues[0]['itemids']===['10'],'problem deduplication');
$metric=static fn($id,$value,$state='CURRENT',$mount=null,$rollup=true)=>['itemid'=>$id,'name'=>'Metric '.$id,'key'=>'x','units'=>'%','value'=>$value,'clock'=>$now-10,'mount'=>$mount,'rollup'=>$rollup,'freshness'=>['state'=>$state,'age'=>10,'grace_active'=>false]];
$base=['hostid'=>'1','host'=>'h1','name'=>'Router 1','site'=>'DC','profile'=>'router_switch','profile_status'=>'MAPPED','capabilities'=>array_fill_keys(['cpu','memory','temperature','storage','power_fan','ha'],true),'maintenance'=>false,'availability'=>'UP','missing_first_observed'=>[],'no_data_grace_s'=>3600,'metric_details'=>[]];
$device=$base+['metrics'=>['cpu'=>[$metric('10',95)],'memory'=>[$metric('11',80)],'storage'=>[$metric('12',70,'CURRENT','/',true)]],
	'issues'=>[['id'=>'9','triggerid'=>'7','name'=>'High CPU','severity'=>4,'clock'=>$now-10,'acknowledged'=>false,'suppressed'=>false,'hostids'=>['1'],'itemids'=>['10']]]];
$snapshot=(new DeviceHealthResolver())->resolve([$device],$now);$d=$snapshot['devices'][0];
$assert($d['columns']['cpu']['severity']===4&&$d['columns']['memory']['severity']===0,'only trigger-linked metric receives severity');
$assert((float)$d['columns']['memory']['value']===80.0,'triggerless metric remains visible');
$assert(count($snapshot['needs_attention'])===1&&$snapshot['needs_attention'][0]['id']==='9','one normalized issue drives attention');
$unknown=$base;$unknown['profile']='unknown';$unknown['profile_status']='UNRESOLVED';$unknown['capabilities']=[];$unknown['metrics']=['cpu'=>[$metric('20',12)]];$unknown['issues']=[];
$du=(new DeviceHealthResolver())->resolve([$unknown],$now)['devices'][0];$assert((float)$du['columns']['cpu']['value']===12.0&&$du['columns']['memory']['data_state']==='NOT_APPLICABLE','unknown profile shows discovered data and dash elsewhere');
$storage=$base+['metrics'=>['storage'=>[$metric('30',25,'CURRENT','/boot',false),$metric('31',60,'CURRENT','/',true)]],'issues'=>[]];$ds=(new DeviceHealthResolver())->resolve([$storage],$now)['devices'][0];
$assert((float)$ds['columns']['storage']['value']===60.0&&count($ds['columns']['storage']['details'])===2,'storage rollup excludes ambiguous mount but Details retains it');
$missing=$base+['metrics'=>[],'issues'=>[],'missing_first_observed'=>['cpu'=>$now-30,'memory'=>$now-30,'temperature'=>$now-30,'storage'=>$now-30,'power_fan'=>$now-30,'ha'=>$now-30]];
$sm=(new DeviceHealthResolver())->resolve([$missing],$now);$assert($sm['needs_attention']===[],'new expected metrics do not enter attention during persisted grace');
$assert($sm['devices'][0]['columns']['cpu']['data_state']==='NO_DATA','expected missing metric is no-data');
echo "PASS: $pass Device Health domain assertions\n";
