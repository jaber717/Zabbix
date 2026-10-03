<?php declare(strict_types=1);
namespace Modules\FlowSearch\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;

/**
 * Initial view render — paints an empty search page. Live data arrives via
 * flowsearch.query / flowsearch.topn XHRs.
 */
class WidgetView extends CControllerDashboardWidgetView {

    protected function checkInput(): bool {
        return $this->validateInput(['name' => 'string']);
    }

    protected function checkPermissions(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_USER;
    }

    protected function doAction(): void {
        $this->setResponse(new CControllerResponseData([
            'name' => $this->getInput('name', 'Flow Search'),
            'error' => null,
            'user' => [
                'can_edit' => $this->getUserType() >= USER_TYPE_ZABBIX_ADMIN,
                'csrf_token' => $this->getCsrfTokenHash(),
            ],
            'defaults' => [
                'range_minutes' => 60,
                'page_size' => 50,
            ],
        ]));
    }
}
