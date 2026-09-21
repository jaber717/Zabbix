<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Collector;

interface AvailabilityCollectorInterface {
	/** @return array{nodes: array, warnings: array, instrumentation: array} */
	public function collect(int $now): array;
}
