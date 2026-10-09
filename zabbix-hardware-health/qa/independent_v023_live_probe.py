#!/usr/bin/env python3
"""Bounded read-only LAB API shape/hash probe; never prints IDs, messages or tokens."""
import os
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hwh import action as A
from hwh.api import ZabbixAPI


def main():
    api = ZabbixAPI(os.environ["ZABBIX_HARDWARE_URL_LAB"], os.environ["ZABBIX_HARDWARE_TOKEN_LAB"])
    print("version", api.call("apiinfo.version"))
    identity = api.call("usermacro.get", {"output": ["macro", "value"], "globalmacro": True,
                                           "filter": {"macro": "{$NETOPS.ENVIRONMENT}"}})
    print("identity_is_lab", len(identity) == 1 and identity[0].get("value") == "lab")
    inventory = yaml.safe_load((pathlib.Path(__file__).resolve().parents[1] / "config" / "hardware.lab.yaml").read_text())
    print("approved_hardware_inventory_empty", inventory.get("hosts") == {})
    actions = api.call("action.get", {"output": "extend", "search": {"name": A.INTERFACE_PREFIX},
                                      "startSearch": True, "selectFilter": "extend", "selectOperations": "extend",
                                      "selectRecoveryOperations": "extend"})
    print("interface_action_count", len(actions))
    if actions:
        aid = actions[0]["actionid"]
        first = A.get_action_by_id(api, aid)
        second = A.get_action_by_id(api, aid)
        print("actionids_lookup_same_id", first.get("actionid") == second.get("actionid") == aid)
        print("status_type", type(first.get("status")).__name__, "status_is_0_or_1", str(first.get("status")) in ("0", "1"))
        print("definition_hash_stable_two_reads", A.core_sha256(first) == A.core_sha256(second))
        print("root_keys", sorted(first))
        print("filter_keys", sorted(first.get("filter") or {}))
        print("operation_count", len(first.get("operations") or []), "recovery_operation_count", len(first.get("recovery_operations") or []))
        for label, ops in (("problem", first.get("operations") or []), ("recovery", first.get("recovery_operations") or [])):
            if ops:
                o = ops[0]
                msg = (o.get("opmessage") or {}).get("message") or ""
                print(label + "_operation_keys", sorted(o))
                print(label + "_message_keys", sorted((o.get("opmessage") or {})))
                print(label + "_newline_shape", {"crlf": msg.count("\r\n"), "bare_lf": msg.count("\n") - msg.count("\r\n"), "bare_cr": msg.count("\r") - msg.count("\r\n")})
    print("hardware_action_absent", A.get_action(api, A.ACTION_NAME) is None)
    print("api_writes", api.writes_made())


if __name__ == "__main__":
    main()
