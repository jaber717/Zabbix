<?php declare(strict_types = 1);
/* Render the real widget.view.php with synthetic Zabbix-shaped data for browser QA. */
if (($argc ?? 0) !== 2) { fwrite(STDERR, "usage: php ui_fixture.php OUTPUT.html\n"); exit(2); }
$module = dirname(__DIR__, 2).'/frontend/modules/NetworkUtilization';
class CTag {
	private array $items = []; private array $attrs = [];
	public function __construct(private string $tag, private bool $closed = true, mixed $items = []) { $this->addItem($items); }
	public function addItem(mixed $item): self { if (is_array($item)) foreach ($item as $part) $this->addItem($part); elseif ($item !== null) $this->items[] = $item; return $this; }
	public function addClass(string $class): self { $this->attrs['class'] = trim(($this->attrs['class'] ?? '').' '.$class); return $this; }
	public function setAttribute(string $key, mixed $value): self { $this->attrs[$key] = (string) $value; return $this; }
	public function __toString(): string { $attrs = ''; foreach ($this->attrs as $key=>$value) $attrs .= ' '.htmlspecialchars($key, ENT_QUOTES).'="'.htmlspecialchars($value, ENT_QUOTES).'"';
		$out = '<'.$this->tag.$attrs.'>'; if (!$this->closed) return $out; foreach ($this->items as $item) $out .= $item instanceof self ? (string) $item : htmlspecialchars((string) $item, ENT_QUOTES); return $out.'</'.$this->tag.'>'; }
}
class CDiv extends CTag { public function __construct(mixed $items = []) { parent::__construct('div', true, $items); } }
class CSpan extends CTag { public function __construct(mixed $items = []) { parent::__construct('span', true, $items); } }
class CWidgetView { private array $items = []; public function __construct(array $data) {} public function addItem(mixed $item): self { $this->items[]=$item; return $this; } public function show(): void { foreach ($this->items as $item) echo $item; } }

