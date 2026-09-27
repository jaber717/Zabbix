<?php declare(strict_types = 1);

namespace Modules\NetworkAvailability\Actions;

use API;
use CController;
use CControllerResponseData;
use CRoleHelper;
use JsonException;
use Modules\NetworkAvailability\Config\NodeDefinitionRepository;
use Throwable;

final class ConfigUpdate extends CController {
	protected function init(): void {
		$this->setPostContentType(self::POST_CONTENT_TYPE_JSON);
	}

	protected function checkInput(): bool {
		$valid = $this->validateInput([
			'payload' => 'required|string',
			'expected_revision' => 'required|int32'
		]);
		if (!$valid) {
			$this->jsonError('Invalid configuration request', array_column(get_and_clear_messages(), 'message'));
		}
		return $valid;
	}

	protected function checkPermissions(): bool {
		return $this->checkAccess(CRoleHelper::UI_ADMINISTRATION_GENERAL);
	}

	protected function doAction(): void {
		try {
			$document = json_decode($this->getInput('payload'), true, 64, JSON_THROW_ON_ERROR);
			if (!is_array($document)) {
				throw new JsonException('Configuration must be a JSON object');
			}
			$document = NodeDefinitionRepository::validateDocument($document);
			$visible_hosts = array_fill_keys(array_column(API::Host()->get([
				'output' => ['host'],
				'monitored_hosts' => true,
				'preservekeys' => false
			]), 'host'), true);
			foreach ($document['nodes'] as $node) {
				foreach ($node['members'] as $member) {
					if (!isset($visible_hosts[$member['host']])) {
						throw new \RuntimeException("Node {$node['name']} references a Host that is not visible: {$member['host']}");
					}
				}
			}
			$saved = (new NodeDefinitionRepository())->save($document, (int) $this->getInput('expected_revision'));
			$this->setResponse((new CControllerResponseData(['main_block' => json_encode([
				'success' => ['title' => 'Network Availability configuration saved'],
				'configuration' => $saved
			], JSON_THROW_ON_ERROR)]))->disableView());
		}
		catch (Throwable $exception) {
			$this->jsonError('Cannot save Network Availability configuration', [$exception->getMessage()]);
		}
	}

	private function jsonError(string $title, array $messages): void {
		$this->setResponse((new CControllerResponseData(['main_block' => json_encode([
			'error' => ['title' => $title, 'messages' => array_values($messages)]
		], JSON_THROW_ON_ERROR)]))->disableView());
	}
}
