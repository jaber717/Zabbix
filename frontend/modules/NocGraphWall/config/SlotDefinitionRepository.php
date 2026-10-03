<?php declare(strict_types=1);
namespace Modules\NocGraphWall\Config;

/**
 * Loads and persists the six NOC Graph Wall slot bindings.
 *
 * Config path: $ZABBIX_DATA_DIR/noc_graph_wall/slot-definitions.json
 * Example:     frontend/modules/NocGraphWall/config/slot-definitions.example.json
 *
 * No in-browser-only persistence: the browser never writes the authoritative file.
 * The config update action verifies role, writes atomically, and increments a schema version.
 */
class SlotDefinitionRepository {
    private const SCHEMA_VERSION = 1;
    private const MAX_SLOTS = 6;

    private string $configPath;

    public function __construct(string $configPath) {
        $this->configPath = $configPath;
    }

    public function load(): array {
        if (!is_file($this->configPath)) {
            return $this->emptyConfiguration();
        }
        $raw = file_get_contents($this->configPath);
        if ($raw === false) {
            throw new \RuntimeException('Unable to read slot definitions');
        }
        $decoded = json_decode($raw, true, 32, JSON_THROW_ON_ERROR);
        return $this->normalize($decoded);
    }

    public function save(array $configuration): void {
        $normalized = $this->normalize($configuration);
        $dir = dirname($this->configPath);
        if (!is_dir($dir) && !mkdir($dir, 0750, true) && !is_dir($dir)) {
            throw new \RuntimeException('Unable to create config dir');
        }
        $tmp = $this->configPath.'.tmp';
        $json = json_encode($normalized, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
        if (file_put_contents($tmp, $json, LOCK_EX) === false) {
            throw new \RuntimeException('Unable to write slot definitions');
        }
        chmod($tmp, 0640);
        if (!rename($tmp, $this->configPath)) {
            @unlink($tmp);
            throw new \RuntimeException('Unable to replace slot definitions');
        }
    }

    private function emptyConfiguration(): array {
        $slots = [];
        for ($i = 1; $i <= self::MAX_SLOTS; $i++) {
            $slots[] = ['position' => $i, 'label' => 'Slot '.$i, 'kind' => 'empty'];
        }
        return [
            '$schema_version' => self::SCHEMA_VERSION,
            'defaults' => ['refresh_seconds' => 30, 'default_range_hours' => 1],
            'slots' => $slots,
        ];
    }

    private function normalize(array $cfg): array {
        $slots = $cfg['slots'] ?? [];
        if (count($slots) !== self::MAX_SLOTS) {
            throw new \InvalidArgumentException('Exactly '.self::MAX_SLOTS.' slots required');
        }
        $out = [];
        foreach ($slots as $slot) {
            $pos = (int) ($slot['position'] ?? 0);
            if ($pos < 1 || $pos > self::MAX_SLOTS) {
                throw new \InvalidArgumentException('Slot position out of range');
            }
            $kind = (string) ($slot['kind'] ?? 'empty');
            $normalized = [
                'position' => $pos,
                'label' => (string) ($slot['label'] ?? ''),
                'kind' => $kind,
            ];
            switch ($kind) {
                case 'paired_interface':
                    $normalized['in_itemid'] = isset($slot['in_itemid']) ? (int) $slot['in_itemid'] : null;
                    $normalized['out_itemid'] = isset($slot['out_itemid']) ? (int) $slot['out_itemid'] : null;
                    $normalized['unit'] = (string) ($slot['unit'] ?? 'bps');
                    $normalized['capacity_bps'] = isset($slot['capacity_bps']) ? (int) $slot['capacity_bps'] : null;
                    break;
                case 'single_item':
                    $normalized['itemid'] = isset($slot['itemid']) ? (int) $slot['itemid'] : null;
                    $normalized['unit'] = (string) ($slot['unit'] ?? '');
                    break;
                case 'aggregate':
                    $normalized['itemids'] = array_values(array_map('intval', $slot['itemids'] ?? []));
                    $normalized['unit'] = (string) ($slot['unit'] ?? 'bps');
                    break;
                case 'empty':
                    break;
                default:
                    throw new \InvalidArgumentException('Unknown slot kind: '.$kind);
            }
            $out[] = $normalized;
        }
        usort($out, fn($a, $b) => $a['position'] <=> $b['position']);
        return [
            '$schema_version' => self::SCHEMA_VERSION,
            'defaults' => $cfg['defaults'] ?? ['refresh_seconds' => 30, 'default_range_hours' => 1],
            'slots' => $out,
        ];
    }
}
