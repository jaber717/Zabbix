#!/usr/bin/env python3
"""Bounded, read-only LAB Zabbix API shape probe; prints no IDs, names or payloads."""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hwh.api import AuditError, ZabbixAPI
from hwh import action as A
from hwh import synthetic as S


def shape(value):
    if isinstance(value, dict):
        return "dict:" + ",".join(sorted(value))
    if isinstance(value, list):
        return "list:" + str(len(value))
    return type(value).__name__


def main():
    api = ZabbixAPI(os.environ["ZABBIX_HARDWARE_URL_LAB"], os.environ["ZABBIX_HARDWARE_TOKEN_LAB"])
    print("version", api.call("apiinfo.version"))
    identity = api.call("usermacro.get", {"output": ["macro", "value"], "globalmacro": True,
                                           "filter": {"macro": "{$NETOPS.ENVIRONMENT}"}})
    print("identity_is_lab", len(identity) == 1 and identity[0].get("value") == "lab")

    actions = api.call("action.get", {"output": ["actionid", "name", "status"],
                                      "search": {"name": A.INTERFACE_PREFIX}, "startSearch": True})
    print("interface_action_count", len(actions))
    if actions:
        a = api.call("action.get", {"output": "extend", "actionids": [actions[0]["actionid"]],
                                    "selectFilter": "extend", "selectOperations": "extend",
                                    "selectRecoveryOperations": "extend"})
        print("actionids_lookup_count", len(a), "status_type", type(a[0].get("status")).__name__ if a else "empty",
              "status_value", a[0].get("status") if a else "empty")
        print("action_shape", shape(a[0]) if a else "empty", "filter_shape", shape(a[0].get("filter")) if a else "empty")
    print("hardware_action_exists", A.get_action(api, A.ACTION_NAME) is not None)

    groups = api.call("usergroup.get", {"output": ["usrgrpid", "name"],
                                         "filter": {"name": ["Network Operations"]}})
    print("approved_group_count", len(groups), "group_shape", shape(groups[0]) if groups else "empty")
    shape_groups = groups or api.call("usergroup.get", {"output": ["usrgrpid"], "limit": 1})
    if shape_groups:
        users = api.call("user.get", {"output": ["userid"], "usrgrpids": [shape_groups[0]["usrgrpid"]],
                                      "selectMedias": ["mediatypeid", "active"], "limit": 3})
        print("user_get_count_bounded", len(users), "user_shape", shape(users[0]) if users else "empty",
              "medias_shape", shape(users[0].get("medias")) if users else "empty")
        if users and users[0].get("medias"):
            print("medium_shape", shape(users[0]["medias"][0]))
    media = api.call("mediatype.get", {"output": ["mediatypeid", "name", "status"],
                                     "filter": {"name": ["Telegram"]}})
    print("telegram_media_count", len(media), "status_type", type(media[0].get("status")).__name__ if media else "empty")

    events = api.call("event.get", {"output": ["eventid", "r_eventid", "clock", "value", "objectid"],
                                    "source": 0, "object": 0, "sortfield": "eventid", "sortorder": "DESC", "limit": 5})
    print("event_get_count_bounded", len(events), "event_shape", shape(events[0]) if events else "empty",
          "r_eventid_present", bool(events) and "r_eventid" in events[0])
    alerts = api.call("alert.get", {"output": ["alertid", "actionid", "eventid", "p_eventid", "userid", "status", "retries", "error", "alerttype"],
                                    "sortfield": "alertid", "sortorder": "DESC", "limit": 100})
    print("alert_get_count_bounded", len(alerts), "alert_shape", shape(alerts[0]) if alerts else "empty",
          "p_eventid_present", bool(alerts) and "p_eventid" in alerts[0],
          "recovery_rows", sum(str(a.get("p_eventid", "0")) != "0" for a in alerts))

    obj = S.synthetic_objects(api)
    print("synthetic_namespace_counts", {k: len(v) for k, v in obj.items()})
    # Diagnostic-only in-memory scope. It is deliberately outside any approval
    # window and never passed to a command that creates a synthetic fixture.
    past = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    diagnostic_scope = {"usergroups": ["Network Operations"], "media_type": "Telegram",
                        "_window": (past, past + datetime.timedelta(hours=1))}
    notif = {"usergroups": ["Network Operations"], "media_type": "Telegram"}
    review = S.preflight(api, diagnostic_scope, notif, mode="review")
    execute = S.preflight(api, diagnostic_scope, notif, mode="execute")
    print("diagnostic_review_ready", review["ok"], "execution_allowed", review["execution_allowed"])
    print("diagnostic_preflight_ready", execute["ok"], "execution_allowed", execute["execution_allowed"])
    print("diagnostic_failed_checks", sorted(c["check"] for c in execute["checks"] if not c["ok"]))
    try:
        api.call("action.update", {"actionid": "0", "status": 1})
        print("readonly_write_refused", False)
    except AuditError:
        print("readonly_write_refused", True)
    print("writes_made", api.writes_made())


if __name__ == "__main__":
    main()
