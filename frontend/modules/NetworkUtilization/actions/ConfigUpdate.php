<?php declare(strict_types = 1);

namespace Modules\NetworkUtilization\Actions;

use API;
use CController;
use CControllerResponseData;
use CRoleHelper;
use JsonException;
use Modules\NetworkUtilization\Config\LinkDefinitionRepository;
use Throwable;

final class ConfigUpdate extends CController {
	protected function init(): void { $this->setPostContentType(self::POST_CONTENT_TYPE_JSON); }
	protected function checkInput(): bool {
		$valid=$this->validateInput(['payload'=>'required|string','expected_revision'=>'required|int32']);
		if(!$valid)$this->jsonError('Invalid configuration request',array_column(get_and_clear_messages(),'message'));
		return $valid;
	}
	protected function checkPermissions(): bool { return $this->checkAccess(CRoleHelper::UI_ADMINISTRATION_GENERAL); }
	protected function doAction(): void {
		try {
			$document=json_decode($this->getInput('payload'),true,64,JSON_THROW_ON_ERROR); if(!is_array($document))throw new JsonException('Configuration must be a JSON object');
			$document=LinkDefinitionRepository::validateDocument($document);
			$visible=array_fill_keys(array_column(API::Host()->get(['output'=>['host'],'monitored_hosts'=>true]),'host'),true);
			foreach($document['links'] as $link)if(!isset($visible[$link['host']]))throw new \RuntimeException("Link {$link['display_name']} references a Host that is not visible: {$link['host']}");
			$saved=(new LinkDefinitionRepository())->save($document,(int)$this->getInput('expected_revision'));
			$this->setResponse((new CControllerResponseData(['main_block'=>json_encode(['success'=>['title'=>'Network Utilization configuration saved'],
				'configuration'=>$saved],JSON_THROW_ON_ERROR)]))->disableView());
		}catch(Throwable $e){$this->jsonError('Cannot save Network Utilization configuration',[$e->getMessage()]);}
	}
	private function jsonError(string $title,array $messages):void{$this->setResponse((new CControllerResponseData(['main_block'=>json_encode([
		'error'=>['title'=>$title,'messages'=>array_values($messages)]],JSON_THROW_ON_ERROR)]))->disableView());}
}
