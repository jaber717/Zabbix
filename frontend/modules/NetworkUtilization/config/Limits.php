<?php declare(strict_types = 1);

namespace Modules\NetworkUtilization\Config;

final class Limits {
	public const MAX_HOSTS = 500;
	public const MAX_DISCOVERY_ITEMS = 20000;
	public const MAX_CONFIGURED_LINKS = 250;
	public const MAX_HISTORY_ROWS = 60000;
	public const P95_WINDOW_S = 86400;
	public const SPARKLINE_WINDOW_S = 3600;
	public const MIN_PERCENTILE_SAMPLES = 20;
	public const DEFAULT_WARNING_PCT = 80.0;
	public const DEFAULT_CRITICAL_PCT = 90.0;
	public const DEFAULT_CAPACITY_RISK_PCT = 80.0;
	public const DEFAULT_SUSTAINED_MIN = 5;
}
