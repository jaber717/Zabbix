<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Domain;

final class ItemClassifier {
	public function classify(array $item): ?array {
		$key = strtolower((string) ($item['key_'] ?? '')); $name = strtolower((string) ($item['name'] ?? ''));
		if ($key === 'system.cpu.util' || str_starts_with($key, 'system.cpu.util[') || str_contains($name, 'cpu utilization')) return ['metric'=>'cpu'];
		if ($key === 'vm.memory.util' || str_starts_with($key, 'vm.memory.util[') || str_contains($name, 'memory utilization')) return ['metric'=>'memory'];
		if (str_contains($key, 'temperature') || str_contains($key, 'temp.') || str_contains($name, 'temperature')) return ['metric'=>'temperature'];
		if ((str_contains($key, 'vfs.fs.') || str_contains($name, 'filesystem')) && (str_contains($key, 'pused') || str_contains($name, 'space utilization'))) {
			return ['metric'=>'storage','mount'=>$this->mount($item)];
		}
		if (str_contains($name, 'power supply') || preg_match('/(^|[.\[])psu/', $key) || str_contains($key, 'power')) return ['metric'=>'power_fan','unit'=>'power'];
		if (str_contains($name, 'fan') || str_contains($key, 'fan')) return ['metric'=>'power_fan','unit'=>'fan'];
		if (str_contains($key, 'failover') || str_contains($key, 'syncstatus') || str_contains($key, '.ha.') || str_contains($name, 'high availability') || str_contains($name, 'cluster sync')) return ['metric'=>'ha'];
		if ($key === 'system.uptime' || str_contains($name, 'uptime')) return ['metric'=>'uptime'];
		if (str_contains($name, 'session') && is_numeric($item['lastvalue'] ?? null)) return ['metric'=>'sessions'];
		return null;
	}
	private function mount(array $item): ?string {
		$key = (string) ($item['key_'] ?? ''); $name = (string) ($item['name'] ?? '');
		if (preg_match('/\[([^,\]]+),pused\]/i', $key, $m)) return trim($m[1], '"');
		if (preg_match('/FS \[([^\]]+)\]/i', $name, $m)) return $m[1];
		return null;
	}
}
