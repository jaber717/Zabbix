<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use CRoleHelper;
use CCsrfTokenHelper;
use CWebUser;
use Modules\NetworkAvailability\Collector\ZabbixAvailabilityCollector;
use Modules\NetworkAvailability\Config\NodeDefinitionRepository;
use Modules\NetworkAvailability\Domain\AvailabilityResolver;
use Modules\NetworkAvailability\Domain\ExpectedIntervalResolver;
use Throwable;

final class WidgetView extends CControllerDashboardWidgetView {
	protected function init(): void {
		parent::init();
		$this->addValidationRules([
			'availability_hero_id' => 'string',
			'availability_hero_selected_at' => 'int32'
		]);
	}

	protected function doAction(): void {
		$total_started = hrtime(true);
		$now = time();
		try {
			$collector = new ZabbixAvailabilityCollector(
				new NodeDefinitionRepository(),
				new ExpectedIntervalResolver()
			);
			$collected = $collector->collect($now);
			$current_hero_id = trim((string) $this->getInput('availability_hero_id', ''));
			$current_hero_selected_at = (int) $this->getInput('availability_hero_selected_at', 0);
			$current_hero = $current_hero_id !== '' && $current_hero_selected_at > 0
					&& $current_hero_selected_at <= $now
				? ['id' => $current_hero_id, 'selected_at' => $current_hero_selected_at]
				: null;

			$resolver_started = hrtime(true);
			$snapshot = (new AvailabilityResolver())->resolve($collected['nodes'], $now, $current_hero);
			$resolver_ms = round((hrtime(true) - $resolver_started) / 1_000_000, 3);
			$snapshot['warnings'] = array_values(array_unique(array_merge(
				$collected['warnings'], $snapshot['warnings']
			)));
			$instrumentation = $collected['instrumentation'] + [
				'resolver_time_ms' => $resolver_ms,
				'total_widget_time_ms' => round((hrtime(true) - $total_started) / 1_000_000, 3)
			];
			$data = [
				'name' => $this->getInput('name', $this->widget->getDefaultName()),
				'error' => null,
				'snapshot' => $snapshot,
				'configuration' => $collected['configuration'],
				'available_hosts' => $collected['available_hosts'],
				'instrumentation' => $instrumentation,
				'user' => [
					'debug_mode' => $this->getDebugMode(),
					'can_edit' => CWebUser::checkAccess(CRoleHelper::UI_ADMINISTRATION_GENERAL),
					'csrf_token' => CWebUser::checkAccess(CRoleHelper::UI_ADMINISTRATION_GENERAL)
						? CCsrfTokenHelper::get('networkavailability.config.update')
						: null
				]
			];
		}
		catch (Throwable $exception) {
			$data = [
				'name' => $this->getInput('name', $this->widget->getDefaultName()),
				'error' => $exception->getMessage(),
				'snapshot' => null,
				'configuration' => null,
				'available_hosts' => [],
				'instrumentation' => [
					'total_widget_time_ms' => round((hrtime(true) - $total_started) / 1_000_000, 3)
				],
				'user' => [
					'debug_mode' => $this->getDebugMode(),
					'can_edit' => false,
					'csrf_token' => null
				]
			];
		}
		$this->setResponse(new CControllerResponseData($data));
	}
}
