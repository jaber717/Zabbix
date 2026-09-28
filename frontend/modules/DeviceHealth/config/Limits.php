<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Config;

final class Limits {
	public const STALE_MULTIPLIER = 3;
	public const NO_DATA_GRACE_S = 3600;
	public const MAX_HOSTS = 2000;
	public const MAX_ITEMS = 30000;
	public const MAX_PROBLEMS = 10000;
	private function __construct() {}
}
