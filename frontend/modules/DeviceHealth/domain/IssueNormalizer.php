<?php declare(strict_types = 1);

namespace Modules\DeviceHealth\Domain;

final class IssueNormalizer {
	public function normalize(array $problems, array $triggers): array {
		$by_trigger = []; foreach ($triggers as $trigger) $by_trigger[(string)$trigger['triggerid']] = $trigger;
		$seen = []; $issues = [];
		foreach ($problems as $problem) {
			$key = (string) ($problem['eventid'] ?? ''); if ($key === '' || isset($seen[$key])) continue; $seen[$key] = true;
			$trigger = $by_trigger[(string)($problem['objectid'] ?? '')] ?? [];
			$hostids = array_values(array_unique(array_map(static fn($h)=>(string)$h['hostid'], $trigger['hosts'] ?? [])));
			$itemids = array_values(array_unique(array_map(static fn($i)=>(string)$i['itemid'], $trigger['items'] ?? [])));
			$issues[] = ['id'=>$key,'triggerid'=>(string)($problem['objectid']??''),'name'=>(string)($problem['name']??'Zabbix problem'),
				'severity'=>(int)($problem['severity']??0),'clock'=>(int)($problem['clock']??0),
				'acknowledged'=>(string)($problem['acknowledged']??'0')==='1','suppressed'=>(string)($problem['suppressed']??'0')==='1',
				'hostids'=>$hostids,'itemids'=>$itemids];
		}
		return $issues;
	}
}