$now = time(); $history = [];
foreach ([36000=>2_000_000, 18000=>6_000_000, 3000=>11_000_000, 1200=>45_000_000, 300=>9_000_000] as $age=>$value) $history[] = ['clock'=>$now-$age,'value'=>$value];
$trends = [['clock'=>$now-6*86400,'value'=>4_000_000],['clock'=>$now-3*86400,'value'=>8_000_000],['clock'=>$now-86400,'value'=>5_000_000]];
$specs = [
	['a','STC Internet','CENT-NETWORK','EDGE-R1','Te0/0/0',95,70,5_000_000,0,5,'WAN'],
	['b','MPLS Riyadh circuit with a deliberately very long operational display name','CENT-NETWORK','RTR-WAN-01-WITH-AN-EXTRA-LONG-HOSTNAME-FOR-LAYOUT-TESTING','GE0/0/5',85,90,20_000_000,3,0,'WAN'],
	['c','DCI-A-B','DR-SITE','N9K-01','Po10',50,60,40_000_000,1,2,'DCI'],
	['d','Capacity pending','DR-SITE','RTR-EDGE-DR','GE0/0/12345678901234567890',null,null,null,0,0,'UPLINK'],
	['e','ISP Secondary','CENT-NETWORK','EDGE-R2','Te0/0/1',10,20,90_000_000,8,1,'ISP']
];
$links=[]; $config_links=[];
foreach ($specs as [$id,$name,$site,$host,$iface,$current,$p95,$remaining,$errors,$discards,$role]) {
	$missing = $current === null; $site_id = $site === 'CENT-NETWORK' ? 'cent' : 'dr';
	$alias = $id === 'b' ? 'A very long connected-to description that must wrap safely without shifting any inspector label or value' : 'Connected to circuit';
	$metrics = ['in'=>['expected_interval'=>300,'history'=>$history,'trends_7d'=>$trends],
		'out'=>['expected_interval'=>300,'history'=>array_map(static fn($r)=>['clock'=>$r['clock']+3,'value'=>$r['value']*.7],$history),'trends_7d'=>$trends]];
	$links[] = ['id'=>$id,'display_name'=>$name,'site'=>$site,'site_id'=>$site_id,'site_order'=>$site_id==='cent'?0:10,
		'host'=>$host,'host_name'=>$host,'hostid'=>(string) (100+count($links)),'interface'=>['if_name'=>$iface,'if_alias'=>$alias,'if_descr'=>''],
		'current_alias'=>$alias,'role'=>$role,'order'=>count($links)*10,'visible'=>true,'required'=>true,'mapping_issue'=>null,
		'capacity_source'=>$missing?'interface_speed':'service_override','port_speed_bps'=>$missing?null:1_000_000_000,
		'capacity_in_bps'=>$missing?null:100_000_000,'capacity_out_bps'=>$missing?null:100_000_000,
		'current_in_bps'=>$missing?12_000_000:($current/100*100_000_000),'current_out_bps'=>$missing?8_000_000:($current*.6/100*100_000_000),
		'in_util_pct'=>$current,'out_util_pct'=>$current===null?null:$current*.6,'worst_util_pct'=>$current,'worst_direction'=>$missing?null:'IN',
		'p95_in_pct'=>$p95,'p95_out_pct'=>$p95===null?null:$p95*.7,'p95_worst_pct'=>$p95,'p95_in_bps'=>$p95===null?null:$p95/100*100_000_000,
		'p95_out_bps'=>$p95===null?null:$p95*.7/100*100_000_000,'peak_bps'=>48_000_000,
		'remaining_in_bps'=>$remaining,'remaining_out_bps'=>$remaining===null?null:$remaining+10_000_000,'worst_headroom_bps'=>$remaining,
		'sustained'=>$id==='a','sustained_seconds'=>$id==='a'?720:0,'spike'=>false,'warning_util_pct'=>80,'critical_util_pct'=>90,
		'data_state'=>'CURRENT','data_age_s'=>32,'admin_status'=>'UP','oper_status'=>'UP','errors_total'=>$errors,'discards_total'=>$discards,
		'attention_kind'=>$id==='d'?'CONFIG_OR_DATA':($id==='a'?'SUSTAINED_CRITICAL':($errors||$discards?'ERRORS_DISCARDS':null)),
		'metrics'=>$metrics];
	$config_links[] = ['id'=>$id,'display_name'=>$name,'site_id'=>$site_id,'host'=>$host,'interface'=>['if_name'=>$iface,'if_alias'=>$alias,'if_descr'=>''],
		'role'=>$role,'order'=>count($config_links)*10,'visible'=>true,'required'=>true,'capacity_source'=>$missing?'interface_speed':'service_override',
		'symmetric_service_bandwidth'=>true,'service_capacity_in_bps'=>$missing?null:100_000_000,'service_capacity_out_bps'=>$missing?null:100_000_000,
		'capacity_warning_accepted'=>$missing];
}
$attention=[];
foreach ([['a','SUSTAINED_CRITICAL',20,'OUT 95% sustained'],['b','CURRENT_CRITICAL',40,'IN 85%'],['e','ERRORS_DISCARDS',30,'Errors/discards increasing'],
	['d','CONFIG_OR_DATA',60,'Capacity required'],['c','ERRORS_DISCARDS',30,'Discards increasing']] as [$id,$kind,$rank,$detail]) {
	$link = current(array_filter($links,static fn($x)=>$x['id']===$id));
	$attention[]=['id'=>'attention-'.$id,'rank'=>$rank,'kind'=>$kind,'label'=>$link['display_name'],'detail'=>$detail,'link_id'=>$id];
}
$sites = [['id'=>'cent','name'=>'CENT-NETWORK','order'=>0],['id'=>'dr','name'=>'DR-SITE','order'=>10]];
$site_rows=[]; foreach ($sites as $site) { $subset=array_values(array_filter($links,static fn($l)=>$l['site_id']===$site['id'])); $site_rows[]=$site+['links'=>$subset,'attention'=>count(array_filter($subset,static fn($l)=>$l['attention_kind']!==null))]; }
$data = ['error'=>null,'snapshot'=>['generated_at'=>$now,'summary'=>['HOT_NOW'=>2,'SUSTAINED'=>1,'ERRORS_DISCARDS'=>3,'CAPACITY_RISK'=>2,'UNKNOWN_STALE'=>1,'MONITORED_LINKS'=>5],
	'needs_attention'=>$attention,'links'=>$links,'sites'=>$site_rows],
	'configuration'=>['schema'=>'network-utilization-config-v1','revision'=>1,'settings'=>['warning_util_pct'=>80,'critical_util_pct'=>90,'capacity_risk_p95_pct'=>80,'sustained_window_min'=>5],
		'sites'=>$sites,'links'=>$config_links],
	'candidates'=>[['host'=>'EDGE-R1','host_name'=>'EDGE-R1','if_name'=>'Te0/0/0','if_alias'=>'Circuit','capacity_bps'=>1_000_000_000,'oper_status'=>'UP','metric_types'=>['in','out']]],
	'instrumentation'=>['api_call_count'=>4,'collector_time_ms'=>72,'analytics_time_ms'=>.6,'total_widget_time_ms'=>75],
	'user'=>['can_edit'=>true,'csrf_token'=>'fixture-only'],'warnings'=>[]];
ob_start(); include $module.'/views/widget.view.php'; $markup=ob_get_clean();
$bootstrap = <<<'JS'
class CWidget { constructor(){this._contents=document.getElementById('mount');} setContents(html){this._contents.innerHTML=html;} isEditMode(){return false;} _pauseUpdating(){} _resumeUpdating(){} _startUpdating(){} }
class Curl { constructor(){} setArgument(){} getUrl(){return 'fixture-save';} }
const CSRF_TOKEN_NAME='_csrf_token';
window.fetch=async (_url,options)=>{const posted=JSON.parse(options.body); const config=JSON.parse(posted.payload); config.revision++; window.__lastSavedConfig=config; return {json:async()=>({configuration:config})};};
JS;
$init = <<<'JS'
window.widget=new CWidgetNetworkUtilization();
window.widget.setContents(document.getElementById('markup').innerHTML);
JS;
$html='<!doctype html><html><head><meta charset="utf-8"><title>Network Utilization real-module fixture</title><style>body{margin:0;padding:12px;background:#fff;color:#202b33;font:12px Arial,sans-serif}body.dark{background:#22282d;color:#e7edf0}#mount{width:100%;margin:auto}button,input,select{font:inherit}button{min-height:24px}input,select{padding:4px}</style><style>'.file_get_contents($module.'/assets/css/network-utilization.css').'</style></head><body><div id="mount"></div><template id="markup">'.$markup.'</template><script>'.$bootstrap.'</script>';
foreach (['traffic-chart.js','capacity-config.js','class.widget.js'] as $asset) $html.='<script>'.file_get_contents($module.'/assets/js/'.$asset).'</script>';
$html.='<script>'.$init.'</script></body></html>';
if (file_put_contents($argv[1],$html)===false) throw new RuntimeException('Unable to write fixture');
echo "FIXTURE=PASS LINKS=".count($specs)." ATTENTION=5\n";
