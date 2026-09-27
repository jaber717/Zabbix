<?php declare(strict_types = 1);

namespace Modules\NetworkUtilization\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use CRoleHelper;
use CCsrfTokenHelper;
use CWebUser;
use Modules\NetworkUtilization\Collector\ZabbixLinkUtilizationCollector;
use Modules\NetworkUtilization\Config\LinkDefinitionRepository;
use Modules\NetworkUtilization\Domain\LinkUtilizationResolver;
use Throwable;

final class WidgetView extends CControllerDashboardWidgetView {
	protected function doAction(): void {
		$started=hrtime(true); $now=time();
		try {
			$collected=(new ZabbixLinkUtilizationCollector(new LinkDefinitionRepository()))->collect($now);
			$analytics_started=hrtime(true);
			$snapshot=(new LinkUtilizationResolver())->resolve($collected['links'],$collected['sites'],$collected['configuration']['settings'],$now);
			$instrumentation=$collected['instrumentation']+['analytics_time_ms'=>round((hrtime(true)-$analytics_started)/1_000_000,3),
				'total_widget_time_ms'=>round((hrtime(true)-$started)/1_000_000,3)];
			$data=['name'=>$this->getInput('name',$this->widget->getDefaultName()),'error'=>null,'snapshot'=>$snapshot,
				'configuration'=>$collected['configuration'],'candidates'=>$collected['candidates'],'warnings'=>$collected['warnings'],
				'instrumentation'=>$instrumentation,'user'=>['debug_mode'=>$this->getDebugMode(),
					'can_edit'=>CWebUser::checkAccess(CRoleHelper::UI_ADMINISTRATION_GENERAL),
					'csrf_token'=>CWebUser::checkAccess(CRoleHelper::UI_ADMINISTRATION_GENERAL)?CCsrfTokenHelper::get('networkutilization.config.update'):null]];
		}
		catch(Throwable $e){$data=['name'=>$this->getInput('name',$this->widget->getDefaultName()),'error'=>$e->getMessage(),'snapshot'=>null,
			'configuration'=>null,'candidates'=>[],'warnings'=>[],'instrumentation'=>['total_widget_time_ms'=>round((hrtime(true)-$started)/1_000_000,3)],
			'user'=>['debug_mode'=>$this->getDebugMode(),'can_edit'=>false,'csrf_token'=>null]];}
		$this->setResponse(new CControllerResponseData($data));
	}
}
