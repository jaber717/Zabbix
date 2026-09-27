<?php declare(strict_types = 1);
/* Render the real Availability widget view against resolver-produced synthetic LAB data. */
if (($argc ?? 0) !== 2) { fwrite(STDERR, "usage: php ui_fixture.php OUTPUT.html\n"); exit(2); }
$module = dirname(__DIR__, 2).'/frontend/modules/NetworkAvailability';
require_once $module.'/config/Limits.php';
require_once $module.'/domain/AvailabilityResolver.php';

class CTag {
	private array $items = []; private array $attrs = [];
	public function __construct(private string $tag, private bool $closed = true, mixed $items = []) { $this->addItem($items); }
	public function addItem(mixed $item): self { if (is_array($item)) foreach ($item as $part) $this->addItem($part); elseif ($item !== null) $this->items[] = $item; return $this; }
	public function addClass(string $class): self { $this->attrs['class'] = trim(($this->attrs['class'] ?? '').' '.$class); return $this; }
	public function setAttribute(string $key, mixed $value): self { $this->attrs[$key] = (string) $value; return $this; }
	public function setTitle(string $value): self { return $this->setAttribute('title', $value); }
	public function __toString(): string { $attrs = ''; foreach ($this->attrs as $key=>$value) $attrs .= ' '.htmlspecialchars($key, ENT_QUOTES).'="'.htmlspecialchars($value, ENT_QUOTES).'"';
		$out = '<'.$this->tag.$attrs.'>'; if (!$this->closed) return $out; foreach ($this->items as $item) $out .= $item instanceof self ? (string) $item : htmlspecialchars((string) $item, ENT_QUOTES); return $out.'</'.$this->tag.'>'; }
}
class CDiv extends CTag { public function __construct(mixed $items = []) { parent::__construct('div', true, $items); } }
class CSpan extends CTag { public function __construct(mixed $items = []) { parent::__construct('span', true, $items); } }
class CList extends CTag { public function __construct(mixed $items = []) { parent::__construct('ul', true, $items); } }
class CWidgetView { private array $items = []; public function __construct(array $data) {} public function addItem(mixed $item): self { $this->items[]=$item; return $this; } public function show(): void { foreach ($this->items as $item) echo $item; } }

$now = time();
$member = static function(string $id, string $state, bool $stale = false, bool $flapping = false) use ($now): array {
	return ['id'=>$id,'name'=>$id,'host'=>$id,'hostid'=>$id,'raw_availability_state'=>$state,
		'last_success'=>$now-($stale?400:15),'expected_interval'=>60,'availability_source'=>'SNMP',
		'availability_source_id'=>'fixture-proxy','transitions'=>$flapping?array_map(static fn($n)=>$now-$n,[10,20,30,40,50,60]):[]];
};
$make = static function(string $id, string $name, ?string $siteId, ?string $tier, array $members, array $extra = []) use ($now): array {
	$sites=['cent'=>['CENT-NETWORK',0],'dr'=>['DR',10],'healthy'=>['HEALTHY-SITE',20]];
	return $extra + ['id'=>$id,'name'=>$name,'site_id'=>$siteId,'site'=>$siteId===null?'Unassigned':$sites[$siteId][0],
		'site_order'=>$siteId===null?PHP_INT_MAX:$sites[$siteId][1],'order'=>10,'kind'=>count($members)===1?'host':'cluster',
		'criticality'=>$tier,'policy'=>count($members)===1?'ANY_REQUIRED':'MIN_N_REQUIRED','min_n'=>1,
		'members'=>$members,'event_since'=>$now-720];
};
$nodes=[
	$make('down','Critical uplink with an exceptionally long circuit and host name that must never overlap its badges','cent','tier1',[$member('EDGE-R1','DOWN')],
		['problems'=>[['eventid'=>'7001','name'=>'Interface unavailable','acknowledged'=>false]],'acknowledged'=>false]),
	$make('unassigned-down','DOWN unassigned host with a long hostname for priority testing',null,null,[$member('UNASSIGNED-LONG-HOST','DOWN')],
		['problems'=>[['eventid'=>'7002','name'=>'Host down','acknowledged'=>false]],'acknowledged'=>false]),
	$make('hidden-down','Hidden operational incident','cent','tier2',[$member('HIDDEN-HOST','DOWN')],['hidden'=>true]),
	$make('degraded','Degraded HA pair','dr','tier2',[$member('HA-A','UP',false,true),$member('HA-B','DOWN')]),
	$make('unknown','Unknown visibility node','dr','tier3',[$member('STALE-HOST','UP',true)]),
	$make('partial','Available service with partial visibility','cent','tier2',[$member('SERVICE-A','UP'),$member('SERVICE-B','UP',true)]),
	$make('maint','Maintenance down node','dr','tier1',[$member('MAINT-HOST','DOWN')],['maintenance'=>true]),
	$make('healthy','Healthy node','healthy','tier3',[$member('GOOD-HOST','UP')]),
	$make('many','Seven-member healthy cluster','healthy','tier2',array_map(static fn($n)=>$member('MEMBER-'.$n,'UP'),range(1,7)))
];
$snapshot=(new Modules\NetworkAvailability\Domain\AvailabilityResolver())->resolve($nodes,$now);
$configuration=['schema'=>'network-availability-config-v1','revision'=>1,
	'sites'=>[['id'=>'cent','name'=>'CENT-NETWORK','order'=>0],['id'=>'dr','name'=>'DR','order'=>10],['id'=>'healthy','name'=>'HEALTHY-SITE','order'=>20]],'nodes'=>[]];
