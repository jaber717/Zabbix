<?php declare(strict_types = 1);

require_once __DIR__.'/../../frontend/modules/NetworkUtilization/config/Limits.php';
require_once __DIR__.'/../../frontend/modules/NetworkUtilization/config/LinkDefinitionRepository.php';

use Modules\NetworkUtilization\Config\LinkDefinitionRepository;

$directory=sys_get_temp_dir().'/network-utilization-'.bin2hex(random_bytes(5)); mkdir($directory,0700,true); $path=$directory.'/link-definitions.json';
$base=['schema'=>LinkDefinitionRepository::SCHEMA,'revision'=>1,'settings'=>['warning_util_pct'=>80,'critical_util_pct'=>90,'capacity_risk_p95_pct'=>80,'sustained_window_min'=>5],
	'sites'=>[['id'=>'dc','name'=>'DC','order'=>0]],'links'=>[['id'=>'wan','display_name'=>'WAN','site_id'=>'dc','host'=>'RTR-01','interface'=>['if_name'=>'Gi0/0','if_alias'=>'ISP','if_descr'=>''],'role'=>'WAN','order'=>0,'visible'=>true,'required'=>true]]];
file_put_contents($path,json_encode($base,JSON_PRETTY_PRINT)); $repo=new LinkDefinitionRepository($path); $loaded=$repo->loadDocument();
if($loaded['links'][0]['interface']['if_name']!=='Gi0/0'||array_key_exists('ifindex',$loaded['links'][0]['interface']))throw new RuntimeException('stable identity contract failed');
if($loaded['links'][0]['capacity_source']!=='interface_speed')throw new RuntimeException('legacy auto-capacity migration failed');
$legacy=$base;$legacy['links'][0]['capacity_override_bps']=50000000;
$migrated=LinkDefinitionRepository::validateDocument($legacy)['links'][0];
if($migrated['capacity_source']!=='service_override'||$migrated['service_capacity_in_bps']!==50000000||$migrated['service_capacity_out_bps']!==50000000)throw new RuntimeException('legacy override migration failed');
$symmetric=$base;$symmetric['links'][0]['capacity_source']='service_override';$symmetric['links'][0]['symmetric_service_bandwidth']=true;$symmetric['links'][0]['service_capacity_in_bps']=50000000;$symmetric['links'][0]['capacity_warning_accepted']=true;
$sym=LinkDefinitionRepository::validateDocument($symmetric)['links'][0];
if($sym['service_capacity_in_bps']!==50000000||$sym['service_capacity_out_bps']!==50000000||$sym['capacity_warning_accepted'])throw new RuntimeException('one-input symmetric service normalization or warning scope failed');
$asymmetric=$base;$asymmetric['links'][0]['capacity_source']='service_override';$asymmetric['links'][0]['symmetric_service_bandwidth']=false;$asymmetric['links'][0]['service_capacity_in_bps']=100000000;$asymmetric['links'][0]['service_capacity_out_bps']=50000000;
$normalized=LinkDefinitionRepository::validateDocument($asymmetric)['links'][0];
if($normalized['service_capacity_in_bps']!==100000000||$normalized['service_capacity_out_bps']!==50000000)throw new RuntimeException('asymmetric capacity was not preserved');
$loaded['links'][0]['display_name']='Internet'; $saved=$repo->save($loaded,1); if($saved['revision']!==2||!is_file($directory.'/link-definitions.last-known-good.json'))throw new RuntimeException('atomic save/LKG failed');
$service=$saved;$service['links'][0]['capacity_source']='service_override';$service['links'][0]['symmetric_service_bandwidth']=true;$service['links'][0]['service_capacity_in_bps']=50000000;
$persisted=$repo->save($service,2);$reloaded=$repo->loadDocument()['links'][0];
if($persisted['revision']!==3||$reloaded['capacity_source']!=='service_override'||$reloaded['service_capacity_in_bps']!==50000000||$reloaded['service_capacity_out_bps']!==50000000)throw new RuntimeException('service capacity did not persist after reload');
try{$bad=$saved;$bad['links'][0]['capacity_source']='service_override';$bad['links'][0]['service_capacity_in_bps']=0;$bad['links'][0]['service_capacity_out_bps']=50000000;LinkDefinitionRepository::validateDocument($bad);throw new RuntimeException('invalid config accepted');}catch(RuntimeException $e){if($e->getMessage()==='invalid config accepted')throw $e;}
try{$bad=$asymmetric;unset($bad['links'][0]['service_capacity_out_bps']);LinkDefinitionRepository::validateDocument($bad);throw new RuntimeException('missing asymmetric OUT accepted');}catch(RuntimeException $e){if($e->getMessage()==='missing asymmetric OUT accepted')throw $e;}
try{$repo->save($saved,1);throw new RuntimeException('revision conflict accepted');}catch(RuntimeException $e){if($e->getMessage()==='revision conflict accepted')throw $e;}
foreach(glob($directory.'/*') as $file)unlink($file); @unlink($directory.'/.link-definitions.lock'); rmdir($directory); echo "PASS: configuration persistence, LKG, validation and stable identity\n";
