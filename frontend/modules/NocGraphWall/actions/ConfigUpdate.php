<?php declare(strict_types=1);
namespace Modules\NocGraphWall\Actions;

use CController;
use CControllerResponseData;
use CControllerResponseRedirect;
use Modules\NocGraphWall\Config\SlotDefinitionRepository;

/**
 * POST /zabbix.php?action=nocgraphwall.config.update
 * Admin-only. CSRF-checked. Writes slot-definitions.json atomically on disk.
 */
class ConfigUpdate extends CController {

    protected function init(): void {
        $this->disableCsrfValidation(); // use our own below
    }

    protected function checkInput(): bool {
        return $this->validateInput([
            'configuration' => 'required|string',
            '_csrf_token' => 'required|string',
        ]);
    }

    protected function checkPermissions(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_ADMIN
            && $this->checkCsrfToken($this->getInput('_csrf_token'));
    }

    protected function doAction(): void {
        $raw = $this->getInput('configuration');
        try {
            $decoded = json_decode($raw, true, 32, JSON_THROW_ON_ERROR);
        } catch (\Throwable $e) {
            $this->setResponse(new CControllerResponseData(['error' => 'Invalid JSON']));
            return;
        }
        $cfg_path = $this->resolveConfigPath();
        try {
            (new SlotDefinitionRepository($cfg_path))->save($decoded);
        } catch (\Throwable $e) {
            $this->setResponse(new CControllerResponseData(['error' => $e->getMessage()]));
            return;
        }
        $this->setResponse(new CControllerResponseData(['ok' => true, 'saved_at' => time()]));
    }

    private function resolveConfigPath(): string {
        $base = getenv('ZABBIX_DATA_DIR') ?: '/var/lib/zabbix';
        return rtrim($base, '/').'/noc_graph_wall/slot-definitions.json';
    }

    private function checkCsrfToken(string $token): bool {
        return hash_equals($this->getCsrfTokenHash(), $token);
    }
}