foreach ($nodes as $node) if ($node['site_id']!==null) $configuration['nodes'][]=['id'=>$node['id'],'name'=>$node['name'],'site_id'=>$node['site_id'],
	'kind'=>$node['kind'],'criticality'=>$node['criticality'],'aggregation_policy'=>$node['policy'],'min_n'=>$node['min_n'],
	'order'=>count($configuration['nodes'])*10,'hidden'=>$node['hidden']??false,'description'=>'',
	'members'=>array_map(static fn($m)=>['id'=>$m['id'],'name'=>$m['name'],'host'=>$m['host']],$node['members'])];
$available=[]; foreach ($nodes as $node) foreach ($node['members'] as $m) $available[]=['host'=>$m['host'],'name'=>$m['name']];
$data=['error'=>null,'snapshot'=>$snapshot,'configuration'=>$configuration,'available_hosts'=>$available,
	'instrumentation'=>['api_call_count'=>4],'user'=>['can_edit'=>true,'csrf_token'=>'fixture-only','debug_mode'=>false]];
ob_start(); include $module.'/views/widget.view.php'; $markup=ob_get_clean();
$bootstrap=<<<'JS'
class CWidget { constructor(){this._contents=document.getElementById('mount');} setContents(html){this._contents.innerHTML=html;} isEditMode(){return false;} getUpdateRequestData(){return {};} _pauseUpdating(){} _resumeUpdating(){} _startUpdating(){} }
class Curl { constructor(){} setArgument(){} getUrl(){return 'fixture-save';} }
const CSRF_TOKEN_NAME='_csrf_token';
window.PopUp=(action,params)=>{window.__nativeAck={action,params};};
window.fetch=async (_url,options)=>{const posted=JSON.parse(options.body); const config=JSON.parse(posted.payload); config.revision++; window.__lastSavedConfig=config; return {json:async()=>({configuration:config})};};
JS;
$init=<<<'JS'
window.widget=new CWidgetNetworkAvailability();window.widget.setContents(document.getElementById('markup').innerHTML);
JS;
$html='<!doctype html><html><head><meta charset="utf-8"><title>Availability real-module fixture</title><style>body{margin:0;padding:12px;background:#fff;color:#1e2a31;font:12px Arial,sans-serif}body.dark{background:#20272b;color:#edf2f5}#mount{width:100%;margin:auto}input,select{padding:4px}</style><style>'.file_get_contents($module.'/assets/css/network-availability.css').'</style></head><body><div id="mount"></div><template id="markup">'.$markup.'</template><script>'.$bootstrap.'</script><script>'.file_get_contents($module.'/assets/js/class.widget.js').'</script><script>'.$init.'</script></body></html>';
if (file_put_contents($argv[1],$html)===false) throw new RuntimeException('Unable to write fixture');
echo 'FIXTURE=PASS INCIDENTS='.count($snapshot['needs_attention'])."\n";
