<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Config;

final class Limits {
	public const STALE_MULTIPLIER = 3;
	public const MIN_REFRESH_INTERVAL_S = 10;
	public const FLAP_WINDOW_S = 300;
	public const FLAP_TRANSITIONS_N = 4;
	public const HERO_DWELL_S = 90;
	public const SECONDARY_INCIDENTS_MAX = 3;
	public const MASS_STALE_THRESHOLD_PCT = 30;
	public const MASS_STALE_MIN_N = 5;
	public const MASS_STALE_WINDOW_S = 120;

	public const MAX_HOSTS = 2000;
	public const MAX_ITEMS = 4000;
	public const MAX_HISTORY_ROWS = 20000;

	private function __construct() {
	}
}
