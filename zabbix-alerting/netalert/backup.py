"""Snapshot of the objects this tool manages, taken before every apply.

Only managed objects (owned macros, the generated template, the alert action,
the identity macro) — not the whole Zabbix. The supported rollback is
`git revert` of interfaces.yaml followed by another apply; this file is the
audit record of exactly what was there.
"""
import datetime
import json
import os

from . import planner
from . import template as tpl
from .envsafety import IDENTITY_MACRO

BACKUP_FORMAT = 1


def snapshot(client, env, plan, config_path, version, now=None):
    cols = ["hostmacroid", "hostid", "macro", "value", "description"]
    rows = client.call("usermacro.get", {"output": cols, "search": {"macro": tpl.MACRO_PREFIX}})
    rows += client.call("usermacro.get", {"output": cols, "search": {"macro": "{$IFCONTROL:"}})
    owned = [r for r in rows if tpl.MARKER in (r.get("description") or "")]
    tp = planner.get_template(client)
    exported = None
    if tp and tpl.MARKER in (tp.get("description") or ""):
        exported = client.call("configuration.export", {"format": "json",
                                                        "options": {"templates": [tp["templateid"]]}})
    action = None
    spec = (env.get("alert_action") or {}).get("name")
    if spec:
        action = planner.get_action(client, spec)
    ident = client.call("usermacro.get", {"output": ["globalmacroid", "macro", "value"], "globalmacro": True,
                                           "filter": {"macro": IDENTITY_MACRO}})
    return {
        "format": BACKUP_FORMAT,
        "taken_utc": (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment": env["environment"],
        "zabbix_version": version,
        "config_file": os.path.basename(config_path),
        "planned": [c.line() for c in plan.changes],
        "owned_macros": owned,
        "template": tp,
        "template_export": exported,
        "action": action,
        "identity": ident[0] if ident else None,
    }


def write(base, data):
    d = os.path.join(base, "state", "backups")
    os.makedirs(d, exist_ok=True)
    stamp = data["taken_utc"].replace(":", "").replace("-", "")
    path = os.path.join(d, "%s-%s.json" % (data["environment"], stamp))
    n = 1
    while os.path.exists(path):          # never overwrite an earlier backup (two applies in one second)
        n += 1
        path = os.path.join(d, "%s-%s_%d.json" % (data["environment"], stamp, n))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
