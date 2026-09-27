<?php declare(strict_types = 1);

require_once __DIR__.'/../../frontend/modules/NetworkUtilization/config/Limits.php';
require_once __DIR__.'/../../frontend/modules/NetworkUtilization/config/LinkDefinitionRepository.php';

use Modules\NetworkUtilization\Config\LinkDefinitionRepository;

$directory=sys_get_temp_dir().'/network-utilization-'.bin2hex(random_bytes(5)); mkdir($directory,0700,true); $path=$directory.'/link-definitions.json';
$base=['schema'=>LinkDefinitionRepository::SCHEMA,'revision'=>1,'settings'=>['warning_util_pct'=>80,'critical_util_pct'=>90,'capacity_risk_p95_pct'=>80,'sustained_window_min'=>5],
	'sites'=>[['id'=>'dc','name'=>'DC','order'=>0]],'links'=>[['id'=>'wan','display_name'=>'WAN','site_id'=>'dc','host'=>'RTR-01','interface'=>['if_name'=>'Gi0/0','if_alias'=>'ISP','if_descr'=>''],'role'=>'WAN','order'=>0,'visible'=>true,'required'=>true]]];
file_put_contents($path,json_encode($base,JSON_PRETTY_PRINT)); $repo=new LinkDefinitionRepository($path); $loaded=$repo->loadDocument();
if($loaded['links'][0]['interface']['if_name']!=='Gi0/0'||array_key_exists('ifindex',$loaded['links'][0]['interface']))throw new RuntimeException('stable identity contract failed');
$loaded['links'][0]['display_name']='Internet'; $saved=$repo->save($loaded,1); if($saved['revision']!==2||!is_file($directory.'/link-definitions.last-known-good.json'))throw new RuntimeException('atomic save/LKG failed');
try{$bad=$saved;$bad['links'][0]['capacity_override_bps']=0;LinkDefinitionRepository::validateDocument($bad);throw new RuntimeException('invalid config accepted');}catch(RuntimeException $e){if($e->getMessage()==='invalid config accepted')throw $e;}
try{$repo->save($saved,1);throw new RuntimeException('revision conflict accepted');}catch(RuntimeException $e){if($e->getMessage()==='revision conflict accepted')throw $e;}
foreach(glob($directory.'/*') as $file)unlink($file); @unlink($directory.'/.link-definitions.lock'); rmdir($directory); echo "PASS: configuration persistence, LKG, validation and stable identity\n";
