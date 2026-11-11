"""Zabbix 7.0 API request contract, transcribed from the official 7.0 method reference
(https://www.zabbix.com/documentation/7.0/en/manual/api/reference/<object>/get), read 2026-11-11.

Used two ways: tests assert that every request the read-only discovery makes uses documented, non-deprecated
parameters and documented sub-select fields; and the offline mock rejects undocumented parameters/fields the way
the real API validator does, instead of silently answering them (which is how rc3's defects stayed hidden).

VERIFIED_FROM_DOCS lists what was actually read in the 7.0 pages. Anything not listed there is not claimed; it is
a LAB item (docs/LAB-VALIDATION-v1.1.md).
"""

COMMON = {"output", "countOutput", "editable", "excludeSearch", "filter", "limit", "preservekeys", "search",
          "searchByAny", "searchWildcardsEnabled", "sortfield", "sortorder", "startSearch", "limitSelects"}

PARAMS = {
    "trigger.get": COMMON | {
        "triggerids", "groupids", "templateids", "hostids", "itemids", "functions", "group", "host", "inherited",
        "templated", "dependent", "monitored", "active", "maintenance", "withUnacknowledgedEvents",
        "withAcknowledgedEvents", "withLastEventUnacknowledged", "skipDependent", "lastChangeSince",
        "lastChangeTill", "only_true", "min_severity", "evaltype", "tags", "expandComment", "expandDescription",
        "expandExpression", "selectHostGroups", "selectHosts", "selectItems", "selectFunctions",
        "selectDependencies", "selectDiscoveryRule", "selectLastEvent", "selectTags", "selectTemplateGroups",
        "selectTriggerDiscovery", "selectGroups"},
    "event.get": COMMON | {
        "eventids", "groupids", "hostids", "objectids", "source", "object", "acknowledged", "action",
        "action_userids", "suppressed", "symptom", "severities", "trigger_severities", "evaltype", "tags",
        "eventid_from", "eventid_till", "time_from", "time_till", "problem_time_from", "problem_time_till",
        "value", "selectAcknowledges", "selectAlerts", "selectHosts", "selectRelatedObject",
        "selectSuppressionData", "selectTags", "groupBy", "select_acknowledges", "select_alerts"},
    "host.get": COMMON | {
        "groupids", "dserviceids", "graphids", "hostids", "httptestids", "interfaceids", "itemids",
        "maintenanceids", "monitored_hosts", "proxyids", "proxy_groupids", "templated_hosts", "templateids",
        "triggerids", "with_items", "with_item_prototypes", "with_simple_graph_item_prototypes", "with_graphs",
        "with_graph_prototypes", "with_httptests", "with_monitored_httptests", "with_monitored_items",
        "with_monitored_triggers", "with_simple_graph_items", "with_triggers", "withProblemsSuppressed",
        "evaltype", "severities", "tags", "inheritedTags", "selectDiscoveries", "selectDiscoveryRule",
        "selectGraphs", "selectHostDiscovery", "selectHostGroups", "selectHttpTests", "selectInterfaces",
        "selectInventory", "selectItems", "selectMacros", "selectParentTemplates", "selectDashboards",
        "selectTags", "selectInheritedTags", "selectTriggers", "selectValueMaps", "searchInventory",
        "selectGroups"},
    "item.get": COMMON | {
        "itemids", "groupids", "templateids", "hostids", "proxyids", "interfaceids", "graphids", "triggerids",
        "webitems", "inherited", "templated", "monitored", "group", "host", "evaltype", "tags", "with_triggers",
        "selectHosts", "selectInterfaces", "selectTriggers", "selectGraphs", "selectDiscoveryRule",
        "selectItemDiscovery", "selectPreprocessing", "selectTags", "selectValueMap"},
    "template.get": COMMON | {
        "templateids", "groupids", "parentTemplateids", "hostids", "graphids", "itemids", "triggerids",
        "with_items", "with_triggers", "with_graphs", "with_httptests", "evaltype", "tags", "selectTags",
        "selectHosts", "selectTemplateGroups", "selectTemplates", "selectParentTemplates", "selectHttpTests",
        "selectItems", "selectDiscoveries", "selectTriggers", "selectGraphs", "selectMacros", "selectDashboards",
        "selectValueMaps", "selectGroups"},
    "action.get": COMMON | {
        "actionids", "groupids", "hostids", "triggerids", "mediatypeids", "usrgrpids", "userids", "scriptids",
        "selectFilter", "selectOperations", "selectRecoveryOperations", "selectUpdateOperations"},
    "user.get": COMMON | {
        "mediaids", "mediatypeids", "userids", "usrgrpids", "selectMedias", "selectMediatypes", "selectUsrgrps",
        "selectRole", "getAccess"},
    "usergroup.get": COMMON | {
        "mfaids", "mfa_status", "status", "userids", "usrgrpids", "selectTagFilters", "selectUsers",
        "selectHostGroupRights", "selectTemplateGroupRights", "selectRights"},
}

DEPRECATED = {
    "trigger.get": {"selectGroups"},
    "event.get": {"select_acknowledges", "select_alerts"},
    "host.get": {"selectGroups"},
    "template.get": {"selectGroups"},
    "usergroup.get": {"selectRights"},
}

# Sub-select fields whose object schema was read in the 7.0 docs.
SUBSELECT_FIELDS = {
    ("trigger.get", "selectFunctions"): {"functionid", "itemid", "function", "parameter"},
    ("event.get", "selectAlerts"): {"alertid", "actionid", "alerttype", "clock", "error", "esc_step", "eventid",
                                    "mediatypeid", "message", "retries", "sendto", "status", "subject", "userid",
                                    "p_eventid", "acknowledgeid"},
    ("event.get", "select_alerts"): {"alertid", "actionid", "alerttype", "clock", "error", "esc_step", "eventid",
                                     "mediatypeid", "message", "retries", "sendto", "status", "subject", "userid",
                                     "p_eventid", "acknowledgeid"},
    ("user.get", "selectMedias"): {"mediaid", "mediatypeid", "active", "severity", "period", "sendto",
                                   "provisioned", "userdirectory_mediaid"},
}

# Not verified from docs in this round (kept as LAB items, never asserted here).
NOT_VERIFIED = ("mediatype.get", "hostgroup.get", "usermacro.get", "apiinfo.version",
                "host.get selectInterfaces fields available/error", "usergroup.get hostgroup_rights fields id/permission",
                "trigger/item/action output field names", "recovery-alert eventid (problem or recovery event)")


def violations(method, params):
    """Contract problems of one request: undocumented or deprecated parameter, undocumented sub-select field."""
    out = []
    if method not in PARAMS or not isinstance(params, dict):
        return out
    for k, v in params.items():
        if k not in PARAMS[method]:
            out.append('%s: unexpected parameter "%s"' % (method, k))
        elif k in DEPRECATED.get(method, ()):
            out.append('%s: deprecated parameter "%s"' % (method, k))
        fields = SUBSELECT_FIELDS.get((method, k))
        if fields is not None and isinstance(v, list):
            for f in v:
                if f not in fields:
                    out.append('%s: "%s" has no field "%s" (7.0: %s)' % (method, k, f, ", ".join(sorted(fields))))
    return out
