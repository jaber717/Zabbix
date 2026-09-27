<?php declare(strict_types = 1);

namespace Modules\NetworkUtilization\Collector;

interface LinkUtilizationCollectorInterface {
	public function collect(int $now): array;
}
