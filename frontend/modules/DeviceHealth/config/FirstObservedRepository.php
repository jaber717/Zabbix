<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Config;

use RuntimeException;

final class FirstObservedRepository {
	public const DEFAULT_PATH = '/var/lib/zabbix/device-health/first-observed.json';
	private array $state = [];
	private bool $dirty = false;
	public function __construct(private readonly string $path = self::DEFAULT_PATH) {
		if (is_readable($path)) {
			$data = json_decode((string) file_get_contents($path), true);
			if (is_array($data) && ($data['schema'] ?? '') === 'device-health-first-observed-v1') {
				$this->state = is_array($data['items'] ?? null) ? $data['items'] : [];
			}
		}
	}
	public function getOrRecord(string $key, int $now): int {
		if (!isset($this->state[$key]) || !is_int($this->state[$key])) {
			$this->state[$key] = $now; $this->dirty = true;
		}
		return (int) $this->state[$key];
	}
	public function save(): void {
		if (!$this->dirty) return;
		$directory = dirname($this->path);
		if (!is_dir($directory) || !is_writable($directory)) throw new RuntimeException('First-observed runtime directory is not writable');
		$lock = fopen($directory.'/.first-observed.lock', 'c');
		if ($lock === false || !flock($lock, LOCK_EX)) throw new RuntimeException('Unable to lock first-observed state');
		try {
			$temp = $directory.'/.first-observed.'.bin2hex(random_bytes(6)).'.tmp';
			$json = json_encode(['schema'=>'device-health-first-observed-v1','items'=>$this->state], JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR)."\n";
			if (file_put_contents($temp, $json, LOCK_EX) === false || !chmod($temp, 0640) || !rename($temp, $this->path)) {
				@unlink($temp); throw new RuntimeException('Unable to persist first-observed state');
			}
			$this->dirty = false;
		}
		finally { flock($lock, LOCK_UN); fclose($lock); }
	}
}
