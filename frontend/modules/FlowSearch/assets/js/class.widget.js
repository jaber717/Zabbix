/* Thin wrapper so Zabbix widget framework can find a class. All UI wiring is in flow-search.js. */
class CWidgetFlowSearch extends CWidget {
    _init() { super._init(); this._refresh_seconds = 0; }
}
