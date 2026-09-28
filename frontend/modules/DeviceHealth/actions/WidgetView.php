<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use Modules\DeviceHealth\Collector\ZabbixDeviceHealthCollector;
use Modules\DeviceHealth\Config\FirstObservedRepository;
use Modules\DeviceHealth\Config\HealthConfigRepository;
use Modules\DeviceHealth\Domain\DeviceHealthResolver;
use Modules\DeviceHealth\Domain\IssueNormalizer;
use Modules\DeviceHealth\Domain\ItemClassifier;
use Modules\DeviceHealth\Domain\MetricFreshnessPolicy;
use Throwable;

final class WidgetView extends CControllerDashboardWidgetView {
	protected function doAction(): void {
		$started=hrtime(true);$now=time();
		try{$collected=(new ZabbixDeviceHealthCollector(new HealthConfigRepository(),new FirstObservedRepository(),new MetricFreshnessPolicy(),new ItemClassifier(),new IssueNormalizer()))->collect($now);
			$resolverStarted=hrtime(true);$snapshot=(new DeviceHealthResolver())->resolve($collected['devices'],$now);$resolver=round((hrtime(true)-$resolverStarted)/1_000_000,3);
			$data=['name'=>$this->getInput('name',$this->widget->getDefaultName()),'error'=>null,'snapshot'=>$snapshot,'warnings'=>$collected['warnings'],
				'instrumentation'=>$collected['instrumentation']+['resolver_time_ms'=>$resolver,'total_widget_time_ms'=>round((hrtime(true)-$started)/1_000_000,3)]];
		}catch(Throwable $e){$data=['name'=>$this->getInput('name',$this->widget->getDefaultName()),'error'=>$e->getMessage(),'snapshot'=>null,'warnings'=>[],
			'instrumentation'=>['total_widget_time_ms'=>round((hrtime(true)-$started)/1_000_000,3)]];}
		$this->setResponse(new CControllerResponseData($data));
	}
}
