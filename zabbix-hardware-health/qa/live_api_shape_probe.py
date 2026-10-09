#!/usr/bin/env python3
"""Read-only LAB API shape probe. Prints schemas and counts, never values or credentials."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hwh.api import AuditError, ZabbixAPI
from hwh.audit import INVENTORY_FIELDS
from hwh.identity import verify
from hwh.items import ITEM_FIELDS, ITEM_SELECTS


def shape(value):
    if isinstance(value, dict):
        return "dict:" + ",".join(sorted(value.keys()))
    if isinstance(value, list):
        return "list:" + str(len(value))
    return type(value).__name__


def main():
    api = ZabbixAPI(os.environ["ZABBIX_HARDWARE_URL_LAB"], os.environ["ZABBIX_HARDWARE_TOKEN_LAB"])
    print("apiinfo.version", api.call("apiinfo.version"))
    macros = api.call("usermacro.get", {"output": ["macro", "value"], "globalmacro": True,
                                        "filter": {"macro": "{$NETOPS.ENVIRONMENT}"}})
    print("usermacro.get", "count", len(macros), "shape", shape(macros[0]) if macros else "empty",
          "identity_is_lab", len(macros) == 1 and macros[0].get("value") == "lab")
    try:
        verify(api, "production", api.base_url, {"zabbix": {"url_regex": ".*"}})
        print("wrong_environment_refused", False)
    except AuditError as exc:
        print("wrong_environment_refused", "IDENTITY MISMATCH" in str(exc))
    for name in ("PNET-SITE-A", "DR-FW01", "DR-LEAF01"):
        hosts = api.call("host.get", {"output": ["hostid", "host", "status"], "filter": {"host": [name]},
                                      "selectParentTemplates": ["name"], "selectInventory": INVENTORY_FIELDS,
                                      "selectInterfaces": ["interfaceid", "type", "main", "available", "error"]})
        print("host.get", name, "count", len(hosts), "shape", shape(hosts[0]) if hosts else "empty")
        if not hosts:
            continue
        h = hosts[0]
        print(" host selects", "inventory", shape(h.get("inventory")), "interfaces", shape(h.get("interfaces")),
              "templates", shape(h.get("parentTemplates")))
        params = {"hostids": [h["hostid"]], "output": ITEM_FIELDS}
        params.update(ITEM_SELECTS)
        items = api.call("item.get", params)
        print("item.get", "count", len(items), "shape", shape(items[0]) if items else "empty")
        if items:
            i = items[0]
            print(" item selects", "valuemap", shape(i.get("valuemap")), "preprocessing", shape(i.get("preprocessing")),
                  "tags", shape(i.get("tags")), "lastvalue_field", "lastvalue" in i,
                  "lastclock_field", "lastclock" in i, "snmp_oid_field", "snmp_oid" in i)
        triggers = api.call("trigger.get", {"hostids": [h["hostid"]], "expandExpression": True,
                                            "output": ["triggerid", "description", "expression", "status", "priority", "value", "state", "error", "flags"],
                                            "selectTags": ["tag", "value"], "selectItems": ["itemid", "key_"]})
        print("trigger.get", "count", len(triggers), "shape", shape(triggers[0]) if triggers else "empty")
        if triggers:
            t = triggers[0]
            print(" trigger selects", "items", shape(t.get("items")), "tags", shape(t.get("tags")),
                  "expanded_expression_field", "expression" in t)
    actions = api.call("action.get", {"output": ["actionid", "name", "status", "eventsource"],
                                      "search": {"name": "NETOPS"}, "selectFilter": "extend"})
    for a in actions:
        print("action.get", a.get("name"), "status", a.get("status"), "filter", shape(a.get("filter")))
        f = a.get("filter") or {}
        print(" action conditions", [(c.get("conditiontype"), c.get("operator"), c.get("value"))
                                      for c in f.get("conditions", [])])
    groups = api.call("usergroup.get", {"output": ["usrgrpid", "name"]})
    media = api.call("mediatype.get", {"output": ["mediatypeid", "name", "status"]})
    print("usergroup.get names", sorted(g.get("name", "") for g in groups))
    print("mediatype.get names", sorted(m.get("name", "") for m in media))
    print("Telegram media status", next((m.get("status") for m in media if m.get("name") == "Telegram"), "not found"))
    print("writes_made", api.writes_made())


if __name__ == "__main__":
    main()
