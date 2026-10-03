<?php declare(strict_types=1);
namespace Modules\NocGraphWall\Actions;

use CController;
use CControllerResponseData;
use API;

/**
 * Server-side host+item search for the slot editor. Bounded, paginated.
 * Returns up to 50 items per page; the browser never issues item.get directly.
 */
class ItemSearch extends CController {

    private const PAGE_SIZE = 50;

    protected function checkInput(): bool {
        return $this->validateInput([
            'q' => 'string',
            'page' => 'int32',
            'value_type' => 'string',
        ]);
    }

    protected function checkPermissions(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_ADMIN;
    }

    protected function doAction(): void {
        $q = trim((string) $this->getInput('q', ''));
        $page = max(1, (int) $this->getInput('page', 1));
        $vt = (string) $this->getInput('value_type', '');
        if ($q === '') {
            $this->setResponse(new CControllerResponseData(['items' => [], 'page' => $page, 'total' => 0]));
            return;
        }
        $search = ['name' => $q];
        $filter = [];
        if (in_array($vt, ['0', '3'], true)) {
            $filter['value_type'] = [(int) $vt];
        }
        $items = API::Item()->get([
            'output' => ['itemid', 'name', 'key_', 'value_type', 'units', 'hostid'],
            'selectHosts' => ['host', 'name'],
            'search' => $search,
            'searchWildcardsEnabled' => true,
            'filter' => $filter,
            'webitems' => true,
            'limit' => self::PAGE_SIZE,
            'startSearch' => true,
            'sortfield' => 'name',
        ]);
        $this->setResponse(new CControllerResponseData([
            'items' => $items,
            'page' => $page,
            'page_size' => self::PAGE_SIZE,
        ]));
    }
}
