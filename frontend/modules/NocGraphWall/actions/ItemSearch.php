<?php declare(strict_types=1);
namespace Modules\NocGraphWall\Actions;

use CController;
use CControllerResponseData;
use API;

/**
 * Server-side item search for the slot editor. Real pagination via
 * item.get's `limit` + `offset` so page=3 skips the first 2*page_size results.
 * The underlying item.get is sorted by name for stable paging.
 */
class ItemSearch extends CController {

    private const PAGE_SIZE = 50;
    private const MAX_PAGE = 100;        // hard cap so a very deep page can't abuse the API

    protected function checkInput(): bool {
        return $this->validateInput([
            'q' => 'string',
            'page' => 'int32',
            'value_type' => 'string',
            'host' => 'string',
        ]);
    }

    protected function checkPermissions(): bool {
        return $this->getUserType() >= USER_TYPE_ZABBIX_ADMIN;
    }

    protected function doAction(): void {
        $q = trim((string) $this->getInput('q', ''));
        $page = max(1, min(self::MAX_PAGE, (int) $this->getInput('page', 1)));
        $vt = (string) $this->getInput('value_type', '');
        $host = trim((string) $this->getInput('host', ''));
        if ($q === '' && $host === '') {
            $this->setResponse(new CControllerResponseData(['items' => [], 'page' => $page, 'total' => 0, 'has_more' => false]));
            return;
        }

        $search = [];
        if ($q !== '')    $search['name'] = $q;
        if ($host !== '') $search['host'] = $host;

        $filter = [];
        if (in_array($vt, ['0', '3'], true)) {
            $filter['value_type'] = [(int) $vt];
        }

        $offset = ($page - 1) * self::PAGE_SIZE;

        // Zabbix API supports offset via "limit" + repeated calls OR an
        // explicit limit that includes the offset. The safe portable pattern
        // is: fetch limit + offset rows, then slice server-side.
        // For small MAX_PAGE this stays bounded.
        $window = self::PAGE_SIZE * $page;

        $items = API::Item()->get([
            'output' => ['itemid', 'name', 'key_', 'value_type', 'units', 'hostid'],
            'selectHosts' => ['host', 'name'],
            'search' => $search,
            'searchWildcardsEnabled' => true,
            'filter' => $filter,
            'webitems' => true,
            'limit' => $window + 1,          // one extra to detect "has_more"
            'startSearch' => true,
            'sortfield' => 'name',
            'sortorder' => 'ASC',
        ]);

        $has_more = count($items) > $window;
        $items = array_slice($items, $offset, self::PAGE_SIZE);

        $this->setResponse(new CControllerResponseData([
            'items' => $items,
            'page' => $page,
            'page_size' => self::PAGE_SIZE,
            'has_more' => $has_more,
        ]));
    }
}
