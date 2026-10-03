<?php declare(strict_types=1);
namespace Modules\NocGraphWall;

use Zabbix\Core\CWidget;

class Widget extends CWidget {
    public function getDefaultName(): string {
        return _('NOC Graph Wall');
    }

    public function getTranslationStrings(): array {
        return [
            'class.widget.js' => [
                'No data' => _('No data'),
                'Updated' => _('Updated'),
                'Edit wall' => _('Edit wall'),
                'Full screen' => _('Full screen'),
                'Save' => _('Save'),
                'Cancel' => _('Cancel'),
            ],
        ];
    }
}
